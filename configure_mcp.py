#!/usr/bin/env python3
# This is the interactive MCP server setup script, not a packaging file.
# Run directly: python3 configure_mcp.py
# Or via the platform launchers: ./get.sh (macOS/Linux)  |  .\get.ps1 (Windows)
"""Interactive setup: installs dependencies and writes .mcp.json."""
from __future__ import annotations

import getpass
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
MCP_JSON = ROOT / ".mcp.json"

_IS_WINDOWS = sys.platform == "win32"


# ── helpers ───────────────────────────────────────────────────────────────────


def _venv_binary() -> Path:
    if _IS_WINDOWS:
        return VENV / "Scripts" / "openproject-mcp.exe"
    return VENV / "bin" / "openproject-mcp"


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
    dest = path.with_suffix(f".bak.{ts}")
    path.rename(dest)
    print(f"Backed up {path.name} → {dest.name}")


def _write_mcp_json(env: dict[str, str]) -> None:
    config = {
        "mcpServers": {
            "openproject": {
                "command": str(_venv_binary()),
                "env": env,
            }
        }
    }
    if MCP_JSON.exists():
        _backup(MCP_JSON)
    MCP_JSON.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
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


# ── main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    _check_python()

    uv = _find_uv()
    _install_deps(uv)

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

    read_projects = _prompt(
        "Readable projects (* for all)",
        existing.get("OPENPROJECT_ALLOWED_PROJECTS_READ", "*"),
    )
    write_projects = _prompt(
        "Writable projects (empty = none, * = all)",
        existing.get("OPENPROJECT_ALLOWED_PROJECTS_WRITE", ""),
    )
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
    print()
    print("Setup complete — but this is only step 1.")
    print(f"Binary:      {_venv_binary()}")
    print(f"Config file: {MCP_JSON}")
    print()
    print("Next: register the server with your MCP client. The config was written")
    print("inside this install directory, but your client does not look here on its")
    print("own — a project-scoped client expects .mcp.json in your project root, and")
    print("a user-wide client expects the server in its own config. Follow the guide")
    print("for your client (both project-scoped and user-wide setups are shown):")
    print(f"  - Claude / Claude Code: {ROOT / 'docs' / 'claude.md'}")
    print(f"  - Codex:                {ROOT / 'docs' / 'codex.md'}")
    print(f"  - GitHub Copilot:       {ROOT / 'docs' / 'github.md'}")
    print()
    print("Then restart the client so it picks up the server.")


if __name__ == "__main__":
    main()
