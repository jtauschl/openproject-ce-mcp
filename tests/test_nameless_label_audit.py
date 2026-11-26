"""No text fallback of the adapters, services or the client is built from an id.

A name, title or subject that the server did not send is replaced by a fallback (`_trim_text(x) or <fallback>`). The
hide stamp drops the `id` member of a record but does not edit a text, so a fallback built from the id repeats a
hidden id. The rule is positive and does not depend on the member the fallback fills: in every `or` chain or
conditional expression whose first operand reads a text (`_trim_text`, `_link_title`, ...), and in every
`if not x: x = ...`, the fallback is a constant, `None` or `unnamed(<constant>)`. Anything else is in `EXEMPT`
with the reason it is safe, and an entry that matches nothing fails, so the table cannot rot.

Stated boundary: a text read is a call of a reader listed here, a `.get` of `name`, `title`, `subject` or `fileName`
(also through `str(...)`, a walrus or a name the function assigned from one); a chain that starts with another call and
a fallback built in a helper that is itself called with an id, and a subscript read (`payload["name"]`, which raises on a
missing key and so is no fallback) are not matched; `test_nameless_labels.py` and the nameless variant of the read-result scan cover the sites that exist.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import openproject_ce_mcp

SRC = Path(openproject_ce_mcp.__file__).parent
TEXT_READERS = frozenset({"_trim_text", "trim_text", "_link_title", "link_title", "_extract_formattable_text"})
# A `.get` of one of these keys reads a text a server may leave out.
NAME_KEYS = frozenset({"name", "title", "subject", "fileName"})
# Chains and conditional expressions found on the tree when this guard was written: the guard has to find them.
MIN_FALLBACKS = 72

_NOT_AN_ID = "the key or slug of a schema property, a query column or an operator: a string name, no record id"
# (file, function, fallback) -> why it is safe.
EXEMPT: dict[tuple[str, str, str], str] = {
    (
        "app/adapters/httpx_board_api.py",
        "_normalize_query_link_label",
        "_slug_from_href(value.get('href'))",
    ): _NOT_AN_ID,
    (
        "app/adapters/httpx_board_api.py",
        "_normalize_board_filter",
        "_slug_from_href(links.get('operator', {}).get('href'))",
    ): _NOT_AN_ID,
    (
        "app/adapters/httpx_board_api.py",
        "_filter_value_label",
        "_UNNAMED_KEPT_LINK[collection]",
    ): "a lookup in a module-level table of `unnamed(<literal>)` labels, one per instance-wide collection: no id",
    ("app/adapters/httpx_group_api.py", "normalize_group_detail", "_link_title(item.get('_links', {}).get('self'))"): (
        "the title of the group's own link, text the server sent"
    ),
    ("app/adapters/httpx_project_api.py", "normalize_project_field_schema", "key"): _NOT_AN_ID,
    ("app/services/_custom_field_writes.py", "apply_custom_fields", "schema_key"): _NOT_AN_ID,
    ("client.py", "_normalize_field_schema", "key"): _NOT_AN_ID,
}
_CHOICE = "a choice between two readings of one value by its property, not a fallback"
_OTHER_TEXT = "another text the server sent for the same thing (a title, a name, the record's project): no id"
EXEMPT.update(
    {
        ("app/adapters/httpx_backlog_bucket_api.py", "_defining_workspace_link", "embedded.get('name')"): _OTHER_TEXT,
        ("app/adapters/httpx_query_metadata_api.py", "normalize_query_column", "self_link.get('title')"): _OTHER_TEXT,
        ("app/adapters/httpx_query_metadata_api.py", "normalize_query_operator", "self_link.get('title')"): _OTHER_TEXT,
        ("app/adapters/httpx_query_metadata_api.py", "normalize_query_sort_by", "self_link.get('title')"): _OTHER_TEXT,
        ("app/adapters/httpx_sprint_api.py", "_defining_workspace_link", "embedded.get('name')"): _OTHER_TEXT,
        ("app/services/board_service.py", "update", "current.summary.project"): _OTHER_TEXT,
        ("app/services/meeting_service.py", "create", "project_payload.get('name')"): _OTHER_TEXT,
        ("app/services/meeting_service.py", "update", "current.summary.project"): _OTHER_TEXT,
        ("app/services/recurring_meeting_service.py", "create", "project_payload.get('name')"): _OTHER_TEXT,
        (
            "app/adapters/httpx_notification_api.py",
            "normalize_notification_detail",
            "_delimit_user_content(_trim_text(item.get('value'), limit=FORMATTABLE_LIMIT))",
        ): _CHOICE,
        ("app/offered_values.py", "candidates_clause", "str(identifier)"): (
            "the id is the point of the clause: an ambiguity text offers the numeric id to pass, a separate surface "
            "from the labels of this guard"
        ),
        (
            "app/services/_schema_write_helpers.py",
            "_option_title",
            "item.get('_links', {}).get('self', {}).get('title')",
        ): _OTHER_TEXT,
        ("app/services/_schema_write_helpers.py", "resolve_custom_field_key", "key"): _NOT_AN_ID,
        ("app/adapters/httpx_action_capability_api.py", "normalize_capability", "_slug_from_href(href)"): (
            "the fallback of the `id` member itself, a string id, not a label that repeats an id"
        ),
    }
)


def _is_text_read(node: ast.AST, names: frozenset[str] = frozenset()) -> bool:
    """A call of a text reader, or a name the same function assigned from one."""
    if isinstance(node, ast.Name):
        return node.id in names
    if isinstance(node, ast.NamedExpr):
        return _is_text_read(node.value, names)
    if not isinstance(node, ast.Call):
        return False
    function = node.func
    if isinstance(function, ast.Name) and function.id == "str" and node.args:
        return _is_text_read(node.args[0], names)
    if isinstance(function, ast.Attribute) and function.attr == "get" and node.args:
        key = node.args[0]
        if isinstance(key, ast.Constant) and key.value in NAME_KEYS:
            return True
    name = (
        function.id if isinstance(function, ast.Name) else function.attr if isinstance(function, ast.Attribute) else ""
    )
    return name in TEXT_READERS


def _allowed(fallback: ast.AST) -> bool:
    if isinstance(fallback, ast.Constant):
        return True
    return (
        isinstance(fallback, ast.Call)
        and isinstance(fallback.func, ast.Name)
        and fallback.func.id == "unnamed"
        and len(fallback.args) == 1
        and isinstance(fallback.args[0], ast.Constant)
    )


def _fallbacks(tree: ast.AST) -> list[tuple[str, ast.AST]]:
    """(function name, the fallback expression) of every text fallback in the tree."""
    found: list[tuple[str, ast.AST]] = []

    def visit(node: ast.AST, function: str, names: frozenset[str] = frozenset()) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names = frozenset(
                target.id
                for inner in ast.walk(node)
                if isinstance(inner, ast.Assign) and _is_text_read(inner.value)
                for target in inner.targets
                if isinstance(target, ast.Name)
            )
        for block in (getattr(node, field, None) for field in ("body", "orelse", "finalbody")):
            if not isinstance(block, list):
                continue
            read: set[str] = set()
            for statement in block:
                if isinstance(statement, ast.Assign) and _is_text_read(statement.value, names):
                    read |= {ast.unparse(target) for target in statement.targets}
                elif (
                    isinstance(statement, ast.If)
                    and isinstance(statement.test, ast.UnaryOp)
                    and isinstance(statement.test.op, ast.Not)
                    and ast.unparse(statement.test.operand) in read
                ):
                    target = ast.unparse(statement.test.operand)
                    for inner in statement.body:
                        if isinstance(inner, ast.Assign) and [ast.unparse(t) for t in inner.targets] == [target]:
                            found.append((function, inner.value))
        for child in ast.iter_child_nodes(node):
            name = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else function
            if isinstance(child, ast.BoolOp) and isinstance(child.op, ast.Or):
                reads = [index for index, value in enumerate(child.values[:-1]) if _is_text_read(value, names)]
                if reads:
                    # Every operand after the first text read is a fallback, the last one always; a further text
                    # read in the middle of the chain is another source of the same text.
                    middle = [v for v in child.values[reads[0] + 1 : -1] if not _is_text_read(v, names)]
                    found.extend((name, fallback) for fallback in [*middle, child.values[-1]])
            elif isinstance(child, ast.IfExp):
                if _is_text_read(child.test, names) or _is_text_read(child.body, names):
                    found.append((name, child.orelse))
                elif _is_text_read(child.orelse, names):
                    found.append((name, child.body))
            visit(child, name, names)

    visit(tree, "<module>")
    return found


def _violations(text: str, path: str) -> list[tuple[str, str, str]]:
    return [
        (path, function, ast.unparse(fallback))
        for function, fallback in _fallbacks(ast.parse(text))
        if not _allowed(fallback)
    ]


def _tree() -> dict[str, str]:
    return {
        str(path.relative_to(SRC)): path.read_text()
        for path in sorted([*(SRC / "app").rglob("*.py"), *SRC.glob("*.py")])
    }


def test_every_text_fallback_is_a_constant_none_or_an_unnamed_label_or_is_listed() -> None:
    sources = _tree()
    found = {violation for path, text in sources.items() for violation in _violations(text, path)}

    assert found - set(EXEMPT) == set(), "a text fallback that is not a constant: build it with `unnamed(kind)`"
    assert set(EXEMPT) - found == set(), "an exemption matches nothing any more: remove it"
    assert all(EXEMPT.values())


def test_the_guard_finds_the_fallbacks_of_the_tree() -> None:
    total = sum(len(_fallbacks(ast.parse(text))) for text in _tree().values())

    assert total >= MIN_FALLBACKS


@pytest.mark.parametrize(
    "planted",
    [
        'name = _trim_text(payload.get("name"), limit=1) or f"Status {payload[\'id\']}"',
        'name = _trim_text(payload.get("name"), limit=1) or str(payload["id"])',
        'name = _trim_text(payload.get("name"), limit=1) or "Status {}".format(payload["id"])',
        'name = _trim_text(payload.get("name"), limit=1) or "Status %s" % payload["id"]',
        'name = _trim_text(payload.get("name"), limit=1) or "Status " + str(payload["id"])',
        'name = _link_title(link) or _trim_text(payload.get("name"), limit=1) or f"Status {payload[\'id\']}"',
        'name = _trim_text(payload.get("name"), limit=1) if payload else f"Status {payload[\'id\']}"',
        'name = _trim_text(payload.get("name"), limit=1)\nif not name:\n    name = f"Status {payload[\'id\']}"',
        'name = _trim_text(payload.get("name"), limit=1) or unnamed(f"status {payload[\'id\']}")',
        'name = _trim_text(payload.get("name"), limit=1) or unnamed(kind)',
        'name = _trim_text(payload.get("name"), limit=1) or f"Status {payload[\'id\']}" or "x"',
        'name = payload.get("name") or f"Status {payload[\'id\']}"',
        'name = str(payload.get("title", "")) or f"Status {payload[\'id\']}"',
        'name = f"Status {payload[\'id\']}" if not payload.get("name") else payload.get("name")',
        'name = (text := _trim_text(payload.get("name"), limit=1)) or f"Status {payload[\'id\']}"',
        'text = _trim_text(payload.get("name"), limit=1)\nname = text or f"Status {payload[\'id\']}"',
        'return Summary(title=_trim_text(payload.get("title"), limit=1) or label_of(payload["id"]))',
        'return {"name": _trim_text(payload.get("name"), limit=1) or f"X {payload[\'id\']}"}',
    ],
)
def test_the_guard_flags_a_fallback_built_from_an_id(planted: str) -> None:
    source = "def normalize(payload, link=None, kind='x'):\n    " + planted.replace("\n", "\n    ") + "\n"

    assert _violations(source, "planted.py") != []


@pytest.mark.parametrize(
    "planted",
    [
        'name = _trim_text(payload.get("name"), limit=1) or unnamed("status")',
        'name = _trim_text(payload.get("name"), limit=1) or "Unknown"',
        "name = _link_title(link) if link else None",
        'name = _trim_text(payload.get("name"), limit=1) or None',
        'name = payload.get("id") or 0',
    ],
)
def test_the_guard_passes_a_constant_a_none_and_an_unnamed_label(planted: str) -> None:
    source = "def normalize(payload, link=None):\n    " + planted + "\n"

    assert _violations(source, "planted.py") == []


def _lookup_name_keywords(text: str) -> list[str]:
    return [
        ast.unparse(keyword.value)
        for node in ast.walk(ast.parse(text))
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg == "lookup_name"
    ]


def test_every_lookup_name_of_an_adapter_is_the_one_raw_name_helper() -> None:
    """`str(payload.get("name", ""))` turns a JSON null into the text `None`, which a caller could then resolve."""
    values = [
        value
        for path in sorted((SRC / "app" / "adapters").glob("*.py"))
        for value in _lookup_name_keywords(path.read_text())
    ]

    assert len(values) >= 10
    assert [value for value in values if not value.startswith("lookup_name(")] == []


def test_the_lookup_name_rule_flags_a_str_of_a_get() -> None:
    planted = 'Record(lookup_name=str(payload.get("name", "")))'

    assert _lookup_name_keywords(planted) == ["str(payload.get('name', ''))"]
