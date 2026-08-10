from __future__ import annotations

import logging
from typing import Any, Sequence

from mcp import types
from mcp.server.fastmcp import FastMCP
from mcp.types import ContentBlock

logger = logging.getLogger(__name__)


class StrictFastMCP(FastMCP):
    """FastMCP with fail-closed argument validation.

    FastMCP's auto-generated per-tool Pydantic argument models inherit
    ``ArgModelBase``, which sets no ``extra=`` and therefore defaults to
    pydantic's ``extra="ignore"``. An unknown or misnamed keyword argument
    (e.g. ``filters=`` on a tool that only accepts ``version=``) is silently
    dropped before validation ever runs, and the tool executes with defaults
    for the arguments the caller actually meant to set — with no error
    surfaced anywhere. This subclass intercepts the raw arguments dict before
    that drop happens and rejects unknown top-level keys explicitly.

    Must be instantiated in place of ``FastMCP`` — not swapped in afterwards.
    ``FastMCP.__init__`` binds ``self.call_tool`` once into the low-level
    server's request handler via ``_setup_handlers()``; that binding captures
    whichever class ``self`` belongs to at construction time, so mutating
    ``__class__`` on an already-constructed instance would not change which
    ``call_tool`` implementation actually runs.
    """

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> Sequence[ContentBlock] | dict[str, Any]:
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
        return await super().call_tool(name, arguments)

    def add_tool(self, fn: Any, **kwargs: Any) -> None:
        """As FastMCP.add_tool, plus a top-level `additionalProperties: false`
        on the generated schema.

        This is documentation for well-behaved clients that validate against
        the advertised schema before sending — it is not itself enforcement.
        FastMCP wires its low-level handler with `validate_input=False`, so
        `jsonschema.validate` never runs against this schema for FastMCP
        tools regardless; `call_tool` above remains the only real gate.
        Non-recursive: nested `dict[str, Any]`-typed parameters (e.g.
        `custom_fields`, `filters` payloads) keep their own, independently
        generated `additionalProperties`, untouched by this.
        """
        super().add_tool(fn, **kwargs)
        name = kwargs.get("name") or fn.__name__
        tool = self._tool_manager.get_tool(name)
        if tool is not None:
            tool.parameters["additionalProperties"] = False


async def verify_strict_dispatch(mcp: StrictFastMCP) -> None:
    """Assert that unknown-argument rejection actually reaches this instance's
    dispatch path, not just its Python method-resolution order.

    ``StrictFastMCP.call_tool`` overriding ``FastMCP.call_tool`` is not, by
    itself, proof that the low-level server's ``CallToolRequest`` handler
    calls it — see the class docstring on why a stale bound-method capture is
    possible. This registers a disposable probe tool and drives one call
    through the real low-level handler (the same path a connected client
    uses), so a future `mcp` SDK upgrade that changes handler wiring fails
    loudly at startup instead of silently reintroducing the bug this class
    exists to close.
    """
    probe_name = "__strict_fastmcp_probe__"

    @mcp.tool(name=probe_name)
    async def _probe(known: str = "x") -> str:  # pragma: no cover - never runs
        return known

    try:
        request = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(
                name=probe_name, arguments={"known": "x", "__unknown__": "x"}
            ),
        )
        handler = mcp._mcp_server.request_handlers[types.CallToolRequest]
        result = await handler(request)
        is_error = getattr(result.root, "isError", False)
        text = "".join(
            getattr(block, "text", "")
            for block in getattr(result.root, "content", [])
        )
        if not is_error or "[validation_error]" not in text:
            raise RuntimeError(
                "StrictFastMCP self-test failed: an unknown tool argument was "
                "not rejected by the live dispatch path. The installed mcp "
                "SDK version likely changed how FastMCP.call_tool is wired "
                "into request handling; strict argument validation is "
                "currently NOT enforced. Refusing to start."
            )
    finally:
        mcp._tool_manager._tools.pop(probe_name, None)
