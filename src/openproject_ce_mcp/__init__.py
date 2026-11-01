"""OpenProject CE MCP Server - Model Context Protocol integration for OpenProject Community Edition."""

import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

_DISTRIBUTION = "openproject-ce-mcp"


def _source_tree_version() -> str | None:
    """The version in the pyproject.toml next to src/, for a package imported from a source checkout.

    A checkout run without installing the project (the dependencies installed, `src/` put on `sys.path` by
    `configure_mcp.py`) has no dist-info to read, but its pyproject.toml is the same file a build would read.
    Nothing is returned for a copy outside a `src/` layout, such as an installed one: there the missing
    dist-info is a broken install."""
    package_dir = Path(__file__).resolve().parent
    if package_dir.parent.name != "src":
        return None
    pyproject = package_dir.parent.parent / "pyproject.toml"
    try:
        project = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {})
    except OSError:
        return None
    return project.get("version") if project.get("name") == _DISTRIBUTION else None


# No silent fallback for an installed copy: every supported install path (editable dev install, uv
# tool, pip, pipx) publishes dist-info; a raise here means the package
# genuinely isn't installed, which is worth surfacing directly -- but the
# bare PackageNotFoundError's fixed "No package metadata was found for
# {name}" message gives no hint that a stale/broken editable install (e.g. a
# venv whose symlinks survived a `brew upgrade python`, see this project's
# own CLAUDE.md) is the most likely real-world cause, not a from-scratch
# missing install. A plain RuntimeError (not PackageNotFoundError itself,
# whose __str__ ignores any message and always renders that fixed template
# from a single `name` arg) carries the actual remediation hint instead.
# A source checkout whose editable install lost its dist-info reads the same as a bare checkout: the
# package cannot tell them apart, and the version it then serves is the checkout's own.
try:
    __version__ = version(_DISTRIBUTION)
except PackageNotFoundError as exc:
    source_version = _source_tree_version()
    if source_version is None:
        raise RuntimeError(
            "openproject-ce-mcp is not installed in this Python environment (no dist-info found). "
            "Reinstall it (`uv tool install openproject-ce-mcp`, `pipx install openproject-ce-mcp` or "
            "`pip install openproject-ce-mcp`); in a source checkout run `uv sync --dev`."
        ) from exc
    __version__ = source_version
