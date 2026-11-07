"""A project result with custom field values is built in one place, from a decision made once.

The values of a project record carry link titles that may name a version outside the read scope.
`_project_presentation` asks `_scoped_references` which references the result may name and builds the
summary or detail with that answer; the project service masks the result with the hide settings. A
service that called the record's factories itself, or read the identity summary into a result, could
show a title nobody judged.
"""

from __future__ import annotations

import ast

from _source_scan import APP, SERVICES, calls_named, matching_nodes

PRESENTATION = "_project_presentation.py"


def _scoped_builds(source: str | None = None) -> dict[str, list[ast.AST]]:
    found: dict[str, list[ast.AST]] = {}
    for method in ("scoped_summary", "scoped_detail"):
        for name, nodes in matching_nodes(calls_named(method), directories=(SERVICES,), source=source).items():
            found.setdefault(name, []).extend(nodes)
    return found


def test_the_project_factories_are_called_only_by_the_presentation_module() -> None:
    files = {name.split(":")[0] for name in _scoped_builds()}

    assert files == {PRESENTATION, "_work_package_presentation.py"}


def test_a_factory_call_in_a_service_is_found() -> None:
    planted = "def show(record, visible):\n    return record.scoped_detail(visible=visible)\n"

    assert list(_scoped_builds(planted)) == ["planted.py:show"]


def _mask_calls(source: str | None = None):
    def predicate(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "mask_custom_field_values"
            and any(
                keyword.arg == "entity" and isinstance(keyword.value, ast.Constant) and keyword.value.value == "project"
                for keyword in node.keywords
            )
        )

    return matching_nodes(predicate, directories=(SERVICES,), source=source)


def test_the_project_service_stamps_every_project_summary_with_the_custom_field_mask() -> None:
    assert list(_mask_calls()) == ["project_service.py:_stamp_project"]


def test_the_records_of_a_list_are_fetched_only_where_they_are_presented() -> None:
    callers = matching_nodes(
        lambda node: isinstance(node, ast.Name) and node.id == "fetch_project_records",
        directories=(SERVICES, APP / "resolvers"),
    )

    assert {name.split(":")[0] for name in callers} == {"project_service.py", "project_query.py"}
