"""Every `update_*` tool that writes a stored long text offers the edit pair, or says why not.

The set is derived from the source, not from a table: the unbounded text validators of the tool modules
(`test_long_text_limit_gate.py` pins which fields are unbounded) are attributed to their enclosing `update_*`
tool, and each such field must be a parameter of that tool together with its `<field>_append` and
`<field>_replace`. A new unbounded long text on an update tool therefore fails here until it gets the pair
or an entry in the exclusion list with a reason.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from test_long_text_limit_gate import _TOOLS_DIR, _field_name, _is_none, _max_length, _validator_calls

# A helper validates the fields of the tool that calls it.
_HELPER_OF = {"_validate_work_package_update_fields": "update_work_package"}

_EXCLUDED = {
    ("tools_time_entries.py", "update_time_entry", "comment"): "a single-line comment of a time entry, rewritten whole",
    (
        "tools_time_entries.py",
        "update_time_entry_until",
        "comment",
    ): "a single-line comment of a time entry, rewritten whole",
    ("tools_memberships.py", "update_membership", "notification_message"): "sent as a notification, never stored",
}


def _tool_parameters(path: Path) -> dict[str, set[str]]:
    tree = ast.parse(path.read_text(), filename=str(path))
    return {
        node.name: {arg.arg for arg in (*node.args.args, *node.args.kwonlyargs)}
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith("update_")
    }


def _unbounded_update_fields() -> set[tuple[str, str, str]]:
    sites: set[tuple[str, str, str]] = set()
    for path in sorted(_TOOLS_DIR.glob("tools_*.py")):
        for call in _validator_calls(path):
            tool = _HELPER_OF.get(call.enclosing_function, call.enclosing_function)  # type: ignore[attr-defined]
            field = _field_name(call)
            if tool.startswith("update_") and field is not None and _is_none(_max_length(call)):
                sites.add((path.name, tool, field))
    return sites


def test_the_derivation_finds_the_known_update_tools() -> None:
    fields = {(tool, field) for _, tool, field in _unbounded_update_fields()}
    assert {
        ("update_work_package", "description"),
        ("update_work_package_comment", "comment"),
        ("update_project", "description"),
        ("update_project", "status_explanation"),
        ("update_version", "description"),
        ("update_document", "description"),
        ("update_news", "description"),
    } <= fields


@pytest.mark.parametrize(
    ("module", "tool", "field"),
    sorted(site for site in _unbounded_update_fields() if site not in _EXCLUDED),
)
def test_an_unbounded_long_text_of_an_update_tool_has_the_edit_pair(module: str, tool: str, field: str) -> None:
    parameters = _tool_parameters(_TOOLS_DIR / module)[tool]
    assert {field, f"{field}_append", f"{field}_replace"} <= parameters


def test_every_exclusion_matches_a_live_site() -> None:
    assert set(_EXCLUDED) <= _unbounded_update_fields()
