"""Parity test: every tool classified in tools.py must appear in docs/tools.md."""

import re
from pathlib import Path

from openproject_ce_mcp import tools as _tools

TOOLS_MD = Path(__file__).parent.parent / "docs" / "tools.md"


def _registered_tool_names() -> set[str]:
    """Every tool name known to the classification constants.

    register_tools() no longer contains hand-written `tool(name)` calls to
    parse — it iterates `enabled_tool_names()`, which resolves names through
    `_TOOL_FUNCTIONS`. Each tool function populates that dict itself via the
    `@register_tool` decorator at import time; `test_tool_groups.py`'s
    `test_every_classified_name_resolves_to_a_real_function` separately
    verifies `_TOOL_FUNCTIONS`'s keys exactly match the classification
    constants (READ_TOOLS_BY_SCOPE, WRITE_TOOLS_BY_SCOPE,
    PERSONAL_MUTATION_TOOLS, ATTACHMENT_UPLOAD_TOOLS), so reading its keys
    directly here is both simpler and more accurate than re-parsing
    register_tools() via AST.
    """
    return set(_tools._TOOL_FUNCTIONS)


def _documented_tool_names() -> set[str]:
    """Parse docs/tools.md and return all backtick-quoted identifiers in table rows."""
    content = TOOLS_MD.read_text()
    # Match `identifier` at the start of a table cell (pipe-separated)
    return set(re.findall(r"\|\s*`([a-z_]+)`", content))


def test_all_registered_tools_are_documented() -> None:
    registered = _registered_tool_names()
    documented = _documented_tool_names()

    missing = registered - documented
    assert not missing, "Tools registered in register_tools() but missing from docs/tools.md:\n" + "\n".join(
        f"  - {name}" for name in sorted(missing)
    )


def test_no_extra_tools_documented() -> None:
    registered = _registered_tool_names()
    documented = _documented_tool_names()

    extra = documented - registered
    assert not extra, "Tools in docs/tools.md but not registered in register_tools():\n" + "\n".join(
        f"  - {name}" for name in sorted(extra)
    )
