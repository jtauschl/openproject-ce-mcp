"""The members of a write result that repeat a hidden field's value leave the result with that field.

`IDENTITY_FIELDS` names, per write result class, the members that repeat the value of one field of one entity.
These tests keep the table complete (every member of every class is classified, every named field exists), keep every
service that returns such a result decorated with `stamped_results`, and check the stamp itself. What a stamp
leaves out of a real tool result, in every state and every copy, is the job of
`test_write_results_hide_values_everywhere.py`.
"""

from __future__ import annotations

import ast
import dataclasses
import re
from pathlib import Path

import pytest
from _client_test_helpers import make_settings

import openproject_ce_mcp
from openproject_ce_mcp import models, tools  # noqa: F401 -- importing the tools registers them in _TOOL_FUNCTIONS
from openproject_ce_mcp.app.policies.identity_fields import (
    HEADER,
    IDENTITY_FIELDS,
    NOT_AN_IDENTITY,
    PAYLOAD_COPIES,
    STAMPED_BY_THEIR_OWN_ENTITY,
)
from openproject_ce_mcp.app.services._payload_masking import stamp_result
from openproject_ce_mcp.config import HIDE_FIELD_ENV_BY_ENTITY
from openproject_ce_mcp.presentation import _to_payload
from openproject_ce_mcp.tools_runtime import _TOOL_FUNCTIONS, _return_model

SERVICES = Path(openproject_ce_mcp.__file__).parent / "app" / "services"


def _write_result_classes() -> dict[str, type]:
    classes: dict[str, type] = {}
    for function in _TOOL_FUNCTIONS.values():
        model = _return_model(function)
        if model is None:
            continue
        names = {field.name for field in dataclasses.fields(model)}
        if "action" in names and ({"state", "ready"} <= names or "confirmed" in names):
            classes[model.__name__] = model
    return classes


def _entity_fields(entity: str) -> set[str]:
    camel = "".join(part.capitalize() for part in entity.split("_"))
    names: set[str] = set()
    for suffix in ("Summary", "Detail"):
        model = getattr(models, camel + suffix, None)
        if model is not None:
            names |= {field.name for field in dataclasses.fields(model)}
    return names


def _settings(entity: str, *patterns: str):
    return dataclasses.replace(make_settings(), hidden_fields={entity: tuple(patterns)})


CLASSES = _write_result_classes()


def _looks_like_a_write_result(model: type) -> bool:
    names = {field.name for field in dataclasses.fields(model)}
    return {"action", "message"} <= names and ({"state", "ready"} <= names or "confirmed" in names)


# Every dataclass of the models that looks like a write result, registered as a tool return type or not.
RESULT_MODELS = {
    name: model
    for name, model in vars(models).items()
    if isinstance(model, type) and dataclasses.is_dataclass(model) and _looks_like_a_write_result(model)
}


def test_every_write_result_class_is_found_and_tabled() -> None:
    assert {"WorkPackageWriteResult", "BulkWorkPackageWriteResult", "ProjectCopyResult"} <= set(CLASSES)
    tabled = set(IDENTITY_FIELDS) | set(NOT_AN_IDENTITY)
    # A result without a field of the kinds below carries no identity: it needs no row.
    carrying = {
        name
        for name, model in CLASSES.items()
        if {field.name for field in dataclasses.fields(model)} - HEADER - STAMPED_BY_THEIR_OWN_ENTITY
    }
    assert carrying - tabled == set(), "a write result class nobody classified"
    assert tabled - set(CLASSES) == set(), "a table row for a class that is no write result"


@pytest.mark.parametrize("name", sorted(CLASSES))
def test_every_member_of_a_write_result_is_classified(name: str) -> None:
    members = {field.name for field in dataclasses.fields(CLASSES[name])} - HEADER - STAMPED_BY_THEIR_OWN_ENTITY
    tabled = set(IDENTITY_FIELDS.get(name, {})) | set(NOT_AN_IDENTITY.get(name, {}))

    assert members - tabled == set(), "a member nobody classified"


@pytest.mark.parametrize("name", sorted(IDENTITY_FIELDS))
def test_every_table_row_names_a_real_member_and_a_real_owner_field(name: str) -> None:
    members = {field.name for field in dataclasses.fields(CLASSES[name])}
    for member, owners in IDENTITY_FIELDS[name].items():
        assert member in members, f"{name}.{member} is not a member"
        assert owners
        for entity, field in owners:
            assert entity in HIDE_FIELD_ENV_BY_ENTITY, f"{entity} is no hide entity"
            assert field in _entity_fields(entity), f"{entity} has no field {field}"
    assert all(NOT_AN_IDENTITY.get(name, {}).values())


def _decorated(node: ast.ClassDef) -> bool:
    return any(isinstance(item, ast.Name) and item.id == "stamped_results" for item in node.decorator_list)


def test_every_service_that_returns_a_write_result_stamps_it() -> None:
    """A public async method whose return annotation names a write result class (also inside a union or an
    optional) puts its class under `stamped_results`; a result class the tables do not know fails here."""
    returned = set(IDENTITY_FIELDS) | {"BulkWorkPackageWriteResult"}
    undecorated: list[str] = []
    unknown: list[str] = []
    for path in sorted(SERVICES.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.ClassDef):
                continue
            for method in node.body:
                if (
                    not isinstance(method, ast.AsyncFunctionDef)
                    or method.name.startswith("_")
                    or method.returns is None
                ):
                    continue
                named = set(re.findall(r"[A-Za-z_]+", ast.unparse(method.returns))) & set(RESULT_MODELS)
                if named - set(CLASSES):
                    unknown.append(f"{path.name}:{node.name}.{method.name} -> {sorted(named - set(CLASSES))}")
                if named & returned and not _decorated(node):
                    undecorated.append(f"{path.name}:{node.name}.{method.name}")
    assert unknown == []
    assert undecorated == []


def test_no_service_class_builds_a_write_result_without_stamping_it() -> None:
    """The constructor call is the other way in: a method without an annotation, a sync method or a helper of a
    class that is not decorated still builds the result inside the class."""
    stamped = set(IDENTITY_FIELDS) | {"BulkWorkPackageWriteResult"}
    unstamped: list[str] = []
    for path in sorted(SERVICES.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.ClassDef) or _decorated(node):
                continue
            for call in ast.walk(node):
                if isinstance(call, ast.Call):
                    callee = call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, "id", "")
                    if callee in stamped:
                        unstamped.append(f"{path.name}:{node.name} builds {callee}")
    assert unstamped == []


def _work_package_result() -> models.WorkPackageWriteResult:
    return models.WorkPackageWriteResult(
        action="update",
        state="confirmed",
        ready=True,
        message="ok",
        work_package_id="PROJ-42",
        project="Demo",
        payload={},
        validation_errors={},
        result=None,
        target=None,
    )


@pytest.mark.parametrize("hidden", ["id", "display_id"])
def test_the_work_package_reference_is_hidden_with_either_spelling(hidden: str) -> None:
    result = stamp_result(_work_package_result(), settings=_settings("work_package", hidden))

    assert "work_package_id" not in _to_payload(result)
    assert _to_payload(result)["project"] == "Demo"


def test_an_unrelated_hide_setting_keeps_the_identity_fields() -> None:
    result = stamp_result(_work_package_result(), settings=_settings("work_package", "description"))

    assert _to_payload(result)["work_package_id"] == "PROJ-42"
    assert not hasattr(result, "_hidden_keys")


def test_the_project_name_is_the_one_owner_of_a_project_member() -> None:
    result = stamp_result(_work_package_result(), settings=_settings("project", "name"))

    assert _to_payload(result)["project"] == "Demo"


def test_stamping_twice_changes_nothing() -> None:
    settings = _settings("work_package", "project")
    once = stamp_result(_work_package_result(), settings=settings)
    hidden = once._hidden_keys  # type: ignore[attr-defined]

    twice = stamp_result(once, settings=settings)

    assert twice._hidden_keys == hidden  # type: ignore[attr-defined]
    assert hidden == frozenset({"project"})


def test_the_write_result_of_each_batch_item_is_stamped() -> None:
    item = models.BulkWorkPackageItemResult(index=0, success=True, error=None, result=_work_package_result())
    batch = models.BulkWorkPackageWriteResult(
        action="bulk_update",
        confirmed=True,
        requires_confirmation=False,
        total=1,
        succeeded=1,
        failed=0,
        message="ok",
        items=[item],
    )

    stamp_result(batch, settings=_settings("work_package", "project"))

    assert _to_payload(batch)["items"][0]["result"].get("project") is None


def _created_with_a_parent(action: str) -> models.WorkPackageWriteResult:
    result = _work_package_result()
    result.action = action
    result.target = models.ResolvedWorkPackage(
        display_id="PROJ-1", id=42, project="Demo", subject="Parent", status="New"
    )
    return result


def test_the_target_of_a_create_is_the_parent_and_hangs_on_the_parent_fields() -> None:
    result = stamp_result(_created_with_a_parent("create"), settings=_settings("work_package", "parent_id"))

    assert "target" not in _to_payload(result)


def test_the_target_of_an_update_is_the_work_package_itself_and_stays() -> None:
    result = stamp_result(_created_with_a_parent("update"), settings=_settings("work_package", "parent_id"))

    assert _to_payload(result)["target"]["id"] == 42


def _payload_with(key: str) -> dict:
    if key.startswith("_links."):
        return {
            "_links": {key.removeprefix("_links."): {"href": "/api/v3/x/42"}, "other": {"href": "/api/v3/y/7"}},
            "keep": 1,
        }
    return {key: 42, "keep": 1}


def _copy_rows() -> list[tuple[str, str, str, str]]:
    return [
        (name, key, entity, field)
        for name, keys in PAYLOAD_COPIES.items()
        for key, owners in keys.items()
        for entity, field in owners
    ]


@pytest.mark.parametrize(("name", "key", "entity", "field"), _copy_rows())
def test_a_payload_copy_leaves_with_each_of_its_owners(name: str, key: str, entity: str, field: str) -> None:
    """Every row, whether or not a fake of the contract cases reaches it: the key goes, the rest of the payload stays."""
    result = CLASSES[name].__new__(CLASSES[name])
    result.payload = _payload_with(key)  # type: ignore[attr-defined]
    result.action = "create"  # type: ignore[attr-defined]

    stamp_result(result, settings=_settings(entity, field))

    shown = result.payload  # type: ignore[attr-defined]
    assert shown["keep"] == 1
    if key.startswith("_links."):
        assert key.removeprefix("_links.") not in shown["_links"] and "other" in shown["_links"]
    else:
        assert key not in shown


def _member_rows() -> list[tuple[str, str, str, str]]:
    return [
        (name, member, entity, field)
        for name, members in IDENTITY_FIELDS.items()
        for member, owners in members.items()
        for entity, field in owners
    ]


@pytest.mark.parametrize(("name", "member", "entity", "field"), _member_rows())
def test_a_member_leaves_with_each_of_its_owners_and_stays_with_any_other_field(
    name: str, member: str, entity: str, field: str
) -> None:
    result = CLASSES[name].__new__(CLASSES[name])
    other = CLASSES[name].__new__(CLASSES[name])
    result.action = other.action = "update"  # type: ignore[attr-defined]

    stamp_result(result, settings=_settings(entity, field))
    stamp_result(other, settings=_settings(entity, "no_such_field"))

    assert member in result._hidden_keys  # type: ignore[attr-defined]
    assert not hasattr(other, "_hidden_keys")
