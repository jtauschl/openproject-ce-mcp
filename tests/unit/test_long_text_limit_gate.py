"""Long-text fields stay unbounded on the way in.

OpenProject stores descriptions, comments, status explanations and
notification messages as unbounded text with no length validation. A cap
in this layer mirrors no real constraint, only invites a caller to shorten
text to get it accepted, and leaves work packages with longer descriptions
uneditable through the server. This pins every such call site to
``max_length=None`` and keeps a 10,000 literal out of every text-validator
call, by AST, so a spelling variant of the number cannot slip past.
"""

from __future__ import annotations

import ast
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parents[2] / "src" / "openproject_ce_mcp"
_TEXT_VALIDATORS = {"_validate_optional_text", "_validate_optional_update_text", "_validate_required_text"}
_RETIRED_LITERAL = 10_000

# (tool module, field name) pairs whose backing OpenProject column is unbounded
# text. Other "description" fields (relations, news summaries) have real
# server-side caps and are deliberately not listed.
_UNBOUNDED_LONG_TEXT_SITES = {
    ("tools_work_packages.py", "description"),
    ("tools_work_packages.py", "comment"),
    ("tools_projects.py", "description"),
    ("tools_projects.py", "status_explanation"),
    ("tools_versions.py", "description"),
    ("tools_documents.py", "description"),
    ("tools_attachments.py", "description"),
    ("tools_time_entries.py", "comment"),
    ("tools_memberships.py", "notification_message"),
}


def _field_name(node: ast.Call) -> str | None:
    """The literal field name of a validator call; f-strings such as
    ``f"{field_prefix}description"`` resolve to their trailing constant."""
    for keyword in node.keywords:
        if keyword.arg != "field_name":
            continue
        value = keyword.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
        if isinstance(value, ast.JoinedStr) and value.values and isinstance(value.values[-1], ast.Constant):
            return str(value.values[-1].value)
    return None


def _max_length(node: ast.Call) -> ast.expr | None:
    return next((keyword.value for keyword in node.keywords if keyword.arg == "max_length"), None)


def _validator_calls(path: Path) -> list[ast.Call]:
    tree = ast.parse(path.read_text(), filename=str(path))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _TEXT_VALIDATORS
    ]


def _is_none(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def test_max_length_none_sites_match_the_unbounded_inventory_exactly() -> None:
    """Both directions: every inventoried site passes None, and nothing outside the
    inventory does -- a relation description or news summary accidentally set to
    None would show up as ``extra``."""
    none_sites: set[tuple[str, str]] = set()
    capped_inventory_sites: list[str] = []
    for path in sorted(_TOOLS_DIR.glob("tools_*.py")):
        for call in _validator_calls(path):
            field = _field_name(call) or f"<dynamic field_name at line {call.lineno}>"
            site = (path.name, field)
            if _is_none(_max_length(call)):
                none_sites.add(site)
            elif site in _UNBOUNDED_LONG_TEXT_SITES:
                capped_inventory_sites.append(f"{path.name}:{call.lineno} {field}")
    assert capped_inventory_sites == [], (
        f"unbounded long-text fields must pass max_length=None: {capped_inventory_sites}"
    )
    extra = none_sites - _UNBOUNDED_LONG_TEXT_SITES
    missing = _UNBOUNDED_LONG_TEXT_SITES - none_sites
    assert not extra and not missing, (
        f"max_length=None sites drifted from the inventory: extra={sorted(extra)} missing={sorted(missing)}"
    )


def test_no_text_validator_call_hard_codes_the_retired_long_text_cap() -> None:
    offenders = [
        f"{path.name}:{call.lineno}"
        for path in sorted(_TOOLS_DIR.glob("tools_*.py"))
        for call in _validator_calls(path)
        if isinstance(limit := _max_length(call), ast.Constant) and limit.value == _RETIRED_LITERAL
    ]
    assert offenders == [], offenders
