"""Process environments as a child sees them, and how hosts substitute placeholders."""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Callable, Iterable, Iterator, Mapping, MutableMapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from ..config import API_TOKEN_ENV_VAR, API_TOKEN_VAR_ENV_VAR, ENV_VAR_NAME, ConfigConsistencyError
from .report import Finding

BASE_URL_KEY = "OPENPROJECT_BASE_URL"
REQUIRED_KEYS = (BASE_URL_KEY, API_TOKEN_ENV_VAR)
# Syntactically valid values that let the remaining keys be validated while a
# required key is missing or unresolvable; an entry using one is never probed.
STAND_IN_TOKEN = "stand-in-token"
# The name given to a stand-in token when the real name is a placeholder this doctor cannot resolve.
STAND_IN_TOKEN_VARIABLE = "STAND_IN_TOKEN_VARIABLE"
STAND_INS = {
    BASE_URL_KEY: "https://openproject.invalid",
    API_TOKEN_ENV_VAR: STAND_IN_TOKEN,
}
# What a finding calls the variable that OPENPROJECT_API_TOKEN_VAR names: the name itself is never printed, because
# a token pasted into OPENPROJECT_API_TOKEN_VAR would end up in output that people paste into issues.
NAMED_TOKEN_LABEL = f"the variable that {API_TOKEN_VAR_ENV_VAR} names"


def token_variable(values: Mapping[str, str]) -> str | None:
    """The variable that `OPENPROJECT_API_TOKEN_VAR` names, or None when it is unset or not a name (the settings
    check reports the latter)."""
    named = (values.get(API_TOKEN_VAR_ENV_VAR) or "").strip()
    return named if ENV_VAR_NAME.fullmatch(named) else None


def token_keys(values: Mapping[str, str]) -> tuple[str, ...]:
    """The variable that must hold the token: `OPENPROJECT_API_TOKEN`, or the one `OPENPROJECT_API_TOKEN_VAR` names.
    None when that value is not a name: the settings check reports it, and a stand-in would hide it."""
    if not (values.get(API_TOKEN_VAR_ENV_VAR) or "").strip():
        return (API_TOKEN_ENV_VAR,)
    named = token_variable(values)
    return () if named is None else (named,)


def with_stand_ins(values: Mapping[str, str]) -> dict[str, str]:
    """`values` with a stand-in for what they leave out, so the other settings can be validated on their own."""
    stand_ins = {BASE_URL_KEY: STAND_INS[BASE_URL_KEY]}
    stand_ins |= dict.fromkeys(token_keys(values), STAND_IN_TOKEN)
    return {**stand_ins, **values}


# The minimum a Python child needs to start and open sockets; without SYSTEMROOT a
# Windows child cannot create sockets at all.
_POSIX_BASE_KEYS = ("HOME", "USER", "PATH", "LOGNAME", "SHELL", "TMPDIR", "LANG")
_WINDOWS_BASE_KEYS = (
    *_POSIX_BASE_KEYS,
    "SYSTEMROOT",
    "WINDIR",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
)


def base_keys(platform: str) -> tuple[str, ...]:
    return _WINDOWS_BASE_KEYS if platform == "win32" else _POSIX_BASE_KEYS


class EnvMap(MutableMapping[str, str]):
    """A process environment as the child process will see it.

    On Windows a name exists once regardless of case, so names are folded for every
    lookup, overlay and removal while the last writer's spelling is kept for the child.
    """

    def __init__(self, items: Mapping[str, str] | Iterable[tuple[str, str]] = (), *, case_insensitive: bool) -> None:
        self.case_insensitive = case_insensitive
        self._items: dict[str, tuple[str, str]] = {}
        self.update(items)

    def fold(self, name: str) -> str:
        return name.upper() if self.case_insensitive else name

    def __getitem__(self, name: str) -> str:
        return self._items[self.fold(name)][1]

    def __setitem__(self, name: str, value: str) -> None:
        self._items[self.fold(name)] = (name, value)

    def __delitem__(self, name: str) -> None:
        del self._items[self.fold(name)]

    def __iter__(self) -> Iterator[str]:
        return (spelling for spelling, _ in self._items.values())

    def __len__(self) -> int:
        return len(self._items)

    def copy(self) -> EnvMap:
        return EnvMap(self, case_insensitive=self.case_insensitive)

    def names_with_prefix(self, prefix: str) -> list[str]:
        folded = self.fold(prefix)
        return [name for name in self if self.fold(name).startswith(folded)]

    def remove_ignoring_case(self, name: str) -> None:
        for existing in [n for n in self if n.upper() == name.upper()]:
            del self[existing]

    def as_dict(self) -> dict[str, str]:
        return dict(self._items.values())


@dataclass(frozen=True)
class SystemPaths:
    """Machine-wide files outside the user's home, separate so tests can relocate them."""

    claude_managed_settings: Path
    codex_system_config: Path
    codex_managed_config: Path | None

    @classmethod
    def for_platform(cls, platform: str, environ: Mapping[str, str]) -> SystemPaths:
        if platform == "win32":
            program_data = Path(environ.get("ProgramData") or r"C:\ProgramData")
            return cls(
                claude_managed_settings=Path(r"C:\Program Files\ClaudeCode\managed-settings.json"),
                codex_system_config=program_data / "OpenAI" / "Codex" / "config.toml",
                codex_managed_config=None,
            )
        claude_dir = "/Library/Application Support/ClaudeCode" if platform == "darwin" else "/etc/claude-code"
        return cls(
            claude_managed_settings=Path(claude_dir) / "managed-settings.json",
            codex_system_config=Path("/etc/codex/config.toml"),
            codex_managed_config=Path("/etc/codex/managed_config.toml"),
        )


@dataclass(frozen=True)
class HostContext:
    """What the doctor knows about the machine; the shell stands in for a host's own environment."""

    shell_env: EnvMap
    cwd: Path
    home: Path
    platform: str
    system: SystemPaths

    @classmethod
    def current(cls, cwd: Path) -> HostContext:
        platform = sys.platform
        return cls(
            shell_env=EnvMap(os.environ, case_insensitive=platform == "win32"),
            cwd=cwd,
            home=Path.home(),
            platform=platform,
            system=SystemPaths.for_platform(platform, os.environ),
        )

    @property
    def path_separator(self) -> str:
        return ";" if self.platform == "win32" else ":"

    def env(self, items: Mapping[str, str] | Iterable[tuple[str, str]] = ()) -> EnvMap:
        return EnvMap(items, case_insensitive=self.platform == "win32")

    def base_env(self) -> EnvMap:
        """The platform minimum every probe child gets from this shell."""
        return self.env((k, self.shell_env[k]) for k in base_keys(self.platform) if k in self.shell_env)


# ── placeholders ────────────────────────────────────────────────────────────────


class Syntax(Enum):
    LITERAL = "literal"  # the host passes values unchanged
    VSCODE = "vscode"  # ${env:X}, ${workspaceFolder}, ${userHome}, ${input:...}
    CLAUDE_CODE = "claude-code"  # ${X}, ${X:-default}
    COPILOT = "copilot"  # ${X}, ${X:-default} with shell-like defaults; bare $X stays literal
    UNKNOWN = "unknown"  # closed source: whether ${...} is substituted is not known


_VSCODE_VAR_RE = re.compile(r"\$\{([^}]*)\}")
# The exact pattern Claude Code's expansion uses.
_CLAUDE_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*(?::-[^}]*)?)\}")


def resolve(value: str, syntax: Syntax, lookup: Mapping[str, str], *, workspace: Path | None, home: Path) -> str | None:
    """The value the host would pass, or None when this doctor cannot know it.

    ``lookup`` stands in for the host's environment, so a referenced variable it lacks
    makes the value unknown rather than wrong.
    """
    if syntax is Syntax.LITERAL:
        return value
    if syntax is Syntax.UNKNOWN:
        return None if "${" in value else value
    if syntax is Syntax.COPILOT:
        return _expand_copilot(value, lookup)
    if syntax is Syntax.CLAUDE_CODE:
        unresolved = False

        def claude(match: re.Match[str]) -> str:
            nonlocal unresolved
            name, _, default = match.group(1).partition(":-")
            if name in lookup:
                return lookup[name]
            if ":-" in match.group(1):
                return default
            unresolved = True
            return ""

        result = _CLAUDE_VAR_RE.sub(claude, value)
        return None if unresolved else result

    missing = False

    def vscode(match: re.Match[str]) -> str:
        nonlocal missing
        variable = match.group(1)
        if variable.startswith("env:") and variable[4:] in lookup:
            return lookup[variable[4:]]
        if variable == "workspaceFolder" and workspace is not None:
            return str(workspace)
        if variable == "userHome":
            return str(home)
        missing = True
        return ""

    result = _VSCODE_VAR_RE.sub(vscode, value)
    return None if missing else result


# Port of VS Code's envVarResolution.ts (itself a port of the Copilot runtime's
# env_var_resolution) with bareReferences off, as VS Code expands `.mcp.json` and
# the Copilot CLI configuration.
_COPILOT_MAX_LENGTH = 1000


def _identifier_end(value: str, start: int) -> int | None:
    if start >= len(value) or not (value[start].isascii() and (value[start].isalpha() or value[start] == "_")):
        return None
    end = start + 1
    while end < len(value) and value[end].isascii() and (value[end].isalnum() or value[end] == "_"):
        end += 1
    return end


def _balanced_close_brace(value: str, start: int) -> int | None:
    unquoted, single, double = 0, 1, 2
    brace, parenthesis = 0, 1
    quoting = unquoted
    groups: list[tuple[int, int]] = []
    cursor = start
    while cursor < len(value):
        char = value[cursor]
        following = value[cursor + 1] if cursor + 1 < len(value) else ""
        consumed = 1
        if quoting == single:
            if char == "'":
                quoting = unquoted
            elif char == "}":
                return None
        elif char == "\\":
            if quoting == double and following == "}":
                return None
            consumed = 2
        elif quoting == double:
            if char == "}":
                return None
            if char == '"':
                quoting = unquoted
            elif char == "$" and following in ("{", "("):
                groups.append((brace if following == "{" else parenthesis, quoting))
                quoting = unquoted
                consumed = 2
        else:
            top = groups[-1] if groups else None
            if char == "'":
                quoting = single
            elif char == '"':
                quoting = double
            elif char in ("#", "`"):
                return None
            elif char == "$":
                if following in ("'", '"'):
                    return None
                if following in ("{", "("):
                    groups.append((brace if following == "{" else parenthesis, quoting))
                    quoting = unquoted
                    consumed = 2
            elif char == "<":
                if following == "<":
                    return None
            elif char == "(":
                if top is not None and top[0] == parenthesis:
                    groups.append((parenthesis, quoting))
            elif char == ")":
                if top is not None and top[0] == parenthesis:
                    quoting = top[1]
                    groups.pop()
            elif char == "}":
                if top is None:
                    return cursor
                if top[0] == brace:
                    quoting = top[1]
                    groups.pop()
        cursor += consumed
    return None


def _copilot_reference(value: str, start: int) -> tuple[str, str | None, int] | None:
    """(name, default, end) of the ``${...}`` reference at ``start``, if it is one."""
    if value[start + 1 : start + 2] != "{":
        return None
    name_end = _identifier_end(value, start + 2)
    if name_end is None:
        return None
    name = value[start + 2 : name_end]
    if value[name_end : name_end + 1] == "}":
        return name, None, name_end + 1
    if value[name_end : name_end + 2] != ":-":
        return None
    default_start = name_end + 2
    close = _balanced_close_brace(value, default_start)
    if close is None:
        first = value.find("}", default_start)
        close = None if first == -1 else first
    if close is None:
        return None
    return name, value[default_start:close], close + 1


def _expand_copilot(value: str, lookup: Mapping[str, str]) -> str | None:
    if len(value) > _COPILOT_MAX_LENGTH:
        return value
    result: list[str] = []
    cursor = 0
    start = value.find("$")
    while start != -1:
        result.append(value[cursor:start])
        reference = _copilot_reference(value, start)
        if reference is None:
            result.append("$")
            cursor = start + 1
        else:
            name, default, end = reference
            if name in lookup:
                result.append(lookup[name])
            elif default is not None:
                result.append(default)
            else:
                return None
            cursor = end
        start = value.find("$", cursor)
    result.append(value[cursor:])
    return "".join(result)


# ── effective environment ───────────────────────────────────────────────────────


@dataclass
class EffectiveEnv:
    env: EnvMap
    # Keys whose value this doctor cannot know (folded names).
    unresolved: set[str] = field(default_factory=set)
    # Keys the host might still supply although absent here, with the reason.
    may_supply: dict[str, str] = field(default_factory=dict)
    # Set for hosts that inherit their own environment: why any absent key may still arrive.
    inherits: str | None = None
    notes: list[Finding] = field(default_factory=list)
    # Codex locality was resolved from readable layers only; every derived result inherits this.
    assumed_local: bool = False
    # Only the values the entry sets were checked; values that need other sources are not FAILs.
    entry_values_only: bool = False
    # Keys the entry itself sets (folded): only these can make a contradiction certain.
    entry_keys: set[str] = field(default_factory=set)


def overlay_entry_env(
    target: EnvMap,
    spec_env: Mapping[str, str | None],
    syntax: Syntax,
    lookup: Mapping[str, str],
    *,
    workspace: Path | None,
    home: Path,
    result: EffectiveEnv,
    append_path_with: str | None = None,
) -> None:
    for key, raw in spec_env.items():
        result.entry_keys.add(target.fold(key))
        if raw is None:
            target.pop(key, None)
            continue
        value = resolve(raw, syntax, lookup, workspace=workspace, home=home)
        if value is None:
            result.unresolved.add(target.fold(key))
            target[key] = raw
        elif append_path_with and target.fold(key) == target.fold("PATH") and target.get("PATH"):
            target[key] = target["PATH"] + append_path_with + value
        else:
            target[key] = value


def certain_contradiction(error: ConfigConsistencyError, owned: Callable[[str], bool]) -> str | None:
    """The first broken rule whose variables are all ``owned``: other sources cannot resolve it."""
    return next((message for message, keys in error.violations if all(owned(key) for key in keys)), None)
