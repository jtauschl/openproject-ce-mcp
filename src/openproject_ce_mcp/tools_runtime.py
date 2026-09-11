"""Tool-registration, dispatch, error-translation, and trimming mechanics.

This module is the shared kernel every domain's tool functions (each living
in its own per-domain `tools_<domain>.py` file; `tools.py` itself holds no
tool functions, only registration/classification infrastructure) depend on:
the `@register_tool` decorator + registry, `register_selected_tools()` (the
mechanical half of registration), request-scoped MCP `Context` access, error
categorization, and the return-model/select-trimming machinery.

Strictly one-directional: this module never imports from `tools.py`, any
`tools_<domain>.py`, or `app/` -- it only imports from `.client`, `.models`,
`.presentation`, and stdlib/`mcp`. Which tools exist and which scope/policy
gates them is Catalog/Policy concern, owned by `tools.py`, not this module --
`register_selected_tools()` takes an already-decided iterable of tool names,
never `Settings` or the classification tables themselves.
"""

from __future__ import annotations

import functools
import inspect
import json
import re
from collections.abc import Callable, Iterable
from dataclasses import fields as dataclass_fields
from dataclasses import is_dataclass
from typing import Any, TypeVar, cast

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import TextContent

from .client import (
    AuthenticationError,
    InvalidInputError,
    NotFoundError,
    OpenProjectClient,
    OpenProjectError,
    OpenProjectServerError,
    PermissionDeniedError,
    TransportError,
)
from .presentation import ContentBundle, _to_payload

# Resolves every classified tool name (via @register_tool below) to its
# actual function object. Explicit registration, not module-namespace
# introspection, so this stays correct regardless of which module a tool
# function is defined in -- each function carries its own registration with
# it wherever it's defined.
_ToolFunc = TypeVar("_ToolFunc", bound=Callable[..., Any])
_TOOL_FUNCTIONS: dict[str, Callable[..., Any]] = {}


def register_tool(fn: _ToolFunc) -> _ToolFunc:
    name = fn.__name__
    if name in _TOOL_FUNCTIONS:
        raise RuntimeError(
            f"Duplicate tool registration: {name} ({fn.__module__}.{fn.__qualname__} "
            f"collides with an already-registered function of the same name)"
        )
    _TOOL_FUNCTIONS[name] = fn
    return fn


def register_selected_tools(mcp: MCPServer, *, names: Iterable[str], hide_active: bool) -> None:
    """Register exactly the given (already policy-selected) tool names with `mcp`.

    `names` is the caller's already-decided set of enabled tool names (the
    Catalog/Policy layer's job, not this module's) -- this function only
    resolves each name to its registered function and applies the
    error-categorization/trimming wrapping shared by every tool.

    Tools that return a list/write/bulk result are routed through _to_payload for
    context reduction: payload is dropped on confirmed writes,
    count/truncated on lists, and `select` trims rows. Those tools are registered
    with structured_output=False so the SDK does not build a fixed dataclass
    output schema — it serializes the trimmed dict we return verbatim, letting us
    omit keys. Detection is by the result model's fields, so no per-tool tagging
    is needed and it cannot drift. Tool bodies are unchanged; they still return
    their dataclass, which the wrapper trims.

    When `hide_active` is set (i.e. any hide-field config is active), every
    dataclass-returning tool is trimmed too, so single-entity reads (get_*) can
    drop hidden keys entirely rather than emit them as null. This only widens
    schema loss when the operator opted into hiding.
    """

    def tool(fn):
        wrapped = _categorize_tool_errors(fn)
        # Python 3.13 dedents function docstrings at compile time; older
        # supported interpreters preserve indentation after blank lines.
        # Normalize at the public registration boundary so one source exposes
        # one MCP description on every supported interpreter.
        description = wrapped.__doc__ or ""
        trailing_newline = "\n" if description.rstrip(" \t").endswith("\n") else ""
        wrapped.__doc__ = inspect.cleandoc(description) + trailing_newline

        if not (_returns_trimmable(fn) or (hide_active and _returns_dataclass(fn))):
            return mcp.tool()(wrapped)

        # Whether this tool's own signature accepts `select` -- NOT whether its
        # return model happens to carry a `results`/`items` field. Some list
        # tools (e.g. list_statuses) return a `results`-bearing model but have
        # no `select` parameter at all, so relying on the return type alone
        # would wrongly treat them as select-driven and keep eliding their
        # None fields with no way for a caller to ask for them back.
        elide_none = "select" in inspect.signature(fn).parameters

        @functools.wraps(wrapped)
        async def trimming(*args, **kwargs):
            select = _normalize_select(kwargs.get("select"))
            result = await wrapped(*args, **kwargs)
            if isinstance(result, ContentBundle):
                # The bundle's body is trimmed exactly like any other result
                # and emitted as the leading JSON block; only the extra
                # content blocks travel outside the seam, because JSON cannot
                # carry them (see presentation.ContentBundle).
                payload = _to_payload(result.body, select=select, elide_none=elide_none)
                return [
                    TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, default=str)),
                    *result.blocks,
                ]
            return _to_payload(result, select=select, elide_none=elide_none)

        return mcp.tool(structured_output=False)(trimming)

    # Materialize once: `names` is consumed twice below (the completeness
    # check, then the registration loop), which would silently register
    # nothing on the second pass if a caller ever passed a single-use
    # generator instead of a reusable sequence.
    names = tuple(names)

    missing = [name for name in names if name not in _TOOL_FUNCTIONS]
    if missing:
        raise RuntimeError(
            "The following tool names are classified for registration but never "
            "registered via @register_tool -- their defining module was likely "
            "never imported by the composition root: " + ", ".join(sorted(missing))
        )

    for name in names:
        tool(_TOOL_FUNCTIONS[name])


def _client_from_context(ctx: Context) -> OpenProjectClient:
    app_context = cast(Any, ctx.request_context.lifespan_context)
    return app_context.client


# Stable, machine-readable category prefixes so a calling agent can branch on the
# kind of failure rather than parsing free text. The prefix leads the message,
# which stays human-readable, e.g.
#   "[permission_denied] OpenProject work package write support is disabled. ..."
_ERROR_CATEGORY: dict[type[Exception], str] = {
    InvalidInputError: "validation_error",
    AuthenticationError: "auth_error",
    PermissionDeniedError: "permission_denied",
    NotFoundError: "not_found",
    TransportError: "transport_error",
    OpenProjectServerError: "server_error",
    OpenProjectError: "openproject_error",  # base fallback
}
_CATEGORY_PREFIX_RE = re.compile(r"^\[[a-z_]+\]\s")


def _prefix(category: str, message: str) -> str:
    if _CATEGORY_PREFIX_RE.match(message):
        return message  # already categorized; don't double-prefix
    return f"[{category}] {message}"


async def _run_tool(awaitable):
    try:
        return await awaitable
    except InvalidInputError as exc:
        # Validation failures surface as ValueError; everything else as RuntimeError.
        raise ValueError(_prefix("validation_error", str(exc))) from exc
    except OpenProjectError as exc:
        category = next(
            (cat for typ, cat in _ERROR_CATEGORY.items() if isinstance(exc, typ)),
            "openproject_error",
        )
        raise RuntimeError(_prefix(category, str(exc))) from exc


def _return_model(fn: Any) -> type | None:
    """Resolve a tool's return-annotation to its dataclass model, or None.

    ``from __future__ import annotations`` makes the return annotation a string,
    so we resolve it against ``fn``'s own defining module's namespace
    (``fn.__globals__``, not the caller's) -- this stays correct regardless of
    which ``tools_<domain>.py`` module defines the tool, since a tool function
    defined in any module still resolves against its own home rather than
    silently returning None.
    Callers must pass the actual tool function, not a wrapper around it --
    functools.wraps() copies __annotations__ but not __globals__, so a
    wrapper's __globals__ points at the wrapper's own defining module, not the
    original function's.
    """
    ann = fn.__annotations__.get("return")
    model = fn.__globals__.get(ann) if isinstance(ann, str) else ann
    return model if isinstance(model, type) and is_dataclass(model) else None


def _returns_dataclass(fn: Any) -> bool:
    """True if the tool returns a dataclass result (so it can be serialized/trimmed)."""
    return _return_model(fn) is not None


def _returns_trimmable(fn: Any) -> bool:
    """True if a tool returns a result the context-reduction seam should trim.

    A result is trimmable when its model carries a field the seam acts on:
    ``results`` (list results → count/truncated drop + select), ``payload`` (write
    results → payload drop on confirm), or ``items`` (bulk results, whose nested
    per-item write results carry their own payload to drop). Detection inspects the
    model's fields, so it cannot drift from suffix conventions (e.g.
    RelationUpdateResult, ProjectCopyResult carry payload but are not *WriteResult).

    Also trimmable when the tool's own signature accepts ``select`` directly,
    even if its return model has none of those three fields -- this is the
    bare single-entity case (e.g. get_work_package → WorkPackageDetail): the
    model itself has no results/items for select to act on, but
    _to_payload's top-level-select branch (see presentation.py) still needs
    the trimming wrapper to run at all in order to reach select in the first
    place.
    """
    if "select" in inspect.signature(fn).parameters:
        return True
    if _returns_content_bundle(fn):
        return True
    model = _return_model(fn)
    if model is None:
        return False
    names = {f.name for f in dataclass_fields(model)}
    return bool(names & {"results", "payload", "items"})


def _returns_content_bundle(fn: Any) -> bool:
    """True if the tool can return a ContentBundle (native MCP content blocks
    alongside a normal result).

    Checked against the raw annotation text rather than through
    ``_return_model``, because such a tool's annotation is typically a union
    (``AttachmentListResult | ContentBundle`` — the bundle only comes back
    when the caller asked for inlined content), which resolves to no single
    dataclass. The wrapper's own ``isinstance`` check is what actually decides
    per call; this only has to be right about whether the wrapper must run.
    """
    ann = fn.__annotations__.get("return")
    if isinstance(ann, str):
        return "ContentBundle" in ann
    return ann is ContentBundle


def _normalize_select(select: Any) -> frozenset[str] | None:
    """Turn a raw ``select`` kwarg into a field set for the trimming wrapper.

    Validation already happened in the tool body (tools_validation._validate_select);
    here we only normalize the shape. Returns None when no usable selection is present.
    """
    if not select:
        return None
    return frozenset(str(name).strip() for name in select if str(name).strip())


def _categorize_tool_errors(fn):
    """Wrap a tool so every failure carries a category prefix.

    _run_tool already prefixes errors from the client call, but input validators
    in the tool body raise plain ValueError *before* _run_tool runs. This wrapper
    catches those and tags them [validation_error] too, so an agent sees a
    consistent, machine-readable category for every tool failure.
    """

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except ValueError as exc:
            raise ValueError(_prefix("validation_error", str(exc))) from exc

    return wrapper
