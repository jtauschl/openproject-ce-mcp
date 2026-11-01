"""OpenProject CE MCP Server - Model Context Protocol integration for OpenProject Community Edition."""

import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

_DISTRIBUTION = "openproject-ce-mcp"


def _source_tree_version() -> str | None:
    """The version in the pyproject.toml next to src/, for a package imported from a source checkout.

    A checkout run without installing the project (the dependencies installed, `src/` put on `sys.path` by
    `configure_mcp.py`) has no dist-info to read, but its pyproject.toml is the same file a build would read.
    Nothing is returned for an installed copy: there the missing dist-info is a broken install."""
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
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
try:
    __version__ = version(_DISTRIBUTION)
except PackageNotFoundError as exc:
    source_version = _source_tree_version()
    if source_version is None:
        raise RuntimeError(
            "openproject-ce-mcp is not installed in this Python environment (no dist-info found). "
            "If this is a source checkout with a previously-working editable install, the venv is "
            "likely stale (e.g. after a Python upgrade) -- run `uv sync --dev` to rebuild it."
        ) from exc
    __version__ = source_version
