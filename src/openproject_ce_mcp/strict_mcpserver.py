from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from mcp import types
from mcp.server.mcpserver import MCPServer
from mcp.types import Icon, ToolAnnotations

logger = logging.getLogger(__name__)


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
        tool = self._tool_manager.get_tool(name)
        if tool is not None:
            allowed = set(tool.parameters.get("properties", {}).keys())
            unknown = sorted(set(arguments.keys()) - allowed)
            if unknown:
                raise ValueError(
                    f"[validation_error] Unknown argument(s) for tool "
                    f"'{name}': {', '.join(unknown)}. "
                    f"Allowed arguments: {', '.join(sorted(allowed))}"
                )
        return await super().call_tool(name, arguments, context)

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
    roundtrip via ``mcp.shared.memory.create_client_server_memory_streams``
    to catch SDK changes to serialization/dispatch/middleware this direct
    call cannot see.
    """
    probe_name = "__strict_mcpserver_probe__"

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
        if not is_error or "[validation_error]" not in text:
            raise RuntimeError(
                "StrictMCPServer self-test failed: an unknown tool argument was not "
                "rejected by the live dispatch path. The installed mcp SDK version "
                "likely changed how MCPServer.call_tool is wired into request "
                "handling; strict argument validation is currently NOT enforced. "
                "Refusing to start."
            )
    finally:
        mcp.remove_tool(probe_name)
