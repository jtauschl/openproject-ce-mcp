"""Every entity that carries custom fields reads, masks and writes them through the shared modules.

Work packages and projects have `custom_fields` on their results. A third entity that gained them with
a copy of the logic could miss a rule the others have (a hide setting, the scope of a version title,
the clearing of a link). The other entities the server renders custom fields for are listed with the
reason they are not covered, so adding one is a decision that shows in a diff.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest
from _source_scan import ADAPTERS, APP, SERVICES, calls_named, matching_nodes

from openproject_ce_mcp import models

COVERED = {
    "ProjectSummary": "project",
    "ProjectDetail": "project",
    "WorkPackageSummary": "work_package",
    "WorkPackageDetail": "work_package",
}

# Carries the definitions of the fields (a schema), not the values of one resource.
DEFINITIONS_ONLY = {"ProjectWorkPackageContext"}

# The entities whose representer takes the custom field injector in OpenProject 16.0 and 17.9 and that
# this server does not read custom fields for.
NOT_COVERED = {
    "time_entry": "costs module; no ticket asked for it",
    "version": "no ticket asked for it",
    "user": "admin read tools only; no ticket asked for it",
    "group": "admin read tools only; no ticket asked for it",
}


def _result_types_with_custom_fields() -> set[str]:
    return {
        name
        for name, cls in vars(models).items()
        if isinstance(cls, type)
        and dataclasses.is_dataclass(cls)
        and "custom_fields" in {f.name for f in dataclasses.fields(cls)}
    }


def test_the_result_types_with_custom_fields_are_the_covered_ones() -> None:
    assert _result_types_with_custom_fields() - DEFINITIONS_ONLY == set(COVERED), (
        "an entity gained `custom_fields`: read it through adapters/_custom_fields.py, mask it with "
        "services/_custom_field_masking.py, write it with services/_custom_field_writes.py, then add it here"
    )


def test_no_not_covered_entity_has_a_result_type_with_custom_fields() -> None:
    names = {name.lower() for name in _result_types_with_custom_fields()}
    assert not any(entity.replace("_", "") in name for name in names for entity in NOT_COVERED)


def _imports(path: Path) -> set[str]:
    return {
        node.module or ""
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.ImportFrom) and node.level >= 1
    }


def test_an_adapter_that_reads_custom_field_keys_does_so_through_the_shared_module() -> None:
    reading = {
        path.name
        for path in sorted(ADAPTERS.glob("httpx_*.py"))
        if "customField" in path.read_text() or "custom_fields" in path.read_text()
    }

    assert reading == {"httpx_project_api.py", "httpx_work_package_api.py"}
    for name in reading:
        assert "_custom_fields" in _imports(ADAPTERS / name), name


def test_the_adapters_do_not_define_a_custom_field_extractor_of_their_own() -> None:
    def defines_extractor(node: ast.AST) -> bool:
        return isinstance(node, ast.FunctionDef) and node.name.startswith(("extract_custom", "_extract_custom"))

    defined = {
        path.name
        for path in sorted(ADAPTERS.glob("*.py"))
        if any(defines_extractor(node) for node in ast.walk(ast.parse(path.read_text())))
    }
    assert defined == {"_custom_fields.py"}


def test_only_the_masking_module_removes_custom_field_entries_from_a_result() -> None:
    callers = matching_nodes(calls_named("custom_field_hidden"), directories=(SERVICES,))
    assert {name.split(":")[0] for name in callers} <= {
        "_custom_field_masking.py",
        "_custom_field_writes.py",
        "_custom_field_filters.py",
        "_project_presentation.py",
        "_scoped_references.py",
        "_work_package_presentation.py",
        "_work_package_references.py",
        "project_service.py",
    }


@pytest.mark.parametrize("entity", sorted(set(COVERED.values())))
def test_each_covered_entity_masks_through_the_neutral_function(entity: str) -> None:
    sources = {
        "project": [SERVICES / "project_service.py"],
        "work_package": [SERVICES / "_work_package_presentation.py"],
    }[entity]
    text = "\n".join(path.read_text() for path in sources)

    assert f'entity="{entity}"' in text and "mask_custom_field_values" in text


def test_the_apps_other_layers_name_no_custom_field_extractor() -> None:
    for directory in (APP / "resolvers", APP / "policies"):
        for path in sorted(directory.glob("*.py")):
            assert "extract_custom_fields" not in path.read_text(), path.name
