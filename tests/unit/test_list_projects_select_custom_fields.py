"""`list_projects` returns the project attributes on every row, and `select` keeps them when it names them."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from _tools_test_helpers import make_settings
from mcp import types
from mcp.client import Client

import openproject_ce_mcp.tools_runtime as tools_runtime
from openproject_ce_mcp import tools, tools_projects
from openproject_ce_mcp.client import OpenProjectClient
from openproject_ce_mcp.strict_mcpserver import StrictMCPServer

_PROJECT = {
    "id": 6,
    "_type": "Project",
    "name": "Demo",
    "identifier": "demo",
    "active": True,
    "customField1": "old",
    "_links": {"self": {"href": "/api/v3/projects/6"}},
}


def _handler(request: httpx.Request) -> httpx.Response:
    if request.method == "GET" and request.url.path == "/api/v3/projects":
        return httpx.Response(200, json={"total": 1, "_embedded": {"elements": [_PROJECT]}}, request=request)
    raise AssertionError(f"Unexpected request: {request.method} {request.url}")


@pytest.fixture
def list_projects_over_mcp() -> Callable[[dict], Awaitable[dict]]:
    @asynccontextmanager
    async def lifespan(_):
        client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(_handler))
        try:
            yield SimpleNamespace(client=client)
        finally:
            await client.aclose()

    server = StrictMCPServer("test", lifespan=lifespan)
    tools_runtime.register_selected_tools(
        server,
        names=[tools_projects.list_projects.__name__],
        annotations=tools.TOOL_ANNOTATIONS,
    )

    async def call(arguments: dict) -> dict:
        async with Client(server, mode="legacy") as client:
            result: types.CallToolResult = await client.call_tool("list_projects", arguments)
        text = "".join(getattr(block, "text", "") for block in result.content)
        assert result.is_error is False, text
        return json.loads(text)["results"][0]

    return call


@pytest.mark.asyncio
async def test_every_row_carries_the_project_attributes_without_a_select(list_projects_over_mcp) -> None:
    row = await list_projects_over_mcp({})

    assert row["custom_fields"] == {"customField1": "<user-content>old</user-content>"}


@pytest.mark.asyncio
async def test_a_select_naming_the_attributes_keeps_them(list_projects_over_mcp) -> None:
    row = await list_projects_over_mcp({"select": ["id", "custom_fields"]})

    assert row == {"id": 6, "custom_fields": {"customField1": "<user-content>old</user-content>"}}


@pytest.mark.asyncio
async def test_a_select_without_the_attributes_leaves_them_out(list_projects_over_mcp) -> None:
    row = await list_projects_over_mcp({"select": ["id", "name"]})

    assert row == {"id": 6, "name": "Demo"}


@pytest.mark.asyncio
async def test_the_description_tells_select_keeps_the_attributes_when_named() -> None:
    server = StrictMCPServer("test")
    tools_runtime.register_selected_tools(
        server,
        names=[tools_projects.list_projects.__name__],
        annotations=tools.TOOL_ANNOTATIONS,
    )

    async with Client(server, mode="legacy") as client:
        listed = await client.list_tools()

    description = next(tool.description for tool in listed.tools if tool.name == "list_projects")
    assert "with select, name custom_fields to keep them" in description
    assert "select leaves them out" not in description
