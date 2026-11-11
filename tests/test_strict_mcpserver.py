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
from mcp.server.mcpserver import Context, MCPServer
from packaging.version import Version
from pydantic import BaseModel, SecretStr, ValidationError

from openproject_ce_mcp.config import Settings
from openproject_ce_mcp.server import create_app
from openproject_ce_mcp.strict_mcpserver import StrictMCPServer, verify_strict_dispatch
from openproject_ce_mcp.tool_errors import ToolInputError


def make_settings(**overrides) -> Settings:
    defaults = {
        "base_url": "https://op.example.com",
        "api_token": SecretStr("token"),
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
    """Regression: a genuinely unknown/misspelled/
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
    """Regression: verify_strict_dispatch's own
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


# Tool arguments keep their own JSON type: lax coercion turned `confirm="yes"` into a confirmed
# write and `group_id=true` into group 1.


class _Item(BaseModel):
    value: int


@pytest.fixture
def typed_mcp() -> StrictMCPServer:
    mcp = StrictMCPServer("typed")
    mcp._test_calls = []  # type: ignore[attr-defined]

    @mcp.tool()
    async def typed(
        count: int = 1, ratio: float = 1.0, flag: bool = False, label: str | None = None, ids: list[int] | None = None
    ) -> str:
        mcp._test_calls.append((count, ratio, flag, label, ids))  # type: ignore[attr-defined]
        return "ran"

    @mcp.tool()
    async def bag(extra: dict[str, Any] | None = None) -> str:
        mcp._test_calls.append(extra)  # type: ignore[attr-defined]
        return "ran"

    @mcp.tool()
    async def modelled(item: _Item | None = None) -> str:
        mcp._test_calls.append(item)  # type: ignore[attr-defined]
        return "ran"

    return mcp


@pytest.mark.parametrize("extra", [{"a": float("nan")}, {"a": [1, {"b": float("inf")}]}])
async def test_a_non_finite_number_inside_an_untyped_container_is_rejected(
    typed_mcp: StrictMCPServer, extra: dict[str, Any]
) -> None:
    result = await _dispatch(typed_mcp, "bag", {"extra": extra})

    assert result.is_error is True
    assert "NaN or Infinity" in _text(result)
    assert typed_mcp._test_calls == []  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "extra",
    ['{"a": NaN}', '{"a": [Infinity]}', "[NaN]", '{"a": 1e999}', '{"a": [-1e999]}', '[{"b": 1E400}]', "[1e999]"],
)
async def test_a_non_finite_number_in_json_text_is_not_decoded_into_a_value(
    typed_mcp: StrictMCPServer, extra: str
) -> None:
    result = await _dispatch(typed_mcp, "bag", {"extra": extra})

    assert result.is_error is True
    assert typed_mcp._test_calls == []  # type: ignore[attr-defined]


async def test_a_json_text_object_is_decoded_for_a_model_argument(typed_mcp: StrictMCPServer) -> None:
    result = await _dispatch(typed_mcp, "modelled", {"item": '{"value": 3}'})

    assert result.is_error is False, _text(result)
    assert typed_mcp._test_calls == [_Item(value=3)]  # type: ignore[attr-defined]


async def test_a_mistyped_argument_error_carries_the_category_and_not_the_value(typed_mcp: StrictMCPServer) -> None:
    result = await _dispatch(typed_mcp, "typed", {"flag": "yes", "count": 7})

    text = _text(result)
    assert result.is_error is True
    assert text.startswith("[VALIDATION_FAILED] Invalid argument(s) for tool 'typed': flag: ")
    assert "yes" not in text


async def test_finite_numbers_inside_an_untyped_container_reach_the_tool(typed_mcp: StrictMCPServer) -> None:
    result = await _dispatch(typed_mcp, "bag", {"extra": {"a": 1.5, "b": [1, 2]}})

    assert result.is_error is False, _text(result)
    assert typed_mcp._test_calls == [{"a": 1.5, "b": [1, 2]}]  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "arguments",
    [
        {"count": True},
        {"count": "5"},
        {"count": 5.0},
        {"count": None},
        {"ratio": True},
        {"ratio": "1.5"},
        {"ratio": float("nan")},
        {"ratio": float("inf")},
        {"flag": "yes"},
        {"flag": "true"},
        {"flag": "false"},
        {"flag": 1},
        {"flag": 0},
        {"label": 5},
        {"ids": [True]},
        {"ids": ["5"]},
        {"ids": [5.0]},
        {"ids": "null"},
        {"ids": "[true]"},
    ],
    ids=lambda arguments: repr(arguments),
)
async def test_a_mistyped_argument_is_rejected_before_the_tool_runs(
    typed_mcp: StrictMCPServer, arguments: dict[str, Any]
) -> None:
    result = await _dispatch(typed_mcp, "typed", arguments)

    assert result.is_error is True
    assert next(iter(arguments)) in _text(result)
    assert typed_mcp._test_calls == []  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "arguments, expected",
    [
        ({"count": 5}, (5, 1.0, False, None, None)),
        ({"ratio": 2}, (1, 2, False, None, None)),
        ({"ratio": 2.5}, (1, 2.5, False, None, None)),
        ({"flag": True}, (1, 1.0, True, None, None)),
        ({"label": "null"}, (1, 1.0, False, "null", None)),
        ({"label": "5"}, (1, 1.0, False, "5", None)),
        ({"label": "[1, 2]"}, (1, 1.0, False, "[1, 2]", None)),
        ({"label": '{"a": 1}'}, (1, 1.0, False, '{"a": 1}', None)),
        ({"ids": [1, 2]}, (1, 1.0, False, None, [1, 2])),
        ({"ids": "[1, 2]"}, (1, 1.0, False, None, [1, 2])),
    ],
    ids=lambda value: repr(value),
)
async def test_a_correctly_typed_argument_reaches_the_tool_unchanged(
    typed_mcp: StrictMCPServer, arguments: dict[str, Any], expected: tuple[Any, ...]
) -> None:
    result = await _dispatch(typed_mcp, "typed", arguments)

    assert result.is_error is False, _text(result)
    assert typed_mcp._test_calls == [expected]  # type: ignore[attr-defined]


async def test_json_text_is_decoded_only_for_a_list_or_object_argument(typed_mcp: StrictMCPServer) -> None:
    """A client that sends the list `[1, 2]` as text still works; the text `null` for a string
    argument stays the string "null" and is not turned into a missing value."""
    result = await _dispatch(typed_mcp, "typed", {"ids": "[1, 2]", "label": "null"})

    assert result.is_error is False, _text(result)
    assert typed_mcp._test_calls == [(1, 1.0, False, "null", [1, 2])]  # type: ignore[attr-defined]


def test_the_strict_metadata_keeps_everything_else_the_sdk_built(typed_mcp: StrictMCPServer) -> None:
    tool = typed_mcp._tool_manager.get_tool("typed")
    fresh = StrictMCPServer("plain")

    async def typed_plain(count: int = 1) -> str:
        return "ran"

    MCPServer.add_tool(fresh, typed_plain, name="typed_plain")
    reference = fresh._tool_manager.get_tool("typed_plain")

    assert tool.fn_metadata.output_schema is not None
    assert tool.fn_metadata.output_schema["properties"] == reference.fn_metadata.output_schema["properties"]
    assert tool.fn_metadata.wrap_output == reference.fn_metadata.wrap_output


async def test_verify_strict_dispatch_raises_if_the_typed_rejection_does_not_name_the_argument() -> None:
    class _VagueRejection(StrictMCPServer):
        async def call_tool(self, name, arguments, context=None):  # type: ignore[override]
            if arguments == {"flag": "true"}:
                raise ToolInputError("[VALIDATION_FAILED] something is wrong")
            return await super().call_tool(name, arguments, context)

    with pytest.raises(RuntimeError, match='the string "true" was accepted'):
        await verify_strict_dispatch(_VagueRejection("vague"))


async def test_verify_strict_dispatch_raises_if_argument_types_are_not_enforced(monkeypatch) -> None:
    monkeypatch.setattr(StrictMCPServer, "_make_arguments_strict", staticmethod(lambda tool: None))

    with pytest.raises(RuntimeError, match='the string "true" was accepted'):
        await verify_strict_dispatch(StrictMCPServer("lax"))


_VALID_SAMPLE = {"integer": 1, "number": 1.0, "boolean": True, "string": "x", "array": [], "object": {}}


def _schema_types(schema: dict[str, Any]) -> set[str]:
    types_ = {schema["type"]} if "type" in schema else set()
    for option in (*schema.get("anyOf", []), *schema.get("oneOf", [])):
        types_ |= _schema_types(option)
    return types_ - {"null"}


def _valid_value(schema: dict[str, Any]) -> Any:
    return _VALID_SAMPLE[sorted(_schema_types(schema))[0]]


def _wrong_values(types_: set[str]) -> list[Any]:
    """Values of a JSON type the schema does not admit, or that a lax parser would coerce to one it does."""
    wrong: list[Any] = []
    if "integer" in types_:
        wrong += [True, 5.0] + ([] if "string" in types_ else ["5"])
    if "number" in types_ and "integer" not in types_:
        wrong += [True, float("nan")] + ([] if "string" in types_ else ["1.5"])
    if "boolean" in types_:
        wrong += [] if "string" in types_ else [1, "yes", "true"]
    if types_ == {"string"}:
        wrong += [5, True]
    return wrong


def _catalog_tools() -> list[Any]:
    # Project-bound write tools are registered only when a write scope exists.
    settings = make_settings(write_projects=("*",), **dict.fromkeys(_ALL_ENABLE_FLAGS, True))
    tools = list(create_app(settings)._tool_manager.list_tools())
    names = {tool.name for tool in tools}
    assert {"delete_work_package", "bulk_create_work_packages", "create_membership", "delete_group"} <= names
    return tools


# Every group the catalog can enable; the default settings leave the optional groups out.
_ALL_ENABLE_FLAGS = [field for field in Settings.__dataclass_fields__ if field.startswith("enable_")]


def test_every_tool_of_the_catalog_validates_its_arguments_strictly() -> None:
    tools = _catalog_tools()
    assert len(tools) > 180

    not_strict = [
        tool.name
        for tool in tools
        if tool.fn_metadata.arg_model.model_config.get("strict") is not True
        or tool.fn_metadata.arg_model.model_config.get("allow_inf_nan") is not False
        or tool.fn_metadata.arg_model.model_config.get("validate_default") is not True
    ]

    assert not_strict == []


def test_every_scalar_argument_of_the_catalog_rejects_a_wrong_type_and_accepts_a_right_one() -> None:
    checked = 0
    for tool in _catalog_tools():
        properties = tool.parameters.get("properties", {})
        required = {
            key: _valid_value(schema)
            for key, schema in properties.items()
            if key in tool.parameters.get("required", [])
        }
        model = tool.fn_metadata.arg_model
        model.model_validate(required)
        for key, schema in properties.items():
            scalar = _schema_types(schema)
            if scalar and not scalar & {"array", "object"}:
                # the positive control per argument: a value of its own type passes
                model.model_validate({**required, key: _valid_value(schema)})
                cases = [(key, wrong) for wrong in _wrong_values(scalar)]
            elif scalar == {"array"} and schema.get("items") and "$ref" not in schema["items"]:
                item_types = _schema_types(schema["items"])
                model.model_validate({**required, key: [_valid_value(schema["items"])]})
                cases = [(key, [wrong]) for wrong in _wrong_values(item_types)]
            else:
                continue
            for name, wrong in cases:
                with pytest.raises(ValidationError) as error:
                    model.model_validate({**required, name: wrong})
                assert any(err["loc"][0] == name for err in error.value.errors()), (tool.name, name, wrong)
                checked += 1
    assert checked > 1000


def test_every_key_of_a_structured_item_rejects_a_wrong_type_and_an_unknown_key() -> None:
    """The items of a bulk tool are objects with a schema of their own; each of their keys is checked
    like a top-level argument, and a key the schema does not list is refused."""
    checked = 0
    for tool in _catalog_tools():
        defs = tool.parameters.get("$defs", {})
        required = {
            key: _valid_value(schema)
            for key, schema in tool.parameters.get("properties", {}).items()
            if key in tool.parameters.get("required", [])
        }
        model = tool.fn_metadata.arg_model
        for key, schema in tool.parameters.get("properties", {}).items():
            reference = schema.get("items", {}).get("$ref") if schema.get("type") == "array" else None
            if reference is None:
                continue
            item_schema = defs[reference.rsplit("/", 1)[-1]]
            properties = item_schema["properties"]
            valid_item = {
                name: _valid_value(prop) for name, prop in properties.items() if name in item_schema.get("required", [])
            }
            model.model_validate({**required, key: [valid_item]})
            with pytest.raises(ValidationError) as unknown:
                model.model_validate({**required, key: [{**valid_item, "no_such_key": 1}]})
            assert unknown.value.errors()[0]["type"] == "extra_forbidden", (tool.name, key)
            for name, prop in properties.items():
                types_ = _schema_types(prop)
                if not types_ or types_ & {"array", "object"}:
                    continue
                model.model_validate({**required, key: [{**valid_item, name: _valid_value(prop)}]})
                for wrong in _wrong_values(types_):
                    with pytest.raises(ValidationError) as error:
                        model.model_validate({**required, key: [{**valid_item, name: wrong}]})
                    assert any(err["loc"][:3] == (key, 0, name) for err in error.value.errors()), (tool.name, name)
                    checked += 1
    assert checked > 40


# Parameters whose value is an object with no fixed set of keys. Their values are checked by the tool body
# (`_validate_custom_field_value`, `_validate_custom_field_filters`), because the type of a value depends on the
# custom field it names; a structured item is a typed schema instead (test above).
FREE_FORM_OBJECT_PARAMETERS = {
    ("list_work_packages", "custom_field_filters"),
    ("search_work_packages", "custom_field_filters"),
    ("create_work_package", "custom_fields"),
    ("create_subtask", "custom_fields"),
    ("update_work_package", "custom_fields"),
    ("list_projects", "custom_field_filters"),
    ("create_project", "custom_fields"),
    ("copy_project", "custom_fields"),
    ("update_project", "custom_fields"),
}


def test_every_object_parameter_is_a_typed_item_or_a_reviewed_free_form_one() -> None:
    free_form = {
        (tool.name, key)
        for tool in _catalog_tools()
        for key, schema in tool.parameters.get("properties", {}).items()
        if "object" in _schema_types(schema)
    }

    assert free_form == FREE_FORM_OBJECT_PARAMETERS, "a new object parameter needs a typed schema, or a review here"
