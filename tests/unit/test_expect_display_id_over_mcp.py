"""`expect_display_id` as an MCP client passes it: through the SDK's argument handling, the tool, the client
and the write guard, with the refusal text the agent reads."""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from _client_test_helpers import make_settings, started_client
from _work_package_target_helpers import R1, form_response, project_response
from mcp import types
from mcp.client import Client

import openproject_ce_mcp.tools_runtime as tools_runtime
from openproject_ce_mcp import tools, tools_attachments, tools_watchers, tools_work_packages
from openproject_ce_mcp.strict_mcpserver import StrictMCPServer

CallTool = Callable[[str, dict], Awaitable[types.CallToolResult]]

_WP_PATH = re.compile(r"^/api/v3/work_packages/([^/]+)(/form)?$")


class _Recorder:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        wp = _WP_PATH.match(request.url.path)
        if wp is not None and wp.group(1) == "436":
            if wp.group(2) == "/form":
                return form_response(request)
            if request.method == "GET":
                return httpx.Response(200, json=R1, request=request)
        if request.url.path in {"/api/v3/projects/demo", "/api/v3/projects/1"}:
            return project_response(request, 1, "demo", "Project A")
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    def writes(self) -> list[tuple[str, str]]:
        return [(method, path) for method, path in self.requests if method != "GET" and not path.endswith("/form")]


@pytest.fixture
def recorder() -> _Recorder:
    return _Recorder()


@pytest.fixture
def server(recorder: _Recorder) -> StrictMCPServer:
    settings = dataclasses.replace(make_settings(), enable_work_package_write=True)

    @asynccontextmanager
    async def lifespan(_):
        client = await started_client(settings, recorder.handler, [(1, "demo", "Demo")])
        try:
            yield SimpleNamespace(client=client)
        finally:
            await client.aclose()

    server = StrictMCPServer("test", lifespan=lifespan)
    tools_runtime.register_selected_tools(
        server,
        names=[
            tools_work_packages.update_work_package.__name__,
            tools_work_packages.bulk_update_work_packages.__name__,
            tools_watchers.set_work_package_watcher.__name__,
            tools_attachments.create_work_package_attachment.__name__,
        ],
        hide_active=False,
        annotations=tools.TOOL_ANNOTATIONS,
    )
    return server


@pytest.fixture
def call_tool(server: StrictMCPServer, recorder: _Recorder) -> CallTool:
    async def call(name: str, arguments: dict) -> types.CallToolResult:
        async with Client(server, mode="legacy") as client:
            recorder.requests.clear()
            return await client.call_tool(name, arguments)

    return call


def _text(result: types.CallToolResult) -> str:
    return "".join(getattr(block, "text", "") for block in result.content)


@pytest.mark.parametrize("confirm", [False, True])
async def test_a_bare_number_is_refused_with_the_ticket_it_resolved_to(
    call_tool: CallTool, recorder: _Recorder, confirm: bool
) -> None:
    result = await call_tool("update_work_package", {"work_package_id": 436, "subject": "s", "confirm": confirm})

    assert result.is_error is True
    assert "[VALIDATION_FAILED] 436 is A-1 (Project A). If you mean A-1, repeat with expect_display_id 'A-1'" in _text(
        result
    )
    assert recorder.writes() == []


async def test_the_named_ticket_passes_the_guard(call_tool: CallTool, recorder: _Recorder) -> None:
    result = await call_tool(
        "update_work_package", {"work_package_id": 436, "subject": "s", "expect_display_id": "A-1", "confirm": False}
    )

    assert result.is_error is False, _text(result)
    assert recorder.writes() == []


@pytest.mark.parametrize("value", [51, True, ["A-1"]])
async def test_an_expectation_of_the_wrong_json_type_is_rejected_before_any_request(
    call_tool: CallTool, recorder: _Recorder, value: Any
) -> None:
    result = await call_tool("update_work_package", {"work_package_id": 436, "expect_display_id": value})

    assert result.is_error is True
    assert "expect_display_id" in _text(result)
    assert recorder.requests == []


async def test_a_bulk_item_reports_its_refusal_and_the_named_sibling_goes_on(
    call_tool: CallTool, recorder: _Recorder
) -> None:
    result = await call_tool(
        "bulk_update_work_packages",
        {
            "items": [
                {"work_package_id": 436, "subject": "alone"},
                {"work_package_id": 436, "subject": "named", "expect_display_id": "A-1"},
            ],
            "confirm": False,
        },
    )

    assert result.is_error is False, _text(result)
    payload = json.loads(_text(result))
    assert (payload["succeeded"], payload["failed"]) == (1, 1)
    refused, accepted = payload["items"]
    assert refused["success"] is False and "repeat with expect_display_id 'A-1'" in refused["error"]
    assert accepted["success"] is True
    assert recorder.writes() == []


async def test_a_bulk_item_rejects_an_unknown_key_beside_expect_display_id(
    call_tool: CallTool, recorder: _Recorder
) -> None:
    result = await call_tool(
        "bulk_update_work_packages",
        {"items": [{"work_package_id": 436, "expect_display_ids": "A-1"}], "confirm": False},
    )

    assert result.is_error is True
    assert "expect_display_ids" in _text(result)
    assert recorder.requests == []


GUARDED_BY_EXPECT_DISPLAY_ID = ("set_work_package_watcher", "create_work_package_attachment")


@pytest.mark.parametrize("name", GUARDED_BY_EXPECT_DISPLAY_ID)
async def test_the_schema_offers_an_optional_expectation_of_a_string_or_null(
    server: StrictMCPServer, name: str
) -> None:
    async with Client(server, mode="legacy") as client:
        listed = {tool.name: tool for tool in (await client.list_tools()).tools}

    schema = listed[name].input_schema
    parameter = schema["properties"]["expect_display_id"]
    assert {branch["type"] for branch in parameter["anyOf"]} == {"string", "null"}
    assert parameter["description"]
    assert "expect_display_id" not in schema.get("required", [])


async def test_a_watcher_write_by_a_bare_number_is_refused_over_mcp(call_tool: CallTool, recorder: _Recorder) -> None:
    result = await call_tool(
        "set_work_package_watcher", {"work_package_id": 436, "user_id": 3, "watching": False, "confirm": True}
    )

    assert result.is_error is True
    assert "[VALIDATION_FAILED] 436 is A-1 (Project A). If you mean A-1, repeat with expect_display_id 'A-1'" in _text(
        result
    )
    assert recorder.writes() == []


@pytest.mark.parametrize("name", GUARDED_BY_EXPECT_DISPLAY_ID)
async def test_a_group_one_expectation_of_the_wrong_json_type_is_rejected_before_any_request(
    call_tool: CallTool, recorder: _Recorder, name: str
) -> None:
    arguments = {"work_package_id": 436, "expect_display_id": 51}
    result = await call_tool(
        name, {**arguments, "user_id": 3, "watching": False} if "watcher" in name else {**arguments, "file_path": "x"}
    )

    assert result.is_error is True
    assert "expect_display_id" in _text(result)
    assert recorder.requests == []
