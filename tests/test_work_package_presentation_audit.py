"""Every service that returns work package results presents them through one module.

The parent check and the hidden-field masking live in `_work_package_presentation`. A service that
stamped work packages itself could miss a rule the other one has, as `execute_query` once did for
hidden custom fields.
"""

from __future__ import annotations

import ast

import pytest
from _source_scan import APP, SERVICES, calls_named, matching_nodes

PRESENTATION = "_work_package_presentation.py"
CONSUMERS = {"work_package_service.py", "query_execution_service.py"}
STAMPS = ("apply_hidden_fields_with_aliases", "_mask_custom_field_values")


def _imports(text: str, module: str) -> set[str]:
    return {
        alias.name
        for node in ast.walk(ast.parse(text))
        if isinstance(node, ast.ImportFrom) and node.module == module
        for alias in node.names
    }


def _files_importing(module: str, name: str) -> set[str]:
    return {p.name for p in sorted(SERVICES.glob("*.py")) if name in _imports(p.read_text(), module)}


def _of_work_packages(stamp: str):
    """A call of `stamp`; the generic one only when it names the work package entity."""
    named = calls_named(stamp)

    def predicate(node: ast.AST) -> bool:
        if not named(node):
            return False
        if stamp != "apply_hidden_fields_with_aliases":
            return True
        first = node.args[0] if isinstance(node, ast.Call) and node.args else None
        return isinstance(first, ast.Constant) and first.value == "work_package"

    return predicate


def _stamping_functions(source: str | None = None) -> dict[str, list[ast.AST]]:
    found: dict[str, list[ast.AST]] = {}
    for stamp in STAMPS:
        for name, nodes in matching_nodes(_of_work_packages(stamp), directories=(SERVICES,), source=source).items():
            found.setdefault(name, []).extend(nodes)
    return found


def test_only_the_presentation_module_stamps_work_packages() -> None:
    stamping = _stamping_functions()

    assert stamping, "the scan sees no stamping call at all"
    assert {name.split(":")[0] for name in stamping} == {PRESENTATION}


def test_a_stamping_call_outside_the_presentation_module_is_found() -> None:
    planted = "def present(summary, settings):\n    return hidden_fields.apply_hidden_fields_with_aliases('work_package', summary)\n"

    assert list(_stamping_functions(planted)) == ["planted.py:present"]


def test_every_service_that_reads_work_packages_presents_them_through_the_presentation_module() -> None:
    readers = _files_importing("ports.work_package_api", "WorkPackageApi")
    presenters = _files_importing("_work_package_presentation", "present_summaries") | _files_importing(
        "_work_package_presentation", "stamp_detail"
    )

    assert readers == CONSUMERS
    assert readers <= presenters


DECISION = "_scoped_references.py"


def _builds_visible_references(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    named = func.id if isinstance(func, ast.Name) else None
    on_class = (
        isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "VisibleReferences"
    )
    return named == "VisibleReferences" or (on_class and func.attr in {"everything", "only"})  # type: ignore[union-attr]


def _decision_sites(source: str | None = None) -> dict[str, list[ast.AST]]:
    directories = (APP / "adapters", APP / "resolvers", SERVICES, APP / "policies")
    return matching_nodes(_builds_visible_references, directories=directories, source=source)


def test_only_the_reference_helper_decides_which_references_a_result_may_name() -> None:
    sites = _decision_sites()

    assert sites, "the scan sees no decision at all"
    assert {name.split(":")[0] for name in sites} == {DECISION}


@pytest.mark.parametrize(
    "construction", ["VisibleReferences.everything()", "VisibleReferences.only([])", "VisibleReferences(None)"]
)
def test_a_decision_made_anywhere_else_is_found(construction: str) -> None:
    assert list(
        _decision_sites(f"def present(record):\n    return record.scoped_summary(visible={construction})\n")
    ) == ["planted.py:present"]
