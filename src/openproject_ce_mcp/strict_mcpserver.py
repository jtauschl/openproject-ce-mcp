from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import pydantic
from mcp import types
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import Icon, ToolAnnotations

from . import http_request_counter, policy_observation
from .logging_support import ToolCallLogRecord
from .tool_errors import ToolInputError

logger = logging.getLogger(__name__)

# verify_strict_dispatch's self-test tool name, hoisted to module level so
# call_tool below can recognize and skip logging it -- see the log-suppression
# comment at that call site for why.
_STRICT_DISPATCH_PROBE_NAME = "__strict_mcpserver_probe__"


class StrictMCPServer(MCPServer):
    """MCPServer with fail-closed argument validation.

    MCPServer's auto-generated per-tool Pydantic argument models inherit
    ``ArgModelBase``, which sets no ``extra=`` and therefore defaults to
    pydantic's ``extra="ignore"``. An unknown or misnamed keyword argument
    (e.g. ``filters=`` on a tool that only accepts ``version=``) is silently
    dropped before validation ever runs, and the tool executes with defaults
    for the arguments the caller actually meant to set — with no error
    surfaced anywhere. This subclass intercepts the raw arguments dict before
    that drop happens and rejects unknown top-level keys explicitly.

    Instantiate in place of ``MCPServer`` as a matter of discipline, not
    because the SDK strictly requires it under the current (late-bound-
    through-``self``) dispatch wiring: ``MCPServer.__init__`` passes
    ``on_call_tool=self._handle_call_tool`` to the low-level server, and
    ``_handle_call_tool`` calls ``self.call_tool(...)`` at request time, so
    the override is reached regardless of when ``__class__`` was set.
    ``verify_strict_dispatch()`` is what actually guards against a future
    SDK change silently breaking this override, not this docstring.
    """

    async def call_tool(
        self, name: str, arguments: dict[str, Any], context: Any | None = None
    ) -> types.CallToolResult | types.InputRequiredResult:
        """Two distinct schema-validation failure points share one
        [VALIDATION_FAILED]-coded, structured-logged outcome here, since
        neither ever reaches `_categorize_tool_errors` (that wrapper only
        runs INSIDE a tool's own handler body, once dispatch has already
        succeeded):

        1. An unknown top-level argument key -- caught explicitly below,
           before pydantic ever sees it (see class docstring).
        2. A MISSING required argument, or one with the WRONG TYPE -- these
           have no unknown key to catch; they reach `super().call_tool()`
           and fail inside the SDK's own pydantic argument-model validation,
           which the SDK wraps in a generic `ToolError("Error executing
           tool ...")` with no `[VALIDATION_FAILED]` prefix and no
           structured log entry. Unwrapped here via `ToolError.__cause__`
           (a real `pydantic.ValidationError`) into the same coded,
           structured-logged form as case 1 -- using `.errors()`'s field
           path and error type only, never `error["input"]` (the offending
           value itself), which could carry caller-supplied data (a token,
           a work-package body fragment) that must never reach a raw,
           unsanitized error message.
        """
        # Reset here, not only inside tools_runtime.py's per-tool wrapper: an
        # unknown-argument rejection below never reaches that wrapper at all
        # (the tool handler is never invoked), so without this the dispatch
        # log would attribute a PRIOR, unrelated call's leftover
        # http_requests/project_scope/policy_decision to this validation
        # failure. Currently masked by the SDK's own per-request task
        # isolation (each dispatch gets a fresh copy of the ContextVar
        # context, see context_gather.py's docstring for the general
        # mechanism), but that isolation is an SDK implementation detail
        # this module doesn't control -- resetting explicitly here makes the
        # correctness local instead of borrowed from it.
        http_request_counter.reset()
        policy_observation.reset()
        start = time.monotonic()
        # Context.request_id is a property that raises ValueError (not
        # AttributeError) when the Context wraps no real request_context
        # (e.g. a test driving dispatch directly without the SDK's normal
        # request-handling machinery around it) -- plain getattr() does not
        # catch that, so a broken request_id lookup would otherwise mask
        # the real [VALIDATION_FAILED] error entirely, same class of bug as
        # tools_runtime.py's own _emit_tool_call_log exception-safety fix.
        try:
            request_id = context.request_id if context is not None else None
        except Exception:
            request_id = None
        tool = self._tool_manager.get_tool(name)
        if tool is None:
            # A genuinely unknown/misspelled/stale tool name -- the SDK's
            # own "Unknown tool" ToolError below (raised inside
            # super().call_tool()) is left as the actual error surfaced to
            # the caller, unchanged; this only ensures the documented
            # one-line-per-tool-call structured-logging contract still
            # covers this dispatch failure too, the same as every other
            # coded error path in this method already does.
            self._emit_dispatch_error_log(name, start, request_id, error_code="TOOL_NOT_FOUND", layer="dispatch")
        else:
            allowed = set(tool.parameters.get("properties", {}).keys())
            unknown = sorted(set(arguments.keys()) - allowed)
            if unknown:
                message = (
                    f"[VALIDATION_FAILED] Unknown argument(s) for tool "
                    f"'{name}': {', '.join(unknown)}. "
                    f"Allowed arguments: {', '.join(sorted(allowed))}"
                )
                self._emit_dispatch_error_log(name, start, request_id)
                raise ToolInputError(message)
        try:
            return await super().call_tool(name, arguments, context)
        except ToolError as exc:
            if isinstance(exc.__cause__, pydantic.ValidationError):
                self._emit_dispatch_error_log(name, start, request_id)
                field_errors = "; ".join(
                    f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.__cause__.errors()
                )
                raise ToolInputError(
                    f"[VALIDATION_FAILED] Invalid argument(s) for tool '{name}': {field_errors}"
                ) from exc
            raise

    @staticmethod
    def _emit_dispatch_error_log(
        tool: str, start: float, request_id: Any, *, error_code: str = "VALIDATION_FAILED", layer: str = "validation"
    ) -> None:
        # verify_strict_dispatch() deliberately calls this exact tool name
        # with an unknown argument on EVERY server startup and doctor
        # handshake, to prove the validation gate above is actually wired
        # in -- that self-test rejection is expected, internal, and never
        # caller-triggered, so logging it as a WARNING-level structured
        # tool_call record on every healthy launch would misrepresent
        # ordinary startup as a tool failure to any monitoring watching this
        # log stream. Suppressed by name, not by silencing this method
        # entirely, so a genuine caller-triggered error for any other tool
        # (or tool name) is still logged exactly as before.
        if tool == _STRICT_DISPATCH_PROBE_NAME:
            return
        try:
            record: ToolCallLogRecord = {
                "tool": tool,
                "status": "error",
                "duration_ms": int((time.monotonic() - start) * 1000),
                "error_code": error_code,
                "layer": layer,
                "http_requests": http_request_counter.current(),
                "project_scope": policy_observation.current_project_scope(),
                "policy_decision": policy_observation.current_policy_decision(),
                "request_id": str(request_id) if request_id is not None else None,
            }
            logger.warning("tool_call", extra={"structured": record})
        except Exception:
            logger.exception("Failed to emit structured tool-call log for %s", tool)

    def add_tool(
        self,
        fn: Callable[..., Any],
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        annotations: ToolAnnotations | None = None,
        icons: list[Icon] | None = None,
        meta: dict[str, Any] | None = None,
        structured_output: bool | None = None,
    ) -> None:
        """As MCPServer.add_tool, plus a top-level `additionalProperties: false`
        on the generated schema.

        This is documentation for well-behaved clients that validate against
        the advertised schema before sending — it is not itself enforcement.
        The SDK advertises this schema but never validates a call against it
        before handler execution regardless; `call_tool` above remains the
        only real gate. Non-recursive: nested `dict[str, Any]`-typed
        parameters (e.g. `custom_fields`, `filters` payloads) keep their own,
        independently generated `additionalProperties`, untouched by this.
        """
        super().add_tool(
            fn,
            name=name,
            title=title,
            description=description,
            annotations=annotations,
            icons=icons,
            meta=meta,
            structured_output=structured_output,
        )
        tool_name = name or fn.__name__
        tool = self._tool_manager.get_tool(tool_name)
        if tool is not None:
            tool.parameters["additionalProperties"] = False


async def verify_strict_dispatch(mcp: StrictMCPServer) -> None:
    """Assert that unknown-argument rejection actually reaches this instance's
    dispatch path, not just its Python method-resolution order.

    Uses the low-level server's internal handler registry
    (``_lowlevel_server.get_request_handler``) rather than a full
    client-server roundtrip — SDK-internal and version-sensitive by
    necessity (there is no more public API for driving a request through the
    dispatch path directly), but appropriate for a startup check that must
    run fast and deterministically on every launch. A separate test
    (test_strict_mcpserver.py) additionally exercises the real client-server
    roundtrip via the SDK's ``mcp.client.Client`` to catch SDK changes to
    serialization/dispatch/middleware this direct call cannot see.
    """
    probe_name = _STRICT_DISPATCH_PROBE_NAME

    @mcp.tool(name=probe_name)
    async def _probe(known: str = "x") -> str:  # pragma: no cover - never runs
        return known

    try:
        params = types.CallToolRequestParams(name=probe_name, arguments={"known": "x", "__unknown__": "x"})
        entry = mcp._lowlevel_server.get_request_handler("tools/call")
        if entry is None:
            raise RuntimeError(
                "StrictMCPServer self-test failed: no 'tools/call' request handler is "
                "registered on the low-level server at all. The installed mcp SDK "
                "version likely changed how MCPServer registers its handlers with "
                "mcp.server.lowlevel.Server; strict argument validation cannot be "
                "verified. Refusing to start."
            )
        # The handler's declared type requires a real ServerRequestContext, but
        # for a plain tools/call dispatch it's only used to construct the
        # injected Context object, never dereferenced otherwise -- verified
        # at runtime that None works here. mypy can't see that leniency.
        result = await entry.handler(None, params)  # type: ignore[arg-type]
        is_error = getattr(result, "is_error", False)
        text = "".join(getattr(block, "text", "") for block in getattr(result, "content", []))
        if not is_error or "[VALIDATION_FAILED]" not in text:
            raise RuntimeError(
                "StrictMCPServer self-test failed: an unknown tool argument was not "
                "rejected by the live dispatch path. The installed mcp SDK version "
                "likely changed how MCPServer.call_tool is wired into request "
                "handling; strict argument validation is currently NOT enforced. "
                "Refusing to start."
            )
    finally:
        mcp.remove_tool(probe_name)
