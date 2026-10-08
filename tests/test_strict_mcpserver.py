"""Tests for StrictMCPServer: unknown tool arguments must be rejected, not silently
dropped by the SDK's default extra="ignore" argument-model validation.

These drive calls through the real MCP protocol dispatch path (the low-level
server's "tools/call" request handler), not by awaiting the raw Python tool
function directly — a raw-function call would TypeError on an unknown kwarg,
which is a different failure mode than the silent-drop bug being closed here.
"""

import logging
from importlib.metadata import version
from typing import Any

import pytest
from mcp import types
from mcp.client import Client
from mcp.server.mcpserver import Context
from packaging.version import Version

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
    assert "[VALIDATION_FAILED]" in _text(result)
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
    assert "VALIDATION_FAILED" not in _text(result)
    assert "Unknown tool" in _text(result)


async def test_unknown_tool_name_is_still_logged_as_a_structured_dispatch_failure(
    strict_mcp: StrictMCPServer, caplog: pytest.LogCaptureFixture
) -> None:
    """Regression (Codex review round 15): a genuinely unknown/misspelled/
    stale tool name reached the SDK's own "Unknown tool" ToolError (whose
    __cause__ is never a pydantic.ValidationError) with no structured log
    entry at all -- the documented one-line-per-tool-call contract silently
    didn't cover this dispatch failure, leaving misspelled or stale tool
    names invisible to OPENPROJECT_LOG_FORMAT=json monitoring. The client-
    facing error itself is unchanged (still the SDK's own "Unknown tool"
    message, not [VALIDATION_FAILED] -- see the test above)."""
    import logging

    with caplog.at_level(logging.WARNING, logger="openproject_ce_mcp.strict_mcpserver"):
        result = await _dispatch(strict_mcp, "does_not_exist", {"anything": 1})

    assert result.is_error is True
    assert "VALIDATION_FAILED" not in _text(result)
    structured = [r.structured for r in caplog.records if hasattr(r, "structured")]
    assert len(structured) == 1
    assert structured[0]["tool"] == "does_not_exist"
    assert structured[0]["error_code"] == "TOOL_NOT_FOUND"


async def test_missing_required_argument_is_sanitized_and_logged(
    strict_mcp: StrictMCPServer, caplog: pytest.LogCaptureFixture
) -> None:
    """Regression: a MISSING required argument has no unknown key for the
    class docstring's explicit check to catch -- it reaches the SDK's own
    pydantic argument-model validation inside `super().call_tool()`, which
    used to surface as an uncoded `ToolError("Error executing tool ...")`
    (no [VALIDATION_FAILED] prefix, raw pydantic error text including a
    docs.pydantic.dev URL) with no structured log entry at all, since this
    dispatch-level failure point is upstream of `_categorize_tool_errors`
    (which only runs inside a tool's own handler body)."""
    import logging

    with caplog.at_level(logging.WARNING, logger="openproject_ce_mcp.strict_mcpserver"):
        result = await _dispatch(strict_mcp, "plain_tool", {})
    assert result.is_error is True
    text = _text(result)
    assert "[VALIDATION_FAILED]" in text
    assert "pydantic.dev" not in text
    structured = [r.structured for r in caplog.records if hasattr(r, "structured")]
    assert len(structured) == 1
    assert structured[0]["tool"] == "plain_tool"
    assert structured[0]["status"] == "error"
    assert structured[0]["error_code"] == "VALIDATION_FAILED"


async def test_wrong_typed_argument_is_sanitized_and_logged(
    strict_mcp: StrictMCPServer, caplog: pytest.LogCaptureFixture
) -> None:
    """Same dispatch-level gap as the missing-argument case above, but for a
    present argument with the wrong type (int where a str is required) --
    the offending value itself must never appear in the sanitized message,
    since it could carry caller-supplied data."""
    import logging

    with caplog.at_level(logging.WARNING, logger="openproject_ce_mcp.strict_mcpserver"):
        result = await _dispatch(strict_mcp, "plain_tool", {"name": 12345})
    assert result.is_error is True
    text = _text(result)
    assert "[VALIDATION_FAILED]" in text
    assert "12345" not in text
    structured = [r.structured for r in caplog.records if hasattr(r, "structured")]
    assert len(structured) == 1
    assert structured[0]["error_code"] == "VALIDATION_FAILED"


async def test_unknown_argument_dispatch_failure_is_also_logged(
    strict_mcp: StrictMCPServer, caplog: pytest.LogCaptureFixture
) -> None:
    """The pre-existing unknown-argument rejection path (class docstring's
    original bug fix) previously produced a correctly-coded error message
    but, like the pydantic-validation cases above, emitted no structured
    log entry at all."""
    import logging

    with caplog.at_level(logging.WARNING, logger="openproject_ce_mcp.strict_mcpserver"):
        await _dispatch(strict_mcp, "plain_tool", {"name": "World", "filters": ["x"]})
    structured = [r.structured for r in caplog.records if hasattr(r, "structured")]
    assert len(structured) == 1
    assert structured[0]["tool"] == "plain_tool"
    assert structured[0]["error_code"] == "VALIDATION_FAILED"


async def test_dispatch_validation_log_does_not_leak_a_prior_calls_counters(
    strict_mcp: StrictMCPServer, caplog: pytest.LogCaptureFixture
) -> None:
    """Regression (Opus review): an unknown-argument rejection never reaches
    tools_runtime.py's per-tool wrapper (the tool handler is never invoked),
    so that wrapper's own http_request_counter.reset()/policy_observation.reset()
    never runs for this call. Without call_tool's own reset, a validation
    failure right after a call that left the counters non-empty/non-None
    would misattribute that PRIOR call's http_requests/project_scope/
    policy_decision to this one. Currently masked by the real MCP SDK's
    per-request task isolation (each dispatch gets a fresh ContextVar
    context copy) -- this test drives both calls through the SAME task
    (matching this file's own _dispatch helper, which calls the handler
    directly rather than through the SDK's request-dispatch loop) to prove
    the reset is genuinely local to call_tool, not borrowed from that
    isolation."""
    import logging

    from openproject_ce_mcp import http_request_counter, policy_observation

    http_request_counter.increment()
    http_request_counter.increment()
    policy_observation.record_project_scope("OPM")
    policy_observation.record_policy_decision("work_package_write_allowed")

    with caplog.at_level(logging.WARNING, logger="openproject_ce_mcp.strict_mcpserver"):
        await _dispatch(strict_mcp, "plain_tool", {"name": "World", "filters": ["x"]})

    structured = [r.structured for r in caplog.records if hasattr(r, "structured")]
    assert len(structured) == 1
    assert structured[0]["http_requests"] == 0
    assert structured[0]["project_scope"] is None
    assert structured[0]["policy_decision"] is None


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


@pytest.mark.parametrize("mode", ["legacy", "auto"])
async def test_unknown_argument_rejected_over_a_real_client_server_roundtrip(
    strict_mcp: StrictMCPServer, mode: str
) -> None:
    """Complements the direct-dispatch tests above (which reach into SDK-internal
    handler registries) with the SDK's own client: real serialization, real
    request loop. Catches SDK changes to serialization/dispatch/middleware the
    direct-dispatch tests cannot see. "legacy" is the initialize handshake
    today's stdio clients use, "auto" the SDK's newer per-request path."""
    async with Client(strict_mcp, mode=mode) as client:
        result = await client.call_tool("plain_tool", {"name": "World", "filters": ["x"]})
        assert result.is_error is True
        assert "[VALIDATION_FAILED]" in _text(result)

        valid_result = await client.call_tool("plain_tool", {"name": "World"})
        assert valid_result.is_error is not True
        assert "hello, World" in _text(valid_result)


@pytest.mark.skipif(Version(version("mcp")) < Version("2.1"), reason="mcp 2.0 logs no tool failures")
async def test_unknown_argument_is_logged_as_a_caller_mistake_not_a_crash(
    strict_mcp: StrictMCPServer, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="mcp.server.mcpserver"):
        await _dispatch(strict_mcp, "plain_tool", {"name": "World", "filters": ["x"]})

    failures = [record for record in caplog.records if "plain_tool" in record.getMessage()]
    assert [(record.levelno, record.exc_info) for record in failures] == [(logging.INFO, None)]


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
    assert "[VALIDATION_FAILED]" in _text(result)
    assert "filters" in _text(result)


async def test_list_versions_rejects_unknown_page_argument() -> None:
    mcp = create_app(make_settings())
    result = await _dispatch(mcp, "list_versions", {"project": "ENC", "page": 3})
    assert result.is_error is True
    assert "[VALIDATION_FAILED]" in _text(result)
    assert "page" in _text(result)


async def test_search_work_packages_rejects_legacy_query_argument() -> None:
    """v0.4.0 renamed the free-text parameter to `search`; a caller still using
    the v0.3.6 name `query` must now be rejected loudly instead of silently
    running an unfiltered/defaulted search."""
    mcp = create_app(make_settings())
    result = await _dispatch(mcp, "search_work_packages", {"query": "0.1.0"})
    assert result.is_error is True
    assert "[VALIDATION_FAILED]" in _text(result)
    assert "query" in _text(result)


async def test_verify_strict_dispatch_passes_on_live_app() -> None:
    """The startup self-test itself must succeed against the real app, and must
    not leave its disposable probe tool registered afterwards."""
    mcp = create_app(make_settings())
    await verify_strict_dispatch(mcp)
    assert "__strict_mcpserver_probe__" not in {t.name for t in mcp._tool_manager.list_tools()}


async def test_verify_strict_dispatch_does_not_emit_a_warning_log(caplog: pytest.LogCaptureFixture) -> None:
    """Regression (Codex review round 11): verify_strict_dispatch's own
    internal self-test deliberately triggers the exact same
    [VALIDATION_FAILED] rejection path a real caller's bad request would --
    without this suppression, every healthy server startup and doctor
    handshake would emit a structured WARNING log record that looks
    identical to a genuine tool-call failure, misleading anything watching
    this log stream (monitoring, alerting) into treating a normal startup
    as an error."""
    import logging

    mcp = create_app(make_settings())
    with caplog.at_level(logging.WARNING, logger="openproject_ce_mcp.strict_mcpserver"):
        await verify_strict_dispatch(mcp)

    assert caplog.records == []


async def test_a_real_callers_validation_failure_is_still_logged_after_the_suppression(
    strict_mcp: StrictMCPServer, caplog: pytest.LogCaptureFixture
) -> None:
    """The suppression above is scoped to the internal probe tool's exact
    name only -- it must not accidentally silence logging for a genuine,
    caller-triggered VALIDATION_FAILED on any other tool."""
    import logging

    with caplog.at_level(logging.WARNING, logger="openproject_ce_mcp.strict_mcpserver"):
        await _dispatch(strict_mcp, "plain_tool", {"name": "World", "filters": ["x"]})

    structured = [r.structured for r in caplog.records if hasattr(r, "structured")]
    assert len(structured) == 1
    assert structured[0]["tool"] == "plain_tool"


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
            # [VALIDATION_FAILED] marker" check for a different reason than
            # this test intends. Keep the signature exact so a real dispatch-
            # bypass regression (not a signature typo) is what's asserted.
            return await super(StrictMCPServer, self).call_tool(name, arguments, context)

    mcp = _AlwaysPermissiveMCP("broken")
    with pytest.raises(RuntimeError, match="StrictMCPServer self-test failed"):
        await verify_strict_dispatch(mcp)
