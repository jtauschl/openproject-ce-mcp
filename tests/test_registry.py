"""Parity test: every tool registered in register_tools() must appear in docs/tools.md."""
import ast
import re
from pathlib import Path

TOOLS_PY = Path(__file__).parent.parent / "src" / "openproject_ce_mcp" / "tools.py"
TOOLS_MD = Path(__file__).parent.parent / "docs" / "tools.md"


def _registered_tool_names() -> set[str]:
    """Parse register_tools() from tools.py and return all registered function names."""
    source = TOOLS_PY.read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "register_tools":
            names: set[str] = set()
            for stmt in ast.walk(node):
                # Registrations go through the local helper: tool(some_name).
                # (The helper wraps mcp.tool() with error categorization.)
                if (
                    isinstance(stmt, ast.Expr)
                    and isinstance(stmt.value, ast.Call)
                    and isinstance(stmt.value.func, ast.Name)
                    and stmt.value.func.id == "tool"
                    and stmt.value.args
                    and isinstance(stmt.value.args[0], ast.Name)
                ):
                    names.add(stmt.value.args[0].id)
            return names

    raise RuntimeError("register_tools() not found in tools.py")


def _documented_tool_names() -> set[str]:
    """Parse docs/tools.md and return all backtick-quoted identifiers in table rows."""
    content = TOOLS_MD.read_text()
    # Match `identifier` at the start of a table cell (pipe-separated)
    return set(re.findall(r"\|\s*`([a-z_]+)`", content))


def test_all_registered_tools_are_documented() -> None:
    registered = _registered_tool_names()
    documented = _documented_tool_names()

    missing = registered - documented
    assert not missing, (
        "Tools registered in register_tools() but missing from docs/tools.md:\n"
        + "\n".join(f"  - {name}" for name in sorted(missing))
    )


def test_no_extra_tools_documented() -> None:
    registered = _registered_tool_names()
    documented = _documented_tool_names()

    extra = documented - registered
    assert not extra, (
        "Tools in docs/tools.md but not registered in register_tools():\n"
        + "\n".join(f"  - {name}" for name in sorted(extra))
    )
