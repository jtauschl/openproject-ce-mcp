"""Shared presentation-layer validation helpers for tools.py (MCP tool handlers).

Per ADR 0001, tools.py stays presentation-only and never imports from `app/` —
this module is a plain sibling, imported only by tools.py, never the reverse.
"""

from __future__ import annotations

from typing import Any


def _validate_positive_int(value: int, *, field_name: str) -> int:
    # Type-safe: MCP args arrive as JSON, so a wrong type (e.g. "5", None, True)
    # must yield a clean ValueError, not a raw TypeError from the comparison.
    # bool is an int subclass, so reject it explicitly.
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer.")
    if value < 1:
        raise ValueError(f"{field_name} must be at least 1.")
    return value


def _validate_offset(offset: int) -> int:
    return _validate_positive_int(offset, field_name="offset")


def _validate_limit(limit: int | None) -> int | None:
    if limit is None:
        return None
    return _validate_positive_int(limit, field_name="limit")


def _validate_optional_query(value: str | None, *, field_name: str, max_length: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        # Reachable with a non-str JSON scalar (e.g. a bare number or bool) from
        # bulk_update_work_packages' untyped `items: list[dict[str, Any]]` — MCP
        # tool parameters are str-typed and coerced/rejected by FastMCP before
        # reaching here, but a dict value has no such guarantee.
        raise ValueError(f"{field_name} must be a string.")
    normalized = " ".join(value.split())
    if not normalized:
        return None
    if len(normalized) > max_length:
        raise ValueError(f"{field_name} must be at most {max_length} characters.")
    return normalized


def _validate_list_query_params(
    search: str | None,
    offset: int,
    limit: int | None,
    *,
    search_max_length: int = 100,
) -> tuple[str | None, int, int | None]:
    """The search/offset/limit trio repeated verbatim at every list_* tool handler."""
    safe_search = _validate_optional_query(search, field_name="search", max_length=search_max_length)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return safe_search, safe_offset, safe_limit


def _require_at_least_one(*values: Any, message: str) -> None:
    """The "at least one field to update" guard repeated across every update_* tool
    handler. Each call site supplies its own existing message text — the guard
    logic is what's shared, not the wording, since the message is MCP-visible
    output.
    """
    if not any(value is not None for value in values):
        raise ValueError(message)
