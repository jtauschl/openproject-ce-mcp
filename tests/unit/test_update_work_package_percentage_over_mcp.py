"""percentage_done as an MCP client passes it: through the SDK's argument
handling, the tool, the client and the form request it ends in."""

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
from _client_test_helpers import _make_wp_form_response, make_settings, started_client
from mcp import types
from mcp.client import Client

import openproject_ce_mcp.tools_runtime as tools_runtime
from openproject_ce_mcp import tools, tools_work_packages
from openproject_ce_mcp.strict_mcpserver import StrictMCPServer

CallTool = Callable[[str, dict], Awaitable[types.CallToolResult]]


class _Recorder:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, bytes]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path, request.content))
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "lockVersion": 1,
                    "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}},
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42/form":
            return _make_wp_form_response(request, json.loads(request.content))
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    def forms(self) -> list[bytes]:
        return [content for _, path, content in self.requests if path.endswith("/form")]


@pytest.fixture
def recorder() -> _Recorder:
    return _Recorder()


@pytest.fixture
def call_tool(recorder: _Recorder) -> CallTool:
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
            tools_work_packages.bulk_create_work_packages.__name__,
        ],
        annotations=tools.TOOL_ANNOTATIONS,
    )

    async def call(name: str, arguments: dict) -> types.CallToolResult:
        async with Client(server, mode="legacy") as client:
            recorder.requests.clear()
            return await client.call_tool(name, arguments)

    return call


def _text(result: types.CallToolResult) -> str:
    return "".join(getattr(block, "text", "") for block in result.content)


_ARGS: dict[str, Any] = {"work_package_id": 42}


async def test_a_whole_number_is_sent_as_a_json_integer(call_tool: CallTool, recorder: _Recorder) -> None:
    result = await call_tool("update_work_package", {**_ARGS, "percentage_done": 40})

    assert result.is_error is False, _text(result)
    (form,) = recorder.forms()
    assert re.search(rb'"percentageDone":\s*40[,}]', form), form


@pytest.mark.parametrize("value", [True, False, 40.0, 40.5, "40"])
async def test_a_non_integer_is_rejected_by_the_argument_schema_before_any_request(
    call_tool: CallTool, recorder: _Recorder, value: Any
) -> None:
    result = await call_tool("update_work_package", {**_ARGS, "percentage_done": value})

    assert result.is_error is True
    assert "percentage_done" in _text(result)
    assert "Input should be a valid integer" in _text(result)
    assert recorder.requests == []


@pytest.mark.parametrize("value", [-1, 101])
async def test_a_value_outside_0_to_100_is_rejected_before_any_request(
    call_tool: CallTool, recorder: _Recorder, value: int
) -> None:
    result = await call_tool("update_work_package", {**_ARGS, "percentage_done": value})

    assert result.is_error is True
    assert "[VALIDATION_FAILED] percentage_done must be between 0 and 100." in _text(result)
    assert recorder.requests == []


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (True, "items.0.percentage_done:"),
        (40.0, "items.0.percentage_done:"),
        ("40", "items.0.percentage_done:"),
        (-1, "items[0].percentage_done must be"),
        (101, "items[0].percentage_done must be"),
    ],
)
async def test_a_bulk_item_rejects_what_the_single_call_rejects(
    call_tool: CallTool, recorder: _Recorder, value: Any, message: str
) -> None:
    """A value of the wrong JSON type fails the item schema; a number out of range, the tool's own check."""
    result = await call_tool(
        "bulk_update_work_packages", {"items": [{"work_package_id": 42, "percentage_done": value}], "confirm": True}
    )

    assert result.is_error is True
    assert message in _text(result)
    assert recorder.requests == []


@pytest.mark.parametrize(
    ("tool", "item", "path"),
    [
        ("bulk_update_work_packages", {"work_package_id": 42, "subject": True}, "items.0.subject"),
        ("bulk_update_work_packages", {"work_package_id": 42, "description": 5}, "items.0.description"),
        ("bulk_update_work_packages", {"work_package_id": True, "subject": "s"}, "items.0.work_package_id"),
        ("bulk_update_work_packages", {"work_package_id": 42, "target_versions": [True]}, "items.0.target_versions"),
        ("bulk_create_work_packages", {"project": 1, "type": "Task", "subject": True}, "items.0.subject"),
        (
            "bulk_create_work_packages",
            {"project": 1, "type": "Task", "subject": "s", "description": 5},
            "items.0.description",
        ),
        ("bulk_create_work_packages", {"project": True, "type": "Task", "subject": "s"}, "items.0.project"),
        ("bulk_create_work_packages", {"type": "Task", "subject": "s"}, "items.0.project"),
        ("bulk_create_work_packages", {"project": 1, "type": "Task", "subject": "s", "other": 1}, "items.0.other"),
    ],
)
async def test_a_bulk_item_of_the_wrong_shape_is_refused_with_its_index_and_sends_nothing(
    call_tool: CallTool, recorder: _Recorder, tool: str, item: dict, path: str
) -> None:
    result = await call_tool(tool, {"items": [item], "confirm": True})

    assert result.is_error is True
    assert result.content and "[VALIDATION_FAILED]" in _text(result)
    assert path in _text(result)
    assert recorder.requests == []


async def test_a_bulk_item_of_the_right_shape_still_reaches_the_form(call_tool: CallTool, recorder: _Recorder) -> None:
    result = await call_tool(
        "bulk_update_work_packages", {"items": [{"work_package_id": 42, "subject": "renamed"}], "confirm": False}
    )

    assert result.is_error is False, _text(result)
    assert recorder.forms()
