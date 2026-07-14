#!/usr/bin/env python3
# This is the interactive MCP server setup, not a packaging file.
# Run via the installed console command: openproject-ce-mcp configure
#   (or the openproject-ce-mcp-setup alias)
# From a source checkout it also runs via ./get.sh / .\get.ps1 or
# `python3 configure_mcp.py` (a thin shim that imports this module).
"""Interactive setup: registers the openproject MCP server with clients and writes .mcp.json.

Runs in two modes:

* **installed** — the package was installed from PyPI (pip/uv/pipx). The server
  command written into client configs is the installed ``openproject-ce-mcp``
  binary (resolved via PATH), and ``.mcp.json`` is written to the current
  directory (project-local) or a global client config.
* **clone** — running from a source checkout. Dependencies are installed with
  ``uv``/pip, the command points at ``.venv/bin/openproject-ce-mcp``, and
  project-scoped config lands in the launch directory.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Literal, NamedTuple

import httpx

from openproject_ce_mcp.client import (
    AuthenticationError,
    InvalidInputError,
    NotFoundError,
    OpenProjectClient,
    OpenProjectError,
    OpenProjectServerError,
    PermissionDeniedError,
    TransportError,
)
from openproject_ce_mcp.config import ConfigError, Settings, tool_exposure_violations

# tomllib is stdlib only on Python 3.11+. This installer supports 3.10 (which
# lacks it) and must stay dependency-free, so import it optionally. When present
# we use it to *validate* merged TOML before writing; when absent we fall back to
# the text-level checks in _merge_codex_toml.
try:
    import tomllib as _tomllib
except ModuleNotFoundError:  # Python 3.10
    _tomllib = None

# This file lives at src/openproject_ce_mcp/setup_cli.py inside a checkout. The
# repo root (two levels up) then contains pyproject.toml and the source tree;
# when installed into site-packages it does not. That difference is our mode
# signal — see _installed_mode().
_PKG_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _PKG_DIR.parent.parent
VENV = _REPO_ROOT / ".venv"

_IS_WINDOWS = sys.platform == "win32"
_IS_MACOS = sys.platform == "darwin"

_SERVER_BIN = "openproject-ce-mcp"


# ── run mode ────────────────────────────────────────────────────────────────────


def _installed_mode() -> bool:
    """True when running from an installed wheel rather than a source checkout.

    A checkout has ``src/openproject_ce_mcp/setup_cli.py`` == this file and a
    ``pyproject.toml`` two levels up; site-packages has neither of those markers.
    """
    return not (
        (_REPO_ROOT / "pyproject.toml").exists()
        and Path(__file__).resolve() == (_REPO_ROOT / "src" / "openproject_ce_mcp" / "setup_cli.py")
    )


def _looks_like_project_dir(path: Path) -> bool:
    """Heuristic: does ``path`` look like a project the user wants a local config in?

    A local ``.mcp.json`` only makes sense in a project directory. We treat the
    presence of a VCS/project marker as the signal; an existing ``.mcp.json``
    also counts (re-running setup in a dir already configured locally).
    """
    markers = (".git", ".mcp.json", "pyproject.toml", "package.json", ".hg", ".svn")
    return any((path / m).exists() for m in markers)


def _project_cwd() -> Path:
    """Directory the user launched configure from, used for project-scoped files.

    ``uv run --directory <repo> ...`` changes the process cwd to the repo so it
    can resolve the project, but keeps PWD pointing at the user's shell
    directory. For project-scoped MCP config, that launch directory is the least
    surprising target.
    """
    pwd = os.environ.get("PWD")
    if pwd:
        path = Path(pwd)
        if path.is_absolute() and path.is_dir():
            return path
    return Path.cwd()


def _resolve_mcp_json(scope: str | None, installed: bool) -> Path | None:
    """Resolve where the project-local ``.mcp.json`` goes, or ``None`` for global.

    This owns the whole scope policy in one place:

    * ``scope="global"`` → ``None`` (no project file; register clients instead),
    * ``scope="local"`` → launch directory,
    * ``scope=None`` (auto) → source/clone mode writes to the launch directory;
      installed mode writes a local file only when the launch directory looks
      like a project, otherwise ``None`` (global registration).
    """
    if scope == "global":
        return None
    if scope == "local":
        return _project_cwd() / ".mcp.json"
    if not installed:
        return _project_cwd() / ".mcp.json"
    if _looks_like_project_dir(_project_cwd()):
        return _project_cwd() / ".mcp.json"
    return None


# ── helpers ───────────────────────────────────────────────────────────────────


def _venv_binary() -> Path:
    if _IS_WINDOWS:
        return VENV / "Scripts" / f"{_SERVER_BIN}.exe"
    return VENV / "bin" / _SERVER_BIN


def _server_command(installed: bool) -> tuple[str, bool]:
    """The ``command`` value for client configs, and whether it is a resolved path.

    Returns ``(command, resolved)``. ``resolved`` is False only when we had to
    fall back to the bare name ``openproject-ce-mcp`` — the caller warns in that
    case, because a bare name fails for GUI clients that do not inherit the shell
    PATH.

    Installed mode: prefer ``shutil.which`` (on PATH for pip/pipx/uv-tool
    installs); else a sibling of the running launcher in the same bin/Scripts
    directory (covers uvx/pipx shim dirs off PATH). The launcher is located via
    ``sys.argv[0]``; when that is a bare name we still resolve it through PATH so
    the sibling probe works even for basename-style argv[0].

    Clone mode: the project's ``.venv`` binary, exactly as before (always resolved).
    """
    if not installed:
        return str(_venv_binary()), True

    resolved = shutil.which(_SERVER_BIN)
    if resolved:
        return resolved, True

    # Locate the launcher (openproject-ce-mcp-setup) so we can look for the server
    # binary next to it. A bare-basename argv[0] would resolve against CWD, which
    # is wrong — run it through PATH first so we find the real launcher location.
    argv0 = sys.argv[0]
    launcher = Path(shutil.which(argv0) or argv0).resolve() if os.sep not in argv0 else Path(argv0).resolve()
    exe = f"{_SERVER_BIN}.exe" if _IS_WINDOWS else _SERVER_BIN
    sibling = launcher.with_name(exe)
    if sibling.exists():
        return str(sibling), True

    return _SERVER_BIN, False


# ── global client registration ─────────────────────────────────────────────────
#
# The interactive setup can optionally write a *user-wide* (global) config for any
# MCP client it detects on this machine. Global config means every project sees
# this OpenProject instance with these permissions — convenient, but broad. The
# project-scoped setup documented in docs/ is the recommended path; global writing
# is opt-in per client and defaults to "no".


def _home() -> Path:
    return Path.home()


def _vscode_user_mcp_path() -> Path:
    """User-wide MCP config for VS Code (GitHub Copilot)."""
    if _IS_WINDOWS:
        base = Path(os.environ.get("APPDATA", _home() / "AppData" / "Roaming"))
        return base / "Code" / "User" / "mcp.json"
    if _IS_MACOS:
        return _home() / "Library" / "Application Support" / "Code" / "User" / "mcp.json"
    return _home() / ".config" / "Code" / "User" / "mcp.json"


def _claude_desktop_path() -> Path:
    """User-wide MCP config for the standalone Claude Desktop app."""
    if _IS_WINDOWS:
        base = Path(os.environ.get("APPDATA", _home() / "AppData" / "Roaming"))
        return base / "Claude" / "claude_desktop_config.json"
    if _IS_MACOS:
        return _home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    return _home() / ".config" / "Claude" / "claude_desktop_config.json"


def _server_entry(command: str, env: dict[str, str], *, stdio: bool) -> dict:
    entry: dict[str, object] = {}
    if stdio:
        entry["type"] = "stdio"
    entry["command"] = command
    entry["env"] = env
    return entry


def _merge_json(existing: str, root_key: str, command: str, env: dict[str, str], *, stdio: bool) -> str:
    """Insert/replace only the ``openproject`` server under ``root_key``.

    Everything else in the file (other servers, unrelated user settings) is
    preserved. ``existing`` is the current file text, or "" for a new file.
    """
    data: dict = {}
    if existing.strip():
        loaded = json.loads(existing)  # may raise; caller surfaces a clear error
        if not isinstance(loaded, dict):
            # Parsed fine but the shape is wrong (list/str/number at top level).
            # Treat this like a parse failure so the caller leaves the file
            # untouched instead of us silently discarding the user's data.
            raise ValueError(f"expected a JSON object at the top level, got {type(loaded).__name__}")
        data = loaded
    servers = data.get(root_key)
    if servers is None:
        servers = {}
    elif not isinstance(servers, dict):
        # e.g. "mcpServers": [] — refuse rather than overwrite the user's value.
        raise ValueError(f'expected "{root_key}" to be a JSON object, got {type(servers).__name__}')
    servers["openproject"] = _server_entry(command, env, stdio=stdio)
    data[root_key] = servers
    return json.dumps(data, indent=2) + "\n"


def _toml_quote(value: str) -> str:
    """Quote a string for a TOML basic string (escapes backslash and quote)."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _codex_block(command: str, env: dict[str, str]) -> str:
    """The ``[mcp_servers.openproject]`` table as TOML text (no trailing blank)."""
    lines = ["[mcp_servers.openproject]", f"command = {_toml_quote(command)}", ""]
    lines.append("[mcp_servers.openproject.env]")
    for key, val in env.items():
        lines.append(f"{key} = {_toml_quote(val)}")
    return "\n".join(lines)


# A real TOML table header: a whole line that is just ``[name]`` (or ``[[name]]``),
# optionally followed by a comment. Crucially this does NOT match a continuation
# line of a multi-line array value such as ``  ["--flag"],`` — those start with
# ``[`` but are not headers. Matching only true headers is what keeps multi-line
# array values inside a table from being mistaken for the end of that table.
# Limitation (accepted): a header whose quoted key contains a literal ``]`` (e.g.
# ``["weird]name"]``) is not recognized. Codex never emits such names; the worst
# case is that _merge_codex_toml's tomllib round-trip check (3.11+) rejects the
# result and we refuse to write — fail-safe, not corruption.
_TOML_HEADER_RE = re.compile(r"^\[\[?[^\]]+\]\]?\s*(#.*)?$")

# The openproject server expressed as a dotted key or inline table at top level,
# e.g. ``mcp_servers.openproject = { ... }`` or ``mcp_servers.openproject.command
# = "…"``. Codex does not emit this form, but a hand-edited config might. We can't
# safely rewrite it with text edits (no TOML writer on 3.10), so we detect it and
# refuse rather than append a ``[mcp_servers.openproject]`` header that would
# collide with it ("Cannot declare openproject twice").
_CODEX_DOTTED_RE = re.compile(r"^mcp_servers\.openproject(\.[^\s=]+)?\s*=")


class CodexMergeError(ValueError):
    """Raised when a Codex config can't be safely merged by text editing.

    Subclasses ValueError so the existing ``except (json.JSONDecodeError,
    ValueError)`` guard in _write_client_config catches it and leaves the file
    untouched.
    """


def _strip_codex_openproject(existing: str) -> str:
    """Remove any existing [mcp_servers.openproject] / .env tables from TOML text.

    The stdlib has no TOML writer, so we edit text: drop the openproject tables
    (and their key/value lines up to the next table header) and keep the rest of
    the file verbatim. Other tables and top-level keys are untouched.

    Only genuine ``[table]`` header lines start/stop skipping — a multi-line array
    value whose continuation lines begin with ``[`` (e.g. ``args = [\\n ["x"],\\n]``)
    does NOT toggle skipping, so such tables survive intact. Prefix siblings like
    ``[mcp_servers.openproject2]`` are preserved.

    Raises CodexMergeError if openproject is expressed as a dotted key / inline
    table, which this text approach cannot safely rewrite.
    """
    out: list[str] = []
    skipping = False
    for line in existing.splitlines():
        stripped = line.strip()
        if _CODEX_DOTTED_RE.match(stripped):
            raise CodexMergeError(
                "existing openproject entry uses a dotted key or inline table; cannot merge by text edit"
            )
        if _TOML_HEADER_RE.match(stripped):
            table = stripped.lstrip("[").rstrip("]").strip()
            skipping = table == "mcp_servers.openproject" or table.startswith("mcp_servers.openproject.")
        if not skipping:
            out.append(line)
    return "\n".join(out)


def _merge_codex_toml(existing: str, command: str, env: dict[str, str]) -> str:
    """Preserve the rest of the Codex config, replacing only the openproject table.

    On Python 3.11+ the merged output is parsed with tomllib as a final guard: if
    it does not round-trip to valid TOML with the expected openproject command,
    we raise CodexMergeError rather than write a corrupt config. On 3.10 (no
    tomllib) we rely on the text-level checks in _strip_codex_openproject.
    """
    kept = _strip_codex_openproject(existing).rstrip()
    block = _codex_block(command, env)
    merged = f"{kept}\n\n{block}\n" if kept else f"{block}\n"
    if _tomllib is not None:
        try:
            data = _tomllib.loads(merged)
        except _tomllib.TOMLDecodeError as exc:
            raise CodexMergeError(f"merged Codex config is not valid TOML ({exc})") from exc
        server = data.get("mcp_servers", {}).get("openproject", {})
        if server.get("command") != command:
            raise CodexMergeError("merged Codex config did not round-trip openproject")
    return merged


class Client:
    """A registerable MCP client: how to detect it and where its config lives.

    ``target`` is the user-wide (global) config path; ``project_target`` is the
    project-local (cwd-relative) path, or ``None`` when the client has no
    project-local config (Claude Desktop). ``restart_hint`` is how the user makes
    the client pick up a newly written config.
    """

    def __init__(
        self,
        key: str,
        label: str,
        target: Path,
        fmt: str,
        detect,
        doc: str,
        *,
        root_key: str = "",
        stdio: bool = False,
        project_target: Path | None = None,
        restart_hint: str = "",
    ) -> None:
        self.key = key
        self.label = label
        self.target = target  # global / user-wide
        self.fmt = fmt  # "json" or "toml"
        self._detect = detect
        self.doc = doc
        self.root_key = root_key
        self.stdio = stdio
        self.project_target = project_target  # cwd-relative; None = global-only
        self.restart_hint = restart_hint

    def detected(self) -> bool:
        return self._detect()

    def target_for(self, scope: str) -> Path | None:
        """Return the config path for ``scope`` ("global" | "project")."""
        return self.target if scope == "global" else self.project_target

    def merge(self, existing: str, command: str, env: dict[str, str]) -> str:
        # Format is a property of the client, not the scope: the same JSON/TOML
        # shape is written to either the global or the project-local target.
        if self.fmt == "toml":
            return _merge_codex_toml(existing, command, env)
        return _merge_json(existing, self.root_key, command, env, stdio=self.stdio)


# Detection tradeoff: each heuristic prefers a strong signal (the client's binary
# on PATH) and falls back to a client-specific marker. We deliberately key the
# fallbacks off markers the client *owns* (its own dotfile / app-support folder /
# per-user config dir) rather than broad shared paths, to cut false positives
# (offering to configure a client that isn't installed) without risking false
# negatives for a genuinely-installed client. We do NOT tighten all the way down
# to "the MCP config file already exists", because that would miss an installed
# client that has simply never registered an MCP server yet — the exact case this
# installer exists to handle. Registration is opt-in and defaults to No, so a
# stray false positive only costs one extra "n" at the prompt.


def _detect_claude_code() -> bool:
    return bool(shutil.which("claude")) or (_home() / ".claude.json").exists() or (_home() / ".claude").exists()


def _detect_claude_desktop() -> bool:
    # The app-support "Claude" folder is created by the Desktop app itself, so its
    # presence is a client-specific marker (not shared with the CLI, which uses
    # ~/.claude). We check the folder rather than the config file so a freshly
    # installed app that has never configured MCP is still detected.
    return _claude_desktop_path().parent.exists()


def _detect_codex() -> bool:
    return bool(shutil.which("codex")) or (_home() / ".codex").exists()


def _detect_vscode() -> bool:
    # Fall back to the per-user "Code/User" directory (where mcp.json lives), not
    # the broader "Code" root: "Code/User" is created once the user has actually
    # run VS Code, which is a tighter signal than the top-level config dir while
    # still not requiring an existing mcp.json.
    return bool(shutil.which("code")) or _vscode_user_mcp_path().parent.exists()


def _detect_cursor() -> bool:
    return bool(shutil.which("cursor")) or (_home() / ".cursor").exists()


def _clients() -> list[Client]:
    # project_target is launch-directory-relative so it honours the directory the
    # user ran configure from, even under `uv run --directory <repo>`.
    cwd = _project_cwd()
    return [
        Client(
            "claude-code",
            "Claude Code (CLI + IDE extension)",
            _home() / ".claude.json",
            "json",
            _detect_claude_code,
            "docs/claude.md",
            root_key="mcpServers",
            project_target=cwd / ".mcp.json",
            restart_hint="run /mcp in Claude Code, or start a new session",
        ),
        Client(
            "claude-desktop",
            "Claude Desktop app",
            _claude_desktop_path(),
            "json",
            _detect_claude_desktop,
            "docs/claude-desktop.md",
            root_key="mcpServers",
            project_target=None,  # global-only
            restart_hint="quit Claude Desktop completely and reopen it (a window reload is not enough)",
        ),
        Client(
            "codex",
            "Codex (CLI + IDE extension)",
            _home() / ".codex" / "config.toml",
            "toml",
            _detect_codex,
            "docs/codex.md",
            project_target=cwd / ".codex" / "config.toml",
            restart_hint="reload the editor window or restart Codex",
        ),
        Client(
            "vscode",
            "VS Code (GitHub Copilot)",
            _vscode_user_mcp_path(),
            "json",
            _detect_vscode,
            "docs/github.md",
            root_key="servers",
            stdio=True,
            project_target=cwd / ".vscode" / "mcp.json",
            restart_hint="Start/Restart the server from the MCP view, or run 'Developer: Reload Window'",
        ),
        Client(
            "cursor",
            "Cursor",
            _home() / ".cursor" / "mcp.json",
            "json",
            _detect_cursor,
            "docs/cursor.md",
            root_key="mcpServers",
            project_target=cwd / ".cursor" / "mcp.json",
            restart_hint="reload the Cursor window",
        ),
    ]


def _write_client_config(client: Client, command: str, env: dict[str, str], *, target: Path | None = None) -> bool:
    """Merge the ``openproject`` server into a client config at ``target``.

    ``target`` defaults to the client's global config; pass ``client.project_target``
    for the project-local file. Existing content is preserved — only the
    ``openproject`` entry is added or replaced — and a timestamped backup is taken
    before any existing file is rewritten. Returns True on success, False if the
    existing file could not be parsed. The rest of the body uses the local
    ``target`` throughout (never ``client.target``) so project-local writes land in
    the right file.
    """
    target = target if target is not None else client.target
    existing = ""
    if target.exists():
        existing = target.read_text(encoding="utf-8")
        try:
            merged = client.merge(existing, command, env)
        except (json.JSONDecodeError, ValueError) as exc:
            print(f"  ! {target} exists but could not be parsed ({exc}).")
            print(f"    Leaving it untouched. Add the server by hand — see {client.doc}.")
            return False
        print(f"  · Updating {target} (existing settings are preserved).")
        _backup(target)
    else:
        merged = client.merge("", command, env)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(merged, encoding="utf-8")
    if not _IS_WINDOWS:
        target.chmod(0o600)
    print(f"  ✓ Wrote {target}")
    _git_warning_for_unignored_file(target)
    _git_warning_for_unignored_file(target.with_name(f"{target.name}.bak.example"))
    return True


def _remove_json_openproject(existing: str, root_key: str) -> str | None:
    """Remove only the ``openproject`` server under ``root_key``; keep the rest.

    Returns the new text, or None if nothing changed (no openproject entry).
    Raises ValueError on an unexpected shape (caller leaves the file untouched).
    """
    if not existing.strip():
        return None
    data = json.loads(existing)
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object at the top level, got {type(data).__name__}")
    servers = data.get(root_key)
    if not isinstance(servers, dict) or "openproject" not in servers:
        return None
    del servers["openproject"]
    if servers:
        data[root_key] = servers
    else:
        # Drop an emptied server map so we don't leave "mcpServers": {}
        data.pop(root_key, None)
    return json.dumps(data, indent=2) + "\n"


def _remove_client_config(client: Client, *, target: Path | None = None) -> bool:
    """Remove the openproject entry from a client config at ``target``; keep the rest.

    ``target`` defaults to the client's global config; pass ``client.project_target``
    for the project-local file. Backs up before rewriting. Returns True if something
    was removed.
    """
    target = target if target is not None else client.target
    if target is None or not target.exists():
        return False
    existing = target.read_text(encoding="utf-8")
    try:
        if client.fmt == "toml":
            stripped = _strip_codex_openproject(existing).rstrip()
            new_text = (stripped + "\n") if stripped else ""
            changed = new_text.strip() != existing.strip()
        else:
            merged = _remove_json_openproject(existing, client.root_key)
            changed = merged is not None
            new_text = merged if merged is not None else existing
    except (json.JSONDecodeError, ValueError, CodexMergeError) as exc:
        print(f"  ! {target} could not be parsed ({exc}). Leaving it untouched.")
        return False
    if not changed:
        return False
    _backup(target)
    target.write_text(new_text, encoding="utf-8")
    if not _IS_WINDOWS and new_text:
        target.chmod(0o600)
    print(f"  ✓ Removed openproject from {target}")
    return True


def _run_uninstall() -> None:
    """Remove the openproject entry from client configs (existing settings kept).

    Removes from BOTH the user-wide (global) config of each client AND the
    project-local config in the current directory (mirroring what configure now
    writes). Output is grouped by scope, one line per target with its status. The
    venv/caches of a source checkout are handled by uninstall.sh/.ps1.
    """
    clients = _clients()

    def _clean(scope: str, targets: list[tuple[Client, Path]]) -> bool:
        removed = False
        for client, target in targets:
            if not target.exists():
                print(f"  · {client.label}: {target} — not found")
                continue
            if _remove_client_config(client, target=target):
                removed = True  # message printed inside _remove_client_config
            else:
                print(f"  · {client.label}: {target} — no openproject entry / skipped")
        return removed

    print("Removing the openproject server from client configs (existing settings kept)…")
    print()
    print("User-wide (global):")
    removed_global = _clean("global", [(c, c.target) for c in clients])
    print()
    print(f"Project-local (this directory: {Path.cwd()}):")
    removed_project = _clean("project", [(c, c.project_target) for c in clients if c.project_target is not None])

    print()
    if not (removed_global or removed_project):
        print("No client config contained an openproject entry — nothing removed.")
    else:
        print("Done. Restart any client you had it registered in.")


def _check_python() -> None:
    # Intentional runtime guard: this setup script may be launched by whatever
    # interpreter the user has on PATH, which can predate the project minimum.
    if sys.version_info < (3, 10):  # noqa: UP036
        print(f"Python 3.10+ required. Current: {sys.version}", file=sys.stderr)
        sys.exit(1)


def _find_uv() -> str | None:
    return shutil.which("uv")


def _install_deps(uv: str | None, installed: bool) -> None:
    # Installed mode: the package (and its console scripts) already exist — that
    # is how this setup was launched — so there is nothing to install.
    if installed:
        return
    if uv:
        print("Installing with uv …")
        subprocess.run([uv, "sync"], cwd=_REPO_ROOT, check=True)
    else:
        print("uv not found — falling back to venv + pip …")
        if not VENV.exists():
            subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
        pip = VENV / ("Scripts" if _IS_WINDOWS else "bin") / "pip"
        subprocess.run([str(pip), "install", "-e", "."], cwd=_REPO_ROOT, check=True)


def _read_client_env(client: Client, *, target: Path | None = None) -> dict[str, str]:
    """Read back an already-registered openproject ``env`` from a client config.

    ``target`` defaults to the client's global config; pass ``client.project_target``
    to read the project-local file. Used to pre-fill prompt defaults so amending a
    single flag does not force re-entering the base URL and token. Returns {} if the
    file has no config yet or its openproject entry can't be read; TOML (Codex) is
    not parsed for prefill on Python 3.10 (no tomllib) and returns {}.
    """
    target = target if target is not None else client.target
    if target is None or not target.exists():
        return {}
    try:
        text = target.read_text(encoding="utf-8")
        if client.fmt == "toml":
            if _tomllib is None:
                return {}
            data = _tomllib.loads(text)
            return data.get("mcp_servers", {}).get("openproject", {}).get("env", {})
        data = json.loads(text)
        return data.get(client.root_key, {}).get("openproject", {}).get("env", {})
    except Exception:
        return {}


def _backup(path: Path) -> None:
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    # Append to the full name so the original extension is preserved
    # (config.toml → config.toml.bak.<ts>), not replaced.
    dest = path.with_name(f"{path.name}.bak.{ts}")
    # The timestamp has 1-second resolution, so a second backup in the same
    # second would otherwise clobber the first via rename(). Append a counter
    # to keep every backup.
    if dest.exists():
        counter = 1
        while True:
            candidate = path.with_name(f"{path.name}.bak.{ts}.{counter}")
            if not candidate.exists():
                dest = candidate
                break
            counter += 1
    path.rename(dest)
    if not _IS_WINDOWS:
        dest.chmod(0o600)
    print(f"Backed up {path.name} → {dest.name}")


def _nearest_existing_parent(path: Path) -> Path:
    current = path if path.is_dir() else path.parent
    while not current.exists() and current != current.parent:
        current = current.parent
    return current


def _git_warning_for_unignored_file(path: Path) -> None:
    """Warn when a project-scoped credential file would be tracked by Git."""
    anchor = _nearest_existing_parent(path)
    try:
        in_work_tree = subprocess.run(
            ["git", "-C", str(anchor), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return
    if in_work_tree.returncode != 0 or in_work_tree.stdout.strip() != "true":
        return

    ignored = subprocess.run(
        ["git", "-C", str(anchor), "check-ignore", "-q", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if ignored.returncode == 0:
        return

    print(f"  ! {path} is inside a Git repository but is not ignored.")
    print("    It contains credentials; add it and its backups to .gitignore before committing.")


def _write_mcp_json(env: dict[str, str], mcp_json: Path, command: str) -> None:
    existing = mcp_json.read_text(encoding="utf-8") if mcp_json.exists() else ""
    # Merge first: if the existing file has an unexpected shape, _merge_json
    # raises and we must leave it untouched (do NOT back up then abort, which
    # would strand the user's data in a .bak with no working file written).
    try:
        merged = _merge_json(existing, "mcpServers", command, env, stdio=False)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"Could not update {mcp_json}: {exc}", file=sys.stderr)
        print("Left it untouched. Fix or remove the file by hand, then re-run.", file=sys.stderr)
        return
    if mcp_json.exists():
        _backup(mcp_json)
    mcp_json.parent.mkdir(parents=True, exist_ok=True)
    mcp_json.write_text(merged, encoding="utf-8")
    if not _IS_WINDOWS:
        mcp_json.chmod(0o600)
    print(f"Written: {mcp_json}")
    _git_warning_for_unignored_file(mcp_json)
    _git_warning_for_unignored_file(mcp_json.with_name(f"{mcp_json.name}.bak.example"))


# ── prompts ───────────────────────────────────────────────────────────────────


def _prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        value = input(f"{label}{suffix}: ").strip()
    except EOFError:
        print(f"{label}{suffix}: (no input — using default)")
        return default
    return value if value else default


def _prompt_secret(label: str, has_existing: bool = False) -> str:
    hint = " [leave empty to keep current]" if has_existing else ""
    try:
        return getpass.getpass(f"{label}{hint}: ").strip()
    except (EOFError, OSError):
        # Non-interactive fallback (e.g. piped input in tests)
        try:
            return input(f"{label}{hint}: ").strip()
        except EOFError:
            return ""


def _prompt_bool(label: str, default: bool = False) -> bool:
    suffix = " [Y/n]" if default else " [y/N]"
    try:
        answer = input(f"{label}{suffix}: ").strip().lower()
    except EOFError:
        # No interactive input (e.g. `curl … | sh` left stdin as the pipe).
        # Fall back to the default rather than crashing.
        print(f"{label}{suffix}: (no input — using default)")
        return default
    if not answer:
        return default
    return answer in ("y", "yes")


def _bool_from_env(env: dict[str, str], key: str, fallback: bool = False) -> bool:
    val = env.get(key, "").lower()
    if val in ("true", "1", "yes"):
        return True
    if val in ("false", "0", "no"):
        return False
    return fallback


_WRITE_SCOPE_FLAG_KEYS = (
    "OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE",
    "OPENPROJECT_ENABLE_PROJECT_WRITE",
    "OPENPROJECT_ENABLE_MEMBERSHIP_WRITE",
    "OPENPROJECT_ENABLE_VERSION_WRITE",
    "OPENPROJECT_ENABLE_BOARD_WRITE",
)


def _classify_write_scope(
    existing: dict[str, str],
    *,
    write_projects_existing: str,
) -> Literal["none", "work-packages", "all", "custom"]:
    """Classify the effective write scope for the quick-mode prompt's default.

    write_projects_existing must be the already-resolved value from
    _merge_scope_prefill (legacy-vs-new precedence handled there), not a raw
    lookup in ``existing`` — ``existing`` (from _merge_prefill) drops explicit
    empty values and doesn't translate the legacy scope key.

    An empty writable-projects scope means no project can actually be written
    to, regardless of what the five write flags say (see
    _ensure_project_write_allowed), so it always classifies as "none" —
    never letting a dormant flag combination resolve to a non-"none" default
    that could silently expand access if the prompt's default is accepted.
    """
    if not write_projects_existing.strip():
        return "none"
    flags = tuple(_bool_from_env(existing, key, True) for key in _WRITE_SCOPE_FLAG_KEYS)
    if not any(flags):
        return "none"
    if all(flags):
        return "all"
    if flags == (True, False, False, False, False):
        return "work-packages"
    return "custom"


def _parse_write_scope_choice(raw: str, *, allowed: frozenset[str], default: str) -> str | None:
    """Strict exact-match parser for the quick-mode write-scope prompt.

    Deliberately no prefix/fuzzy matching — "all" materially expands write
    permissions, so an ambiguous or mistyped answer must be rejected and
    re-prompted, never guessed.
    """
    value = raw.strip().lower()
    if not value:
        return default
    if value in allowed:
        return value
    return None


def _scope_prefill(existing: dict[str, str], new_key: str, legacy_keys: list[str]) -> tuple[str, bool]:
    """Resolve a project-scope prefill by key presence, not truthiness.

    A present-but-empty new key (an explicit, deliberate lock-down) must win over
    any legacy key's value — falsy-or-chaining would silently resurrect the old
    value and defeat the point of the migration.
    """
    if new_key in existing:
        return existing[new_key], False
    for legacy_key in legacy_keys:
        if legacy_key in existing:
            return existing[legacy_key], True
    return "", False


def _has_openproject_config(client: Client, target: Path | None) -> bool:
    target = target if target is not None else client.target
    if target is None or not target.exists():
        return False
    try:
        text = target.read_text(encoding="utf-8")
        if client.fmt == "toml":
            for line in text.splitlines():
                stripped = line.strip()
                if _CODEX_DOTTED_RE.match(stripped):
                    return True
                if _TOML_HEADER_RE.match(stripped):
                    table = stripped.lstrip("[").rstrip("]").strip()
                    if table == "mcp_servers.openproject" or table.startswith("mcp_servers.openproject."):
                        return True
            return False
        data = json.loads(text)
        servers = data.get(client.root_key) if isinstance(data, dict) else None
        return isinstance(servers, dict) and "openproject" in servers
    except Exception:
        return False


def _choose_targets(clients: list[Client]) -> tuple[list[Client], list[Client], list[Client], list[Client]]:
    """Two independent gates deciding WHERE to configure the server.

    Returns ``(global_clients, project_clients, remove_global_clients,
    remove_project_clients)``. The gates run before any credentials are collected
    so the user decides the targets first, and CONFIGURE (not install) is the
    wording throughout. Deselected scopes with an existing openproject entry ask
    whether that entry should be removed.

    * Gate 1 (global / user-wide) offers only DETECTED clients — a user-wide config
      for a client that isn't installed makes no sense.
    * Gate 2 (project-scoped) offers ALL project-capable clients (``project_target``
      set), detected or not: a fresh IDE setup can want ``.codex/config.toml`` even
      when the ``codex`` CLI isn't on PATH yet. Detection only sets the default
      answer (detected → yes), never the availability.
    * Configuring both scopes in one run is intentionally not offered. Run
      configure twice if you want separate global and project-scoped entries.
    """
    detected = [c for c in clients if c.detected()]
    project_capable = [c for c in clients if c.project_target is not None]

    print()
    if detected:
        print("Detected MCP clients:")
        for client in detected:
            print(f"  - {client.label}")
        print()

    global_clients: list[Client] = []
    remove_global_clients: list[Client] = []
    project_clients: list[Client] = []
    remove_project_clients: list[Client] = []
    if detected and _prompt_bool("Configure globally (user-wide)?", default=False):
        for client in detected:
            if _prompt_bool(f"  Configure {client.label}? ({client.target})", default=True):
                global_clients.append(client)
            elif _has_openproject_config(client, client.target) and _prompt_bool(
                f"  Remove existing global {client.label} OpenProject config?",
                default=False,
            ):
                remove_global_clients.append(client)
    else:
        for client in detected:
            if _has_openproject_config(client, client.target) and _prompt_bool(
                f"Remove existing global {client.label} OpenProject config?",
                default=False,
            ):
                remove_global_clients.append(client)

    if global_clients:
        for client in project_capable:
            if _has_openproject_config(client, client.project_target) and _prompt_bool(
                f"Remove existing project-scoped {client.label} OpenProject config?",
                default=False,
            ):
                remove_project_clients.append(client)
        return global_clients, project_clients, remove_global_clients, remove_project_clients

    detected_keys = {c.key for c in detected}
    detected_project = [c for c in project_capable if c.key in detected_keys]
    if _prompt_bool("Configure project-scoped (this directory)?", default=False):
        print("  This writes config files into the current directory (they contain")
        print("  your API token — keep them out of version control).")
        for client in project_capable:
            # Default yes if this client is detected; also default yes for Claude
            # Code when nothing else project-capable is detected, so a user standing
            # in a project doesn't end up with nothing written.
            default = client.key in detected_keys or (client.key == "claude-code" and not detected_project)
            if _prompt_bool(f"  Configure {client.label}? ({client.project_target})", default=default):
                project_clients.append(client)
            elif _has_openproject_config(client, client.project_target) and _prompt_bool(
                f"  Remove existing project-scoped {client.label} OpenProject config?",
                default=False,
            ):
                remove_project_clients.append(client)
    else:
        for client in project_capable:
            if _has_openproject_config(client, client.project_target) and _prompt_bool(
                f"Remove existing project-scoped {client.label} OpenProject config?",
                default=False,
            ):
                remove_project_clients.append(client)

    return global_clients, project_clients, remove_global_clients, remove_project_clients


def _apply_registration(clients: list[Client], command: str, env: dict[str, str], *, scope: str) -> None:
    for client in clients:
        _write_client_config(client, command, env, target=client.target_for(scope))


# Backwards-compatible wrapper (global scope) for callers/tests.
def _apply_global_registration(clients: list[Client], command: str, env: dict[str, str]) -> None:
    _apply_registration(clients, command, env, scope="global")


def _merge_prefill(pairs: list[tuple[Client, Path | None]]) -> dict[str, str]:
    """Field-wise prefill merge over (client, target) pairs, in priority order.

    Later pairs override earlier ones ONLY for keys they actually define — so a
    partial config (e.g. a project ``.codex/config.toml`` with a base URL but no
    token) contributes its URL without discarding a complete global entry's
    token. Project-scope keys (``OPENPROJECT_READ_PROJECTS``/
    ``OPENPROJECT_WRITE_PROJECTS`` and their legacy aliases) are deliberately
    NOT specially handled here — they get their own presence-aware,
    per-source-then-cross-source resolution in :func:`_merge_scope_prefill`,
    since a plain field-wise merge of this dict would lose per-source priority
    once a new-key value from one source and a legacy-key value from another
    end up side by side in the same merged dict (see OPM-125 review). Pass
    pairs LOWEST priority first (globals), HIGHEST last (project/cwd).
    """
    merged: dict[str, str] = {}
    for client, target in pairs:
        env = _read_client_env(client, target=target)
        for key, value in env.items():
            if value:
                merged[key] = value
    return merged


_READ_SCOPE_KEYS = ("OPENPROJECT_READ_PROJECTS", "OPENPROJECT_ALLOWED_PROJECTS_READ", "OPENPROJECT_ALLOWED_PROJECTS")
_WRITE_SCOPE_KEYS = ("OPENPROJECT_WRITE_PROJECTS", "OPENPROJECT_ALLOWED_PROJECTS_WRITE")


def _merge_scope_prefill(pairs: list[tuple[Client, Path | None]]) -> tuple[str, str, bool, bool]:
    """Resolve READ_PROJECTS/WRITE_PROJECTS prefill across config sources correctly.

    Cross-source priority must be resolved BEFORE new-vs-legacy resolution, not
    after: merging every source's raw keys into one dict first (as
    ``_merge_prefill`` does for other fields) would let a lower-priority
    source's new key sit next to a higher-priority source's legacy key in the
    same dict, with no way to tell which source either came from — silently
    picking the new key regardless of source priority (see OPM-125 review).
    Instead, each source is resolved (new key wins over legacy within that
    source) independently, and only the last source that defines ANY relevant
    key — new or legacy — contributes its resolved value, so a higher-priority
    source always wins outright, even with an empty value. Pairs must be
    LOWEST priority first (globals), HIGHEST last (project/cwd), matching
    ``_merge_prefill``.
    """
    read_value, write_value = "", ""
    read_used_legacy, write_used_legacy = False, False
    for client, target in pairs:
        env = _read_client_env(client, target=target)
        if any(key in env for key in _READ_SCOPE_KEYS):
            read_value, read_used_legacy = _scope_prefill(env, _READ_SCOPE_KEYS[0], list(_READ_SCOPE_KEYS[1:]))
        if any(key in env for key in _WRITE_SCOPE_KEYS):
            write_value, write_used_legacy = _scope_prefill(env, _WRITE_SCOPE_KEYS[0], list(_WRITE_SCOPE_KEYS[1:]))
    return read_value, write_value, read_used_legacy, write_used_legacy


# ── live connection test + preview/confirm (OPM-121, folded into OPM-128) ──────


class ConnectionCheck(NamedTuple):
    """Outcome of a live API check against candidate wizard settings.

    ``status`` is one of: ``"ok"``, ``"config_error"``, ``"auth_error"``,
    ``"permission_error"``, ``"not_found_error"``, ``"invalid_input_error"``,
    ``"server_error"``, ``"network_error"``, ``"unexpected_error"``, or
    ``"skipped"`` (non-interactive — no check was attempted).
    """

    status: str
    detail: str
    user_name: str | None


async def _test_connection_async(
    env: dict[str, str], *, transport: httpx.AsyncBaseTransport | None = None
) -> ConnectionCheck:
    try:
        settings = Settings.from_env(env)
    except ConfigError as exc:
        return ConnectionCheck("config_error", str(exc), None)

    # Shorter timeout, no retries — same reasoning as doctor.py's diagnostic
    # check: a connection TEST should fail fast, not wait through the user's
    # configured full retry/backoff policy (which could take tens of seconds
    # for a genuinely down host).
    diagnostic_settings = dataclasses.replace(settings, timeout=5.0, max_retries=0)
    client = OpenProjectClient(diagnostic_settings, transport=transport)
    try:
        user = await client.get_current_user()
        return ConnectionCheck("ok", "", user.name)
    except AuthenticationError as exc:
        return ConnectionCheck("auth_error", str(exc), None)
    except PermissionDeniedError as exc:
        return ConnectionCheck("permission_error", str(exc), None)
    except NotFoundError as exc:
        return ConnectionCheck("not_found_error", str(exc), None)
    except InvalidInputError as exc:
        return ConnectionCheck("invalid_input_error", str(exc), None)
    except TransportError as exc:
        return ConnectionCheck("network_error", str(exc), None)
    except OpenProjectServerError as exc:
        return ConnectionCheck("server_error", str(exc), None)
    except OpenProjectError as exc:
        # Fallback bucket: the six named subclasses above are exhaustive today,
        # but a future subclass shouldn't crash the wizard.
        return ConnectionCheck("server_error", str(exc), None)
    except Exception as exc:  # noqa: BLE001 - must not crash the wizard on an unexpected client bug
        return ConnectionCheck("unexpected_error", f"{type(exc).__name__}: {exc}", None)
    finally:
        await client.aclose()


def _test_connection(env: dict[str, str], *, transport: httpx.AsyncBaseTransport | None = None) -> ConnectionCheck:
    """Synchronous wrapper — the wizard itself has no other async call sites.

    ``transport`` is test-only (an ``httpx.MockTransport``); production callers
    never pass it, so the real network stack is used.
    """
    return asyncio.run(_test_connection_async(env, transport=transport))


_MAX_CREDENTIAL_ATTEMPTS = 3


def _collect_credentials(
    prefill_pairs: list[tuple[Client, Path | None]],
    existing: dict[str, str],
    *,
    interactive: bool,
    mode: Literal["quick", "advanced"],
) -> tuple[dict[str, str], ConnectionCheck]:
    """Prompt for base URL/token/scope/settings; return env + connection status.

    ``mode`` selects which questionnaire runs: "quick" asks only client
    target(s)/base URL/token/readable projects/a single *project-scoped*
    write-scope choice (none/work-packages/all) and fills everything else
    from safe defaults; "advanced" asks the full questionnaire (individual
    read/write controls, field-hiding, page sizes, SSL, logging). The
    quick-mode write-scope choice only governs the five project-scoped write
    flags — personal-data writes (``OPENPROJECT_ENABLE_PERSONAL_WRITE``) and admin
    writes (``OPENPROJECT_ENABLE_ADMIN_WRITE``) are independent axes that keep
    whatever value they already had (or the default, on a fresh setup); only
    ``--advanced`` re-prompts them. The caller resolves the mode from the
    ``--quick``/``--advanced`` CLI flags — it is no longer a runtime prompt.

    In interactive mode, validates the candidate settings against a live API
    connection before returning. A `network_error` offers a genuine choice
    (retry the same check / proceed unverified / re-enter credentials) since
    it might be transient; every other error class forces re-entry of
    credentials outright — never a silent proceed past a real config/auth/
    permission problem. Exits (code 1) if no working credentials are produced
    within ``_MAX_CREDENTIAL_ATTEMPTS`` full re-entry attempts.
    """
    for _attempt in range(_MAX_CREDENTIAL_ATTEMPTS):
        print()

        base_url = _prompt(
            "OpenProject base URL",
            existing.get("OPENPROJECT_BASE_URL", "https://op.example.com"),
        )

        has_token = bool(existing.get("OPENPROJECT_API_TOKEN"))
        token = _prompt_secret("OpenProject API token", has_existing=has_token)
        if not token:
            token = existing.get("OPENPROJECT_API_TOKEN", "")
        if not token:
            print("An API token is required.", file=sys.stderr)
            sys.exit(1)
        print("  This token is saved in the config file — keep it private and never commit it.")

        print()
        print("Project scope — comma-separated identifiers, names, or globs (e.g. team-*).")
        read_projects_existing, write_projects_existing, read_used_legacy, write_used_legacy = _merge_scope_prefill(
            prefill_pairs
        )
        if read_used_legacy or write_used_legacy:
            print(
                "Found legacy OPENPROJECT_ALLOWED_PROJECTS_READ/_WRITE — using their values as "
                "defaults for the renamed OPENPROJECT_READ_PROJECTS/OPENPROJECT_WRITE_PROJECTS."
            )
        read_projects = _prompt(
            "Readable projects (empty = none, * = all visible)",
            read_projects_existing,
        )
        existing_write_projects = write_projects_existing.strip()
        advanced = mode == "advanced"

        if advanced:
            write_access = _prompt_bool("Enable write access?", bool(existing_write_projects))
            if write_access:
                write_projects_default = existing_write_projects or read_projects
                write_projects = _prompt(
                    "Writable projects (subset of readable)",
                    write_projects_default,
                )
                wp_write = _bool_from_env(existing, "OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE", True)
                project_write = _bool_from_env(existing, "OPENPROJECT_ENABLE_PROJECT_WRITE", True)
                membership_write = _bool_from_env(existing, "OPENPROJECT_ENABLE_MEMBERSHIP_WRITE", True)
                version_write = _bool_from_env(existing, "OPENPROJECT_ENABLE_VERSION_WRITE", True)
                board_write = _bool_from_env(existing, "OPENPROJECT_ENABLE_BOARD_WRITE", True)
            else:
                write_projects = ""
                print("Write access disabled — project-scoped writes are disabled.")
                wp_write = False
                project_write = False
                membership_write = False
                version_write = False
                board_write = False
        else:
            # Quick mode: one write-scope choice replaces the yes/no gate above
            # entirely — no overlapping decisions (OPM-55).
            write_scope_class = _classify_write_scope(existing, write_projects_existing=write_projects_existing)
            is_custom = write_scope_class == "custom"
            allowed_choices = ["none", "work-packages", "all"] + (["keep"] if is_custom else [])
            default_choice = "keep" if is_custom else write_scope_class

            print()
            print("Write scope — how much can this server write to your OpenProject projects?")
            print("  none            no project-scoped writes")
            print(
                "  work-packages   project-scoped work-package writes only (create/update/delete, "
                "comments, relations, attachments, time entries)"
            )
            print(
                "  all             all project-scoped writes (work packages, projects, memberships, versions, boards)"
            )
            if is_custom:
                print("  keep            keep your current custom write-scope combination unchanged")
            print(
                "  (personal-data and admin writes are unaffected here and keep their existing "
                "value, if any; change them with --advanced)"
            )

            allowed = frozenset(allowed_choices)
            write_scope_choice: str | None = None
            for ws_attempt in range(3):
                raw = _prompt(f"Write scope [{'/'.join(allowed_choices)}]", default_choice)
                write_scope_choice = _parse_write_scope_choice(raw, allowed=allowed, default=default_choice)
                if write_scope_choice is not None:
                    break
                if ws_attempt == 2:
                    print("Could not parse a valid write scope. Nothing written.", file=sys.stderr)
                    sys.exit(1)
                print(f"  ! Invalid write scope. Allowed values: {', '.join(allowed_choices)}.")

            if write_scope_choice == "none":
                write_access = False
                write_projects = ""
                wp_write = project_write = membership_write = version_write = board_write = False
                print("Write access disabled — project-scoped writes are disabled.")
            elif write_scope_choice == "keep":
                write_access = True
                write_projects = existing_write_projects
                wp_write = _bool_from_env(existing, "OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE", True)
                project_write = _bool_from_env(existing, "OPENPROJECT_ENABLE_PROJECT_WRITE", True)
                membership_write = _bool_from_env(existing, "OPENPROJECT_ENABLE_MEMBERSHIP_WRITE", True)
                version_write = _bool_from_env(existing, "OPENPROJECT_ENABLE_VERSION_WRITE", True)
                board_write = _bool_from_env(existing, "OPENPROJECT_ENABLE_BOARD_WRITE", True)
            else:
                write_access = True
                write_projects_default = existing_write_projects or read_projects
                write_projects = _prompt(
                    "Writable projects (subset of readable)",
                    write_projects_default,
                )
                if write_scope_choice == "work-packages":
                    wp_write, project_write, membership_write, version_write, board_write = (
                        True,
                        False,
                        False,
                        False,
                        False,
                    )
                else:  # "all"
                    wp_write = project_write = membership_write = version_write = board_write = True

        print()

        enable_project_read = _bool_from_env(existing, "OPENPROJECT_ENABLE_PROJECT_READ", True)
        enable_work_package_read = _bool_from_env(existing, "OPENPROJECT_ENABLE_WORK_PACKAGE_READ", True)
        enable_membership_read = _bool_from_env(existing, "OPENPROJECT_ENABLE_MEMBERSHIP_READ", True)
        enable_version_read = _bool_from_env(existing, "OPENPROJECT_ENABLE_VERSION_READ", True)
        enable_board_read = _bool_from_env(existing, "OPENPROJECT_ENABLE_BOARD_READ", True)
        enable_personal_read = _bool_from_env(existing, "OPENPROJECT_ENABLE_PERSONAL_READ", False)
        personal_write = _bool_from_env(existing, "OPENPROJECT_ENABLE_PERSONAL_WRITE", False)
        enable_admin_read = _bool_from_env(existing, "OPENPROJECT_ENABLE_ADMIN_READ", False)
        admin_write = _bool_from_env(existing, "OPENPROJECT_ENABLE_ADMIN_WRITE")
        enable_metadata_tools = _bool_from_env(existing, "OPENPROJECT_ENABLE_EXTENDED_READ", False)
        hide_project = existing.get("OPENPROJECT_HIDE_PROJECT_FIELDS", "")
        hide_wp = existing.get("OPENPROJECT_HIDE_WORK_PACKAGE_FIELDS", "")
        hide_activity = existing.get("OPENPROJECT_HIDE_ACTIVITY_FIELDS", "")
        hide_custom = existing.get("OPENPROJECT_HIDE_CUSTOM_FIELDS", "")
        timeout = existing.get("OPENPROJECT_TIMEOUT", "12")
        verify_ssl = existing.get("OPENPROJECT_VERIFY_SSL", "true")
        default_page_size = existing.get("OPENPROJECT_DEFAULT_PAGE_SIZE", "10")
        max_page_size = existing.get("OPENPROJECT_MAX_PAGE_SIZE", "50")
        max_results = existing.get("OPENPROJECT_MAX_RESULTS", "100")
        text_limit = existing.get("OPENPROJECT_TEXT_LIMIT", "500")
        log_level = existing.get("OPENPROJECT_LOG_LEVEL", "WARNING")
        attachment_root = existing.get("OPENPROJECT_ATTACHMENT_ROOT", "")
        max_retries = existing.get("OPENPROJECT_MAX_RETRIES", "3")
        retry_base_delay = existing.get("OPENPROJECT_RETRY_BASE_DELAY", "1.0")
        retry_max_delay = existing.get("OPENPROJECT_RETRY_MAX_DELAY", "60.0")

        if advanced:
            print()
            print(
                "Tool exposure and write controls — which groups are registered as tools, and which "
                "can write. OpenProject permissions and the writable project scope still apply to "
                "writes. Defaults are usually right."
            )
            enable_project_read = _prompt_bool("Enable project tools?", enable_project_read)
            if write_access:
                project_write = _prompt_bool(
                    "Enable project writes (create/update/delete)?",
                    project_write,
                )
            enable_work_package_read = _prompt_bool("Enable work-package tools?", enable_work_package_read)
            if write_access:
                wp_write = _prompt_bool(
                    "Enable work-package writes (create/update/delete, comments, relations, attachments, time entries)?",
                    wp_write,
                )
            enable_membership_read = _prompt_bool("Enable membership tools?", enable_membership_read)
            if write_access:
                membership_write = _prompt_bool(
                    "Enable membership writes (create/update/delete)?",
                    membership_write,
                )
            enable_version_read = _prompt_bool("Enable version tools?", enable_version_read)
            if write_access:
                version_write = _prompt_bool(
                    "Enable version writes (create/update/delete)?",
                    version_write,
                )
            enable_board_read = _prompt_bool("Enable board tools?", enable_board_read)
            if write_access:
                board_write = _prompt_bool(
                    "Enable board writes (create/update/delete)?",
                    board_write,
                )
            enable_personal_read = _prompt_bool(
                "Enable personal tools (own preferences, notifications)?", enable_personal_read
            )
            if enable_personal_read:
                personal_write = _prompt_bool(
                    "Enable personal-data writes (preferences, notification read-state)?",
                    personal_write,
                )
            enable_admin_read = _prompt_bool("Enable admin tools (list/view users and groups)?", enable_admin_read)
            admin_write = _prompt_bool("Enable admin writes (users/groups)?", admin_write)
            enable_metadata_tools = _prompt_bool("Enable extended/rarely-used metadata tools?", enable_metadata_tools)

        if not enable_personal_read:
            # No visible personal surface → personal writes cannot be active either.
            # Still needed standalone (not just inside the `if advanced` block above):
            # in quick mode enable_personal_read keeps its pre-advanced value and the
            # block above never runs, so this is the only place enforcing the rule then.
            personal_write = False

        if advanced:
            print()
            print("Optional field filtering — omit fields from reads. Leave empty unless you need it.")
            hide_project = _prompt("Hidden project fields (comma-separated)", hide_project)
            hide_wp = _prompt("Hidden work-package fields (comma-separated)", hide_wp)
            hide_activity = _prompt("Hidden activity fields (comma-separated)", hide_activity)
            hide_custom = _prompt("Hidden custom fields (comma-separated)", hide_custom)

            print()
            print("Advanced runtime settings.")
            attachment_root = _prompt(
                "Attachment upload root, absolute path (empty = uploads disabled)", attachment_root
            )
            default_page_size = _prompt("Default page size", default_page_size)
            max_page_size = _prompt("Max page size", max_page_size)
            max_results = _prompt("Max total results", max_results)
            text_limit = _prompt("List text preview char limit", text_limit)
            timeout = _prompt("Request timeout seconds", timeout)
            verify_ssl = (
                "true"
                if _prompt_bool("Verify TLS certificates?", _bool_from_env({"v": verify_ssl}, "v", True))
                else "false"
            )
            max_retries = _prompt("Max retries for 429/5xx responses", max_retries)
            retry_base_delay = _prompt("Retry base delay seconds", retry_base_delay)
            retry_max_delay = _prompt("Retry max delay seconds", retry_max_delay)
            log_level = _prompt("Log level", log_level)

        # Write-flag reconciliation: from the ORIGINAL (unmutated) values, once, using
        # the now-validated read booleans — never mutate write_flags across retries
        # above, or a mistaken read toggle could permanently disable an unrelated,
        # correctly chosen write flag.
        read_flags = {
            "project_read": enable_project_read,
            "work_package_read": enable_work_package_read,
            "membership_read": enable_membership_read,
            "version_read": enable_version_read,
            "board_read": enable_board_read,
            "personal_read": enable_personal_read,
            "admin_read": enable_admin_read,
        }
        original_write_flags = {
            "project_write": project_write,
            "work_package_write": wp_write,
            "membership_write": membership_write,
            "version_write": version_write,
            "board_write": board_write,
            "personal_write": personal_write,
            "admin_write": admin_write,
        }
        write_flags = original_write_flags.copy()
        for write_key, _read_key, write_env_var, read_env_var in tool_exposure_violations(read_flags, write_flags):
            print(f"  ! {read_env_var}=false — disabling {write_env_var} (it would otherwise fail at startup).")
            write_flags[write_key] = False
        project_write = write_flags["project_write"]
        wp_write = write_flags["work_package_write"]
        membership_write = write_flags["membership_write"]
        version_write = write_flags["version_write"]
        board_write = write_flags["board_write"]
        personal_write = write_flags["personal_write"]
        admin_write = write_flags["admin_write"]

        env: dict[str, str] = {
            "OPENPROJECT_BASE_URL": base_url,
            "OPENPROJECT_API_TOKEN": token,
            "OPENPROJECT_READ_PROJECTS": read_projects,
            "OPENPROJECT_WRITE_PROJECTS": write_projects,
            "OPENPROJECT_ENABLE_PROJECT_READ": str(enable_project_read).lower(),
            "OPENPROJECT_ENABLE_PROJECT_WRITE": str(project_write).lower(),
            "OPENPROJECT_ENABLE_WORK_PACKAGE_READ": str(enable_work_package_read).lower(),
            "OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE": str(wp_write).lower(),
            "OPENPROJECT_ENABLE_MEMBERSHIP_READ": str(enable_membership_read).lower(),
            "OPENPROJECT_ENABLE_MEMBERSHIP_WRITE": str(membership_write).lower(),
            "OPENPROJECT_ENABLE_VERSION_READ": str(enable_version_read).lower(),
            "OPENPROJECT_ENABLE_VERSION_WRITE": str(version_write).lower(),
            "OPENPROJECT_ENABLE_BOARD_READ": str(enable_board_read).lower(),
            "OPENPROJECT_ENABLE_BOARD_WRITE": str(board_write).lower(),
            "OPENPROJECT_ENABLE_PERSONAL_READ": str(enable_personal_read).lower(),
            "OPENPROJECT_ENABLE_PERSONAL_WRITE": str(personal_write).lower(),
            "OPENPROJECT_ENABLE_ADMIN_READ": str(enable_admin_read).lower(),
            "OPENPROJECT_ENABLE_ADMIN_WRITE": str(admin_write).lower(),
            "OPENPROJECT_ENABLE_EXTENDED_READ": str(enable_metadata_tools).lower(),
            "OPENPROJECT_HIDE_PROJECT_FIELDS": hide_project,
            "OPENPROJECT_HIDE_WORK_PACKAGE_FIELDS": hide_wp,
            "OPENPROJECT_HIDE_ACTIVITY_FIELDS": hide_activity,
            "OPENPROJECT_HIDE_CUSTOM_FIELDS": hide_custom,
            "OPENPROJECT_ATTACHMENT_ROOT": attachment_root,
            "OPENPROJECT_TIMEOUT": timeout,
            "OPENPROJECT_VERIFY_SSL": verify_ssl,
            "OPENPROJECT_DEFAULT_PAGE_SIZE": default_page_size,
            "OPENPROJECT_MAX_PAGE_SIZE": max_page_size,
            "OPENPROJECT_MAX_RESULTS": max_results,
            "OPENPROJECT_TEXT_LIMIT": text_limit,
            "OPENPROJECT_MAX_RETRIES": max_retries,
            "OPENPROJECT_RETRY_BASE_DELAY": retry_base_delay,
            "OPENPROJECT_RETRY_MAX_DELAY": retry_max_delay,
            "OPENPROJECT_LOG_LEVEL": log_level,
        }

        if not interactive:
            return env, ConnectionCheck("skipped", "", None)

        while True:
            check = _test_connection(env)
            if check.status == "ok":
                return env, check
            if check.status != "network_error":
                print(f"  ! Connection check failed ({check.status}): {check.detail}")
                print("  Please re-enter your credentials.")
                break
            print(f"  ! Could not verify the connection: {check.detail}")
            choice = (
                _prompt(
                    "Retry the connection check, proceed without verifying, or re-enter "
                    "credentials? [retry/proceed/edit]",
                    "retry",
                )
                .strip()
                .lower()
            )
            if choice.startswith("p"):
                return env, check
            if choice.startswith("e"):
                break
            # anything else (including the "retry" default) loops back and retries
            # the same connection check without re-prompting any field.

    print(
        f"Could not collect a working configuration after {_MAX_CREDENTIAL_ATTEMPTS} attempts. Nothing written.",
        file=sys.stderr,
    )
    sys.exit(1)


def _preview_changes(
    remove_global_clients: list[Client],
    remove_project_clients: list[Client],
    global_clients: list[Client],
    project_clients: list[Client],
    write_generic_mcp_json: bool,
    env: dict[str, str] | None,
    connection: ConnectionCheck | None,
) -> bool:
    """Print every pending mutation and the effective settings; return the user's confirm.

    ``env``/``connection`` are None for a pure-removal flow with nothing to
    write — only the removal list is shown in that case.
    """
    print()
    print("Preview of changes:")
    for client in remove_global_clients:
        print(f"  - Remove {client.label} (global): {client.target}")
    for client in remove_project_clients:
        print(f"  - Remove {client.label} (project): {client.project_target}")
    for client in global_clients:
        action = "Update" if _has_openproject_config(client, client.target) else "Create"
        print(f"  - {action} {client.label} (global): {client.target}")
    for client in project_clients:
        action = "Update" if _has_openproject_config(client, client.project_target) else "Create"
        print(f"  - {action} {client.label} (project): {client.project_target}")
    if write_generic_mcp_json:
        print("  - Write generic .mcp.json (copy-source for project scope)")

    if env is not None:
        print()
        if connection is None or connection.status == "skipped":
            print("  Connection: skipped (non-interactive)")
        elif connection.status == "ok":
            print(f"  Connection: OK (connected as {connection.user_name})")
        else:
            print(f"  Connection: UNVERIFIED — proceeding without a successful check ({connection.detail})")
        print(f"  Base URL: {env['OPENPROJECT_BASE_URL']}")
        print("  API token: configured (hidden)")
        # Effective scope is always shown here, even though an empty/default
        # value ends up omitted from the written file (see minimal-diff writing) —
        # the file's minimalism must never reduce what the user was told.
        print(f"  Read projects: {env['OPENPROJECT_READ_PROJECTS'] or 'none (fail-closed)'}")
        print(f"  Write projects: {env['OPENPROJECT_WRITE_PROJECTS'] or 'none (fail-closed)'}")
        read_groups = [
            label
            for label, key in (
                ("projects", "OPENPROJECT_ENABLE_PROJECT_READ"),
                ("work-packages", "OPENPROJECT_ENABLE_WORK_PACKAGE_READ"),
                ("memberships", "OPENPROJECT_ENABLE_MEMBERSHIP_READ"),
                ("versions", "OPENPROJECT_ENABLE_VERSION_READ"),
                ("boards", "OPENPROJECT_ENABLE_BOARD_READ"),
                ("personal", "OPENPROJECT_ENABLE_PERSONAL_READ"),
                ("admin", "OPENPROJECT_ENABLE_ADMIN_READ"),
                ("extended", "OPENPROJECT_ENABLE_EXTENDED_READ"),
            )
            if env[key] == "true"
        ]
        print(f"  Tool exposure: {', '.join(read_groups) or 'none'}")
        print(f"  Project writes: {env['OPENPROJECT_ENABLE_PROJECT_WRITE']}")
        print(f"  Work-package writes: {env['OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE']}")
        print(f"  Membership writes: {env['OPENPROJECT_ENABLE_MEMBERSHIP_WRITE']}")
        print(f"  Version writes: {env['OPENPROJECT_ENABLE_VERSION_WRITE']}")
        print(f"  Board writes: {env['OPENPROJECT_ENABLE_BOARD_WRITE']}")
        print(f"  Personal-data writes: {env['OPENPROJECT_ENABLE_PERSONAL_WRITE']}")
        print(f"  Admin writes: {env['OPENPROJECT_ENABLE_ADMIN_WRITE']}")
        if env["OPENPROJECT_VERIFY_SSL"] == "false":
            print("  ! TLS verification disabled (OPENPROJECT_VERIFY_SSL=false)")
        if env["OPENPROJECT_BASE_URL"].startswith("http://"):
            print("  ! Unencrypted HTTP connection")

    print()
    return _prompt_bool("Proceed with these changes?", default=False)


def _apply_changes(
    remove_global_clients: list[Client],
    remove_project_clients: list[Client],
    global_clients: list[Client],
    project_clients: list[Client],
    write_generic_mcp_json: bool,
    generic_target: Path | None,
    command: str,
    env: dict[str, str] | None,
) -> None:
    """Perform every mutation in one bundled step: removals first, then writes.

    Bundling matters because it's called exactly once, after any preview/confirm
    — never split across the flow, or a decline partway through would leave some
    mutations applied and others not (the bug this replaces: removals used to run
    immediately after target selection, before credentials were even collected).
    ``env`` is None for a pure-removal flow with nothing to write.
    """
    if remove_global_clients:
        print()
        print("Removing deselected user-wide (global) config:")
        for client in remove_global_clients:
            _remove_client_config(client, target=client.target)
    if remove_project_clients:
        print()
        print("Removing deselected project-scoped config:")
        for client in remove_project_clients:
            _remove_client_config(client, target=client.project_target)

    if env is None:
        return

    print()
    if global_clients:
        print("Configuring user-wide (global):")
        _apply_registration(global_clients, command, env, scope="global")
    if project_clients:
        print("Configuring project-scoped (this directory):")
        _apply_registration(project_clients, command, env, scope="project")
    if write_generic_mcp_json and generic_target is not None:
        _write_mcp_json(env, generic_target, command)


# ── minimal-diff config writing (OPM-128) ───────────────────────────────────────

# Materialized once, at import time (cheap — no I/O): every optional field's
# real runtime default, from the single source of truth (Settings.from_env
# itself), rather than a second hand-copied table of default literals that
# could silently drift from config.py's actual defaults. BASE_URL/API_TOKEN
# are throwaway placeholders — never written anywhere, always kept unconditionally.
_DEFAULT_SETTINGS = Settings.from_env(
    {"OPENPROJECT_BASE_URL": "https://placeholder.invalid", "OPENPROJECT_API_TOKEN": "placeholder"}
)

# (env key, Settings attribute) — every generated env key except BASE_URL/
# API_TOKEN (always kept).
_MINIMAL_ENV_FIELD_MAP: tuple[tuple[str, str], ...] = (
    ("OPENPROJECT_READ_PROJECTS", "read_projects"),
    ("OPENPROJECT_WRITE_PROJECTS", "write_projects"),
    ("OPENPROJECT_ENABLE_PROJECT_READ", "enable_project_read"),
    ("OPENPROJECT_ENABLE_PROJECT_WRITE", "enable_project_write"),
    ("OPENPROJECT_ENABLE_WORK_PACKAGE_READ", "enable_work_package_read"),
    ("OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE", "enable_work_package_write"),
    ("OPENPROJECT_ENABLE_MEMBERSHIP_READ", "enable_membership_read"),
    ("OPENPROJECT_ENABLE_MEMBERSHIP_WRITE", "enable_membership_write"),
    ("OPENPROJECT_ENABLE_VERSION_READ", "enable_version_read"),
    ("OPENPROJECT_ENABLE_VERSION_WRITE", "enable_version_write"),
    ("OPENPROJECT_ENABLE_BOARD_READ", "enable_board_read"),
    ("OPENPROJECT_ENABLE_BOARD_WRITE", "enable_board_write"),
    ("OPENPROJECT_ENABLE_PERSONAL_READ", "enable_personal_read"),
    ("OPENPROJECT_ENABLE_PERSONAL_WRITE", "enable_personal_write"),
    ("OPENPROJECT_ENABLE_ADMIN_READ", "enable_admin_read"),
    ("OPENPROJECT_ENABLE_ADMIN_WRITE", "enable_admin_write"),
    ("OPENPROJECT_ENABLE_EXTENDED_READ", "enable_metadata_tools"),
    ("OPENPROJECT_HIDE_PROJECT_FIELDS", "hide_project_fields"),
    ("OPENPROJECT_HIDE_WORK_PACKAGE_FIELDS", "hide_work_package_fields"),
    ("OPENPROJECT_HIDE_ACTIVITY_FIELDS", "hide_activity_fields"),
    ("OPENPROJECT_HIDE_CUSTOM_FIELDS", "hide_custom_fields"),
    ("OPENPROJECT_ATTACHMENT_ROOT", "attachment_root"),
    ("OPENPROJECT_TIMEOUT", "timeout"),
    ("OPENPROJECT_VERIFY_SSL", "verify_ssl"),
    ("OPENPROJECT_DEFAULT_PAGE_SIZE", "default_page_size"),
    ("OPENPROJECT_MAX_PAGE_SIZE", "max_page_size"),
    ("OPENPROJECT_MAX_RESULTS", "max_results"),
    ("OPENPROJECT_TEXT_LIMIT", "text_limit"),
    ("OPENPROJECT_MAX_RETRIES", "max_retries"),
    ("OPENPROJECT_RETRY_BASE_DELAY", "retry_base_delay"),
    ("OPENPROJECT_RETRY_MAX_DELAY", "retry_max_delay"),
    ("OPENPROJECT_LOG_LEVEL", "log_level"),
)


def _minimal_env(env: dict[str, str], candidate: Settings) -> dict[str, str]:
    """Trim ``env`` to BASE_URL/API_TOKEN plus only the fields that deviate from
    the safe default — a fresh/default setup writes a near-empty file, not a
    fully-spelled-out table.

    The written value for a kept key is always the original string already in
    ``env`` — never a re-serialized ``Settings`` value — so e.g. ``"12.0"``
    typed for a default-12.0 timeout is recognized as "= default" without ever
    writing back a reformatted ``"12"``. Re-running ``configure`` later
    prefills identically either way: every prefill reader (``_scope_prefill``,
    ``_merge_scope_prefill``, the plain ``existing.get(KEY, "<default>")``
    calls) already treats a *missing* key the same as an explicit default
    value.
    """
    minimal: dict[str, str] = {
        "OPENPROJECT_BASE_URL": env["OPENPROJECT_BASE_URL"],
        "OPENPROJECT_API_TOKEN": env["OPENPROJECT_API_TOKEN"],
    }
    for env_key, attr in _MINIMAL_ENV_FIELD_MAP:
        if getattr(candidate, attr) != getattr(_DEFAULT_SETTINGS, attr):
            minimal[env_key] = env[env_key]
    return minimal


# ── main ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None, *, interactive: bool | None = None) -> None:
    """Console entry point: run the interactive setup, exiting cleanly on Ctrl+C.

    Ctrl+C during any prompt should read as "cancelled", not a Python traceback,
    so we catch KeyboardInterrupt here and exit 130 (the conventional SIGINT code).

    ``interactive`` forces the connection-test/preview-confirm step on or off;
    None (the default) auto-detects from stdin alone being a real terminal
    (redirecting stdout, e.g. `| tee log`, must NOT disable it — a human is
    still typing answers) — see ``--non-interactive`` for the explicit CLI
    opt-out used by scripted installs. Tests always pass ``interactive=False``
    explicitly (see tests/test_configure_mcp.py's ``_run_main``) so no network
    access or extra prompt happens under test.
    """
    try:
        _run_configure(argv, interactive=interactive)
    except KeyboardInterrupt:
        print("\nCancelled — nothing was written.", file=sys.stderr)
        sys.exit(130)


def _run_configure(argv: list[str] | None = None, *, interactive: bool | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="openproject-ce-mcp",
        description="Configure or remove the openproject MCP server for your clients.",
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Remove the openproject entry from client configs (user-wide, and project-local in the current directory). Leaves other servers/settings intact.",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Skip the live connection test and preview/confirm step, and write immediately. "
        "For scripted installs; normally auto-detected from stdin, this is an explicit "
        "override for automation that still runs with a real terminal attached.",
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--quick",
        action="store_true",
        help="Minimal first-run questionnaire: client target(s), base URL, token, readable "
        "projects, and a single project-scoped write-scope choice. Safe defaults for "
        "everything else. This is the default when neither --quick nor --advanced is given.",
    )
    mode_group.add_argument(
        "--advanced",
        action="store_true",
        help="Full questionnaire: individual read/write controls, field-hiding "
        "(including personal-data and admin writes), page sizes, SSL, logging, in addition "
        "to the quick-mode questions.",
    )
    args = parser.parse_args(argv)
    mode: Literal["quick", "advanced"] = "advanced" if args.advanced else "quick"

    if args.uninstall:
        _run_uninstall()
        return

    _check_python()

    if interactive is None:
        # stdin alone, not stdout: a human piping stdout through `| tee log`
        # (or an IDE that captures output) is still typing real answers and
        # must still get the connection test/preview/confirm — only redirected
        # STDIN (piped canned answers, CI, install scripts) has no one to ask.
        # --non-interactive is the explicit opt-out for scripted use that still
        # happens to have a real stdin attached.
        interactive = False if args.non_interactive else sys.stdin.isatty()

    # Compute the run mode once; thread it through instead of re-stat'ing the
    # filesystem in every helper.
    installed = _installed_mode()

    uv = _find_uv()
    _install_deps(uv, installed)

    command, command_resolved = _server_command(installed)

    clients = _clients()

    # Two independent gates decide WHERE to configure — before collecting creds.
    global_clients, project_clients, remove_global_clients, remove_project_clients = _choose_targets(clients)

    # A generic .mcp.json copy-source is written when project scope is chosen,
    # NOT for a purely global configuration. If Claude
    # Code is among the project clients, its project_target IS .mcp.json, so we
    # write it once via _write_client_config and skip the generic write.
    claude_code_project = any(c.key == "claude-code" for c in project_clients)
    write_generic_mcp_json = bool(project_clients) and not claude_code_project

    # Removals are NOT applied here — only recorded. Executing them immediately
    # (the old behavior) meant an abort anywhere after this point left deletions
    # applied with nothing written; they now run inside _apply_changes, bundled
    # with every other mutation, after any preview/confirm.
    removed_any = bool(remove_global_clients or remove_project_clients)
    if not global_clients and not project_clients and not write_generic_mcp_json:
        if not removed_any:
            print(
                "\nNothing selected to configure. Re-run and choose a global and/or "
                "project-scoped target (see the guides).",
                file=sys.stderr,
            )
            sys.exit(1)
        # Removal-only flow: nothing to write, so no credentials/connection test.
        if interactive:
            proceed = _preview_changes(remove_global_clients, remove_project_clients, [], [], False, None, None)
            if not proceed:
                print("\nCancelled — nothing was written.")
                return
        _apply_changes(remove_global_clients, remove_project_clients, [], [], False, None, command, None)
        print()
        print("No targets selected to configure. Removed selected OpenProject entries.")
        return

    # Field-wise prefill from the selected scope only. Project-scoped values never
    # silently override global values, and global values never leak into a local
    # config.
    selected_prefill_clients = project_clients if project_clients else global_clients
    prefill_pairs: list[tuple[Client, Path | None]] = [
        (c, c.project_target if project_clients else c.target) for c in selected_prefill_clients
    ]
    existing = _merge_prefill(prefill_pairs)

    env, connection = _collect_credentials(prefill_pairs, existing, interactive=interactive, mode=mode)

    # Final defensive check: the generated config must always parse cleanly with
    # the exact runtime validation, not just the wizard's own reconciliation above.
    try:
        candidate_settings = Settings.from_env(env)
    except ConfigError as exc:
        print(f"Generated configuration is invalid ({exc}). Nothing written.", file=sys.stderr)
        sys.exit(1)

    # The preview (below) always shows the full/effective settings from `env`;
    # only the file actually written is trimmed to deviations from the default.
    minimal_env = _minimal_env(env, candidate_settings)

    # Generic copy-source .mcp.json: only when project scope was chosen and not
    # already covered by Claude Code's project write.
    generic_target: Path | None = None
    if write_generic_mcp_json:
        generic_target = (
            _resolve_mcp_json("local", installed) if installed else _resolve_mcp_json(None, installed=False)
        )

    if interactive:
        proceed = _preview_changes(
            remove_global_clients,
            remove_project_clients,
            global_clients,
            project_clients,
            write_generic_mcp_json,
            env,
            connection,
        )
        if not proceed:
            print("\nCancelled — nothing was written.")
            return

    _apply_changes(
        remove_global_clients,
        remove_project_clients,
        global_clients,
        project_clients,
        write_generic_mcp_json,
        generic_target,
        command,
        minimal_env,
    )

    print()
    print("Server configured.")
    print(f"Command: {command}")
    if not command_resolved:
        print(
            f"  Note: '{_SERVER_BIN}' could not be resolved to an absolute path. The "
            "config uses the bare name, which works only if the install location "
            "(pipx/uv-tool/venv bin) is on PATH. GUI clients (e.g. Claude Desktop) "
            "often do NOT inherit your shell PATH — if the server fails to start, "
            "edit the written config to use the absolute path to the binary."
        )

    # Per-client restart hints (config written ≠ server running), deduped across
    # both gates by client key.
    configured: dict[str, Client] = {}
    for client in [*global_clients, *project_clients]:
        configured.setdefault(client.key, client)
    if configured:
        print()
        print("Config written — now (re)load each client so it picks up the server:")
        for client in configured.values():
            print(f"  - {client.label}: {client.restart_hint}")
    else:
        print()
        print("Register the server yourself — copy the values from the generated")
        print(".mcp.json into your client's config. Guides:")
        for label, doc in _doc_locations(installed).items():
            print(f"  - {label:<26} {doc}")


def _doc_locations(installed: bool) -> dict[str, str]:
    """Setup guides, as local file paths in a clone or GitHub URLs when installed."""
    docs = {
        "Claude / Claude Code:": "claude.md",
        "Claude Desktop app:": "claude-desktop.md",
        "Codex:": "codex.md",
        "VS Code / GitHub Copilot:": "github.md",
        "Cursor:": "cursor.md",
    }
    if installed:
        base = "https://github.com/jtauschl/openproject-ce-mcp/blob/main/docs/"
        return {label: base + name for label, name in docs.items()}
    return {label: str(_REPO_ROOT / "docs" / name) for label, name in docs.items()}


if __name__ == "__main__":
    main()
