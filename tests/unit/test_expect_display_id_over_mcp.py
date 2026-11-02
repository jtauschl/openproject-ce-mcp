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

GUARDING_A_REFERENCE = (
    "create_work_package_reminder",
    "create_work_package_wiki_link",
    "delete_work_package_wiki_link",
    "create_time_entry",
    "create_time_entry_until",
    "create_meeting_agenda_item",
    "update_meeting_agenda_item",
    "create_meeting_outcome",
    "update_meeting_outcome",
)

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
            tools_work_packages.create_work_package.__name__,
            tools_work_packages.create_subtask.__name__,
            tools_work_packages.bulk_create_work_packages.__name__,
            *GUARDING_A_REFERENCE,
            "create_work_package_relation",
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


GUARDING_A_PARENT = ("create_work_package", "create_subtask", "update_work_package")


async def _listed(server: StrictMCPServer) -> dict[str, types.Tool]:
    async with Client(server, mode="legacy") as client:
        return {tool.name: tool for tool in (await client.list_tools()).tools}


def _assert_optional_string_or_null(parameter: dict) -> None:
    assert {branch["type"] for branch in parameter["anyOf"]} == {"string", "null"}
    assert parameter["description"]


@pytest.mark.parametrize("name", GUARDING_A_PARENT)
async def test_the_schema_offers_an_optional_parent_expectation(server: StrictMCPServer, name: str) -> None:
    schema = (await _listed(server))[name].input_schema

    _assert_optional_string_or_null(schema["properties"]["expect_parent_display_id"])
    assert "expect_parent_display_id" not in schema.get("required", [])


@pytest.mark.parametrize(
    ("name", "item"),
    [
        ("bulk_create_work_packages", "BulkCreateWorkPackageItem"),
        ("bulk_update_work_packages", "BulkUpdateWorkPackageItem"),
    ],
)
async def test_the_bulk_item_schema_offers_an_optional_parent_expectation(
    server: StrictMCPServer, name: str, item: str
) -> None:
    schema = (await _listed(server))[name].input_schema

    definition = schema["$defs"][item]
    _assert_optional_string_or_null(definition["properties"]["expect_parent_display_id"])
    assert "expect_parent_display_id" not in definition.get("required", [])


async def test_a_parent_by_a_bare_number_is_refused_naming_the_parent_parameter(
    call_tool: CallTool, recorder: _Recorder
) -> None:
    result = await call_tool(
        "update_work_package",
        {"work_package_id": 436, "expect_display_id": "A-1", "parent": 436, "confirm": True},
    )

    assert result.is_error is True
    assert "repeat with expect_parent_display_id 'A-1'" in _text(result)
    assert recorder.writes() == []


async def test_a_parent_expectation_of_the_wrong_json_type_is_rejected_before_any_request(
    call_tool: CallTool, recorder: _Recorder
) -> None:
    result = await call_tool(
        "update_work_package", {"work_package_id": 436, "parent": 436, "expect_parent_display_id": 51}
    )

    assert result.is_error is True
    assert "expect_parent_display_id" in _text(result)
    assert recorder.requests == []


async def test_a_bulk_item_accepts_the_parent_expectation_key(call_tool: CallTool, recorder: _Recorder) -> None:
    result = await call_tool(
        "bulk_update_work_packages",
        {"items": [{"work_package_id": 436, "expect_display_id": "A-1", "parent": 436}], "confirm": False},
    )

    assert result.is_error is False, _text(result)
    assert "repeat with expect_parent_display_id 'A-1'" in json.loads(_text(result))["items"][0]["error"]
    assert recorder.writes() == []


@pytest.mark.parametrize("name", [*GUARDING_A_REFERENCE, "create_work_package_relation"])
async def test_the_schema_offers_an_optional_expectation_on_each_remaining_write(
    server: StrictMCPServer, name: str
) -> None:
    schema = (await _listed(server))[name].input_schema

    _assert_optional_string_or_null(schema["properties"]["expect_display_id"])
    assert "expect_display_id" not in schema.get("required", [])


async def test_the_relation_schema_offers_a_separate_optional_related_expectation(server: StrictMCPServer) -> None:
    schema = (await _listed(server))["create_work_package_relation"].input_schema

    _assert_optional_string_or_null(schema["properties"]["expect_related_display_id"])
    assert "expect_related_display_id" not in schema.get("required", [])
    assert (
        schema["properties"]["expect_related_display_id"]["description"]
        != schema["properties"]["expect_display_id"]["description"]
    )


async def test_a_reminder_by_a_bare_number_is_refused_over_mcp(call_tool: CallTool, recorder: _Recorder) -> None:
    result = await call_tool(
        "create_work_package_reminder", {"work_package_id": 436, "remind_at": "2026-12-01T09:00:00Z", "confirm": True}
    )

    assert result.is_error is True
    assert "[VALIDATION_FAILED] 436 is A-1 (Project A). If you mean A-1, repeat with expect_display_id 'A-1'" in _text(
        result
    )
    assert recorder.writes() == []


async def test_a_related_bare_number_is_refused_naming_the_related_parameter(
    call_tool: CallTool, recorder: _Recorder
) -> None:
    result = await call_tool(
        "create_work_package_relation",
        {
            "work_package_id": 436,
            "related_to_work_package_id": 436,
            "relation_type": "relates",
            "expect_display_id": "A-1",
            "confirm": True,
        },
    )

    assert result.is_error is True
    assert "repeat with expect_related_display_id 'A-1'" in _text(result)
    assert recorder.writes() == []


@pytest.mark.parametrize("field", ["expect_display_id", "expect_related_display_id"])
async def test_a_relation_expectation_of_the_wrong_json_type_is_rejected_before_any_request(
    call_tool: CallTool, recorder: _Recorder, field: str
) -> None:
    result = await call_tool(
        "create_work_package_relation",
        {"work_package_id": 436, "related_to_work_package_id": 436, "relation_type": "relates", field: 51},
    )

    assert result.is_error is True
    assert field in _text(result)
    assert recorder.requests == []


async def test_an_expectation_without_a_work_package_is_refused_over_mcp(
    call_tool: CallTool, recorder: _Recorder
) -> None:
    result = await call_tool(
        "create_meeting_agenda_item", {"meeting_id": 4, "title": "Item", "expect_display_id": "A-1", "confirm": True}
    )

    assert result.is_error is True
    assert "expect_display_id was given but work_package_id names no work package" in _text(result)
    assert recorder.requests == []
