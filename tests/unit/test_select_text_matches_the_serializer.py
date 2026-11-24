"""What the texts say about `select` on batch and bulk items is what the serializer does.

Three tools return items that wrap one entity (`presentation._SELECT_NESTED_FIELD`): `get_work_packages`,
`bulk_create_work_packages` and `bulk_update_work_packages`. A caller reads three texts about them: the description of
the `select` parameter, the server instructions and the docstring of `bulk_create_work_packages`. This file ties each
claim of those texts to the behaviour of the registered tool:

- the tools are found by cause (the row type of the return model), not by reading a description, and the set found
  equals the keys of `_SELECT_NESTED_FIELD` in both directions;
- items come from the real service over a fake API (a succeeded item, a rejected one, one that raised, a read that
  failed) and go through the registered wrapper a caller reaches, with preconditions asserted on the raw objects so
  a fixture that no longer produces the case fails instead of passing;
- the expected sets and sentences are written out here, per tool, and not derived by the code that builds the text.

Stated boundary: one preview call per tool (`confirm=False`); the hide cases name one entity setting at a time; the
text checks are presence checks of the sentences and an absence check of the retired wording.
"""

from __future__ import annotations

import dataclasses
import typing
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest
from _client_test_helpers import make_settings
from test_app_work_package_service import _FakeWorkPackageApi, _service

from openproject_ce_mcp import models as m
from openproject_ce_mcp import presentation
from openproject_ce_mcp.config import TOOL_GROUPS
from openproject_ce_mcp.server import CE_INSTRUCTIONS, create_app
from openproject_ce_mcp.tools_runtime import _TOOL_FUNCTIONS, _return_model

BATCH = "get_work_packages"
BULK_CREATE = "bulk_create_work_packages"
BULK_UPDATE = "bulk_update_work_packages"
TOOLS = (BATCH, BULK_CREATE, BULK_UPDATE)

WRAPPED = {
    BATCH: (m.BatchWorkPackageReadItemResult, "work_package"),
    BULK_CREATE: (m.BulkWorkPackageItemResult, "result"),
    BULK_UPDATE: (m.BulkWorkPackageItemResult, "result"),
}
ALWAYS = {BATCH: {"id", "index", "success"}, BULK_CREATE: {"index", "success"}, BULK_UPDATE: {"index", "success"}}
NO_OP_NAMES = ["index", "success", "error"]

SENTENCE_MARKER = "come back whatever is selected"

EXPECTED_DESCRIPTION_PREFIX = {
    BATCH: (
        "Fields of each item's `work_package` to return; a requested unset field comes back as null. "
        "The item fields id, index, success come back whatever is selected; naming index, success, error changes "
        "nothing; with select, an item that has no work_package shows `work_package: null`, read `error`; "
        "`error` is there only when the item failed. Allowed: "
    ),
    BULK_CREATE: (
        "Fields of each item's `result` to return; a requested unset field comes back as null. "
        "The item fields index, success come back whatever is selected; naming index, success, error changes "
        "nothing; with select, an item that has no result shows `result: null`, read `error`; "
        "`error` is there only when the item failed. Allowed: "
    ),
    BULK_UPDATE: (
        "Fields of each item's `result` to return; a requested unset field comes back as null. "
        "The item fields index, success come back whatever is selected; naming index, success, error changes "
        "nothing; with select, an item that has no result shows `result: null`, read `error`; "
        "`error` is there only when the item failed. Allowed: "
    ),
}

NEW_INSTRUCTIONS_SENTENCE = (
    "With `select`, a batch or bulk item omits a null `error` and shows a missing `work_package`/`result` as "
    "`null`; a rejected write keeps its `result`."
)
RETIRED_INSTRUCTIONS_SENTENCE = "a failed batch-read or\nbulk-write item keeps its nested"
BULK_CREATE_DOCSTRING_CLAUSE = (
    "index and success are always included; error only on a failed item; a rejected item keeps its result "
    "with its validation_errors; with select, an item whose write raised shows result: null (without select it "
    "has no result)"
)


@dataclass
class _AppContext:
    client: Any


class _Client:
    def __init__(self, service: Any) -> None:
        self.work_package = service


class _Context:
    def __init__(self, service: Any) -> None:
        self.request_context = SimpleNamespace(lifespan_context=_AppContext(client=_Client(service)))


def _settings(**overrides: Any):
    flags = {group.read_attr: True for group in TOOL_GROUPS}
    flags.update({group.write.attr: True for group in TOOL_GROUPS if group.write is not None})
    return dataclasses.replace(make_settings(), **flags, **overrides)


def _registered(settings: Any) -> dict[str, Any]:
    return {tool.name: tool for tool in create_app(settings)._tool_manager.list_tools()}


def _fresh_service(settings: Any):
    api = _FakeWorkPackageApi()
    api.validation_errors_queue.extend([{}, {"subject": "can't be blank"}])
    service, _ = _service(api, settings=settings)
    return service


BULK_CREATE_ITEMS = [
    {"project": "demo", "type": "Task", "subject": "Good"},
    {"project": "demo", "type": "Task", "subject": "Rejected"},
    {"project": "demo", "type": "Task", "subject": "Raises", "custom_fields": {"customField99": 1}},
]
BULK_UPDATE_ITEMS = [
    {"work_package_id": 6, "subject": "Good"},
    {"work_package_id": 6, "subject": "Rejected"},
    {"work_package_id": 999, "subject": "Raises"},
]
BATCH_IDS = [6, 999]


async def _raw(tool: str, settings: Any) -> list[Any]:
    service = _fresh_service(settings)
    if tool == BATCH:
        return (await service.get_batch(ids=BATCH_IDS)).results
    if tool == BULK_CREATE:
        return (await service.bulk_create(items=BULK_CREATE_ITEMS, confirm=False)).items
    return (await service.bulk_update(items=BULK_UPDATE_ITEMS, confirm=False)).items


async def _call(tool: str, settings: Any, select: list[str] | None) -> list[dict[str, Any]]:
    fn = _registered(settings)[tool].fn
    context = _Context(_fresh_service(settings))
    if tool == BATCH:
        payload = await fn(context, ids=BATCH_IDS, select=select)
        return payload["results"]
    items = BULK_CREATE_ITEMS if tool == BULK_CREATE else BULK_UPDATE_ITEMS
    payload = await fn(context, items=items, select=select, confirm=False)
    return payload["items"]


def _entity_of(tool: str, row: Any) -> Any:
    return getattr(row, WRAPPED[tool][1])


# What the fixtures must produce, asserted on the raw objects before any behaviour is judged.
SET_FIELD = {BATCH: "subject", BULK_CREATE: "ready", BULK_UPDATE: "ready"}
UNSET_FIELD = {BATCH: "assignee", BULK_CREATE: "work_package_id", BULK_UPDATE: "parent_target"}


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", TOOLS)
async def test_the_fixtures_produce_the_cases_the_texts_talk_about(tool: str) -> None:
    rows = await _raw(tool, _settings())
    succeeded, other = rows[0], rows[1:]

    assert succeeded.success is True and succeeded.error is None
    assert getattr(_entity_of(tool, succeeded), SET_FIELD[tool]) is not None
    assert getattr(_entity_of(tool, succeeded), UNSET_FIELD[tool]) is None
    assert all(row.success is False and row.error for row in other)
    if tool == BATCH:
        assert _entity_of(tool, other[0]) is None
        return
    rejected, raised = other
    assert rejected.result is not None and rejected.result.ready is False and rejected.result.validation_errors
    assert raised.result is None


def _row_types_found() -> tuple[set[type], set[str]]:
    found_types: set[type] = set()
    found_tools: set[str] = set()
    for name, function in _TOOL_FUNCTIONS.items():
        model = _return_model(function)
        if model is None:
            continue
        hints = typing.get_type_hints(model)
        for field_name in ("results", "items"):
            if field_name in hints:
                (element,) = typing.get_args(hints[field_name])
                if element in presentation._SELECT_NESTED_FIELD:
                    found_types.add(element)
                    found_tools.add(name)
    return found_types, found_tools


def test_the_wrapped_tools_are_found_by_their_row_type_and_match_the_serializer_table() -> None:
    _registered(_settings())
    found_types, found_tools = _row_types_found()

    assert found_tools == set(TOOLS)
    assert found_types == set(presentation._SELECT_NESTED_FIELD)
    for tool in TOOLS:
        row_type, key = WRAPPED[tool]
        assert presentation._SELECT_NESTED_FIELD[row_type] == key
        hints = typing.get_type_hints(row_type)
        optional = [
            name for name in presentation.wrapper_field_names(row_type) if type(None) in typing.get_args(hints[name])
        ]
        # The sentences name `error` as the one item field that can be missing.
        assert optional == ["error"], (tool, optional)


def test_exactly_the_wrapped_tools_carry_the_wrapper_sentence_in_their_select_description() -> None:
    tools = _registered(_settings())
    carrying = {
        name
        for name, tool in tools.items()
        if SENTENCE_MARKER in tool.parameters.get("properties", {}).get("select", {}).get("description", "")
    }

    assert carrying == set(TOOLS)


@pytest.mark.parametrize("tool", TOOLS)
def test_the_select_description_names_what_comes_back_and_what_changes_nothing(tool: str) -> None:
    description = _registered(_settings())[tool].parameters["properties"]["select"]["description"]

    assert description.startswith(EXPECTED_DESCRIPTION_PREFIX[tool]), description


def test_the_instructions_and_the_bulk_create_docstring_carry_the_corrected_wording() -> None:
    tools = _registered(_settings())

    assert NEW_INSTRUCTIONS_SENTENCE in " ".join(CE_INSTRUCTIONS.split())
    assert RETIRED_INSTRUCTIONS_SENTENCE not in CE_INSTRUCTIONS
    assert BULK_CREATE_DOCSTRING_CLAUSE in " ".join(tools[BULK_CREATE].description.split())
    assert "always included regardless of select" not in tools[BULK_CREATE].description


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", TOOLS)
async def test_an_item_keeps_its_always_fields_and_leaves_out_a_null_error(tool: str) -> None:
    for select in ([SET_FIELD[tool]], None):
        rows = await _call(tool, _settings(), select)
        succeeded = rows[0]

        assert ALWAYS[tool] <= set(succeeded), select
        assert "error" not in succeeded, select
        for row in rows[1:]:
            assert row["success"] is False and row["error"], select
            assert ALWAYS[tool] <= set(row), select


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", TOOLS)
async def test_a_selected_unset_entity_field_comes_back_as_null(tool: str) -> None:
    rows = await _call(tool, _settings(), [UNSET_FIELD[tool]])
    entity_key = WRAPPED[tool][1]

    assert rows[0][entity_key] == {UNSET_FIELD[tool]: None}


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", TOOLS)
async def test_an_item_without_an_entity_shows_a_null_entity_key_only_with_select(tool: str) -> None:
    entity_key = WRAPPED[tool][1]
    selected = await _call(tool, _settings(), [SET_FIELD[tool]])
    unselected = await _call(tool, _settings(), None)
    without_entity = selected[-1]

    assert entity_key in without_entity and without_entity[entity_key] is None
    assert entity_key not in unselected[-1]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", (BULK_CREATE, BULK_UPDATE))
async def test_a_rejected_bulk_write_keeps_its_result_with_the_validation_errors(tool: str) -> None:
    rows = await _call(tool, _settings(), ["ready", "validation_errors"])
    rejected = rows[1]

    assert rejected["success"] is False and rejected["error"]
    assert rejected["result"]["ready"] is False
    assert rejected["result"]["validation_errors"] == {"subject": "can't be blank"}


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", TOOLS)
async def test_naming_a_wrapper_field_that_is_no_entity_field_changes_nothing(tool: str) -> None:
    base = await _call(tool, _settings(), [SET_FIELD[tool]])
    with_names = await _call(tool, _settings(), [SET_FIELD[tool], *NO_OP_NAMES])

    assert with_names == base


@pytest.mark.asyncio
async def test_naming_id_on_the_batch_read_selects_the_id_of_the_work_package() -> None:
    rows = await _call(BATCH, _settings(), ["subject", "id"])

    assert set(rows[0]["work_package"]) == {"subject", "id"}
    assert str(rows[0]["id"]) == "6"


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", TOOLS)
async def test_a_select_of_wrapper_names_only_returns_the_whole_entity(tool: str) -> None:
    only_names = await _call(tool, _settings(), ["index", "success"])
    everything = await _call(tool, _settings(), None)
    entity_key = WRAPPED[tool][1]

    assert only_names[0][entity_key] == everything[0][entity_key]
    assert len(everything[0][entity_key]) > 2
    assert ALWAYS[tool] <= set(only_names[0])


# tool -> (the hide setting, the hidden entity field, a field that stays); the id of the write result is a copy of
# the work package `id`, so the work package setting hides it there.
HIDDEN_ENTITY_FIELD = {
    BATCH: ({"work_package": ("subject",)}, "subject", "assignee"),
    BULK_CREATE: ({"work_package": ("id",)}, "work_package_id", "ready"),
    BULK_UPDATE: ({"work_package": ("id",)}, "work_package_id", "ready"),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", TOOLS)
async def test_a_hidden_entity_field_is_absent_even_when_selected(tool: str) -> None:
    hidden_fields, hidden, kept = HIDDEN_ENTITY_FIELD[tool]

    visible = await _call(tool, _settings(), [hidden, kept])
    rows = await _call(tool, _settings(hidden_fields=hidden_fields), [hidden, kept])

    assert set(visible[0][WRAPPED[tool][1]]) == {hidden, kept}
    assert set(rows[0][WRAPPED[tool][1]]) == {kept}


@pytest.mark.asyncio
@pytest.mark.parametrize("hidden", ["id", "display_id"])
async def test_a_hidden_work_package_id_removes_the_wrapper_id_of_the_batch_read_and_index_stays(hidden: str) -> None:
    settings = _settings(hidden_fields={"work_package": (hidden,)})

    rows = await _call(BATCH, settings, ["subject"])

    assert "id" not in rows[0]
    assert rows[0]["index"] == 0 and rows[0]["success"] is True
