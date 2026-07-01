#!/usr/bin/env python3
# This is the interactive MCP server setup script, not a packaging file.
# Run directly: python3 configure_mcp.py
# Or via the platform launchers: ./get.sh (macOS/Linux)  |  .\get.ps1 (Windows)
"""Interactive setup: installs dependencies and writes .mcp.json."""
from __future__ import annotations

import getpass
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
MCP_JSON = ROOT / ".mcp.json"

_IS_WINDOWS = sys.platform == "win32"
_IS_MACOS = sys.platform == "darwin"


# ── helpers ───────────────────────────────────────────────────────────────────


def _venv_binary() -> Path:
    if _IS_WINDOWS:
        return VENV / "Scripts" / "openproject-mcp.exe"
    return VENV / "bin" / "openproject-mcp"


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
        if isinstance(loaded, dict):
            data = loaded
    servers = data.get(root_key)
    if not isinstance(servers, dict):
        servers = {}
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


def _strip_codex_openproject(existing: str) -> str:
    """Remove any existing [mcp_servers.openproject] / .env tables from TOML text.

    The stdlib has no TOML writer, so we edit text: drop the openproject tables
    (and their key/value lines up to the next table header) and keep the rest of
    the file verbatim. Other tables and top-level keys are untouched.

    Assumes the standard ``[table]`` header form Codex writes; it does not rewrite
    an openproject server expressed as a dotted/inline table (a form Codex does
    not emit). Prefix siblings like ``[mcp_servers.openproject2]`` are preserved.
    """
    out: list[str] = []
    skipping = False
    for line in existing.splitlines():
        header = line.strip()
        if header.startswith("["):
            table = header.strip("[]").strip()
            skipping = table == "mcp_servers.openproject" or table.startswith(
                "mcp_servers.openproject."
            )
        if not skipping:
            out.append(line)
    return "\n".join(out)


def _merge_codex_toml(existing: str, command: str, env: dict[str, str]) -> str:
    """Preserve the rest of the Codex config, replacing only the openproject table."""
    kept = _strip_codex_openproject(existing).rstrip()
    block = _codex_block(command, env)
    if kept:
        return f"{kept}\n\n{block}\n"
    return f"{block}\n"


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


def _detect_claude_code() -> bool:
    return bool(shutil.which("claude")) or (_home() / ".claude.json").exists() or (
        _home() / ".claude"
    ).exists()


def _detect_claude_desktop() -> bool:
    return _claude_desktop_path().parent.exists()


def _detect_codex() -> bool:
    return bool(shutil.which("codex")) or (_home() / ".codex").exists()


def _detect_vscode() -> bool:
    return bool(shutil.which("code")) or _vscode_user_mcp_path().parent.parent.exists()


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
    path.rename(dest)
    print(f"Backed up {path.name} → {dest.name}")


def _write_mcp_json(env: dict[str, str]) -> None:
    existing = MCP_JSON.read_text(encoding="utf-8") if MCP_JSON.exists() else ""
    if MCP_JSON.exists():
        _backup(MCP_JSON)
    MCP_JSON.write_text(
        _merge_json(existing, "mcpServers", str(_venv_binary()), env, stdio=False),
        encoding="utf-8",
    )
    if not _IS_WINDOWS:
        MCP_JSON.chmod(0o600)
    print(f"Written: {MCP_JSON}")


# ── prompts ───────────────────────────────────────────────────────────────────


def _prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value if value else default


def _prompt_secret(label: str, has_existing: bool = False) -> str:
    hint = " [leave empty to keep current]" if has_existing else ""
    try:
        return getpass.getpass(f"{label}{hint}: ").strip()
    except (EOFError, OSError):
        # Non-interactive fallback (e.g. piped input in tests)
        return input(f"{label}{hint}: ").strip()


def _prompt_bool(label: str, default: bool = False) -> bool:
    suffix = " [Y/n]" if default else " [y/N]"
    answer = input(f"{label}{suffix}: ").strip().lower()
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


def main() -> None:
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
