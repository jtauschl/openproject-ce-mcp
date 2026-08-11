"""Tests for StrictMCPServer: unknown tool arguments must be rejected, not silently
dropped by the SDK's default extra="ignore" argument-model validation.

These drive calls through the real MCP protocol dispatch path (the low-level
server's "tools/call" request handler), not by awaiting the raw Python tool
function directly — a raw-function call would TypeError on an unknown kwarg,
which is a different failure mode than the silent-drop bug being closed here.
"""

import asyncio
from typing import Any

import pytest
from mcp import types
from mcp.client.session import ClientSession
from mcp.server.mcpserver import Context
from mcp.shared.memory import create_client_server_memory_streams

from openproject_ce_mcp.config import Settings
from openproject_ce_mcp.server import create_app
from openproject_ce_mcp.strict_mcpserver import StrictMCPServer, verify_strict_dispatch


def make_settings(**overrides) -> Settings:
    defaults = {
        "base_url": "https://op.example.com",
        "api_token": "token",
        "timeout": 12,
        "verify_ssl": True,
        "default_page_size": 20,
        "max_page_size": 50,
        "max_results": 100,
        "log_level": "WARNING",
        "read_projects": ("*",),
    }
    defaults.update(overrides)
    return Settings(**defaults)


async def _dispatch(mcp: StrictMCPServer, name: str, arguments: dict[str, Any]) -> types.CallToolResult:
    """Drive a tool call through the real low-level "tools/call" request handler."""
    params = types.CallToolRequestParams(name=name, arguments=arguments)
    entry = mcp._lowlevel_server.get_request_handler("tools/call")
    assert entry is not None
    return await entry.handler(None, params)


def _text(result: types.CallToolResult) -> str:
    return "".join(getattr(block, "text", "") for block in result.content)


@pytest.fixture
def strict_mcp() -> StrictMCPServer:
    mcp = StrictMCPServer("test")

    calls: list[str] = []
    mcp._test_calls = calls  # type: ignore[attr-defined]

    @mcp.tool()
    async def plain_tool(name: str, greeting: str = "hello") -> str:
        calls.append("plain_tool")
        return f"{greeting}, {name}"

    @mcp.tool()
    async def ctx_tool(ctx: Context, name: str) -> str:
        calls.append("ctx_tool")
        return f"hi {name}"

    @mcp.tool()
    async def dict_arg_tool(custom_fields: dict[str, Any]) -> dict[str, Any]:
        calls.append("dict_arg_tool")
        return custom_fields

    return mcp


async def test_unknown_top_level_argument_is_rejected(strict_mcp: StrictMCPServer) -> None:
    result = await _dispatch(strict_mcp, "plain_tool", {"name": "World", "filters": ["x"]})
    assert result.is_error is True
    assert "[validation_error]" in _text(result)
    assert "filters" in _text(result)
    assert strict_mcp._test_calls == []  # type: ignore[attr-defined]


async def test_valid_call_passes_through_unchanged(strict_mcp: StrictMCPServer) -> None:
    result = await _dispatch(strict_mcp, "plain_tool", {"name": "World"})
    assert result.is_error is not True
    assert "hello, World" in _text(result)
    assert strict_mcp._test_calls == ["plain_tool"]  # type: ignore[attr-defined]


async def test_multiple_unknown_arguments_reported_sorted(strict_mcp: StrictMCPServer) -> None:
    result = await _dispatch(strict_mcp, "plain_tool", {"name": "World", "zeta": 1, "alpha": 2})
    assert result.is_error is True
    text = _text(result)
    # sorted: "alpha" must appear before "zeta"
    assert text.index("alpha") < text.index("zeta")


async def test_context_parameter_not_treated_as_unknown(strict_mcp: StrictMCPServer) -> None:
    """Highest-risk regression case: ctx is injected by the SDK, never sent by
    the caller, and must not appear in the allowlist diff."""
    result = await _dispatch(strict_mcp, "ctx_tool", {"name": "World"})
    assert result.is_error is not True
    assert strict_mcp._test_calls == ["ctx_tool"]  # type: ignore[attr-defined]


async def test_unknown_tool_name_keeps_standard_error(strict_mcp: StrictMCPServer) -> None:
    """Must not be misreported as 'all arguments unknown' — this is a distinct,
    pre-existing SDK error path that must stay unchanged."""
    result = await _dispatch(strict_mcp, "does_not_exist", {"anything": 1})
    assert result.is_error is True
    assert "validation_error" not in _text(result)
    assert "Unknown tool" in _text(result)


async def test_nested_dict_argument_keys_not_rejected(strict_mcp: StrictMCPServer) -> None:
    """Top-level check only — dynamic inner keys of a dict[str, Any]-typed
    parameter (e.g. custom_fields) must pass through untouched."""
    result = await _dispatch(strict_mcp, "dict_arg_tool", {"custom_fields": {"customField1": "x", "anything_else": 2}})
    assert result.is_error is not True
    assert strict_mcp._test_calls == ["dict_arg_tool"]  # type: ignore[attr-defined]


async def test_tool_schema_has_top_level_additional_properties_false(strict_mcp: StrictMCPServer) -> None:
    tool = strict_mcp._tool_manager.get_tool("plain_tool")
    assert tool is not None
    assert tool.parameters.get("additionalProperties") is False


async def test_unknown_argument_rejected_over_a_real_client_server_roundtrip(strict_mcp: StrictMCPServer) -> None:
    """Complements the direct-dispatch tests above (which reach into SDK-internal
    handler registries) with one full, officially-supported client-server
    roundtrip: a real ClientSession over in-memory streams, real JSON-RPC
    serialization, real MCPServer.run() request loop. Catches SDK changes to
    serialization/dispatch/middleware the direct-dispatch tests cannot see."""
    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams
        init_options = strict_mcp._lowlevel_server.create_initialization_options()

        async def run_server() -> None:
            await strict_mcp._lowlevel_server.run(server_read, server_write, init_options)

        server_task = asyncio.create_task(run_server())
        try:
            async with ClientSession(client_read, client_write) as session:
                await session.initialize()
                result = await session.call_tool("plain_tool", {"name": "World", "filters": ["x"]})
                assert result.is_error is True
                assert "[validation_error]" in _text(result)

                valid_result = await session.call_tool("plain_tool", {"name": "World"})
                assert valid_result.is_error is not True
                assert "hello, World" in _text(valid_result)
        finally:
            server_task.cancel()
            try:
                await server_task
            except asyncio.CancelledError:
                pass


# ── regression coverage for the two originally reported bugs ──────────────────


async def test_list_work_packages_rejects_unknown_filters_argument() -> None:
    mcp = create_app(make_settings())
    result = await _dispatch(
        mcp,
        "list_work_packages",
        {
            "project": "ENC",
            "filters": [
                {"field": "version", "operator": "=", "values": ["93"]},
                {"field": "status", "operator": "o"},
            ],
        },
    )
    assert result.is_error is True
    assert "[validation_error]" in _text(result)
    assert "filters" in _text(result)


async def test_list_versions_rejects_unknown_page_argument() -> None:
    mcp = create_app(make_settings())
    result = await _dispatch(mcp, "list_versions", {"project": "ENC", "page": 3})
    assert result.is_error is True
    assert "[validation_error]" in _text(result)
    assert "page" in _text(result)


async def test_search_work_packages_rejects_legacy_query_argument() -> None:
    """v0.4.0 renamed the free-text parameter to `search`; a caller still using
    the v0.3.6 name `query` must now be rejected loudly instead of silently
    running an unfiltered/defaulted search."""
    mcp = create_app(make_settings())
    result = await _dispatch(mcp, "search_work_packages", {"query": "0.1.0"})
    assert result.is_error is True
    assert "[validation_error]" in _text(result)
    assert "query" in _text(result)


async def test_verify_strict_dispatch_passes_on_live_app() -> None:
    """The startup self-test itself must succeed against the real app, and must
    not leave its disposable probe tool registered afterwards."""
    mcp = create_app(make_settings())
    await verify_strict_dispatch(mcp)
    assert "__strict_mcpserver_probe__" not in {t.name for t in mcp._tool_manager.list_tools()}


async def test_verify_strict_dispatch_raises_if_dispatch_not_enforced() -> None:
    """If a future SDK/refactor made call_tool validation a no-op, the startup
    check must fail loudly rather than silently accept it."""

    class _AlwaysPermissiveMCP(StrictMCPServer):
        async def call_tool(self, name, arguments, context=None):  # type: ignore[override]
            # Bypasses the strict check entirely, simulating a broken override.
            # Verified: an override with a mismatched signature (e.g. missing
            # `context`) still makes this test pass, but not vacuously --
            # MCPServer._handle_call_tool catches every Exception from
            # call_tool (including a TypeError from a bad signature) and
            # returns it as an is_error=True CallToolResult, which correctly
            # trips verify_strict_dispatch's "not is_error or no
            # [validation_error] marker" check for a different reason than
            # this test intends. Keep the signature exact so a real dispatch-
            # bypass regression (not a signature typo) is what's asserted.
            return await super(StrictMCPServer, self).call_tool(name, arguments, context)

    mcp = _AlwaysPermissiveMCP("broken")
    with pytest.raises(RuntimeError, match="StrictMCPServer self-test failed"):
        await verify_strict_dispatch(mcp)
