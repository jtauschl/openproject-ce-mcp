"""sort_by as an MCP client passes it: through the SDK's argument handling,
the tool, the client and the HTTP request it ends in."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from _client_test_helpers import make_settings, started_client
from mcp import types
from mcp.client import Client

import openproject_ce_mcp.tools_runtime as tools_runtime
from openproject_ce_mcp import tools, tools_boards, tools_query_schema, tools_work_packages
from openproject_ce_mcp.strict_mcpserver import StrictMCPServer

CallTool = Callable[[str, dict], Awaitable[types.CallToolResult]]

_SORT_BYS = "/api/v3/queries/sort_bys"
_FORMAT_HINT = 'Use "field:direction" or "field-direction", e.g. "id:asc".'


def _board_payload() -> dict[str, Any]:
    return {
        "_type": "Query",
        "id": 12,
        "name": "Sprint Board",
        "public": False,
        "hidden": False,
        "starred": False,
        "includeSubprojects": False,
        "showHierarchies": False,
        "timelineVisible": False,
        "filters": [],
        "_links": {
            "self": {"href": "/api/v3/queries/12", "title": "Sprint Board"},
            "project": {"href": "/api/v3/projects/6", "title": "Demo"},
        },
    }


class _Recorder:
    def __init__(self) -> None:
        self.requests: list[tuple[str, bytes, dict[str, str], Any]] = []

    def form_bodies(self) -> list[Any]:
        return [body for method, path, _, body in self.requests if method == "POST" and path.endswith(b"/form")]

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, request.url.raw_path, dict(request.url.params), body))
        path = request.url.path
        if path == "/api/v3/projects/demo":
            return httpx.Response(200, json={"_type": "Project", "id": 6, "name": "Demo", "identifier": "demo"})
        if path in ("/api/v3/queries/form", "/api/v3/queries/12/form"):
            return httpx.Response(200, json={"_embedded": {"payload": body, "validationErrors": {}}})
        if path == "/api/v3/queries/12" and request.method == "GET":
            return httpx.Response(200, json=_board_payload())
        if path == "/api/v3/work_packages":
            return httpx.Response(
                200, json={"_type": "WorkPackageCollection", "total": 0, "_embedded": {"elements": []}}
            )
        if path.startswith(f"{_SORT_BYS}/"):
            return httpx.Response(200, json={"name": "Subject (Ascending)", "_links": {"self": {"href": path}}})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")


@pytest.fixture
def recorder() -> _Recorder:
    return _Recorder()


# "legacy" is the initialize handshake today's stdio clients use, "auto" the
# SDK's newer per-request path.
@pytest.fixture(params=["legacy", "auto"])
def call_tool(request, recorder: _Recorder) -> CallTool:
    @asynccontextmanager
    async def lifespan(_):
        client = await started_client(make_settings(), recorder.handler, [(6, "demo", "Demo")])
        try:
            yield SimpleNamespace(client=client)
        finally:
            await client.aclose()

    server = StrictMCPServer("test", lifespan=lifespan)
    tools_runtime.register_selected_tools(
        server,
        names=[
            tools_boards.create_board.__name__,
            tools_boards.update_board.__name__,
            tools_work_packages.list_work_packages.__name__,
            tools_work_packages.search_work_packages.__name__,
            tools_query_schema.get_query_sort_by.__name__,
        ],
        annotations=tools.TOOL_ANNOTATIONS,
    )

    async def call(name: str, arguments: dict) -> types.CallToolResult:
        async with Client(server, mode=request.param) as client:
            recorder.requests.clear()
            return await client.call_tool(name, arguments)

    return call


def _text(result: types.CallToolResult) -> str:
    return "".join(getattr(block, "text", "") for block in result.content)


async def _sort_by_links(call_tool: CallTool, recorder: _Recorder, name: str, arguments: dict) -> list[dict]:
    result = await call_tool(name, arguments)
    assert result.is_error is False, _text(result)
    (body,) = recorder.form_bodies()
    return body["_links"]["sortBy"]


async def test_create_board_applies_the_colon_form(call_tool: CallTool, recorder: _Recorder) -> None:
    links = await _sort_by_links(
        call_tool, recorder, "create_board", {"name": "B", "project": "demo", "sort_by": ["id:desc"]}
    )

    assert links == [{"href": f"{_SORT_BYS}/id-desc"}]


async def test_update_board_sorts_a_bare_field_ascending(call_tool: CallTool, recorder: _Recorder) -> None:
    links = await _sort_by_links(call_tool, recorder, "update_board", {"board_id": 12, "sort_by": ["id"]})

    assert links == [{"href": f"{_SORT_BYS}/id-asc"}]


async def test_update_board_keeps_an_upper_case_direction(call_tool: CallTool, recorder: _Recorder) -> None:
    links = await _sort_by_links(call_tool, recorder, "update_board", {"board_id": 12, "sort_by": ["dueDate-DESC"]})

    assert links == [{"href": f"{_SORT_BYS}/dueDate-desc"}]


@pytest.mark.parametrize("item", ["id-up", "id:up"])
async def test_create_board_rejects_an_invalid_direction_before_any_request(
    call_tool: CallTool, recorder: _Recorder, item: str
) -> None:
    result = await call_tool("create_board", {"name": "B", "project": "demo", "sort_by": [item]})

    assert result.is_error is True
    assert f"[VALIDATION_FAILED] sort_by[0]: direction must be 'asc' or 'desc', got 'up'. {_FORMAT_HINT}" in _text(
        result
    )
    assert recorder.requests == []


async def test_update_board_with_an_empty_sort_by_clears_the_sort(call_tool: CallTool, recorder: _Recorder) -> None:
    result = await call_tool("update_board", {"board_id": 12, "sort_by": []})

    assert result.is_error is False, _text(result)
    assert recorder.form_bodies() == [{"_links": {"sortBy": []}}]


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("list_work_packages", {"sort_by": ["status-desc"]}),
        ("search_work_packages", {"search": "x", "sort_by": ["status-desc"]}),
    ],
)
async def test_work_package_tools_accept_the_hyphen_form(
    call_tool: CallTool, recorder: _Recorder, name: str, arguments: dict
) -> None:
    result = await call_tool(name, arguments)

    assert result.is_error is False, _text(result)
    sort_params = [params["sortBy"] for method, path, params, _ in recorder.requests if "sortBy" in params]
    assert sort_params and all(json.loads(p) == [["status", "desc"]] for p in sort_params)


@pytest.mark.parametrize("sort_by_id", ["subject-asc", "subject:asc", "subject", "subject:ASC"])
async def test_get_query_sort_by_accepts_each_form_and_echoes_its_id(
    call_tool: CallTool, recorder: _Recorder, sort_by_id: str
) -> None:
    result = await call_tool("get_query_sort_by", {"sort_by_id": sort_by_id})

    assert result.is_error is False, _text(result)
    assert [path for _, path, _, _ in recorder.requests] == [f"{_SORT_BYS}/subject-asc".encode()]
    assert json.loads(_text(result))["id"] == sort_by_id


async def test_create_board_passes_a_relative_link_through(call_tool: CallTool, recorder: _Recorder) -> None:
    links = await _sort_by_links(
        call_tool, recorder, "create_board", {"name": "B", "project": "demo", "sort_by": [f"{_SORT_BYS}/id-asc"]}
    )

    assert links == [{"href": f"{_SORT_BYS}/id-asc"}]


async def test_create_board_rejects_a_link_to_another_origin(call_tool: CallTool, recorder: _Recorder) -> None:
    result = await call_tool(
        "create_board",
        {"name": "B", "project": "demo", "sort_by": ["https://other.example/api/v3/queries/sort_bys/id-asc"]},
    )

    assert result.is_error is True
    assert "[VALIDATION_FAILED] OpenProject sort by references must stay on the same origin." in _text(result)


async def test_create_board_does_not_apply_the_work_package_field_allowlist(
    call_tool: CallTool, recorder: _Recorder
) -> None:
    links = await _sort_by_links(
        call_tool, recorder, "create_board", {"name": "B", "project": "demo", "sort_by": ["manual_sorting:asc"]}
    )

    assert links == [{"href": f"{_SORT_BYS}/manual_sorting-asc"}]
