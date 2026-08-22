"""Parity test: every tool classified in tools.py must appear in docs/tools.md."""

import re
import subprocess
import sys
from pathlib import Path

from openproject_ce_mcp import tools as _tools  # noqa: F401  (import for its @register_tool side effect)
from openproject_ce_mcp import tools_runtime as _tools_runtime

TOOLS_MD = Path(__file__).parent.parent / "docs" / "tools.md"


def _registered_tool_names() -> set[str]:
    """Every tool name known to the classification constants.

    register_tools() no longer contains hand-written `tool(name)` calls to
    parse — it iterates `enabled_tool_names()`, which resolves names through
    `tools_runtime._TOOL_FUNCTIONS`. Each tool function populates that dict
    itself via the `@register_tool` decorator at import time;
    `test_tool_groups.py`'s `test_every_classified_name_resolves_to_a_real_function`
    separately verifies `_TOOL_FUNCTIONS`'s keys exactly match the
    classification constants (READ_TOOLS_BY_SCOPE, WRITE_TOOLS_BY_SCOPE,
    PERSONAL_MUTATION_TOOLS, ATTACHMENT_UPLOAD_TOOLS), so reading its keys
    directly here is both simpler and more accurate than re-parsing
    register_tools() via AST.
    """
    return set(_tools_runtime._TOOL_FUNCTIONS)


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


def test_cold_process_import_populates_the_full_registry() -> None:
    """Prove registry completeness in a fresh interpreter, not just this test
    process. The other tests in this file (and test_tool_groups.py's
    test_every_classified_name_resolves_to_a_real_function) already assert the
    same invariant, but they run in a pytest process where some other test
    module may have already imported every tools_<domain>.py file as a side
    effect of an unrelated import -- which would hide a composition root that
    forgot to import a new domain module itself. A subprocess that imports
    ONLY `openproject_ce_mcp.tools` (the production composition root, exactly
    as `server.py`/`doctor.py` import it) rules that out.

    The four classification sources unioned below (PERSONAL_MUTATION_TOOLS,
    ATTACHMENT_UPLOAD_TOOLS, READ_TOOLS_BY_SCOPE, WRITE_TOOLS_BY_SCOPE) must be
    kept in sync with test_tool_groups.py's
    test_every_classified_name_resolves_to_a_real_function, which independently
    asserts these four are the COMPLETE set of classification sources (not
    just that they happen to match the registry) -- if a fifth classification
    source is ever added there, add it here too, or this test can stay green
    while silently checking only a subset.
    """
    script = (
        "import openproject_ce_mcp.tools as tools\n"
        "import openproject_ce_mcp.tools_runtime as tools_runtime\n"
        "classified = set(tools.PERSONAL_MUTATION_TOOLS) | set(tools.ATTACHMENT_UPLOAD_TOOLS)\n"
        "for names in tools.READ_TOOLS_BY_SCOPE.values():\n"
        "    classified |= set(names)\n"
        "for names in tools.WRITE_TOOLS_BY_SCOPE.values():\n"
        "    classified |= set(names)\n"
        "registered = set(tools_runtime._TOOL_FUNCTIONS)\n"
        "assert classified == registered, (classified - registered, registered - classified)\n"
        "print(len(registered))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"cold-import registry check failed:\n{result.stdout}\n{result.stderr}"
