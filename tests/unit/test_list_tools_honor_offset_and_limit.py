"""Every list tool honors `offset` and `limit`, whether or not the server pages.

A list tool that sends `offset` and `pageSize` and trusts the answer breaks on a collection OpenProject does not
paginate (the representers built on `UnpaginatedCollection`: `Endpoints::Index` and `ParamsToQuery.collection_response`
leave both parameters out of the representer): `limit` caps nothing, and `next_offset` advances over the same set
without end. This matrix calls every read tool that has
`offset` or `limit` against two fake servers that hold 7 distinct items for every collection: one pages like
OpenProject (`offset` is the page number, `pageSize` its size), one ignores both. The tool is called with `limit=2` and
followed through `next_offset`; it passes when no page is longer than the limit, no item repeats, every item turns up
and the last page ends with `next_offset=None`. A new list tool joins the matrix without an entry.

The ignoring server is a model only for an upstream collection that is unpaginated. A tool whose upstream pages sits in
`PAGED_UPSTREAM` with the representer that says so; an entry that passes the ignoring server anyway is stale and fails.

A tool with an optional `project` is walked twice, as an axis: without it and with `project="demo"`, because a filtered
branch can read the collection differently (the way `list_boards` once did). The table entries are keyed by tool and axis.

Limits, stated on purpose: one generic call per tool and axis (no axis for an optional argument other than `project`:
`search`, `type`, `scope`, `work_package_id`, `capability_id`), and a tool or branch whose generic call yields no item
at all cannot show paging (`BLIND`, a gap and not a pass); the fake serves one collection shape for every endpoint, and
a scanning tool asks for pages of 50 or 100 against 7 items, so for it the paging fake is the ignoring one.
"""

from __future__ import annotations

import inspect
import json
from typing import Any

import httpx
import pytest
from _client_test_helpers import _base_settings, serving_projects
from _read_tool_harness import FOREIGN, OVERRIDES, READABLE, arguments, serve
from _tools_test_helpers import FakeContext

from openproject_ce_mcp import tools, tools_runtime
from openproject_ce_mcp.client import OpenProjectClient
from openproject_ce_mcp.config import TOOL_GROUPS
from openproject_ce_mcp.presentation import ContentBundle, _to_payload

ITEMS = 7
LIMIT = 2

ALL = "all"
PROJECT = "project"

# Upstream collection that pages (OpenProject 17.9: `OffsetPaginatedCollection`, or the SQL collection
# representer): the ignoring server does not model it. Keyed by tool and axis.
PAGED_UPSTREAM = {
    ("list_actions", ALL): "ActionSqlCollectionRepresenter",
    ("list_capabilities", ALL): "CapabilitySqlCollectionRepresenter (the harness gives this call a project)",
    ("list_capabilities", PROJECT): "CapabilitySqlCollectionRepresenter",
    ("list_groups", ALL): "GroupCollectionRepresenter < OffsetPaginatedCollection",
    ("list_notifications", ALL): "NotificationCollectionRepresenter < OffsetPaginatedCollection",
    ("list_principals", ALL): "PrincipalCollectionRepresenter < UserCollectionRepresenter < OffsetPaginatedCollection",
    ("list_users", ALL): "UserCollectionRepresenter < OffsetPaginatedCollection",
    ("list_my_open_work_packages", ALL): "WorkPackageCollectionRepresenter < OffsetPaginatedCollection",
    ("list_work_packages", ALL): "WorkPackageCollectionRepresenter < OffsetPaginatedCollection",
    ("search_work_packages", ALL): "WorkPackageCollectionRepresenter < OffsetPaginatedCollection",
    ("list_work_packages", PROJECT): "WorkPackageCollectionRepresenter < OffsetPaginatedCollection",
    ("search_work_packages", PROJECT): "WorkPackageCollectionRepresenter < OffsetPaginatedCollection",
    ("list_meetings", PROJECT): "MeetingCollectionRepresenter < OffsetPaginatedCollection",
    ("list_recurring_meetings", PROJECT): "RecurringMeetingCollectionRepresenter < OffsetPaginatedCollection",
}

# A tool whose generic call is not a model of its endpoint, with the reason.
NOT_MODELLED = {
    ("list_projects", ALL): "the project directory is served by the test helper, not by this server",
    (
        "list_recurring_meeting_occurrences",
        ALL,
    ): "no `offset`: `limit` goes to the server for `upcoming` only, see the test below",
}

# A tool or branch whose generic call yields no item under this server, so paging cannot show: a gap, not a pass. Each
# reason names what the source says about the paging.
BLIND = {
    (
        "execute_query",
        ALL,
    ): "the items are the saved query's work packages, which the server pages (`offset`, `pageSize`)",
    (
        "list_grids",
        ALL,
    ): "GridCollectionRepresenter pages; the fake grids name no project scope, so each is filtered out",
    ("list_project_memberships", ALL): "MembershipCollectionRepresenter pages; the generic call reads no collection",
    (
        "list_work_package_meeting_agenda_items",
        ALL,
    ): "unpaginated upstream, sliced by `paginate_client`; the fake items belong to no readable meeting",
}


def _server(*, pages: bool, readable: bool = False):
    """`readable` puts every item into the readable project, which a project filter needs to let it through."""

    def handler(request: httpx.Request) -> httpx.Response:
        base = serve(request)
        body = json.loads(base.content)
        if body.get("_type") != "Collection":
            return base
        sample = body["_embedded"]["elements"][0]
        elements = []
        for index in range(ITEMS):
            element = json.loads(json.dumps(sample))
            element["id"] = 100 + index
            element["_links"]["self"] = {"href": f"/api/v3/x/{100 + index}"}
            if readable:
                for link in ("project", "definingProject", "context"):
                    element["_links"][link] = {"href": f"/api/v3/projects/{READABLE}", "title": "readable"}
            elements.append(element)
        if pages:
            size = int(request.url.params.get("pageSize", 20))
            page = int(request.url.params.get("offset", 1))
            chunk = elements[(page - 1) * size : page * size]
            body.update(total=ITEMS, count=len(chunk), pageSize=size, offset=page)
            body["_embedded"]["elements"] = chunk
        else:
            body.update(total=ITEMS, count=ITEMS)
            body["_embedded"]["elements"] = elements
        return httpx.Response(200, json=body, request=request)

    return handler


def _results(payload: Any) -> list[Any] | None:
    if isinstance(payload, dict):
        for key in ("results", "items"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return None


async def _call(name: str, handler, **kwargs: Any) -> dict[str, Any]:
    function = tools_runtime._TOOL_FUNCTIONS[name]
    enabled = {group.read_attr: True for group in TOOL_GROUPS}
    client = OpenProjectClient(
        _base_settings(read_projects=("*",), write_projects=(), **enabled),
        transport=httpx.MockTransport(
            serving_projects(handler, [(READABLE, "demo", "Demo"), (FOREIGN, "foreign", "Foreign")])
        ),
    )
    await client.initialize()
    try:
        result = await function(FakeContext(client), **{**arguments(function), **OVERRIDES.get(name, {}), **kwargs})
    finally:
        await client.aclose()
    body = result.body if isinstance(result, ContentBundle) else result
    return json.loads(json.dumps(_to_payload(body, select=None, elide_none=False), default=str))


def _signature(name: str) -> dict[str, inspect.Parameter]:
    return dict(inspect.signature(tools_runtime._TOOL_FUNCTIONS[name]).parameters)


def _list_tools() -> list[str]:
    names = {name for scope in tools.READ_TOOLS_BY_SCOPE.values() for name in scope}
    return sorted(
        name for name in names if name in tools_runtime._TOOL_FUNCTIONS and {"offset", "limit"} & set(_signature(name))
    )


def _axes(name: str) -> list[str]:
    parameter = _signature(name).get("project")
    optional_project = parameter is not None and parameter.default is not inspect.Parameter.empty
    return [ALL, PROJECT] if optional_project else [ALL]


def _cases() -> list[tuple[str, str]]:
    return [(name, axis) for name in _list_tools() for axis in _axes(name)]


def _arguments(axis: str) -> dict[str, Any]:
    return {"project": "demo"} if axis == PROJECT else {}


def _readable(axis: str) -> bool:
    return axis == PROJECT


async def _walk(name: str, axis: str, *, pages: bool) -> tuple[list[list[str]], list[Any]]:
    """The items of each page, followed through `next_offset`, and the `next_offset` of every page."""
    handler = _server(pages=pages, readable=_readable(axis))
    has_offset = "offset" in _signature(name)
    walked: list[list[str]] = []
    nexts: list[Any] = []
    offset: Any = 1
    while offset is not None and len(walked) < ITEMS + 3:
        payload = await _call(
            name, handler, limit=LIMIT, **_arguments(axis), **({"offset": offset} if has_offset else {})
        )
        results = _results(payload)
        assert results is not None, f"{name} returned no list of results"
        walked.append([json.dumps(item, sort_keys=True) for item in results])
        offset = payload.get("next_offset")
        nexts.append(offset)
        if not has_offset:
            break
    return walked, nexts


def _problems(name: str, pages: list[list[str]], nexts: list[Any]) -> list[str]:
    problems = []
    flat = [item for page in pages for item in page]
    if any(len(page) > LIMIT for page in pages):
        problems.append(f"a page is longer than the limit ({[len(page) for page in pages]})")
    if len(set(flat)) != len(flat):
        problems.append(f"items repeat ({len(flat)} items, {len(set(flat))} distinct)")
    if "offset" in _signature(name):
        if len(set(flat)) != ITEMS:
            problems.append(f"{len(set(flat))} of {ITEMS} items turned up")
        if nexts[-1] is not None:
            problems.append("the last page has a next_offset")
    elif not flat:
        problems.append("no item at all")
    return problems


def _modelled() -> list[tuple[str, str]]:
    return [case for case in _cases() if case not in NOT_MODELLED and case not in BLIND]


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "axis"), _modelled())
async def test_a_list_tool_pages_through_a_server_that_pages(name: str, axis: str) -> None:
    walked, nexts = await _walk(name, axis, pages=True)

    assert _problems(name, walked, nexts) == [], (name, axis)


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "axis"), [case for case in _modelled() if case not in PAGED_UPSTREAM])
async def test_a_list_tool_pages_through_a_server_that_ignores_offset_and_page_size(name: str, axis: str) -> None:
    walked, nexts = await _walk(name, axis, pages=False)

    assert _problems(name, walked, nexts) == [], (name, axis)


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "axis"), sorted(PAGED_UPSTREAM))
async def test_a_tool_on_a_paged_upstream_is_listed_only_while_it_trusts_the_server(name: str, axis: str) -> None:
    walked, nexts = await _walk(name, axis, pages=False)

    assert _problems(name, walked, nexts) != [], f"{name} ({axis}) slices by itself now: drop it from PAGED_UPSTREAM"


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "axis"), sorted(BLIND))
async def test_a_blind_tool_still_yields_no_item(name: str, axis: str) -> None:
    payload = await _call(
        name,
        _server(pages=True, readable=_readable(axis)),
        **_arguments(axis),
        **({"limit": LIMIT} if "limit" in _signature(name) else {}),
    )

    assert _results(payload) == [], f"{name} ({axis}) shows items now: drop it from BLIND"


def test_the_tables_name_listed_cases_only_and_none_twice() -> None:
    cases = set(_cases())
    tables = [set(PAGED_UPSTREAM), set(NOT_MODELLED), set(BLIND)]

    assert all(table <= cases for table in tables), sorted(set().union(*tables) - cases)
    assert sum(len(table) for table in tables) == len(set().union(*tables))


@pytest.mark.asyncio
async def test_the_occurrence_limit_goes_to_the_server_for_upcoming_only() -> None:
    requested: dict[str, dict[str, str]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/api/v3/recurring_meetings/5/occurrences/"):
            requested[request.url.path.rsplit("/", 1)[-1]] = dict(request.url.params)
        return _server(pages=True)(request)

    for filter_name in ("upcoming", "past"):
        await _call("list_recurring_meeting_occurrences", handler, filter=filter_name, limit=LIMIT)

    assert requested == {"upcoming": {"limit": str(LIMIT)}, "past": {}}


def test_the_check_tells_a_clean_walk_from_a_repeat_a_flood_and_an_endless_one() -> None:
    items = [json.dumps(index) for index in range(ITEMS)]
    clean = [items[0:2], items[2:4], items[4:6], items[6:7]]

    assert _problems("list_versions", clean, [2, 3, 4, None]) == []
    assert _problems("list_versions", [items], [2]) != []
    assert _problems("list_versions", [items[0:2], items[0:2]], [2, None]) != []
    assert _problems("list_versions", clean, [2, 3, 4, 5]) != []


def test_a_tool_with_limit_only_is_not_clean_without_any_item() -> None:
    assert _problems("list_recurring_meeting_occurrences", [[]], [None]) == ["no item at all"]
