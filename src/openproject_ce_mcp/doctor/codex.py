"""Codex: effective entries from Codex's own loader, fragments from the readable layer files.

Codex merges up to eight configuration layers key by key, several of which (enterprise
cloud bundles, macOS MDM) cannot be read from files, so the effective entries come from
``codex mcp list --json``. The readable files are still checked for what they set.
``codex mcp list`` output holds tokens: it is parsed in memory and only an allowlist of
metadata (server names, views, paths, key names, ``enabled``, ``disabled_reason``)
ever reaches the output.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ..config import ConfigConsistencyError, ConfigError, Settings
from .environment import EffectiveEnv, HostContext, certain_contradiction, with_stand_ins
from .hosts import Host, Subject, is_openproject_name, names_openproject
from .report import Finding, State, fail, info, unverified, warn

# Copied from Codex as data; tests pin them. Sources (openai/codex):
# codex-rs/rmcp-client/src/utils.rs (DEFAULT_ENV_VARS, create_env_for_mcp_server),
# codex-rs/protocol/src/shell_environment.rs (WINDOWS_CORE_ENV_VARS, NON_INHERITABLE_ENV_VARS),
# codex-rs/network-proxy/src/certs.rs (CUSTOM_CA_ENV_KEYS).
DEFAULT_ENV_VARS_UNIX = (
    "HOME",
    "LOGNAME",
    "PATH",
    "SHELL",
    "USER",
    "__CF_USER_TEXT_ENCODING",
    "LANG",
    "LC_ALL",
    "TERM",
    "TMPDIR",
    "TZ",
)
WINDOWS_CORE_ENV_VARS = (
    "PATH",
    "PATHEXT",
    "SHELL",
    "COMSPEC",
    "SYSTEMROOT",
    "WINDIR",
    "SYSTEMDRIVE",
    "USERNAME",
    "USERDOMAIN",
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "PROGRAMW6432",
    "PROGRAMDATA",
    "LOCALAPPDATA",
    "APPDATA",
    "TEMP",
    "TMP",
    "TMPDIR",
    "POWERSHELL",
    "PWSH",
)
CUSTOM_CA_ENV_KEYS = (
    "CODEX_CA_CERTIFICATE",
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "NODE_EXTRA_CA_CERTS",
    "GIT_SSL_CAINFO",
    "CARGO_HTTP_CAINFO",
    "PIP_CERT",
    "BUNDLE_SSL_CA_CERT",
    "npm_config_cafile",
    "NPM_CONFIG_CAFILE",
)
NON_INHERITABLE_ENV_VARS = (
    "CODEX_EXEC_SERVER_NOISE_AUTH_TOKEN",
    "NODE_REPL_AUTH_TOKEN",
    "CODEX_GUARDIAN_DECISIONS_API_KEY",
    "OPENAI_FEDERATION_RULE_ID",
    "OPENAI_IDENTITY_TOKEN_FILE",
    "OPENAI_WORKLOAD_IDENTITY_CONTEXT",
)
_NON_INHERITABLE = {name.upper() for name in NON_INHERITABLE_ENV_VARS}
_CA_KEYS = {name.upper() for name in CUSTOM_CA_ENV_KEYS}

LIST_TIMEOUT_SECONDS = 20.0
THIS_DIRECTORY = "this directory"
USER_LEVEL = "user level"
_LOCAL = "local"
_LOAD_ERROR_PREFIX = "Error: failed to load"


def default_env_vars(platform: str) -> tuple[str, ...]:
    return WINDOWS_CORE_ENV_VARS if platform == "win32" else DEFAULT_ENV_VARS_UNIX


# ── running Codex ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProcessResult:
    # None when the process did not finish in time.
    returncode: int | None
    stdout: str
    stderr: str


class CodexCli:
    """The installed ``codex`` binary; tests substitute recorded output."""

    def __init__(self, path: str | None) -> None:
        self.path = path

    @classmethod
    def installed(cls, ctx: HostContext) -> CodexCli:
        return cls(shutil.which("codex", path=ctx.shell_env.get("PATH")))

    def run(
        self, args: Sequence[str], cwd: Path, env: Mapping[str, str], *, timeout: float = LIST_TIMEOUT_SECONDS
    ) -> ProcessResult:
        if self.path is None:
            raise RuntimeError("codex is not installed; check CodexCli.path first")
        windows = sys.platform == "win32"
        # stdout and stderr stay in memory: both can quote configuration values.
        process = subprocess.Popen(
            [self.path, *args],
            cwd=cwd,
            env=dict(env),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            # Its own process group, so a timeout can end the helpers it starts too.
            start_new_session=not windows,
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(process)
            return ProcessResult(None, "", "")
        return ProcessResult(process.returncode, _text(stdout), _text(stderr))


def _text(output: bytes) -> str:
    return output.decode("utf-8", errors="replace")


def _kill_tree(process: subprocess.Popen[bytes]) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(process.pid)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        # The process may have finished between the timeout and the kill.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    # Reap without reading: a surviving grandchild could keep the pipes open forever.
    process.wait()
    for pipe in (process.stdout, process.stderr):
        if pipe is not None:
            pipe.close()


# ── the listing ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class EnvVarRef:
    name: str
    source: str | None = None

    @property
    def remote(self) -> bool:
        return self.source == "remote"


@dataclass(frozen=True)
class CodexServer:
    name: str
    enabled: bool
    disabled_reason: str | None
    # None for a streamable HTTP server.
    command: str | None
    args: tuple[str, ...] = ()
    env: tuple[tuple[str, str], ...] = ()
    env_vars: tuple[EnvVarRef, ...] = ()


class ListingShapeError(Exception):
    """The listing does not have the expected shape; carries no data."""


def parse_listing(stdout: str) -> list[CodexServer]:
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        raise ListingShapeError from None
    if not isinstance(data, list):
        raise ListingShapeError
    return [_parse_listed_server(item) for item in data]


def _parse_listed_server(item: object) -> CodexServer:
    if not isinstance(item, dict):
        raise ListingShapeError
    name, enabled, reason, transport = (item.get(k) for k in ("name", "enabled", "disabled_reason", "transport"))
    if not isinstance(name, str) or not isinstance(enabled, bool) or not isinstance(transport, dict):
        raise ListingShapeError
    if reason is not None and not isinstance(reason, str):
        raise ListingShapeError
    if transport.get("type") == "streamable_http":
        return CodexServer(name, enabled, reason, None)
    if transport.get("type") != "stdio":
        raise ListingShapeError
    command, args = transport.get("command"), transport.get("args")
    env, env_vars = transport.get("env") or {}, transport.get("env_vars") or []
    if not isinstance(command, str) or not isinstance(args, list) or not _is_str_list(args):
        raise ListingShapeError
    if not isinstance(env, dict):
        raise ListingShapeError
    if not all(isinstance(v, str) for v in env.values()) or not isinstance(env_vars, list):
        raise ListingShapeError
    refs = []
    for ref in env_vars:
        parsed = _parse_env_var(ref)
        if parsed is None:
            raise ListingShapeError
        refs.append(parsed)
    # Codex prints ``env`` from a hash map, so its order differs between runs.
    return CodexServer(name, enabled, reason, command, tuple(args), tuple(sorted(env.items())), tuple(refs))


def _is_str_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def _parse_env_var(ref: object) -> EnvVarRef | None:
    if isinstance(ref, str):
        return EnvVarRef(ref)
    if isinstance(ref, dict) and isinstance(ref.get("name"), str) and set(ref) <= {"name", "source"}:
        source = ref.get("source")
        if source is None or source in (_LOCAL, "remote"):
            return EnvVarRef(ref["name"], source)
    return None


# ── readable layer files ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LayerFile:
    path: Path
    layer: str  # system, user, project, managed
    data: dict | None
    error: str | None = None

    @property
    def applied(self) -> bool:
        """Codex applies this file without a trust decision this doctor would have to make."""
        return self.layer != "project"


@dataclass(frozen=True)
class Fragment:
    file: LayerFile
    name: str
    table: object


def resolve_codex_home(ctx: HostContext) -> Path | Finding:
    configured = ctx.shell_env.get("CODEX_HOME")
    if not configured:
        return ctx.home / ".codex"
    path = Path(configured)
    if not path.is_absolute():
        path = ctx.cwd / path
    if not path.is_dir():
        return fail(f"CODEX_HOME is set to {configured}, which is not a directory; Codex does not start")
    return path


def _read_layer(path: Path, layer: str) -> LayerFile | None:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        return LayerFile(path, layer, None, f"cannot be read ({type(exc).__name__})")
    try:
        return LayerFile(path, layer, tomllib.loads(text))
    except tomllib.TOMLDecodeError as exc:
        # The message names a position, never the offending text.
        return LayerFile(path, layer, None, f"is not valid TOML ({exc})")


def read_layers(ctx: HostContext, codex_home: Path) -> tuple[list[LayerFile], list[Finding]]:
    """The layer files Codex reads for this directory, lowest precedence first."""
    findings: list[Finding] = []
    base = [
        _read_layer(ctx.system.codex_system_config, "system"),
        _read_layer(codex_home / "config.toml", "user"),
    ]
    managed = _read_layer(ctx.system.codex_managed_config, "managed") if ctx.system.codex_managed_config else None
    trust_free = [f for f in (*base, managed) if f is not None]
    markers: list[str] = [".git"]
    for layer in trust_free:
        value = layer.data.get("project_root_markers") if layer.data else None
        if value is None:
            continue
        if isinstance(value, list) and all(isinstance(m, str) for m in value):
            markers = value
        else:
            findings.append(fail(f"{layer.path}: project_root_markers is not a list of strings"))
    projects = [_read_layer(p, "project") for p in project_config_files(ctx.cwd, markers, codex_home)]
    ordered = [f for f in (*base, *projects, managed) if f is not None]
    return ordered, findings


def project_config_files(cwd: Path, markers: Sequence[str], codex_home: Path) -> list[Path]:
    """Project ``.codex/config.toml`` files Codex would consider, root first.

    Mirrors ``discover_project_root``/``discover_project_layers``: up to the first
    ancestor with a root marker (a ``.git`` directory counts only with ``HEAD``),
    otherwise only the current directory; ``CODEX_HOME`` is never a project folder.
    """
    root = _project_root(cwd, markers)
    directories = []
    for directory in (cwd, *cwd.parents):
        directories.append(directory)
        if root is None or directory == root:
            break
    home = _normalized(codex_home)
    files = []
    for directory in reversed(directories):
        dot_codex = directory / ".codex"
        if dot_codex.is_dir() and _normalized(dot_codex) != home:
            files.append(dot_codex / "config.toml")
    return files


def _project_root(cwd: Path, markers: Sequence[str]) -> Path | None:
    for directory in (cwd, *cwd.parents):
        for marker in markers:
            path = directory / marker
            if not path.exists():
                continue
            if marker == ".git" and path.is_dir() and not (path / "HEAD").exists():
                continue
            return directory
    return None


def _normalized(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path


def fragments_of(files: Sequence[LayerFile]) -> tuple[list[Fragment], list[tuple[LayerFile, str]]]:
    fragments: list[Fragment] = []
    problems: list[tuple[LayerFile, str]] = []
    for layer in files:
        if layer.data is None:
            continue
        servers = layer.data.get("mcp_servers")
        if servers is None:
            continue
        if not isinstance(servers, dict):
            problems.append((layer, "`mcp_servers` is not a table"))
            continue
        fragments.extend(Fragment(layer, name, table) for name, table in servers.items())
    return fragments, problems


def fragment_shape_errors(table: object) -> list[str]:
    if not isinstance(table, dict):
        return ["the entry is not a table"]
    errors = []
    for key in ("command", "environment_id", "cwd"):
        if key in table and not isinstance(table[key], str):
            errors.append(f"`{key}` is not a string")
    if "args" in table and not _is_str_list(table["args"]):
        errors.append("`args` is not a list of strings")
    if "enabled" in table and not isinstance(table["enabled"], bool):
        errors.append("`enabled` is not a boolean")
    env = table.get("env")
    if env is not None and (not isinstance(env, dict) or not all(isinstance(v, str) for v in env.values())):
        errors.append("`env` is not a table of strings")
    env_vars = table.get("env_vars")
    if env_vars is not None and (
        not isinstance(env_vars, list) or any(_parse_env_var(ref) is None for ref in env_vars)
    ):
        errors.append('`env_vars` must list names or tables with `name` and `source = "local"` or `"remote"`')
    return errors


def fragment_value_error(env: Mapping[str, str]) -> str | None:
    """The first problem in the values the fragment sets.

    A contradiction counts only when the fragment sets every value it involves; any
    other value may come from another layer.
    """
    values = {k: v for k, v in env.items() if k.startswith("OPENPROJECT_")}
    if not values:
        return None
    try:
        Settings.from_env(environ=with_stand_ins(values))
    except ConfigConsistencyError as exc:
        return certain_contradiction(exc, lambda key: key in values)
    except ConfigError as exc:
        return str(exc)
    return None


# ── environment ────────────────────────────────────────────────────────────────


class CodexHost(Host):
    """Codex builds the environment of a local stdio server from an allowlist
    (``create_env_for_mcp_server``)."""

    key = "codex"
    label = "Codex"

    def codex_env(self, server: CodexServer, ctx: HostContext) -> EffectiveEnv:
        shell = ctx.shell_env
        result = EffectiveEnv(env=ctx.env(), assumed_local=True)
        env = result.env
        local_refs = [ref for ref in server.env_vars if not ref.remote and ref.name.upper() not in _NON_INHERITABLE]
        for name in (*default_env_vars(ctx.platform), *(ref.name for ref in local_refs)):
            if name in shell:
                env[name] = shell[name]
        for name in CUSTOM_CA_ENV_KEYS:
            value = shell.get(name)
            if value:
                env[name] = value if os.path.isabs(value) else str(ctx.cwd / value)
        for key, value in server.env:
            if ctx.platform != "win32" and key.upper() in _CA_KEYS:
                env.remove_ignoring_case(key)
            env[key] = value
            result.entry_keys.add(env.fold(key))
        for name in [n for n in env if n.upper() in _NON_INHERITABLE]:
            del env[name]
        for ref in local_refs:
            if ref.name not in shell:
                result.may_supply[env.fold(ref.name)] = (
                    "Codex passes it from its own environment (env_vars), and this shell does not have it"
                )
        for ref in server.env_vars:
            if ref.remote:
                result.notes.append(
                    warn(
                        f'env_vars entry {ref.name} uses source = "remote": Codex refuses to start this server '
                        "unless a managed layer sets `environment_id`"
                    )
                )
                result.may_supply[env.fold(ref.name)] = "it comes from a remote environment that is not checked here"
        return result


NOT_LOADED = "not loaded by Codex here, for example from a project layer Codex does not trust"
ASSUMED_LOCAL = "assuming Codex runs it locally; managed configuration this doctor cannot read could change that"


# ── putting it together ─────────────────────────────────────────────────────────


@dataclass
class CodexReport:
    subjects: list[Subject] = field(default_factory=list)
    notes: list[Finding] = field(default_factory=list)
    files: list[LayerFile] = field(default_factory=list)
    entry_files: set[Path] = field(default_factory=set)


def codex_subjects(ctx: HostContext, cli: CodexCli, display: Callable[[Path], str]) -> CodexReport:
    host = CodexHost()
    report = CodexReport()
    home = resolve_codex_home(ctx)
    if isinstance(home, Finding):
        report.subjects.append(Subject(host, "", findings=[home]))
        return report
    files, marker_findings = read_layers(ctx, home)
    report.files = files
    fragments, table_problems = fragments_of(files)

    views: dict[str, list[CodexServer] | None] = {}
    view_findings: dict[str, Finding] = {}
    if cli.path is not None:
        report.notes.append(info("runtime --config and --profile flags of a particular Codex launch are not covered"))
        views[THIS_DIRECTORY], finding = _list_view(cli, ctx.cwd, ctx.shell_env, ())
        if finding:
            view_findings[THIS_DIRECTORY] = finding
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp).resolve()
            if _ancestor_config(empty, home):
                view_findings[USER_LEVEL] = unverified(
                    f"the user-level view is not verified: an ancestor of {empty} holds a .codex/config.toml "
                    "(or cannot be checked) that a managed layer could make Codex read there"
                )
            else:
                views[USER_LEVEL], finding = _list_view(cli, empty, ctx.shell_env, ("-c", "project_root_markers=[]"))
                if finding:
                    view_findings[USER_LEVEL] = finding

    openproject = {f.name for f in fragments if is_openproject_name(f.name) or _fragment_names_openproject(f)}
    openproject |= {
        s.name
        for servers in views.values()
        if servers
        for s in servers
        if is_openproject_name(s.name) or names_openproject(s.command, list(s.args))
    }

    for layer, problem in table_problems:
        report.subjects.append(_file_subject(host, layer, problem, display))
    for finding in marker_findings:
        report.subjects.append(Subject(host, "", findings=[finding]))
    for layer in files:
        if layer.error:
            report.subjects.append(_file_subject(host, layer, layer.error, display))

    this_dir = {s.name: s for s in views.get(THIS_DIRECTORY) or []}
    for fragment in fragments:
        if fragment.name in openproject:
            report.entry_files.add(fragment.file.path)
            subject = _fragment_subject(host, fragment, this_dir.get(fragment.name), display)
            if subject is not None:
                report.subjects.append(subject)

    if cli.path is None:
        report.subjects.extend(
            Subject(host, name, findings=[unverified("Codex CLI not found; its effective entry is not known")])
            for name in sorted(openproject)
        )
        return report
    for view, finding in view_findings.items():
        report.subjects.append(Subject(host, f"({view})", findings=[finding]))
    for name in sorted(openproject):
        report.subjects.extend(_effective_subjects(host, name, views, fragments, ctx))
    return report


def _list_view(
    cli: CodexCli, cwd: Path, env: Mapping[str, str], extra: Sequence[str]
) -> tuple[list[CodexServer] | None, Finding | None]:
    result = cli.run(["mcp", "list", "--json", *extra], cwd, env)
    if result.returncode is None:
        return None, unverified(f"`codex mcp list` did not finish within {LIST_TIMEOUT_SECONDS:g} s")
    if result.returncode == 1 and any(line.startswith(_LOAD_ERROR_PREFIX) for line in result.stderr.splitlines()):
        return None, fail("Codex could not load its configuration; run `codex mcp list` to see why")
    if result.returncode != 0:
        return None, unverified(
            f"`codex mcp list` failed with exit status {result.returncode}; the effective configuration is not known"
        )
    try:
        return parse_listing(result.stdout), None
    except ListingShapeError:
        return None, unverified("`codex mcp list --json` printed output this doctor does not recognize")


def _ancestor_config(directory: Path, codex_home: Path) -> bool:
    """Whether an ancestor holds a ``.codex/config.toml`` (or cannot be checked)."""
    home = _normalized(codex_home)
    for ancestor in (directory, *directory.parents):
        dot_codex = ancestor / ".codex"
        if _normalized(dot_codex) == home:
            continue
        try:
            os.stat(dot_codex / "config.toml")
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError:
            return True
        return True
    return False


def _fragment_names_openproject(fragment: Fragment) -> bool:
    table = fragment.table
    return isinstance(table, dict) and names_openproject(table.get("command"), table.get("args"))


def _file_subject(host: Host, layer: LayerFile, problem: str, display: Callable[[Path], str]) -> Subject:
    finding = fail(f"{display(layer.path)} {problem}") if layer.applied else warn(f"{display(layer.path)} {problem}")
    return Subject(host, f"({layer.layer} layer {display(layer.path)})", findings=[finding])


def _fragment_subject(
    host: Host, fragment: Fragment, effective: CodexServer | None, display: Callable[[Path], str]
) -> Subject | None:
    layer = fragment.file
    label = f"{fragment.name} ({display(layer.path)}, {layer.layer} layer)"
    errors = fragment_shape_errors(fragment.table)
    findings: list[Finding] = []
    if errors:
        findings = [fail(e) if layer.applied else warn(e) for e in errors]
    else:
        assert isinstance(fragment.table, dict)
        env = fragment.table.get("env") or {}
        error = fragment_value_error(env)
        if error:
            reaches = effective is not None and all(
                dict(effective.env).get(k) == v for k, v in env.items() if k.startswith("OPENPROJECT_")
            )
            findings.append(
                fail(error) if layer.applied or reaches else warn(f"{error} (if Codex trusts this project)")
            )
    if not findings:
        return None
    return Subject(host, label, findings=findings)


def environment_remote(name: str, fragments: Sequence[Fragment], *, include_projects: bool) -> bool:
    """Whether the server may run remotely, from the layers that need no trust.

    A project layer can only push towards remote: Codex ignores an untrusted one,
    and this doctor does not decide trust.
    """
    value = _LOCAL
    for fragment in fragments:
        table = fragment.table
        if fragment.name != name or not isinstance(table, dict):
            continue
        environment = table.get("environment_id")
        if not isinstance(environment, str):
            continue
        if fragment.file.layer == "project":
            if include_projects and environment != _LOCAL:
                return True
        else:
            value = environment
    return value != _LOCAL


def _effective_subjects(
    host: CodexHost,
    name: str,
    views: Mapping[str, list[CodexServer] | None],
    fragments: Sequence[Fragment],
    ctx: HostContext,
) -> list[Subject]:
    per_view: dict[str, tuple[CodexServer, bool]] = {}
    for view, servers in views.items():
        server = next((s for s in servers or [] if s.name == name), None)
        if server is not None:
            per_view[view] = (server, environment_remote(name, fragments, include_projects=view == THIS_DIRECTORY))
    if not per_view:
        if any(servers is not None for servers in views.values()):
            return [Subject(host, name, State.INACTIVE, NOT_LOADED)]
        return []
    if len(per_view) == 2 and per_view[THIS_DIRECTORY] == per_view[USER_LEVEL]:
        per_view = {f"{THIS_DIRECTORY} and {USER_LEVEL}": per_view[THIS_DIRECTORY]}
    return [_effective_subject(host, name, view, server, remote, ctx) for view, (server, remote) in per_view.items()]


def _effective_subject(
    host: CodexHost, name: str, view: str, server: CodexServer, remote: bool, ctx: HostContext
) -> Subject:
    subject = Subject(host, f"{name} ({view})")
    if server.command is None:
        subject.state = State.REMOTE
        subject.findings.append(info("HTTP server; not checked"))
        return subject
    if not server.enabled:
        subject.state = State.INACTIVE
        subject.state_reason = f"disabled: {server.disabled_reason}" if server.disabled_reason else "enabled = false"
    if remote:
        subject.state = State.REMOTE
        subject.findings.append(unverified("may run remotely (environment_id); not verified here"))
        return subject
    subject.effective = host.codex_env(server, ctx)
    subject.command = server.command
    subject.args = server.args
    return subject
