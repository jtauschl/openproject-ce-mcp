"""Tool-registration, dispatch, error-translation, and trimming mechanics.

This module is the shared kernel every domain's tool functions (each living
in its own per-domain `tools_<domain>.py` file; `tools.py` itself holds no
tool functions, only registration/classification infrastructure) depend on:
the `@register_tool` decorator + registry, `register_selected_tools()` (the
mechanical half of registration), request-scoped MCP `Context` access, error
categorization, and the return-model/select-trimming machinery.

Strictly one-directional: this module never imports from `tools.py`, any
`tools_<domain>.py`, or `app/` -- it only imports from `.client`, `.models`,
`.presentation`, `.tool_errors`, `.http_request_counter`/`.policy_observation`/
`.logging_support` (OPM-2709's structured-logging plumbing, also
package-root modules, not `app/`), and stdlib/`mcp`. Which tools exist and
which scope/policy gates them is Catalog/Policy concern, owned by `tools.py`,
not this module -- `register_selected_tools()` takes an already-decided
iterable of tool names, never `Settings` or the classification tables
themselves.
"""

from __future__ import annotations

import functools
import inspect
import json
import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import fields as dataclass_fields
from dataclasses import is_dataclass
from typing import Any, Literal, TypeVar, cast

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import TextContent

from . import http_request_counter, policy_observation
from .client import (
    InvalidInputError,
    OpenProjectClient,
    OpenProjectError,
)
from .logging_support import ToolCallLogRecord
from .presentation import ContentBundle, _to_payload
from .tool_errors import ToolCallError, ToolInputError

LOGGER = logging.getLogger(__name__)

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
        # Python 3.13 dedents function docstrings at compile time; older
        # supported interpreters preserve indentation after blank lines.
        # Normalize at the public registration boundary so one source exposes
        # one MCP description on every supported interpreter.
        description = fn.__doc__ or ""
        trailing_newline = "\n" if description.rstrip(" \t").endswith("\n") else ""
        normalized_doc = inspect.cleandoc(description) + trailing_newline

        if not (_returns_trimmable(fn) or (hide_active and _returns_dataclass(fn))):
            wrapped = _categorize_tool_errors(fn)
            wrapped.__doc__ = normalized_doc
            return mcp.tool()(wrapped)

        # Whether this tool's own signature accepts `select` -- NOT whether its
        # return model happens to carry a `results`/`items` field. Some list
        # tools (e.g. list_statuses) return a `results`-bearing model but have
        # no `select` parameter at all, so relying on the return type alone
        # would wrongly treat them as select-driven and keep eliding their
        # None fields with no way for a caller to ask for them back.
        elide_none = "select" in inspect.signature(fn).parameters

        # _categorize_tool_errors wraps THIS function (trimming), not `fn`
        # directly -- trimming's own _to_payload/json.dumps calls run inside
        # the protected/logged operation, not after it. Wrapping `fn` alone
        # (the old shape) let the inner call log "success" and return before
        # trimming/serialization ever ran; a failure in that step then raised
        # an uncoded, unsanitized exception past every guarantee this module
        # otherwise provides, and the structured log record already claimed
        # success for a call that hadn't actually finished.
        @functools.wraps(fn)
        async def trimming(*args, **kwargs):
            select = _normalize_select(kwargs.get("select"))
            result = await fn(*args, **kwargs)
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

        wrapped = _categorize_tool_errors(trimming)
        wrapped.__doc__ = normalized_doc
        return mcp.tool(structured_output=False)(wrapped)

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


# Stable, machine-readable, agent-facing error codes (ARCH-05's three-tier
# translation scheme funnels every failure into one of these). The prefix
# leads the message, which stays human-readable, e.g.
#   "[PROJECT_SCOPE_DENIED] OpenProject writes to this project are disabled..."
#
# The code/layer themselves live on each exception class (app/errors.py's
# `code`/`layer` ClassVars) -- this module only formats/dispatches, it is not
# the source of truth for the mapping (see app/errors.py's module docstring
# for why that's the cleaner home for it than a lookup table here).
def _prefix(category: str, message: str) -> str:
    """Prepend `[category] ` unless `message` is already prefixed with
    EXACTLY that category -- avoiding a double `[VALIDATION_FAILED]
    [VALIDATION_FAILED] ...` when a message built elsewhere (e.g.
    strict_mcpserver.py's own `[VALIDATION_FAILED]`-prefixed argument
    errors) already carries the same tag before reaching here.

    Deliberately does NOT match ANY `[UPPERCASE] ` bracket token, only this
    call's own `category` -- a tool-body validator's message can echo back
    caller-supplied text (a custom field key, a filter value), and a prior,
    looser regex here would have treated any such text that happened to
    look like `[SOME_TOKEN] ...` as "already categorized," silently
    replacing the real, correct category with a caller-influenced,
    misleading one in the message the agent actually sees (while the
    separate structured log still recorded the correct category, making the
    two inconsistent).
    """
    if message.startswith(f"[{category}] "):
        return message
    return f"[{category}] {message}"


def _categorize_openproject_error(exc: OpenProjectError) -> ToolInputError | ToolCallError:
    """Map any OpenProjectError to its coded, agent-facing exception.

    Shared by `_run_tool` (the normal path, wrapping a client/service call)
    and `_categorize_tool_errors`'s catch-all (the sanitization backstop) --
    an OpenProjectError reaching either point must get its own real code,
    never be folded into a generic INTERNAL_ERROR.

    The returned exception carries `.code`/`.layer` attributes (copied from
    `exc`, not re-derived) so `_categorize_tool_errors`'s outer wrapper can
    read them straight off whatever it catches (a plain `RuntimeError`/
    `ValueError` by the time it gets there) for OPM-2709's structured log
    line, without parsing the `[CODE]`-prefixed message string back apart.
    """
    translated: ToolInputError | ToolCallError
    if isinstance(exc, InvalidInputError):
        translated = ToolInputError(_prefix(exc.code, str(exc)))
    else:
        translated = ToolCallError(_prefix(exc.code, str(exc)))
    translated.code = exc.code  # type: ignore[union-attr]
    translated.layer = exc.layer  # type: ignore[union-attr]
    return translated


async def _run_tool(awaitable):
    try:
        return await awaitable
    except OpenProjectError as exc:
        raise _categorize_openproject_error(exc) from exc


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
    """Wrap a tool so every failure carries a stable, coded prefix.

    _run_tool already codes errors from the client/service call, but input
    validators in the tool body raise plain ValueError *before* _run_tool
    runs -- this wrapper catches those and tags them [VALIDATION_FAILED] too.

    Also the sanitization backstop: any OTHER exception (a bug -- KeyError,
    AttributeError, anything not already a typed OpenProjectError/ValueError)
    is caught here and replaced with a generic, sanitized [INTERNAL_ERROR]
    message -- the original exception's own message is never sent to the
    client, only logged locally, since it could contain arbitrary internal
    detail (a variable's value, an internal path, etc.). `except Exception`,
    never bare `except:` -- BaseException subclasses (CancelledError,
    KeyboardInterrupt, SystemExit) are never caught here and propagate
    exactly as they already do through the MCP SDK's own dispatch boundary.
    """

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        http_request_counter.reset()
        policy_observation.reset()
        # The real MCP SDK dispatch path calls every tool via fn(**kwargs) only
        # (mcp.server.mcpserver.utilities.func_metadata.call_fn_with_arg_validation),
        # never positionally -- ctx (every tool's context parameter is named
        # exactly this, never a different name or position) is always a kwarg
        # in production. args is only ever non-empty when a test calls the
        # wrapped function directly and positionally.
        ctx = kwargs.get("ctx", args[0] if args else None)
        # Context.request_id is a property that raises ValueError (not
        # AttributeError) when the Context wraps no real request_context --
        # e.g. this wrapper driven in-process without the SDK's normal
        # request-handling machinery around it, as several tests do. Plain
        # getattr() only catches AttributeError, so a broken request_id
        # lookup here would otherwise escape uncoded and unlogged, before
        # the try block below ever gets a chance to turn the real tool
        # error into a sanitized outcome -- same class of bug already fixed
        # in strict_mcpserver.py's own dispatch-level request_id lookup.
        try:
            request_id = ctx.request_id if ctx is not None else None
        except Exception:
            request_id = None
        start = time.monotonic()
        error_code: str | None = None
        layer: str | None = None
        try:
            result = await fn(*args, **kwargs)
        except ValueError as exc:
            # A ValueError already coded by _run_tool via
            # _categorize_openproject_error (e.g. InvalidInputError, whose
            # real layer is "http_mapper", not "validation") carries real
            # .code/.layer attributes and must keep them, not have them
            # overwritten with the generic tool-body-validator classification
            # -- same reasoning as the RuntimeError branch below. A bare
            # ValueError raised directly by a tool-body validator (no such
            # attributes) is the actual "validation" case.
            if hasattr(exc, "code") and hasattr(exc, "layer"):
                error_code = exc.code  # type: ignore[attr-defined]
                layer = exc.layer  # type: ignore[attr-defined]
                _emit_tool_call_log(fn.__name__, "error", start, error_code, layer, request_id, LOGGER.warning)
                raise
            error_code, layer = "VALIDATION_FAILED", "validation"
            _emit_tool_call_log(fn.__name__, "error", start, error_code, layer, request_id, LOGGER.warning)
            raise ToolInputError(_prefix("VALIDATION_FAILED", str(exc))) from exc
        except RuntimeError as exc:
            # Only a RuntimeError already coded by _run_tool via
            # _categorize_openproject_error (which attaches .code/.layer to
            # exactly that exception instance) is safe to re-raise verbatim
            # -- its message is already the sanitized `[CODE] ...` form. An
            # uncoded RuntimeError (a real bug in library/tool code that
            # happens to raise this built-in type, not something this
            # module produced) has no such guarantee and must fall through
            # to the same sanitization backstop as any other unexpected
            # exception, or its raw message (which could carry an internal
            # path, host, or other detail) would reach the client unfiltered.
            if hasattr(exc, "code") and hasattr(exc, "layer"):
                error_code = exc.code  # type: ignore[attr-defined]
                layer = exc.layer  # type: ignore[attr-defined]
                _emit_tool_call_log(fn.__name__, "error", start, error_code, layer, request_id, LOGGER.warning)
                raise
            error_code, layer = "INTERNAL_ERROR", "internal"
            LOGGER.exception("Unhandled exception in tool %s", fn.__name__)
            _emit_tool_call_log(fn.__name__, "error", start, error_code, layer, request_id, LOGGER.warning)
            raise ToolCallError(_prefix("INTERNAL_ERROR", "An internal error occurred.")) from exc
        except OpenProjectError as exc:
            # Some tool body calls a raising API directly without going
            # through _run_tool -- give it its own real code via the same
            # categorization _run_tool itself uses, rather than falling
            # through to the generic INTERNAL_ERROR case below.
            error_code, layer = exc.code, exc.layer
            _emit_tool_call_log(fn.__name__, "error", start, error_code, layer, request_id, LOGGER.warning)
            raise _categorize_openproject_error(exc) from exc
        except Exception as exc:
            error_code, layer = "INTERNAL_ERROR", "internal"
            LOGGER.exception("Unhandled exception in tool %s", fn.__name__)
            _emit_tool_call_log(fn.__name__, "error", start, error_code, layer, request_id, LOGGER.warning)
            raise ToolCallError(_prefix("INTERNAL_ERROR", "An internal error occurred.")) from exc
        else:
            _emit_tool_call_log(fn.__name__, "success", start, None, None, request_id, LOGGER.info)
            return result

    return wrapper


def _emit_tool_call_log(
    tool: str,
    status: Literal["success", "error"],
    start: float,
    error_code: str | None,
    layer: str | None,
    request_id: Any,
    log: Callable[..., None],
) -> None:
    """Logging is a side effect of a tool call, never allowed to change its
    OUTCOME -- a bug in this function (or in the http_request_counter/
    policy_observation getters it calls) must never replace or mask the
    real business exception a caller's `except` block is already handling
    (e.g. `[VALIDATION_FAILED]`), which is what would happen if this raised
    into that block uncaught. Caught, logged locally, and swallowed instead.
    """
    try:
        record: ToolCallLogRecord = {
            "tool": tool,
            "status": status,
            "duration_ms": int((time.monotonic() - start) * 1000),
            "error_code": error_code,
            "layer": layer,
            "http_requests": http_request_counter.current(),
            "project_scope": policy_observation.current_project_scope(),
            "policy_decision": policy_observation.current_policy_decision(),
            "request_id": str(request_id) if request_id is not None else None,
        }
        log("tool_call", extra={"structured": record})
    except Exception:
        LOGGER.exception("Failed to emit structured tool-call log for %s", tool)
