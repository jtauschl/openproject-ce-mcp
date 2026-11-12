"""How each MCP host turns a configured server entry into the server's environment.

Configuration files and hosts are separate: one file can be loaded by several hosts
(``.mcp.json`` by Claude Code and by VS Code), and each host evaluates the same entry
with its own rules for inheritance, placeholders and allowlists.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ..config import API_TOKEN_ENV_VAR, API_TOKEN_VAR_ENV_VAR
from .environment import (
    BASE_URL_KEY,
    EffectiveEnv,
    EnvMap,
    HostContext,
    Syntax,
    overlay_entry_env,
    resolve,
    token_keys,
    token_variable,
)
from .files import parse_env_file
from .report import Finding, State, fail, info, unverified, warn

_MACOS_LAUNCHD_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
_REMOTE_TYPES = {"http", "sse", "streamable_http", "streamable-http", "remote"}
_OPENPROJECT_COMMAND_RE = re.compile(r"(?:^|[\\/])openproject-ce-mcp(?:$|[^\w-])")


# ── server entries ──────────────────────────────────────────────────────────────


def names_openproject(command: object, args: object) -> bool:
    tokens = [command] if isinstance(command, str) else []
    if isinstance(args, list):
        tokens += [arg for arg in args if isinstance(arg, str)]
    return any(_OPENPROJECT_COMMAND_RE.search(token) for token in tokens)


def is_openproject_name(name: str) -> bool:
    return name == "openproject" or name.startswith("openproject-")


def is_openproject_server(name: str, server: object) -> bool:
    if is_openproject_name(name):
        return True
    return isinstance(server, dict) and names_openproject(server.get("command"), server.get("args"))


@dataclass(frozen=True)
class RawEntry:
    """One server as written in one file, before any host interprets it."""

    file: Path
    name: str
    server: object
    scope: str = ""


@dataclass(frozen=True)
class ServerSpec:
    command: str
    args: tuple[str, ...]
    # None unsets the variable (VS Code's ``null``).
    env: Mapping[str, str | None]
    env_file: str | None = None


def is_remote(server: object) -> bool:
    return isinstance(server, dict) and (
        "url" in server or (isinstance(server.get("type"), str) and server["type"].lower() in _REMOTE_TYPES)
    )


def parse_server(server: object, *, vscode_values: bool) -> tuple[ServerSpec | None, list[str]]:
    """Shape-check a stdio entry; VS Code also accepts numbers and null as env values."""
    if not isinstance(server, dict):
        return None, ["the entry is not an object"]
    errors: list[str] = []
    command = server.get("command")
    if not isinstance(command, str) or not command.strip():
        errors.append("`command` is missing or not a string")
    args = server.get("args", [])
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        errors.append("`args` is not a list of strings")
        args = []
    env_raw = server.get("env", {})
    env: dict[str, str | None] = {}
    if env_raw is None:
        env_raw = {}
    if not isinstance(env_raw, dict):
        errors.append("`env` is not an object")
    else:
        for key, value in env_raw.items():
            if isinstance(value, str):
                env[key] = value
            elif vscode_values and value is None:
                env[key] = None
            elif vscode_values and isinstance(value, (int, float)) and not isinstance(value, bool):
                env[key] = str(value)
            else:
                errors.append(f"`env.{key}` is not a string")
    env_file = server.get("envFile")
    if env_file is not None and not isinstance(env_file, str):
        errors.append("`envFile` is not a string")
        env_file = None
    if errors:
        return None, errors
    return ServerSpec(command=str(command), args=tuple(args), env=env, env_file=env_file), []


@dataclass(frozen=True)
class Source:
    """A file one host reads, with how that host interprets it."""

    path: Path
    root_key: str
    syntax: Syntax
    scope: str
    workspace: Path | None = None
    jsonc: bool = False
    # VS Code hands these to the Agent Host unless they need interactive input.
    forwarded_to_agent_host: bool = False
    # VS Code reads ``envFile`` only from its own configuration files.
    reads_env_file: bool = False
    # VS Code also accepts a workspace ``.mcp.json`` whose top level is the server map.
    root_key_optional: bool = False


# ── hosts ───────────────────────────────────────────────────────────────────────


class Host:
    key: str
    label: str
    vscode_values = False

    def effective_env(self, spec: ServerSpec, source: Source, ctx: HostContext) -> EffectiveEnv:
        raise NotImplementedError(f"{type(self).__name__} does not build an environment")

    def placeholder_env(self, ctx: HostContext) -> Mapping[str, str]:
        """Where ``${...}`` placeholders in this host's entries are looked up."""
        return ctx.shell_env

    def notes(self, ctx: HostContext) -> list[Finding]:
        """Facts about the host as a whole, reported once."""
        return []

    def command_notes(self, command: str, found: str | None, ctx: HostContext) -> list[Finding]:
        return []


class VsCodeHost(Host):
    """The VS Code extension host starts the server with its own environment plus the entry's.

    Only its own files (``.vscode/mcp.json``, the profile ``mcp.json``) get ``envFile`` and
    VS Code's variables; ``.mcp.json`` and the Copilot CLI file are expanded with the
    Copilot rules, and files from other clients are taken literally
    (``nativeMcpDiscoveryAdapters.ts``, ``workspaceDotMcpDiscovery.ts``).
    """

    key = "vscode"
    label = "VS Code"
    vscode_values = True

    def effective_env(self, spec: ServerSpec, source: Source, ctx: HostContext) -> EffectiveEnv:
        env = ctx.shell_env.copy()
        result = EffectiveEnv(
            env=env,
            inherits="VS Code passes its own environment (on macOS and Linux the login shell's), "
            "which this shell only approximates",
        )
        if spec.env_file is not None and not source.reads_env_file:
            result.notes.append(info("VS Code ignores `envFile` in this file"))
        elif spec.env_file is not None:
            path = resolve(spec.env_file, source.syntax, ctx.shell_env, workspace=source.workspace, home=ctx.home)
            if path is None or not Path(path).is_absolute():
                result.notes.append(
                    unverified(f"envFile {spec.env_file} cannot be resolved here; its values are unknown")
                )
            else:
                try:
                    values = parse_env_file(Path(path).read_text(encoding="utf-8-sig"))
                except (OSError, UnicodeDecodeError):
                    result.notes.append(fail(f"envFile {path} cannot be read; VS Code does not start the server"))
                else:
                    env.update(values)
        overlay_entry_env(
            env,
            spec.env,
            source.syntax,
            ctx.shell_env,
            workspace=source.workspace,
            home=ctx.home,
            result=result,
            append_path_with=ctx.path_separator,
        )
        return result


class VsCodeAgentHost(Host):
    """The Agent Host hands the entry to an agent harness that this doctor cannot identify.

    The Codex harness passes only ``env`` (``codexMcpServers.ts``), the Claude harness
    inherits, and no harness reads ``envFile``, so only the values the entry sets are
    checked as such.
    """

    key = "vscode-agent-host"
    label = "VS Code Agent Host"
    vscode_values = True

    def effective_env(self, spec: ServerSpec, source: Source, ctx: HostContext) -> EffectiveEnv:
        env = ctx.env()
        reason = "missing in Agent Host sessions with the Codex agent"
        if spec.env_file is not None:
            reason += "; `envFile` is not read there"
        result = EffectiveEnv(env=env, inherits=reason, entry_values_only=True)
        overlay_entry_env(
            env, spec.env, source.syntax, ctx.shell_env, workspace=source.workspace, home=ctx.home, result=result
        )
        return result


_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}


class ClaudeCodeHost(Host):
    """Claude Code (verified in its binary): process environment plus settings ``env``
    blocks, then the entry's ``env``; ``${X}`` and ``${X:-default}`` placeholders."""

    key = "claude-code"
    label = "Claude Code"

    def __init__(self, settings_env: Sequence[tuple[Path, Mapping[str, str]]], settings_notes: Sequence[Finding]):
        self.settings_env = settings_env
        self.settings_notes = list(settings_notes)

    def placeholder_env(self, ctx: HostContext) -> Mapping[str, str]:
        return self.process_env(ctx)

    def process_env(self, ctx: HostContext) -> EnvMap:
        env = ctx.shell_env.copy()
        for _, values in self.settings_env:
            env.update(values)
        return env

    def notes(self, ctx: HostContext) -> list[Finding]:
        notes = [info("Claude Code can add its agent proxy settings, which this doctor cannot see")]
        if "CLAUDE_CODE_SHELL_PREFIX" in ctx.shell_env:
            notes.append(info("CLAUDE_CODE_SHELL_PREFIX in this shell wraps the server command"))
        return notes

    @staticmethod
    def allowlist_mode(process_env: Mapping[str, str]) -> bool:
        switch = (process_env.get("CLAUDE_CODE_MCP_ALLOWLIST_ENV") or "").strip().lower()
        if switch in _TRUTHY:
            return True
        if switch in _FALSY:
            return False
        return process_env.get("CLAUDE_CODE_ENTRYPOINT") == "local-agent"

    def effective_env(self, spec: ServerSpec, source: Source, ctx: HostContext) -> EffectiveEnv:
        process = self.process_env(ctx)
        notes = list(self.settings_notes)
        if self.allowlist_mode(process):
            result = EffectiveEnv(env=ctx.env(), notes=notes)
            result.notes.append(info("allowlist mode: Claude Code passes only selected variables plus the entry's env"))
            for name in process:
                result.may_supply[process.fold(name)] = (
                    "Claude Code is in allowlist mode, so whether it passes this variable from its "
                    "environment or settings is not known"
                )
        else:
            result = EffectiveEnv(
                env=process.copy(),
                inherits="Claude Code passes its own environment, which this shell only approximates",
                notes=notes,
            )
        overlay_entry_env(
            result.env, spec.env, source.syntax, process, workspace=source.workspace, home=ctx.home, result=result
        )
        return result


class ClaudeDesktopHost(Host):
    """Claude Desktop passes an allowlisted subset of its environment ("a subset like USER,
    HOME, PATH", MCP debugging guide); OpenProject variables come only from the entry."""

    key = "claude-desktop"
    label = "Claude Desktop"

    def effective_env(self, spec: ServerSpec, source: Source, ctx: HostContext) -> EffectiveEnv:
        result = EffectiveEnv(env=ctx.base_env())
        overlay_entry_env(
            result.env, spec.env, source.syntax, ctx.shell_env, workspace=None, home=ctx.home, result=result
        )
        return result

    def command_notes(self, command: str, found: str | None, ctx: HostContext) -> list[Finding]:
        if ctx.platform != "darwin" or found is None or os.path.isabs(command):
            return []
        if shutil.which(command, path=_MACOS_LAUNCHD_PATH):
            return []
        directory = str(Path(found).parent)
        return [
            warn(
                f"`{command}` resolves only through {directory}, which is not on the macOS default PATH "
                f"({_MACOS_LAUNCHD_PATH}) Claude Desktop starts with; use the absolute path {found}"
            )
        ]


class CursorHost(Host):
    """Cursor is closed source: how it builds the environment is not known."""

    key = "cursor"
    label = "Cursor"

    def effective_env(self, spec: ServerSpec, source: Source, ctx: HostContext) -> EffectiveEnv:
        result = EffectiveEnv(env=ctx.env())
        overlay_entry_env(
            result.env, spec.env, source.syntax, ctx.shell_env, workspace=None, home=ctx.home, result=result
        )
        reason = "it works only if Cursor inherits this shell's variables"
        required = (BASE_URL_KEY, *token_keys(result.env))
        for key in required:
            if key in ctx.shell_env:
                result.may_supply[ctx.shell_env.fold(key)] = reason
        shell_token_variable = token_variable(ctx.shell_env)
        if (
            API_TOKEN_VAR_ENV_VAR not in result.env
            and shell_token_variable is not None
            and shell_token_variable in ctx.shell_env
        ):
            # No token in the entry, but the shell names the variable that holds one.
            result.may_supply[ctx.shell_env.fold(API_TOKEN_ENV_VAR)] = reason
        for name in ctx.shell_env.names_with_prefix("OPENPROJECT_"):
            if ctx.shell_env.fold(name) not in result.entry_keys and name not in required:
                result.notes.append(
                    unverified(
                        f"{name} is set in this shell but not in the entry; it changes the server if Cursor inherits it"
                    )
                )
        return result

    def command_notes(self, command: str, found: str | None, ctx: HostContext) -> list[Finding]:
        if os.path.isabs(command):
            return []
        return [unverified("Cursor's PATH when started outside a terminal is not verified")]


class ProcessEnvHost(Host):
    """The doctor's own environment, checked when no client configures OpenProject."""

    key = "process"
    label = "process environment"


@dataclass
class Subject:
    """One (host, entry) pair, or a host-level problem, as the doctor reports it."""

    host: Host
    # What the line is about besides the host, e.g. "openproject (.mcp.json, workspace)".
    label: str
    state: State = State.ACTIVE
    state_reason: str = ""
    findings: list[Finding] = field(default_factory=list)
    effective: EffectiveEnv | None = None
    # None when the command cannot be resolved or the entry has no usable command.
    command: str | None = None
    args: tuple[str, ...] = ()

    @property
    def identity(self) -> str:
        return " ".join(part for part in (self.host.label, self.label) if part)

    @property
    def counts(self) -> bool:
        return self.state in (State.ACTIVE, State.SHADOWED)


# ── helpers ─────────────────────────────────────────────────────────────────────


def claude_project_keys(cwd: Path) -> list[Path]:
    """Keys under which ``~/.claude.json`` may hold this directory's local scope.

    The git root of the current directory, or the directory itself outside a repository;
    in a worktree also the main repository's root.
    """
    toplevel = _git(cwd, "rev-parse", "--show-toplevel")
    if toplevel is None:
        return [cwd]
    keys = [Path(toplevel)]
    common = _git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if common is not None and Path(common).name == ".git" and Path(common).parent != Path(toplevel):
        keys.append(Path(common).parent)
    return keys


def _git(cwd: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = completed.stdout.strip()
    return output if completed.returncode == 0 and output else None


def launcher_package(args: Sequence[str]) -> str | None:
    """The package a ``uvx``/``uv``/``pipx`` launch installs, as written in ``args``."""
    for option in ("--from", "--spec"):
        if option in args:
            index = args.index(option)
            if index + 1 < len(args):
                return args[index + 1]
    return next((arg for arg in args if _OPENPROJECT_COMMAND_RE.search(arg)), None)
