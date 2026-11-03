"""availability_factor as an MCP client passes it: through the SDK's argument
handling, the tool, the client and the HTTP request it ends in."""

from __future__ import annotations

import dataclasses
import re
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
from openproject_ce_mcp import tools, tools_user_schedule
from openproject_ce_mcp.strict_mcpserver import StrictMCPServer

CallTool = Callable[[str, dict], Awaitable[types.CallToolResult]]

_PATH = "/api/v3/users/me/working_hours"


def _record(availability_factor: Any) -> dict[str, Any]:
    return {
        "id": 5,
        "validFrom": "2026-08-01",
        "mondayHours": 8,
        "tuesdayHours": 0,
        "wednesdayHours": 0,
        "thursdayHours": 0,
        "fridayHours": 0,
        "saturdayHours": 0,
        "sundayHours": 0,
        "availabilityFactor": availability_factor,
        "_links": {"user": {"href": "/api/v3/users/3", "title": "Alice"}},
    }


class _Recorder:
    def __init__(self) -> None:
        self.writes: list[tuple[str, bytes]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method in ("POST", "PATCH"):
            self.writes.append((request.method, request.content))
        if path == _PATH and request.method == "POST":
            return httpx.Response(201, json=_record(50))
        if path == f"{_PATH}/5":
            return httpx.Response(200, json=_record(50))
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")


@pytest.fixture
def recorder() -> _Recorder:
    return _Recorder()


@pytest.fixture
def call_tool(recorder: _Recorder) -> CallTool:
    settings = dataclasses.replace(make_settings(), enable_user_schedule_read=True, enable_user_schedule_write=True)

    @asynccontextmanager
    async def lifespan(_):
        client = await started_client(settings, recorder.handler, [(6, "demo", "Demo")])
        try:
            yield SimpleNamespace(client=client)
        finally:
            await client.aclose()

    server = StrictMCPServer("test", lifespan=lifespan)
    tools_runtime.register_selected_tools(
        server,
        names=[
            tools_user_schedule.create_user_working_hours.__name__,
            tools_user_schedule.update_user_working_hours.__name__,
        ],
        annotations=tools.TOOL_ANNOTATIONS,
    )

    async def call(name: str, arguments: dict) -> types.CallToolResult:
        async with Client(server, mode="legacy") as client:
            recorder.writes.clear()
            return await client.call_tool(name, arguments)

    return call


def _text(result: types.CallToolResult) -> str:
    return "".join(getattr(block, "text", "") for block in result.content)


_CREATE = {"user_ref": "me", "valid_from": "2026-08-01", "monday_hours": 8, "confirm": True}
_UPDATE = {"user_ref": "me", "working_hours_id": 5, "confirm": True}


@pytest.mark.parametrize(
    "tool, arguments", [("create_user_working_hours", _CREATE), ("update_user_working_hours", _UPDATE)]
)
async def test_a_whole_number_is_sent_as_a_json_integer(
    call_tool: CallTool, recorder: _Recorder, tool: str, arguments: dict
) -> None:
    result = await call_tool(tool, {**arguments, "availability_factor": 50})

    assert result.is_error is False, _text(result)
    ((_, body),) = recorder.writes
    assert re.search(rb'"availabilityFactor":\s*50[,}]', body), body


@pytest.mark.parametrize(
    "tool, arguments", [("create_user_working_hours", _CREATE), ("update_user_working_hours", _UPDATE)]
)
@pytest.mark.parametrize("value", [0.9, 50.0, True, "50"])
async def test_a_non_integer_is_rejected_by_the_argument_schema_before_any_request(
    call_tool: CallTool, recorder: _Recorder, tool: str, arguments: dict, value: Any
) -> None:
    result = await call_tool(tool, {**arguments, "availability_factor": value})

    assert result.is_error is True
    assert "availability_factor" in _text(result)
    assert "Input should be a valid integer" in _text(result)
    assert recorder.writes == []


@pytest.mark.parametrize(
    "tool, arguments", [("create_user_working_hours", _CREATE), ("update_user_working_hours", _UPDATE)]
)
@pytest.mark.parametrize("value", [-1, 101])
async def test_a_value_outside_0_to_100_is_rejected_before_any_request(
    call_tool: CallTool, recorder: _Recorder, tool: str, arguments: dict, value: int
) -> None:
    result = await call_tool(tool, {**arguments, "availability_factor": value})

    assert result.is_error is True
    assert "[VALIDATION_FAILED] availability_factor must be between 0 and 100." in _text(result)
    assert recorder.writes == []
