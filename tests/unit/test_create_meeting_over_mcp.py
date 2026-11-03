"""create_meeting and update_meeting with state, notify or participants, from the MCP call to
the HTTP requests: a rejection reaches the agent as a validation error and nothing is sent, and
participants end up in the request that creates the meeting."""

from __future__ import annotations

import dataclasses
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from _client_test_helpers import make_settings, started_client
from mcp import types
from mcp.client import Client

import openproject_ce_mcp.tools_runtime as tools_runtime
from openproject_ce_mcp import tools, tools_meetings
from openproject_ce_mcp.strict_mcpserver import StrictMCPServer


class _Recorder:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")


async def _call(recorder: _Recorder, arguments: dict, tool: str = "create_meeting") -> types.CallToolResult:
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
        server,
        names=[tools_meetings.create_meeting.__name__, tools_meetings.update_meeting.__name__],
        annotations=tools.TOOL_ANNOTATIONS,
    )
    async with Client(server, mode="legacy") as client:
        recorder.requests.clear()
        return await client.call_tool(tool, arguments)


def _text(result: types.CallToolResult) -> str:
    return "".join(getattr(block, "text", "") for block in result.content)


@pytest.mark.parametrize("extra", [{"state": "open"}, {"notify": True}])
async def test_state_or_notify_is_rejected_as_a_validation_error_without_a_request(extra: dict) -> None:
    recorder = _Recorder()

    result = await _call(recorder, {"project": "demo", "title": "Weekly", "confirm": True, **extra})

    assert result.is_error is True
    assert "[VALIDATION_FAILED] create_meeting does not apply state or notify" in _text(result)
    assert recorder.requests == []


class _CreateRecorder(_Recorder):
    """Serves a create like OpenProject: the form echoes the payload without the participants."""

    def __init__(self) -> None:
        super().__init__()
        self.posted: dict[str, dict] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        if request.url.path == "/api/v3/projects/demo":
            return httpx.Response(200, json={"_type": "Project", "id": 6, "name": "Demo", "identifier": "demo"})
        body = json.loads(request.content) if request.content else {}
        if request.method == "POST" and request.url.path in ("/api/v3/meetings/form", "/api/v3/meetings"):
            self.posted[request.url.path] = body
        if request.url.path == "/api/v3/meetings/form":
            links = {k: v for k, v in body.get("_links", {}).items() if k != "participants"}
            return httpx.Response(
                200, json={"_embedded": {"payload": {**body, "_links": links}, "validationErrors": {}}}
            )
        if request.url.path == "/api/v3/meetings":
            return httpx.Response(
                201,
                json={
                    "id": 40,
                    "title": "Weekly",
                    "lockVersion": 0,
                    "state": "draft",
                    "template": False,
                    "notify": False,
                    "_links": {"project": {"href": "/api/v3/projects/6", "title": "Demo"}},
                    "_embedded": {"participants": []},
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")


async def test_participants_are_part_of_the_request_that_creates_the_meeting() -> None:
    recorder = _CreateRecorder()

    result = await _call(
        recorder, {"project": "demo", "title": "Weekly", "participant_user_refs": [5, 7], "confirm": True}
    )

    assert result.is_error is False, _text(result)
    expected = [{"href": "/api/v3/users/5"}, {"href": "/api/v3/users/7"}]
    assert recorder.posted["/api/v3/meetings/form"]["_links"]["participants"] == expected
    assert recorder.posted["/api/v3/meetings"]["_links"]["participants"] == expected


async def test_an_empty_participant_list_is_rejected_without_a_request() -> None:
    recorder = _Recorder()

    result = await _call(recorder, {"project": "demo", "title": "Weekly", "participant_user_refs": [], "confirm": True})

    assert result.is_error is True
    assert "[VALIDATION_FAILED] participant_user_refs must name at least one user" in _text(result)
    assert recorder.requests == []


@pytest.mark.parametrize("confirm", [False, True])
async def test_update_meeting_rejects_participants_without_a_request(confirm: bool) -> None:
    recorder = _Recorder()

    result = await _call(
        recorder, {"meeting_id": 12, "participant_user_refs": [5], "confirm": confirm}, tool="update_meeting"
    )

    assert result.is_error is True
    assert "[VALIDATION_FAILED] update_meeting cannot change participants" in _text(result)
    assert recorder.requests == []


async def test_update_meeting_with_an_empty_participant_list_gets_the_update_message() -> None:
    recorder = _Recorder()

    result = await _call(
        recorder, {"meeting_id": 12, "participant_user_refs": [], "confirm": True}, tool="update_meeting"
    )

    assert result.is_error is True
    assert "[VALIDATION_FAILED] update_meeting cannot change participants" in _text(result)
    assert recorder.requests == []
