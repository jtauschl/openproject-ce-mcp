"""The definition a saved query response carries, as the adapter hands it to the policy.

The fixtures are the shape of a real `GET /api/v3/queries/{id}` response (read from the server's representer and
checked against a live 17.x response): `filters[]._links.filter.href` and `operator.href` with an escaped operator,
`_links.sortBy[].href` ending in the direction, `_links.groupBy` with `href: null` for no group, `_links.project`
with `href: null` for a global query. A response that lacks a member the policy judges, or carries one in a shape
this reader does not know, yields no definition at all (None), never a partial one.
"""

from __future__ import annotations

import copy
from typing import Any

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_query_execution_api import HttpxQueryExecutionApi
from openproject_ce_mcp.app.stored_query import StoredFilter, StoredQuery, StoredSort
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _filter(key: str, operator: str, values: list[dict[str, str]] | None = None) -> dict[str, Any]:
    return {
        "_type": f"{key.title()}QueryFilter",
        "name": key,
        "_links": {
            "schema": {"href": f"/api/v3/queries/filter_instance_schemas/{key}"},
            "filter": {"href": f"/api/v3/queries/filters/{key}", "title": key},
            "operator": {"href": f"/api/v3/queries/operators/{operator}", "title": "operator"},
            "values": values or [],
        },
    }


def _payload() -> dict[str, Any]:
    return {
        "_type": "Query",
        "id": 7,
        "filters": [
            _filter("status", "%3D", [{"href": "/api/v3/statuses/7", "title": "In progress"}]),
            _filter("dueDate", "%3C%3Ed"),
            _filter("customField5", "o"),
        ],
        "includeSubprojects": True,
        "showHierarchies": False,
        "_links": {
            "sortBy": [
                {"href": "/api/v3/queries/sort_bys/manualSorting-asc", "title": "Manual sorting"},
                {"href": "/api/v3/queries/sort_bys/dueDate-desc", "title": "Due date (descending)"},
            ],
            "groupBy": {"href": "/api/v3/queries/group_bys/version", "title": "Version"},
            "project": {"href": "/api/v3/projects/3", "title": "Demo"},
            "columns": [{"href": "/api/v3/queries/columns/id", "title": "ID"}],
        },
        "_embedded": {"results": {"total": 1, "_embedded": {"elements": [{"id": 5}]}}},
    }


async def _definition(payload: dict[str, Any]) -> StoredQuery | None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    async with httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    ) as client:
        page = await HttpxQueryExecutionApi(HttpxTransport(client, redact_server_text=False)).execute(
            7, offset=1, page_size=10
        )
    assert page.raw_elements == [{"id": 5}]
    return page.definition


@pytest.mark.asyncio
async def test_the_definition_is_read_from_a_real_shaped_response() -> None:
    assert await _definition(_payload()) == StoredQuery(
        filters=(StoredFilter("status", "="), StoredFilter("dueDate", "<>d"), StoredFilter("customField5", "o")),
        sort_by=(StoredSort("manualSorting", "asc"), StoredSort("dueDate", "desc")),
        group_by="version",
        include_subprojects=True,
        project_scoped=True,
    )


@pytest.mark.asyncio
async def test_no_group_and_a_global_query_read_as_none_and_not_project_scoped() -> None:
    payload = _payload()
    payload["_links"]["groupBy"] = {"href": None, "title": None}
    payload["_links"]["project"] = {"href": None, "title": None}
    payload["filters"] = []
    payload["_links"]["sortBy"] = []

    definition = await _definition(payload)

    assert definition == StoredQuery(
        filters=(), sort_by=(), group_by=None, include_subprojects=True, project_scoped=False
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("workspace", ["projects", "programs", "portfolios"])
async def test_a_project_link_of_any_workspace_type_reads_as_project_scoped(workspace: str) -> None:
    payload = _with(("_links", "project"), {"href": f"/api/v3/{workspace}/3", "title": "Demo"})

    definition = await _definition(payload)

    assert definition is not None and definition.project_scoped is True


@pytest.mark.asyncio
async def test_the_flag_that_selects_nothing_is_not_needed_for_a_definition() -> None:
    definition = await _definition(_without(("showHierarchies",)))

    assert definition == await _definition(_payload())


def _without(path: tuple[str, ...]) -> dict[str, Any]:
    payload = _payload()
    node = payload
    for key in path[:-1]:
        node = node[key]
    del node[path[-1]]
    return payload


def _with(path: tuple[str, ...], value: Any) -> dict[str, Any]:
    payload = _payload()
    node = payload
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = copy.deepcopy(value)
    return payload


UNREADABLE = {
    "no filters member": _without(("filters",)),
    "filters is not a list": _with(("filters",), {}),
    "no includeSubprojects": _without(("includeSubprojects",)),
    "includeSubprojects is not a bool": _with(("includeSubprojects",), "true"),
    "no links": _without(("_links",)),
    "no sortBy": _without(("_links", "sortBy")),
    "sortBy is not a list": _with(("_links", "sortBy"), {}),
    "no groupBy": _without(("_links", "groupBy")),
    "groupBy without href": _with(("_links", "groupBy"), {"title": "x"}),
    "no project link": _without(("_links", "project")),
    "project link without href": _with(("_links", "project"), {"title": "x"}),
    "a sort without direction": _with(("_links", "sortBy"), [{"href": "/api/v3/queries/sort_bys/dueDate"}]),
    "a sort with an unknown direction": _with(("_links", "sortBy"), [{"href": "/api/v3/queries/sort_bys/dueDate-up"}]),
    "a sort without a column": _with(("_links", "sortBy"), [{"href": "/api/v3/queries/sort_bys/-asc"}]),
    "a sort that is no link": _with(("_links", "sortBy"), ["dueDate-asc"]),
    "a filter that is no object": _with(("filters",), ["status"]),
    "a filter without links": _with(("filters",), [{"name": "status"}]),
    "a filter without a key": _with(("filters",), [{"_links": {"operator": {"href": "/x/%3D"}}}]),
    "a filter without an operator": _with(("filters",), [{"_links": {"filter": {"href": "/x/status"}}}]),
    "an operator href ending in a slash": _with(
        ("filters",), [{"_links": {"filter": {"href": "/x/status"}, "operator": {"href": "/api/v3/operators/"}}}]
    ),
    "a filter href ending in a slash": _with(
        ("filters",), [{"_links": {"filter": {"href": "/api/v3/filters/"}, "operator": {"href": "/x/%3D"}}}]
    ),
    "a numeric project href": _with(("_links", "project"), {"href": "3", "title": "Demo"}),
    "a project href without an id": _with(("_links", "project"), {"href": "/api/v3/projects/", "title": "Demo"}),
    "a project href of another resource": _with(("_links", "project"), {"href": "/api/v3/users/3", "title": "Demo"}),
    "a project href that is no string": _with(("_links", "project"), {"href": 3, "title": "Demo"}),
    "a filter with an empty href": _with(
        ("filters",), [{"_links": {"filter": {"href": ""}, "operator": {"href": "/x/%3D"}}}]
    ),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", UNREADABLE.values(), ids=UNREADABLE.keys())
async def test_a_response_the_reader_does_not_know_yields_no_definition(payload: dict[str, Any]) -> None:
    assert await _definition(payload) is None
