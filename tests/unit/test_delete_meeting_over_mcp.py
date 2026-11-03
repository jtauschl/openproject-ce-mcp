"""delete_meeting on a recurring series' template, from the MCP call to the
HTTP requests: the template is read from OpenProject's own payload and no
DELETE is sent."""

from __future__ import annotations

import dataclasses
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from _client_test_helpers import make_settings, started_client
from mcp import types
from mcp.client import Client

import openproject_ce_mcp.tools_runtime as tools_runtime
from openproject_ce_mcp import tools, tools_meetings
from openproject_ce_mcp.strict_mcpserver import StrictMCPServer


def _meeting(meeting_id: int, *, template: bool, recurring_meeting_id: int | None) -> dict[str, Any]:
    links: dict[str, Any] = {
        "project": {"href": "/api/v3/projects/6", "title": "Demo"},
        "author": {"href": "/api/v3/users/1", "title": "Alice"},
    }
    if recurring_meeting_id is not None:
        links["recurringMeeting"] = {"href": f"/api/v3/recurring_meetings/{recurring_meeting_id}", "title": "Weekly"}
    return {
        "id": meeting_id,
        "title": "Weekly",
        "lockVersion": 0,
        "startTime": "2031-03-03T09:00:00Z",
        "duration": "PT1H",
        "state": "open",
        "template": template,
        "notify": False,
        "_links": links,
        "_embedded": {"participants": []},
    }


class _Recorder:
    def __init__(self, meeting: dict[str, Any]) -> None:
        self.meeting = meeting
        self.deletes: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/api/v3/meetings/{self.meeting['id']}":
            if request.method == "GET":
                return httpx.Response(200, json=self.meeting)
            if request.method == "DELETE":
                self.deletes.append(request.url.path)
                return httpx.Response(204)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")


async def _call(recorder: _Recorder, arguments: dict) -> types.CallToolResult:
    settings = dataclasses.replace(make_settings(), enable_meeting_read=True, enable_meeting_write=True)

    @asynccontextmanager
    async def lifespan(_):
        client = await started_client(settings, recorder.handler, [(6, "demo", "Demo")])
        try:
            yield SimpleNamespace(client=client)
        finally:
            await client.aclose()

    server = StrictMCPServer("test", lifespan=lifespan)
    tools_runtime.register_selected_tools(
        server, names=[tools_meetings.delete_meeting.__name__], annotations=tools.TOOL_ANNOTATIONS
    )
    async with Client(server, mode="legacy") as client:
        return await client.call_tool("delete_meeting", arguments)


def _text(result: types.CallToolResult) -> str:
    return "".join(getattr(block, "text", "") for block in result.content)


@pytest.mark.parametrize("confirm", [False, True])
async def test_a_series_template_is_rejected_without_a_delete_request(confirm: bool) -> None:
    recorder = _Recorder(_meeting(412, template=True, recurring_meeting_id=91))

    result = await _call(recorder, {"meeting_id": 412, "confirm": confirm})

    assert result.is_error is True
    assert "[VALIDATION_FAILED] meeting_id 412 is the template of recurring meeting 91" in _text(result)
    assert recorder.deletes == []


async def test_a_one_time_template_is_deleted() -> None:
    recorder = _Recorder(_meeting(413, template=True, recurring_meeting_id=None))

    result = await _call(recorder, {"meeting_id": 413, "confirm": True})

    assert result.is_error is False, _text(result)
    assert recorder.deletes == ["/api/v3/meetings/413"]
