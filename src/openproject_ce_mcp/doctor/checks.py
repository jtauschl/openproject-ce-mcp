"""Checking one entry: its settings, its command, the connection, and the tools it registers."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from ..config import TOOL_GROUPS, ConfigConsistencyError, ConfigError, Settings
from .environment import REQUIRED_KEYS, STAND_INS, EffectiveEnv, EnvMap, HostContext, certain_contradiction
from .hosts import Host, Subject, launcher_package
from .probe import ProbeResult
from .report import Finding, Level, fail, info, ok, unverified, warn

ProbeRunner = Callable[[Mapping[str, str]], ProbeResult]

PROBE_OVERRIDES = {"OPENPROJECT_MAX_RETRIES": "0", "OPENPROJECT_TIMEOUT": "5"}
DISPATCH_TIMEOUT_SECONDS = 5.0
_PROXY_AND_CA_KEYS = tuple(
    name for base in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY") for name in (base, base.lower())
) + ("SSL_CERT_FILE", "SSL_CERT_DIR")
_LAUNCHERS = {"uvx", "uv", "pipx"}
SERVER_BIN = "openproject-ce-mcp"
_URL_USERINFO_RE = re.compile(r"(?<=://)[^/@\s]+@")


@dataclass
class Evaluation:
    subject: Subject
    findings: list[Finding] = field(default_factory=list)
    settings: Settings | None = None
    settings_finding: Finding | None = None
    scope_summary: list[str] = field(default_factory=list)
    probe_env: EnvMap | None = None

    @property
    def failed(self) -> bool:
        return any(f.level is Level.FAIL for f in self.findings)

    @property
    def unverified(self) -> bool:
        return any(f.unverified for f in self.findings)

    @property
    def assumed_local(self) -> bool:
        return self.subject.effective is not None and self.subject.effective.assumed_local


def evaluate(subject: Subject, ctx: HostContext) -> Evaluation:
    evaluation = Evaluation(subject, findings=list(subject.findings))
    effective = subject.effective
    if effective is None:
        return evaluation
    evaluation.findings += effective.notes
    values, probe_ready = _check_settings(subject.host, effective, evaluation)
    evaluation.findings += _check_command(subject, values, ctx)
    if probe_ready and subject.counts and not evaluation.failed and evaluation.settings is not None:
        probe_env = ctx.base_env()
        probe_env.update(values)
        probe_env.update(PROBE_OVERRIDES)
        evaluation.probe_env = probe_env
    return evaluation


def _check_settings(host: Host, effective: EffectiveEnv, evaluation: Evaluation) -> tuple[EnvMap, bool]:
    """Resolve placeholders and required keys, validate as the server would, and add warnings."""
    values = effective.env.copy()
    findings = evaluation.findings
    required = {values.fold(key): key for key in REQUIRED_KEYS}
    probe_ready = True
    for name in list(values):
        folded = values.fold(name)
        if folded not in effective.unresolved:
            continue
        probe_ready = False
        if folded in required:
            values[name] = STAND_INS[required[folded]]
            findings.append(unverified(f"{name} uses a placeholder this doctor cannot resolve"))
        else:
            del values[name]
            findings.append(
                unverified(f"{name} uses a placeholder this doctor cannot resolve; checked with its default")
            )
    for key in REQUIRED_KEYS:
        if key in values:
            continue
        probe_ready = False
        reason = effective.may_supply.get(values.fold(key)) or effective.inherits
        if reason:
            findings.append(unverified(f"{key} is not set in the entry; {reason}"))
        else:
            findings.append(fail(f"{key} is not set, and {host.label} cannot get it from anywhere else"))
        values[key] = STAND_INS[key]

    try:
        settings = Settings.from_env(environ=values)
    except ConfigConsistencyError as exc:
        certain = certain_contradiction(exc, lambda key: _value_known(values.fold(key), effective))
        if certain is not None:
            findings.append(fail(certain))
        elif effective.entry_values_only:
            findings.append(unverified(f"{exc} (with only the values the entry sets)"))
        else:
            findings.append(unverified(f"{exc} (with a default for a value this doctor cannot know)"))
        return values, False
    except ConfigError as exc:
        findings.append(fail(str(exc)))
        return values, False
    evaluation.settings = settings
    evaluation.settings_finding = ok(
        "settings valid" if probe_ready else "settings valid apart from the findings above"
    )
    findings.append(evaluation.settings_finding)
    evaluation.scope_summary = _project_scope_summary(settings)
    findings += _insecure_findings(settings)
    return values, probe_ready


def _value_known(folded: str, effective: EffectiveEnv) -> bool:
    if folded in effective.unresolved:
        return False
    if folded in effective.entry_keys:
        return True
    return not effective.entry_values_only and folded not in effective.may_supply


def _insecure_findings(settings: Settings) -> list[Finding]:
    findings = []
    if not settings.verify_ssl:
        findings.append(warn("SSL verification disabled (OPENPROJECT_VERIFY_SSL=false)"))
    if settings.base_url.startswith("http://"):
        findings.append(warn("Unencrypted HTTP connection"))
    return findings


def _project_scope_summary(settings: Settings) -> list[str]:
    """Make the fail-closed project-scope default and write-group state diagnosable."""
    read_summary = ", ".join(settings.read_projects) or "none (fail-closed — nothing readable)"
    write_summary = ", ".join(settings.write_projects) or "none (fail-closed — nothing writable)"
    lines = [f"Read projects: {read_summary}", f"Write projects: {write_summary}"]
    lines += [f"{g.write.label} writes: {getattr(settings, g.write.attr)}" for g in TOOL_GROUPS if g.write is not None]
    return lines


def _check_command(subject: Subject, values: EnvMap, ctx: HostContext) -> list[Finding]:
    """Whether the command can start; only what is provable fails."""
    command = subject.command
    if command is None:
        return []
    host = subject.host
    findings: list[Finding] = []
    found: str | None
    if os.path.isabs(command):
        if not os.path.exists(command):
            return [fail(f"command {command} does not exist")]
        if ctx.platform != "win32" and not os.access(command, os.X_OK):
            return [fail(f"command {command} is not executable")]
        found = command
    else:
        search_path = values.get("PATH") or ctx.shell_env.get("PATH") or os.defpath
        found = shutil.which(command, path=search_path)
        if found is None:
            findings.append(unverified(f"command `{command}` is not on PATH here; the client's own PATH may differ"))
    if found is not None:
        findings.append(ok(f"command: {found}"))
    findings += host.command_notes(command, found, ctx)

    name = Path(command).name.lower()
    stem = name.rsplit(".", 1)[0] if name.endswith((".exe", ".cmd")) else name
    if stem in _LAUNCHERS:
        package = launcher_package(subject.args)
        if package is None:
            findings.append(info(f"{stem} does not name {SERVER_BIN} in its args"))
        else:
            findings.append(info(f"{stem} runs {_URL_USERINFO_RE.sub('***@', package)}"))
    elif found is not None and stem == SERVER_BIN:
        own = _own_server_binary()
        if own is not None and os.path.realpath(found) != os.path.realpath(own):
            findings.append(
                unverified(
                    f"runs {found}, another install than this doctor's ({own}); "
                    "the checks here used this doctor's settings handling, which may differ"
                )
            )
    return findings


def _own_server_binary() -> Path | None:
    name = f"{SERVER_BIN}.exe" if sys.platform == "win32" else SERVER_BIN
    candidate = Path(sys.executable).parent / name
    return candidate if candidate.exists() else None


def probe_key(evaluation: Evaluation) -> tuple[object, ...]:
    """What makes two connection checks the same: the connection-relevant variables and
    whether the result rests on the Codex locality assumption."""
    env = evaluation.probe_env
    assert env is not None
    relevant = {env.fold(name) for name in _PROXY_AND_CA_KEYS}
    prefix = env.fold("OPENPROJECT_")
    items = [
        (env.fold(name), env[name]) for name in env if env.fold(name).startswith(prefix) or env.fold(name) in relevant
    ]
    return (evaluation.assumed_local, tuple(sorted(items)))


def run_probes(evaluations: Sequence[Evaluation], probe: ProbeRunner) -> None:
    """One connection check per distinct connection-relevant environment."""
    results: dict[tuple[object, ...], ProbeResult] = {}
    for evaluation in evaluations:
        if evaluation.probe_env is None:
            continue
        key = probe_key(evaluation)
        if key not in results:
            results[key] = probe(evaluation.probe_env.as_dict())
        result = results[key]
        if result.ok:
            evaluation.findings.append(ok(f"API: connected ({result.user})"))
        else:
            evaluation.findings.append(fail(f"API: {result.category}: {result.message}"))


def preview_tools(evaluations: Sequence[Evaluation]) -> None:
    """The tool registration preview, once per distinct ``Settings`` and provenance."""
    previews: list[tuple[Settings, bool, list[str]]] = []
    for evaluation in evaluations:
        settings = evaluation.settings
        if settings is None or not evaluation.subject.counts or evaluation.failed:
            continue
        names = next(
            (names for known, local, names in previews if known == settings and local == evaluation.assumed_local),
            None,
        )
        if names is None:
            names = tool_names(settings)
            previews.append((settings, evaluation.assumed_local, names))
        sample = ", ".join(names[:5])
        evaluation.findings.append(ok(f"Tools: {len(names)} would register ({_profile_note(settings)}): {sample}, ..."))


def _profile_note(settings: Settings) -> str:
    if settings.tool_profile == "full":
        return "profile full"
    from ..tools import enabled_tool_names

    under_full = len(enabled_tool_names(replace(settings, tool_profile="full")))
    return f"profile {settings.tool_profile}; {under_full} under full"


def tool_names(settings: Settings) -> list[str]:
    """Preview which tools would register, without network I/O.

    Uses register_tools() directly, not create_app(), to avoid the feature flag
    fetch: a live server may register fewer, depending on instance features.
    """
    from mcp.server.mcpserver import MCPServer

    from ..tools import register_tools

    previous = logging.root.level
    logging.root.setLevel(logging.CRITICAL)
    try:
        # Plain MCPServer: the preview only lists tools and never calls one.
        mcp = MCPServer("doctor-preview", log_level="CRITICAL")
        register_tools(mcp, settings)
        return [tool.name for tool in mcp._tool_manager.list_tools()]
    finally:
        logging.root.setLevel(previous)


def check_dispatch(evaluations: Sequence[Evaluation]) -> None:
    """The MCP dispatch check, once per distinct ``Settings``."""
    results: list[tuple[Settings, Finding]] = []
    for evaluation in evaluations:
        settings = evaluation.settings
        if settings is None or not evaluation.subject.counts or evaluation.failed:
            continue
        finding = next((known_finding for known, known_finding in results if known == settings), None)
        if finding is None:
            finding = asyncio.run(dispatch_finding(settings))
            results.append((settings, finding))
        evaluation.findings.append(finding)


async def dispatch_finding(settings: Settings, *, timeout: float = DISPATCH_TIMEOUT_SECONDS) -> Finding:
    """Verify in memory that the server's dispatch path rejects unknown arguments.

    create_app() only builds the server: its lifespan, which connects, runs only
    in app.run(). So this cannot hang on I/O; the timeout guards against an
    SDK-internal problem.
    """
    try:
        await asyncio.wait_for(_build_and_verify_dispatch(settings), timeout=timeout)
    except TimeoutError:
        return fail(
            f"MCP: dispatch check did not complete within {timeout:g} s (an SDK-internal problem, not a network one)"
        )
    except Exception as exc:  # noqa: BLE001 - any failure here means the server would refuse to start
        return fail(f"MCP: dispatch check failed ({type(exc).__name__})")
    return ok("MCP: dispatch rejects unknown arguments (checked in process)")


async def _build_and_verify_dispatch(settings: Settings) -> None:
    from ..server import create_app
    from ..strict_mcpserver import verify_strict_dispatch

    # create_app configures logging for the entry's OPENPROJECT_LOG_LEVEL; the
    # doctor's own output must not change with it.
    root = logging.getLogger()
    level, handlers = root.level, root.handlers[:]
    formatters = [handler.formatter for handler in handlers]
    try:
        await verify_strict_dispatch(create_app(settings))
    finally:
        root.setLevel(level)
        root.handlers[:] = handlers
        for handler, formatter in zip(handlers, formatters, strict=True):
            handler.setFormatter(formatter)
