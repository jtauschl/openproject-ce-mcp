"""A tool offers, in `select`, exactly the fields its producer fills.

`select_field(RowModel)` advertises every field of the model. A field that only a sibling tool's path fills
would come back as `null` and read like "no value" instead of "never read". Each group below runs every tool
that shares one row model through its real service with a fully populated record and compares what the tool
offers (read from the registered tool's own schema text) with what came back.

Scope: top-level fields, which is all `select` offers on this line. The row itself comes from one shared
normalizer per model, so the producer paths differ in what the service adds to it; a record built by hand
therefore tests the step that can differ.
"""

from __future__ import annotations

import dataclasses
import typing
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from _client_test_helpers import make_settings
from test_app_relation_service import _FakeRelationApi, _record, _resolve_work_package_record_ok, _summary
from test_app_relation_service import _service as _relation_service
from test_app_work_package_service import _FakeWorkPackageApi
from test_app_work_package_service import _service as _work_package_service

from openproject_ce_mcp.models import RelationSummary, WorkPackageWriteResult
from openproject_ce_mcp.tool_params import allowed_select_fields, select_field
from openproject_ce_mcp.tools_relations import get_work_package_relations, list_relations
from openproject_ce_mcp.tools_validation import BULK_ITEM_WRAPPER_FIELDS, _validate_select
from openproject_ce_mcp.tools_work_packages import bulk_create_work_packages, bulk_update_work_packages


@dataclasses.dataclass
class _Sample:
    kept: int
    dropped: int | None = None


def _offered(tool: Callable[..., Any]) -> frozenset[str]:
    """The field names the tool's `select` schema offers, read from its description text."""
    hint = typing.get_type_hints(tool, include_extras=True)["select"]
    if not hasattr(hint, "__metadata__"):
        # Python 3.10 wraps a parameter defaulting to None in Optional[...] around the Annotated type.
        hint = next(argument for argument in typing.get_args(hint) if hasattr(argument, "__metadata__"))
    metadata = hint.__metadata__
    description = next(item.description for item in metadata if getattr(item, "description", None))
    return frozenset(part.strip() for part in description.split("Allowed: ", 1)[1].rstrip(".").split(","))


def test_unfilled_fields_are_left_out_of_the_allowed_set_the_schema_text_and_the_validator() -> None:
    unfilled = frozenset({"dropped"})

    assert allowed_select_fields(_Sample) == {"kept", "dropped"}
    assert allowed_select_fields(_Sample, unfilled=unfilled) == {"kept"}
    assert "dropped" not in select_field(_Sample, unfilled=unfilled).description
    assert _validate_select(["kept"], row_type=_Sample, unfilled=unfilled) == ["kept"]
    with pytest.raises(ValueError, match=r"'dropped' is not a valid _Sample field\. Allowed: kept\."):
        _validate_select(["dropped"], row_type=_Sample, unfilled=unfilled)


def test_unfilled_does_not_remove_a_wrapper_field() -> None:
    assert allowed_select_fields(_Sample, wrapper_fields=frozenset({"index"}), unfilled=frozenset({"dropped"})) == {
        "kept",
        "index",
    }


def _populated_relation() -> RelationSummary:
    return _summary(7, description="Why", from_id=10, to_id=11, relation_type="blocks")


def _fields_set(row: Any) -> set[str]:
    return {field.name for field in dataclasses.fields(row) if getattr(row, field.name) is not None}


@pytest.mark.asyncio
async def test_relation_tools_offer_only_fields_their_producer_fills() -> None:
    populated = dataclasses.replace(_populated_relation(), description_length=3)
    settings = dataclasses.replace(make_settings(), read_projects=("*",))
    record = _record(7, from_href="/api/v3/work_packages/10", to_href="/api/v3/work_packages/11", summary=populated)

    def service():
        return _relation_service(
            api=_FakeRelationApi(records=[record]),
            settings=settings,
            resolve_work_package_record=_resolve_work_package_record_ok(10),
        )

    filled = {
        "list_relations": _fields_set((await service().list_all()).results[0]),
        "get_work_package_relations": _fields_set((await service().list_for_work_package("PROJ-10")).results[0]),
    }
    tools = {"list_relations": list_relations, "get_work_package_relations": get_work_package_relations}

    for name, tool in tools.items():
        assert _offered(tool) <= filled[name], (name, sorted(_offered(tool) - filled[name]))
    assert _offered(get_work_package_relations) == {field.name for field in dataclasses.fields(RelationSummary)}


# Fields a write result leaves empty because of what was written, not because the path skips them: a create
# preview has no work package yet and a preview carries no result.
_WRITE_RESULT_STATE_DEPENDENT = frozenset({"work_package_id", "result"})


async def _write_results(tool_name: str) -> list[WorkPackageWriteResult]:
    service, _ = _work_package_service(_FakeWorkPackageApi())
    results: list[WorkPackageWriteResult] = []
    for confirm in (False, True):
        if tool_name == "bulk_create_work_packages":
            bulk = await service.bulk_create(
                items=[{"project": "demo", "type": "Task", "subject": "One", "parent_work_package_id": 5}],
                confirm=confirm,
            )
        else:
            bulk = await service.bulk_update(
                items=[{"work_package_id": 6, "subject": "New", "parent_work_package_id": 5}], confirm=confirm
            )
        results.extend(item.result for item in bulk.items if item.result is not None)
    return results


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "tool"),
    [
        ("bulk_create_work_packages", bulk_create_work_packages),
        ("bulk_update_work_packages", bulk_update_work_packages),
    ],
)
async def test_bulk_write_tools_offer_only_fields_their_producer_fills(
    tool_name: str, tool: Callable[..., Any]
) -> None:
    results = await _write_results(tool_name)
    assert results, tool_name
    filled: set[str] = set().union(*(_fields_set(result) for result in results))
    offered = _offered(tool) - BULK_ITEM_WRAPPER_FIELDS

    assert offered - _WRITE_RESULT_STATE_DEPENDENT <= filled, (tool_name, sorted(offered - filled))


def _context_that_must_not_be_used() -> Any:
    """Validation of `select` runs before any request, so the client is never reached."""
    return SimpleNamespace(request_context=SimpleNamespace(lifespan_context=SimpleNamespace(client=None)))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "arguments", "field"),
    [
        (list_relations, {}, "queried_perspective"),
        (
            bulk_create_work_packages,
            {"items": [{"project": "demo", "type": "Task", "subject": "One"}]},
            "parent_target",
        ),
    ],
)
async def test_a_tool_rejects_a_field_its_schema_does_not_offer(
    tool: Callable[..., Any], arguments: dict[str, Any], field: str
) -> None:
    with pytest.raises(ValueError, match=f"select field '{field}' is not a valid"):
        await tool(_context_that_must_not_be_used(), select=[field], **arguments)
