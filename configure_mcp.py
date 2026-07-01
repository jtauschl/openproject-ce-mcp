#!/usr/bin/env python3
# This is the interactive MCP server setup script, not a packaging file.
# Run directly: python3 configure_mcp.py
# Or via the platform launchers: ./get.sh (macOS/Linux)  |  .\get.ps1 (Windows)
"""Interactive setup: installs dependencies and writes .mcp.json."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# tomllib is stdlib only on Python 3.11+. This installer supports 3.10 (which
# lacks it) and must stay dependency-free, so import it optionally. When present
# we use it to *validate* merged TOML before writing; when absent we fall back to
# the text-level checks in _merge_codex_toml.
try:
    import tomllib as _tomllib
except ModuleNotFoundError:  # Python 3.10
    _tomllib = None

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
MCP_JSON = ROOT / ".mcp.json"

_IS_WINDOWS = sys.platform == "win32"
_IS_MACOS = sys.platform == "darwin"


# ── helpers ───────────────────────────────────────────────────────────────────


def _venv_binary() -> Path:
    if _IS_WINDOWS:
        return VENV / "Scripts" / "openproject-ce-mcp.exe"
    return VENV / "bin" / "openproject-ce-mcp"


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
            raise ValueError(
                f"expected a JSON object at the top level, got {type(loaded).__name__}"
            )
        data = loaded
    servers = data.get(root_key)
    if servers is None:
        servers = {}
    elif not isinstance(servers, dict):
        # e.g. "mcpServers": [] — refuse rather than overwrite the user's value.
        raise ValueError(
            f'expected "{root_key}" to be a JSON object, got {type(servers).__name__}'
        )
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
                "existing openproject entry uses a dotted key or inline table; "
                "cannot merge by text edit"
            )
        if _TOML_HEADER_RE.match(stripped):
            table = stripped.lstrip("[").rstrip("]").strip()
            skipping = table == "mcp_servers.openproject" or table.startswith(
                "mcp_servers.openproject."
            )
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
    """A registerable MCP client: how to detect it and where its global config lives."""

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
    ) -> None:
        self.key = key
        self.label = label
        self.target = target
        self.fmt = fmt  # "json" or "toml"
        self._detect = detect
        self.doc = doc
        self.root_key = root_key
        self.stdio = stdio

    def detected(self) -> bool:
        return self._detect()

    def merge(self, existing: str, command: str, env: dict[str, str]) -> str:
        if self.fmt == "toml":
            return _merge_codex_toml(existing, command, env)
        return _merge_json(
            existing, self.root_key, command, env, stdio=self.stdio
        )


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
    return bool(shutil.which("claude")) or (_home() / ".claude.json").exists() or (
        _home() / ".claude"
    ).exists()


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
    return [
        Client(
            "claude-code",
            "Claude Code (CLI + IDE extension)",
            _home() / ".claude.json",
            "json",
            _detect_claude_code,
            "docs/claude.md",
            root_key="mcpServers",
        ),
        Client(
            "claude-desktop",
            "Claude Desktop app",
            _claude_desktop_path(),
            "json",
            _detect_claude_desktop,
            "docs/claude-desktop.md",
            root_key="mcpServers",
        ),
        Client(
            "codex",
            "Codex (CLI + IDE extension)",
            _home() / ".codex" / "config.toml",
            "toml",
            _detect_codex,
            "docs/codex.md",
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
        ),
        Client(
            "cursor",
            "Cursor",
            _home() / ".cursor" / "mcp.json",
            "json",
            _detect_cursor,
            "docs/cursor.md",
            root_key="mcpServers",
        ),
    ]


def _write_client_config(client: Client, command: str, env: dict[str, str]) -> bool:
    """Merge the ``openproject`` server into a client's global config.

    Existing content is preserved — only the ``openproject`` entry is added or
    replaced. A timestamped backup is taken before any existing file is rewritten.
    Returns True on success, False if the existing file could not be parsed.
    """
    target = client.target
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


def _remove_client_config(client: Client) -> bool:
    """Remove the openproject entry from a client's config; keep everything else.

    Backs up before rewriting. Returns True if something was removed.
    """
    target = client.target
    if not target.exists():
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
    """Remove the openproject entry from any client config it was registered in.

    The local .mcp.json and the venv are handled by uninstall.sh/.ps1; this Python
    step owns the client-config edits (JSON/TOML merge) so the same robust logic
    used to install is used to uninstall.
    """
    print("Removing the openproject server from client configs (existing settings kept)…")
    removed_any = False
    for client in _clients():
        if client.target.exists() and _remove_client_config(client):
            removed_any = True
    if not removed_any:
        print("  · No client config contained an openproject entry — nothing to remove.")
    print()
    print("Client configs done. Restart any client you had it registered in.")


def _check_python() -> None:
    # Intentional runtime guard: this setup script may be launched by whatever
    # interpreter the user has on PATH, which can predate the project minimum.
    if sys.version_info < (3, 10):  # noqa: UP036
        print(f"Python 3.10+ required. Current: {sys.version}", file=sys.stderr)
        sys.exit(1)


def _find_uv() -> str | None:
    return shutil.which("uv")


def _install_deps(uv: str | None) -> None:
    if uv:
        print("Installing with uv …")
        subprocess.run([uv, "sync"], cwd=ROOT, check=True)
    else:
        print("uv not found — falling back to venv + pip …")
        if not VENV.exists():
            subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
        pip = VENV / ("Scripts" if _IS_WINDOWS else "bin") / "pip"
        subprocess.run([str(pip), "install", "-e", "."], cwd=ROOT, check=True)


def _load_existing() -> dict[str, str]:
    if MCP_JSON.exists():
        try:
            data = json.loads(MCP_JSON.read_text(encoding="utf-8"))
            return data.get("mcpServers", {}).get("openproject", {}).get("env", {})
        except Exception:
            pass
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
    print(f"Backed up {path.name} → {dest.name}")


def _write_mcp_json(env: dict[str, str]) -> None:
    existing = MCP_JSON.read_text(encoding="utf-8") if MCP_JSON.exists() else ""
    # Merge first: if the existing file has an unexpected shape, _merge_json
    # raises and we must leave it untouched (do NOT back up then abort, which
    # would strand the user's data in a .bak with no working file written).
    try:
        merged = _merge_json(existing, "mcpServers", str(_venv_binary()), env, stdio=False)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"Could not update {MCP_JSON}: {exc}", file=sys.stderr)
        print("Left it untouched. Fix or remove the file by hand, then re-run.", file=sys.stderr)
        return
    if MCP_JSON.exists():
        _backup(MCP_JSON)
    MCP_JSON.write_text(merged, encoding="utf-8")
    if not _IS_WINDOWS:
        MCP_JSON.chmod(0o600)
    print(f"Written: {MCP_JSON}")


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


def _choose_registration_mode() -> list[Client]:
    """Ask up front whether to auto-configure any detected client; return the chosen.

    Asked before credentials are collected so the user decides the mode first. The
    default is no — the setup always writes a local config to copy from, and
    project-specific setup (docs/) is the recommended path. Only clients actually
    detected on this machine are offered.
    """
    detected = [c for c in _clients() if c.detected()]
    if not detected:
        return []

    print()
    print("Detected MCP clients:")
    for client in detected:
        print(f"  - {client.label}")
    print()
    print("The setup always writes a local .mcp.json you can copy into any client")
    print("(see the guides). It can also set up a detected client for you — adding the")
    print("server to its config, available in every project (existing settings kept and")
    print("backed up first).")
    print()
    print("No is recommended if you prefer project-specific client config.")
    if not _prompt_bool("Set up a detected client automatically?", default=False):
        return []

    chosen = []
    for client in detected:
        if _prompt_bool(f"  Set up {client.label} automatically? ({client.target})", default=False):
            chosen.append(client)
        else:
            print(f"    Skipped. Use {client.doc} for project-specific setup.")
    return chosen


def _apply_global_registration(clients: list[Client], command: str, env: dict[str, str]) -> None:
    for client in clients:
        _write_client_config(client, command, env)


# ── main ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Set up or remove the openproject MCP server.")
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Remove the openproject entry from detected client configs (leaves other servers/settings intact).",
    )
    args = parser.parse_args(argv)

    if args.uninstall:
        _run_uninstall()
        return

    _check_python()

    uv = _find_uv()
    _install_deps(uv)

    # Decide the registration mode before collecting credentials.
    global_clients = _choose_registration_mode()

    existing = _load_existing()

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
    read_projects = _prompt(
        "Readable projects (* = all visible)",
        existing.get("OPENPROJECT_ALLOWED_PROJECTS_READ", "*"),
    )
    write_projects = _prompt(
        "Writable projects (leave empty to disable writes; * = all)",
        existing.get("OPENPROJECT_ALLOWED_PROJECTS_WRITE", ""),
    )

    print()
    print("Optional field filtering — omit fields from reads. Leave empty unless you")
    print("need it; just press Enter to skip each.")
    hide_project = _prompt(
        "Hidden project fields (comma-separated)",
        existing.get("OPENPROJECT_HIDE_PROJECT_FIELDS", ""),
    )
    hide_wp = _prompt(
        "Hidden work-package fields (comma-separated)",
        existing.get("OPENPROJECT_HIDE_WORK_PACKAGE_FIELDS", ""),
    )
    hide_activity = _prompt(
        "Hidden activity fields (comma-separated)",
        existing.get("OPENPROJECT_HIDE_ACTIVITY_FIELDS", ""),
    )
    hide_custom = _prompt(
        "Hidden custom fields (comma-separated)",
        existing.get("OPENPROJECT_HIDE_CUSTOM_FIELDS", ""),
    )

    print()

    project_read = _prompt_bool(
        "Enable project reads?",
        _bool_from_env(existing, "OPENPROJECT_ENABLE_PROJECT_READ", True),
    )
    membership_read = _prompt_bool(
        "Enable membership reads (memberships, roles, principals)?",
        _bool_from_env(existing, "OPENPROJECT_ENABLE_MEMBERSHIP_READ", True),
    )
    work_package_read = _prompt_bool(
        "Enable work-package reads (work packages, activities, relations, attachments, time entries)?",
        _bool_from_env(existing, "OPENPROJECT_ENABLE_WORK_PACKAGE_READ", True),
    )
    version_read = _prompt_bool(
        "Enable version reads?",
        _bool_from_env(existing, "OPENPROJECT_ENABLE_VERSION_READ", True),
    )
    board_read = _prompt_bool(
        "Enable board reads?",
        _bool_from_env(existing, "OPENPROJECT_ENABLE_BOARD_READ", True),
    )
    wp_write = _prompt_bool(
        "Enable work-package writes (create/update/delete, comments, relations, attachments, time entries)?",
        _bool_from_env(existing, "OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE"),
    )
    project_write = _prompt_bool(
        "Enable project writes (create/update/delete)?",
        _bool_from_env(existing, "OPENPROJECT_ENABLE_PROJECT_WRITE"),
    )
    membership_write = _prompt_bool(
        "Enable membership writes (create/update/delete)?",
        _bool_from_env(existing, "OPENPROJECT_ENABLE_MEMBERSHIP_WRITE"),
    )
    version_write = _prompt_bool(
        "Enable version writes (create/update/delete)?",
        _bool_from_env(existing, "OPENPROJECT_ENABLE_VERSION_WRITE"),
    )
    board_write = _prompt_bool(
        "Enable board writes (create/update/delete)?",
        _bool_from_env(existing, "OPENPROJECT_ENABLE_BOARD_WRITE"),
    )

    env: dict[str, str] = {
        "OPENPROJECT_BASE_URL": base_url,
        "OPENPROJECT_API_TOKEN": token,
        "OPENPROJECT_ALLOWED_PROJECTS_READ": read_projects,
        "OPENPROJECT_ALLOWED_PROJECTS_WRITE": write_projects,
        "OPENPROJECT_ENABLE_PROJECT_READ": str(project_read).lower(),
        "OPENPROJECT_ENABLE_MEMBERSHIP_READ": str(membership_read).lower(),
        "OPENPROJECT_ENABLE_WORK_PACKAGE_READ": str(work_package_read).lower(),
        "OPENPROJECT_ENABLE_VERSION_READ": str(version_read).lower(),
        "OPENPROJECT_ENABLE_BOARD_READ": str(board_read).lower(),
        "OPENPROJECT_HIDE_PROJECT_FIELDS": hide_project,
        "OPENPROJECT_HIDE_WORK_PACKAGE_FIELDS": hide_wp,
        "OPENPROJECT_HIDE_ACTIVITY_FIELDS": hide_activity,
        "OPENPROJECT_HIDE_CUSTOM_FIELDS": hide_custom,
        "OPENPROJECT_ENABLE_PROJECT_WRITE": str(project_write).lower(),
        "OPENPROJECT_ENABLE_MEMBERSHIP_WRITE": str(membership_write).lower(),
        "OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE": str(wp_write).lower(),
        "OPENPROJECT_ENABLE_VERSION_WRITE": str(version_write).lower(),
        "OPENPROJECT_ENABLE_BOARD_WRITE": str(board_write).lower(),
        # Instance-wide user/group administration. Not prompted for on purpose —
        # it is a powerful, rarely needed capability. The key is written as false
        # (preserving any existing value) so it is visible and easy to flip by
        # hand; see .mcp.json.example and the README for details.
        "OPENPROJECT_ENABLE_ADMIN_WRITE": str(
            _bool_from_env(existing, "OPENPROJECT_ENABLE_ADMIN_WRITE")
        ).lower(),
        "OPENPROJECT_TIMEOUT": existing.get("OPENPROJECT_TIMEOUT", "12"),
        "OPENPROJECT_VERIFY_SSL": existing.get("OPENPROJECT_VERIFY_SSL", "true"),
        "OPENPROJECT_DEFAULT_PAGE_SIZE": existing.get("OPENPROJECT_DEFAULT_PAGE_SIZE", "20"),
        "OPENPROJECT_MAX_PAGE_SIZE": existing.get("OPENPROJECT_MAX_PAGE_SIZE", "50"),
        "OPENPROJECT_MAX_RESULTS": existing.get("OPENPROJECT_MAX_RESULTS", "100"),
        "OPENPROJECT_LOG_LEVEL": existing.get("OPENPROJECT_LOG_LEVEL", "WARNING"),
    }

    print()
    _write_mcp_json(env)

    _apply_global_registration(global_clients, str(_venv_binary()), env)

    print()
    print("Server installed.")
    print(f"Binary: {_venv_binary()}")
    print()
    print("Registered a client above? Restart it and you're done.")
    print("Otherwise register the server yourself — copy the values from")
    print(f"{MCP_JSON} into your client's config. Guides (project-scoped, global, verify):")
    print(f"  - Claude / Claude Code:      {ROOT / 'docs' / 'claude.md'}")
    print(f"  - Claude Desktop app:        {ROOT / 'docs' / 'claude-desktop.md'}")
    print(f"  - Codex:                     {ROOT / 'docs' / 'codex.md'}")
    print(f"  - VS Code / GitHub Copilot:  {ROOT / 'docs' / 'github.md'}")


if __name__ == "__main__":
    main()
