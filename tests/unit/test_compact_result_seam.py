"""Every tool result leaves the server through one seam as one compact JSON text block.

Calls go through the MCP client and the registered tools, so the SDK's own result conversion is part of what is
tested: a tool that fell back to the SDK serialiser would show indentation, a second `structuredContent` copy or a
published `outputSchema`.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from _client_test_helpers import make_settings, started_client
from mcp import types
from mcp.client import Client
from mcp.server.mcpserver import Context
from test_tool_contract_snapshot import _all_scopes_enabled_settings

import openproject_ce_mcp.tools_runtime as tools_runtime
from openproject_ce_mcp import tools
from openproject_ce_mcp.config import Settings
from openproject_ce_mcp.presentation import dump_payload
from openproject_ce_mcp.server import create_app
from openproject_ce_mcp.strict_mcpserver import StrictMCPServer


def _status(status_id: int, name: str) -> dict[str, Any]:
    return {
        "id": status_id,
        "name": name,
        "isDefault": status_id == 1,
        "isClosed": False,
        "color": "#1A67A3",
        "position": status_id,
        "isReadonly": False,
        "defaultDoneRatio": 30,
        "excludedFromTotals": False,
    }


def _reaction(count: int) -> dict[str, Any]:
    return {
        "reaction": "thumbs_up",
        "emoji": "\U0001f44d",
        "reactionsCount": count,
        "_links": {"reactingUsers": [{"title": "Ada Lovelace"}, {"title": "Alan Turing"}]},
    }


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if request.method == "GET" and path == "/api/v3/statuses":
        return httpx.Response(200, json={"_embedded": {"elements": [_status(1, "New"), _status(2, "In progress")]}})
    if request.method == "GET" and path == "/api/v3/users/me":
        return httpx.Response(200, json={"id": 4, "name": "Ada Lovelace", "login": "ada"})
    if request.method == "GET" and path == "/api/v3/activities/5":
        return httpx.Response(200, json={"_links": {"workPackage": {"href": "/api/v3/work_packages/77"}}})
    if request.method == "GET" and path == "/api/v3/work_packages/77":
        return httpx.Response(
            200, json={"id": 77, "_links": {"project": {"href": "/api/v3/projects/6", "title": "Demo"}}}
        )
    if request.method == "PATCH" and path == "/api/v3/activities/5/emoji_reactions":
        return httpx.Response(200, json={"_embedded": {"elements": [_reaction(2)]}})
    raise AssertionError(f"Unexpected request: {request.method} {request.url}")


async def _call(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
    settings = dataclasses.replace(make_settings(), enable_work_package_read=True, enable_work_package_write=True)

    @asynccontextmanager
    async def lifespan(_):
        client = await started_client(settings, _handler, [(6, "demo", "Demo")])
        try:
            yield SimpleNamespace(client=client)
        finally:
            await client.aclose()

    server = StrictMCPServer("test", lifespan=lifespan)
    tools_runtime.register_selected_tools(server, names=[name], annotations=tools.TOOL_ANNOTATIONS)
    async with Client(server, mode="legacy") as client:
        return await client.call_tool(name, arguments)


def _only_text(result: types.CallToolResult) -> str:
    assert result.is_error is False, result.content
    assert [type(block) for block in result.content] == [types.TextContent]
    assert result.structured_content is None
    return result.content[0].text


async def test_a_trimmed_list_result_is_one_compact_text_block() -> None:
    text = _only_text(await _call("list_statuses", {}))

    payload = json.loads(text)
    assert [row["name"] for row in payload["results"]] == ["New", "In progress"]
    assert "\n" not in text
    assert text == dump_payload(payload)
    assert '"results":[{' in text


async def test_a_result_the_sdk_used_to_serialise_itself_is_one_compact_text_block() -> None:
    text = _only_text(await _call("get_current_user", {}))

    payload = json.loads(text)
    assert payload["name"] == "Ada Lovelace"
    assert "\n" not in text
    assert text == dump_payload(payload)
    assert '"id":4,"name":"Ada Lovelace"' in text


async def test_a_nested_collection_drops_its_derivable_count_through_the_real_seam() -> None:
    text = _only_text(
        await _call("toggle_activity_emoji_reaction", {"activity_id": 5, "reaction": "thumbs_up", "confirm": True})
    )

    payload = json.loads(text)
    assert payload["state"] == "confirmed"
    assert [row["count"] for row in payload["result"]["results"]] == [2]
    assert "count" not in payload["result"]
    assert "\n" not in text


class _Unserialisable:
    def __str__(self) -> str:
        raise RuntimeError("secret internal path /srv/openproject/token=abc")


@dataclasses.dataclass
class _ProbeResult:
    value: Any


async def test_a_value_the_encoder_cannot_serialise_reaches_the_client_as_a_sanitised_internal_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def probe_unserialisable_result(ctx: Context) -> _ProbeResult:
        """Probe: a result holding a value no serialiser can render."""
        return _ProbeResult(value=_Unserialisable())

    monkeypatch.setitem(tools_runtime._TOOL_FUNCTIONS, "probe_unserialisable_result", probe_unserialisable_result)
    server = StrictMCPServer("test")
    tools_runtime.register_selected_tools(
        server,
        names=["probe_unserialisable_result"],
        annotations={"probe_unserialisable_result": tools.TOOL_ANNOTATIONS["list_statuses"]},
    )

    async with Client(server, mode="legacy") as client:
        result = await client.call_tool("probe_unserialisable_result", {})

    assert result.is_error is True
    text = result.content[0].text
    assert "[INTERNAL_ERROR] An internal error occurred." in text
    assert "secret internal path" not in text


def _tools_of(settings: Settings) -> dict[str, Any]:
    mcp = create_app(settings)
    return {tool.name: tool for tool in asyncio.run(mcp.list_tools())}


@pytest.mark.parametrize("hidden", [{}, {"status": ("name",)}], ids=["no-hidden-fields", "hidden-fields"])
def test_no_registered_tool_publishes_an_output_schema(hidden: dict) -> None:
    settings = dataclasses.replace(_all_scopes_enabled_settings(), hidden_fields=hidden)

    catalog = _tools_of(settings)

    assert len(catalog) > 150
    assert [name for name, tool in catalog.items() if tool.output_schema is not None] == []


@pytest.mark.parametrize("hidden", [{}, {"status": ("name",)}], ids=["no-hidden-fields", "hidden-fields"])
def test_every_registered_tool_runs_through_the_trimming_wrapper(hidden: dict) -> None:
    settings = dataclasses.replace(_all_scopes_enabled_settings(), hidden_fields=hidden)
    mcp = create_app(settings)

    registered = {tool.name: tool for tool in mcp._tool_manager.list_tools()}

    # `functools.wraps` links the wrapper to what it wraps: the outer layer is the error categorisation, the next
    # one the trimming wrapper, whose own `__wrapped__` is the tool function. A tool registered without the
    # trimming wrapper links straight to its function.
    bypassing = [
        name
        for name, tool in registered.items()
        if tool.fn.__wrapped__ is tools_runtime._TOOL_FUNCTIONS[name]  # type: ignore[attr-defined]
    ]
    assert len(registered) > 150
    assert bypassing == []


def _register(fn: Any) -> None:
    server = StrictMCPServer("test")
    name = fn.__name__
    tools_runtime._TOOL_FUNCTIONS[name] = fn
    try:
        tools_runtime.register_selected_tools(
            server, names=[name], annotations={name: tools.TOOL_ANNOTATIONS["list_statuses"]}
        )
    finally:
        del tools_runtime._TOOL_FUNCTIONS[name]


@pytest.mark.parametrize("annotation", [str, dict, "list[int]", None], ids=["str", "dict", "list", "missing"])
def test_a_tool_that_returns_neither_a_dataclass_nor_a_content_bundle_cannot_be_registered(annotation: Any) -> None:
    async def probe_tool_without_result_model(ctx) -> Any:
        return "x"

    if annotation is None:
        del probe_tool_without_result_model.__annotations__["return"]
    else:
        probe_tool_without_result_model.__annotations__["return"] = annotation

    with pytest.raises(RuntimeError, match="must return a result dataclass or a ContentBundle"):
        _register(probe_tool_without_result_model)
