"""What an MCP client sees when a tool fails.

The SDK passes a ToolError's text through; from mcp 2.1 on, any other
exception reaches the client only as "Error executing tool <name>". These
tests go through the SDK's own client so they hold against whichever SDK
version is installed (CI's newest-deps job runs them against the latest).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from mcp import types
from mcp.client import Client
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError

import openproject_ce_mcp.tools_runtime as tools_runtime
from openproject_ce_mcp import tools_work_packages
from openproject_ce_mcp.client import InvalidInputError, OpenProjectPermissionDeniedError
from openproject_ce_mcp.strict_mcpserver import StrictMCPServer

CallTool = Callable[[str, dict], Awaitable[types.CallToolResult]]


async def probe_rejects_input(ctx: Context, value: int) -> str:
    """Probe: a tool-body validator rejecting the input."""
    raise ValueError("value must be positive")


async def probe_openproject_denies(ctx: Context) -> str:
    """Probe: OpenProject refusing the call."""

    async def call() -> str:
        raise OpenProjectPermissionDeniedError("denied by OpenProject")

    return await tools_runtime._run_tool(call())


async def probe_crashes(ctx: Context) -> str:
    """Probe: a bug inside the tool whose own text must not reach the agent."""
    raise KeyError("internal detail")


def _text(result: types.CallToolResult) -> str:
    return "".join(getattr(block, "text", "") for block in result.content)


# "legacy" is the initialize handshake today's stdio clients use, "auto" the
# SDK's newer per-request path; each converts tool errors on its own.
@pytest.fixture(params=["legacy", "auto"])
def call_tool(request, monkeypatch) -> CallTool:
    monkeypatch.setattr(
        tools_runtime,
        "_TOOL_FUNCTIONS",
        {
            "probe_rejects_input": probe_rejects_input,
            "probe_openproject_denies": probe_openproject_denies,
            "probe_crashes": probe_crashes,
            "bulk_create_work_packages": tools_work_packages.bulk_create_work_packages,
            "bulk_update_work_packages": tools_work_packages.bulk_update_work_packages,
        },
    )

    # The bulk tools reject their input before they would touch the client.
    @asynccontextmanager
    async def no_client(_):
        yield SimpleNamespace(client=None)

    server = StrictMCPServer("test", lifespan=no_client)
    tools_runtime.register_selected_tools(server, names=tools_runtime._TOOL_FUNCTIONS, hide_active=False)

    async def call(name: str, arguments: dict) -> types.CallToolResult:
        async with Client(server, mode=request.param) as client:
            return await client.call_tool(name, arguments)

    return call


async def test_client_sees_the_category_and_message_of_rejected_input(call_tool: CallTool):
    result = await call_tool("probe_rejects_input", {"value": -1})

    assert result.is_error is True
    assert "[VALIDATION_FAILED] value must be positive" in _text(result)


async def test_client_sees_the_category_and_message_of_a_refused_openproject_call(call_tool: CallTool):
    result = await call_tool("probe_openproject_denies", {})

    assert result.is_error is True
    assert "[OPENPROJECT_PERMISSION_DENIED] denied by OpenProject" in _text(result)


async def test_client_sees_a_sanitized_internal_error_for_a_crash(call_tool: CallTool):
    result = await call_tool("probe_crashes", {})

    assert result.is_error is True
    assert "[INTERNAL_ERROR] An internal error occurred." in _text(result)
    assert "internal detail" not in _text(result)


@pytest.mark.parametrize(
    ("tool", "item", "field"),
    [
        ("bulk_create_work_packages", {"project": "TST", "type": "Task", "subject": "s"}, "subject"),
        ("bulk_update_work_packages", {"work_package_id": 1, "subject": "s"}, "status"),
    ],
)
async def test_client_sees_why_a_confirmed_bulk_write_rejects_its_select(call_tool: CallTool, tool, item, field):
    result = await call_tool(tool, {"items": [item], "select": ["work_package_id", field], "confirm": True})

    assert result.is_error is True
    assert (
        f"[VALIDATION_FAILED] select field '{field}' is a field of the WorkPackageDetail in 'result'; select it as 'result.{field}'."
        in _text(result)
    )


async def test_categorised_errors_stay_value_and_runtime_errors_for_python_callers():
    async def rejected() -> None:
        raise InvalidInputError("bad")

    async def refused() -> None:
        raise OpenProjectPermissionDeniedError("no")

    with pytest.raises(ValueError) as rejected_error:
        await tools_runtime._run_tool(rejected())
    with pytest.raises(RuntimeError) as refused_error:
        await tools_runtime._run_tool(refused())

    assert isinstance(rejected_error.value, ToolError)
    assert isinstance(refused_error.value, ToolError)
