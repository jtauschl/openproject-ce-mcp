"""A tool offers, in `select`, exactly the fields its producer fills.

`select_field(RowModel)` advertises every field of the model. A field that only a sibling tool's path fills
would come back as `null` and read like "no value" instead of "never read". Each group below runs every tool
that shares one row model through its real service with a fully populated record and compares what the tool
offers (read from the registered tool's own schema text) with what came back.

The row itself comes from one shared normalizer per model, so the producer paths differ in what the service
adds to it. The groups that share one payload across tools (the project and work package detail groups) use
the sibling rule: a field that a sibling tool fills from the same payload, and this tool offers but leaves
empty, is the defect; a field that no tool fills from that payload is a property of the payload.
"""

from __future__ import annotations

import dataclasses
import typing
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from _client_test_helpers import _base_settings, make_settings
from test_app_relation_service import _FakeRelationApi, _record, _resolve_work_package_record_ok, _summary
from test_app_relation_service import _service as _relation_service
from test_app_work_package_service import _api_with_statuses, _FakeWorkPackageApi
from test_app_work_package_service import _service as _work_package_service

from openproject_ce_mcp.client import OpenProjectClient
from openproject_ce_mcp.models import RelationSummary, WorkPackageDetail, WorkPackageWriteResult
from openproject_ce_mcp.tool_params import allowed_select_fields, select_field
from openproject_ce_mcp.tools_projects import list_projects
from openproject_ce_mcp.tools_relations import list_relations, list_work_package_relations
from openproject_ce_mcp.tools_validation import BULK_ITEM_WRAPPER_FIELDS, _validate_select
from openproject_ce_mcp.tools_versions import list_version_projects
from openproject_ce_mcp.tools_work_package_pickers import list_work_package_available_projects
from openproject_ce_mcp.tools_work_packages import (
    bulk_create_work_packages,
    bulk_update_work_packages,
    get_work_packages,
)


@dataclasses.dataclass
class _Sample:
    kept: int
    dropped: int | None = None


def _offered_text(tool: Callable[..., Any]) -> str:
    """The `Allowed: ...` part of the tool's `select` schema description."""
    hint = typing.get_type_hints(tool, include_extras=True)["select"]
    if not hasattr(hint, "__metadata__"):
        # Python 3.10 wraps a parameter defaulting to None in Optional[...] around the Annotated type.
        hint = next(argument for argument in typing.get_args(hint) if hasattr(argument, "__metadata__"))
    description = next(item.description for item in hint.__metadata__ if getattr(item, "description", None))
    return description.split("Allowed: ", 1)[1].rstrip(".")


def _offered(tool: Callable[..., Any]) -> frozenset[str]:
    """The top-level field names the tool's `select` schema offers."""
    return frozenset(part.strip() for part in _offered_text(tool).split(";")[0].split(","))


def _offered_nested(tool: Callable[..., Any], prefix: str) -> frozenset[str]:
    """The nested field names offered as `<prefix>.<field>`, without the prefix."""
    for part in _offered_text(tool).split(";")[1:]:
        head, _, names = part.strip().partition(" for ")
        if head == f"{prefix}.<field>":
            return frozenset(name.strip() for name in names.split(","))
    return frozenset()


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
        "list_work_package_relations": _fields_set((await service().list_for_work_package("PROJ-10")).results[0]),
    }
    tools = {"list_relations": list_relations, "list_work_package_relations": list_work_package_relations}

    for name, tool in tools.items():
        assert _offered(tool) <= filled[name], (name, sorted(_offered(tool) - filled[name]))
    assert _offered(list_work_package_relations) == {field.name for field in dataclasses.fields(RelationSummary)}


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
        (
            bulk_create_work_packages,
            {"items": [{"project": "demo", "type": "Task", "subject": "One"}]},
            "result.allowed_statuses",
        ),
        (bulk_update_work_packages, {"items": [{"work_package_id": 6, "subject": "One"}]}, "result.allowed_statuses"),
        (get_work_packages, {"work_package_ids": [6]}, "allowed_statuses"),
        (list_version_projects, {"version_id": 5}, "custom_fields"),
        (list_work_package_available_projects, {"work_package_id": 42}, "custom_comments"),
    ],
)
async def test_a_tool_rejects_a_field_its_schema_does_not_offer(
    tool: Callable[..., Any], arguments: dict[str, Any], field: str
) -> None:
    with pytest.raises(ValueError, match=f"select field '{field}' is not a valid"):
        await tool(_context_that_must_not_be_used(), select=[field], **arguments)


def _sibling_only(offered: dict[str, frozenset[str]], filled: dict[str, set[str]]) -> dict[str, list[str]]:
    """Per tool, the offered fields it leaves empty although a sibling tool fills them from the same payload."""
    gaps: dict[str, list[str]] = {}
    for name, names in offered.items():
        siblings = set().union(*(fields for other, fields in filled.items() if other != name))
        gap = sorted((names - filled[name]) & siblings)
        if gap:
            gaps[name] = gap
    return gaps


_PROJECT_ROW = {
    "_type": "Project",
    "id": 1,
    "identifier": "demo",
    "name": "Demo",
    "active": True,
    "public": False,
    "description": {"raw": "About"},
    "createdAt": "2026-01-01T00:00:00Z",
    "updatedAt": "2026-01-02T00:00:00Z",
    "customField1": "Alpha",
    "customComment1": "Why",
    "_links": {"self": {"href": "/api/v3/projects/1"}, "update": {"href": "/api/v3/projects/1"}},
}
_PROJECT_PAGE = {"total": 1, "_embedded": {"elements": [_PROJECT_ROW]}}


def _project_routes(request: httpx.Request) -> httpx.Response:
    routes: dict[str, dict[str, Any]] = {
        "/api/v3/projects": _PROJECT_PAGE,
        "/api/v3/projects/1": _PROJECT_ROW,
        "/api/v3/versions/5": {
            "id": 5,
            "name": "1.0",
            "_links": {"definingProject": {"href": "/api/v3/projects/1", "title": "Demo"}},
        },
        "/api/v3/versions/5/projects": _PROJECT_PAGE,
        "/api/v3/work_packages/42": {"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
        "/api/v3/work_packages/42/available_projects": _PROJECT_PAGE,
    }
    body = routes.get(request.url.path)
    if body is None:
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")
    return httpx.Response(200, json=body, request=request)


@pytest.mark.asyncio
async def test_project_tools_offer_only_fields_their_producer_fills() -> None:
    client = OpenProjectClient(_base_settings(read_projects=("*",)), transport=httpx.MockTransport(_project_routes))
    await client.initialize()
    rows = {
        "list_projects": (await client.project.list()).results[0],
        "list_version_projects": (await client.version.list_projects(5)).results[0],
        "list_work_package_available_projects": (await client.work_package_picker.available_projects(42)).results[0],
    }
    await client.aclose()
    tools = {
        "list_projects": list_projects,
        "list_version_projects": list_version_projects,
        "list_work_package_available_projects": list_work_package_available_projects,
    }

    assert rows["list_projects"].custom_fields and rows["list_projects"].custom_comments
    assert (
        _sibling_only(
            {name: _offered(tool) for name, tool in tools.items()}, {n: _fields_set(r) for n, r in rows.items()}
        )
        == {}
    )


async def _detail_fields() -> tuple[dict[str, frozenset[str]], dict[str, set[str]]]:
    """Offered and filled detail field names of the tools that return a `WorkPackageDetail`."""
    service, _ = _work_package_service(_api_with_statuses("New", "Closed"))
    batch = await service.get_batch(ids=[6])
    bulk_update = await service.bulk_update(items=[{"work_package_id": 6, "subject": "New"}], confirm=True)
    bulk_create = await service.bulk_create(items=[{"project": "demo", "type": "Task", "subject": "One"}], confirm=True)
    filled = {
        "get_work_package": _fields_set(await service.get(6, include_allowed_statuses=True)),
        "get_work_packages": _fields_set(batch.results[0].work_package),
        "bulk_update_work_packages": _fields_set(bulk_update.items[0].result.result),
        "bulk_create_work_packages": _fields_set(bulk_create.items[0].result.result),
    }
    offered = {
        "get_work_package": frozenset(field.name for field in dataclasses.fields(WorkPackageDetail)),
        "get_work_packages": _offered(get_work_packages) - {"id", "success", "error"} - {"work_package"},
        "bulk_update_work_packages": _offered_nested(bulk_update_work_packages, "result"),
        "bulk_create_work_packages": _offered_nested(bulk_create_work_packages, "result"),
    }
    return offered, filled


@pytest.mark.asyncio
async def test_work_package_detail_tools_offer_only_fields_their_producer_fills() -> None:
    offered, filled = await _detail_fields()

    assert "allowed_statuses" in filled["get_work_package"]
    assert _sibling_only(offered, filled) == {}
