"""Shared presentation-layer validation helpers for tools.py (MCP tool handlers).

tools.py stays presentation-only and never imports from `app/` — this module
is a plain sibling, imported by tools.py (and directly by some unit tests
exercising a validator in isolation), never the reverse.
"""

from __future__ import annotations

import datetime
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
        # tool parameters are str-typed and coerced/rejected by the SDK before
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


def _validate_optional_text(value: str | None, *, field_name: str, max_length: int) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > max_length:
        raise ValueError(f"{field_name} must be at most {max_length} characters.")
    return normalized


def _validate_optional_update_text(value: str | None, *, field_name: str, max_length: int) -> str | None:
    """Like _validate_optional_text, but preserves an explicit empty string.

    None still means "not provided, leave unchanged"; an explicit "" means
    "clear this field" and is passed through as "" instead of collapsing to
    None. Use only for persisted, genuinely clearable update fields — not for
    create tools (where "" traditionally means "no value given") or transient
    fields like a membership notification message.
    """
    if value is None:
        return None
    normalized = value.strip()
    if len(normalized) > max_length:
        raise ValueError(f"{field_name} must be at most {max_length} characters.")
    return normalized


def _validate_required_text(value: str, *, field_name: str, max_length: int) -> str:
    normalized = _validate_optional_text(value, field_name=field_name, max_length=max_length)
    if not normalized:
        raise ValueError(f"{field_name} is required.")
    return normalized


def _validate_optional_custom_fields(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("custom_fields must be an object mapping field names to values.")
    if len(value) > 50:
        raise ValueError("custom_fields must contain at most 50 entries.")
    normalized: dict[str, Any] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key).strip()
        if not key:
            raise ValueError("custom_fields keys must not be empty.")
        if len(key) > 120:
            raise ValueError("custom_fields keys must be at most 120 characters.")
        normalized[key] = _validate_custom_field_value(raw_value)
    return normalized


def _validate_custom_field_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) > 10_000:
            raise ValueError("custom_fields string values must be at most 10000 characters.")
        return value.strip()
    if isinstance(value, list):
        return [_validate_custom_field_value(item) for item in value]
    raise ValueError("custom_fields values must be strings, numbers, booleans, null, or lists of those values.")


def _validate_required_query(value: str, *, field_name: str, max_length: int) -> str:
    normalized = _validate_optional_query(value, field_name=field_name, max_length=max_length)
    if not normalized:
        raise ValueError(f"{field_name} is required.")
    return normalized


def _validate_optional_user_ref(value: str | None, field_name: str = "assignee") -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        # See _validate_optional_query for why this guard exists.
        raise ValueError(f"{field_name} must be a string.")
    normalized = " ".join(value.split())
    if not normalized:
        return None
    if normalized.casefold() == "me":
        return "me"
    if normalized.isdigit():
        _validate_positive_int(int(normalized), field_name=field_name)
        return normalized
    raise ValueError(f"{field_name}: 'me' or numeric user id (e.g., 42). Call list_users to find ids.")


def _validate_optional_user_or_principal_ref(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    if not normalized:
        return None
    if normalized.casefold() == "me":
        return "me"
    if normalized.isdigit():
        _validate_positive_int(int(normalized), field_name="user")
        return normalized
    if len(normalized) > 255:
        raise ValueError("user must be at most 255 characters.")
    return normalized


def _validate_participant_refs(value: list[str] | None) -> list[str] | None:
    """`_validate_optional_user_or_principal_ref`, but for a list where every
    element is required (an empty/blank participant reference is a genuine
    input error, unlike the single-ref case where an empty value means
    "not provided")."""
    if value is None:
        return None
    validated: list[str] = []
    for ref in value:
        safe_ref = _validate_optional_user_or_principal_ref(ref)
        if safe_ref is None:
            raise ValueError("participant_user_refs entries must not be empty.")
        validated.append(safe_ref)
    return validated


def _validate_required_date(value: str, *, field_name: str) -> str:
    normalized = _validate_optional_date(value, field_name=field_name)
    if not normalized:
        raise ValueError(f"{field_name} is required.")
    return normalized


def _validate_optional_non_negative_int(value: int | None, *, field_name: str) -> int | None:
    if value is None:
        return None
    # Type-safe: MCP args arrive as JSON, so a wrong type (e.g. "5", True) must
    # yield a clean ValueError, not a raw TypeError from the comparison.
    # bool is an int subclass, so reject it explicitly.
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer.")
    if value < 0:
        raise ValueError(f"{field_name} must be at least 0.")
    return value


def _validate_optional_percentage_done(value: int | None, *, field_name: str = "percentage_done") -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer.")
    if not 0 <= value <= 100:
        raise ValueError(f"{field_name} must be between 0 and 100.")
    return value


def _validate_optional_date(value: str | None, field_name: str) -> str | None:
    """Validate ISO 8601 date (YYYY-MM-DD)."""
    if value is None:
        return None
    normalized = value.strip()
    try:
        datetime.date.fromisoformat(normalized)
        return normalized
    except ValueError as exc:
        raise ValueError(f"{field_name} must be YYYY-MM-DD format") from exc


def _validate_date_range(after: str | None, before: str | None, prefix: str) -> None:
    """Ensure after <= before for already-validated ISO date strings."""
    if after and before:
        import datetime

        after_date = datetime.date.fromisoformat(after)
        before_date = datetime.date.fromisoformat(before)
        if after_date > before_date:
            raise ValueError(f"{prefix}_after ({after}) must not be later than {prefix}_before ({before})")


def _validate_optional_date_range(dates: list[str] | None, field_name: str) -> list[str] | None:
    """Validate optional date range [start, end] in YYYY-MM-DD format."""
    if dates is None:
        return None
    if not isinstance(dates, list):
        raise ValueError(f"{field_name} must be a list of 2 dates")
    if len(dates) != 2:
        raise ValueError(f"{field_name} must contain exactly 2 dates [start, end]")

    start = _validate_optional_date(dates[0], f"{field_name}[0]")
    end = _validate_optional_date(dates[1], f"{field_name}[1]")

    if start is None or end is None:
        raise ValueError(f"{field_name} dates cannot be empty")

    _validate_date_range(after=start, before=end, prefix=field_name)

    return [start, end]


def _validate_required_string_list(
    values: list[str],
    *,
    field_name: str,
    max_items: int,
    item_max_length: int,
) -> list[str]:
    if not isinstance(values, list):
        raise ValueError(f"{field_name} must be a list of strings.")
    if not values:
        raise ValueError(f"{field_name} must contain at least one value.")
    if len(values) > max_items:
        raise ValueError(f"{field_name} must contain at most {max_items} values.")
    normalized: list[str] = []
    for value in values:
        item = _validate_required_query(str(value), field_name=field_name, max_length=item_max_length)
        normalized.append(item)
    return normalized


def _validate_optional_string_list(
    values: list[str] | None,
    *,
    field_name: str,
    max_items: int,
    item_max_length: int,
) -> list[str] | None:
    if values is None:
        return None
    if not isinstance(values, list):
        raise ValueError(f"{field_name} must be a list of strings.")
    if len(values) > max_items:
        raise ValueError(f"{field_name} must contain at most {max_items} values.")
    normalized: list[str] = []
    for value in values:
        item = _validate_required_query(str(value), field_name=field_name, max_length=item_max_length)
        normalized.append(item)
    return normalized


def _validate_optional_filter_list(value: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("filters must be a list of objects.")
    if len(value) > 50:
        raise ValueError("filters must contain at most 50 entries.")
    normalized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("filters must be a list of objects.")
        normalized.append(_validate_json_object(item, field_name="filters"))
    return normalized


def _validate_json_object(value: dict[str, Any], *, field_name: str) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key).strip()
        if not key:
            raise ValueError(f"{field_name} keys must not be empty.")
        if len(key) > 120:
            raise ValueError(f"{field_name} keys must be at most 120 characters.")
        normalized[key] = _validate_json_value(raw_value, field_name=field_name)
    return normalized


def _validate_json_value(value: Any, *, field_name: str) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) > 10_000:
            raise ValueError(f"{field_name} string values must be at most 10000 characters.")
        return value
    if isinstance(value, list):
        if len(value) > 100:
            raise ValueError(f"{field_name} lists must contain at most 100 items.")
        return [_validate_json_value(item, field_name=field_name) for item in value]
    if isinstance(value, dict):
        return _validate_json_object(value, field_name=field_name)
    raise ValueError(f"{field_name} values must be JSON-compatible scalars, lists, or objects.")


def _validate_optional_choice(
    value: str | None,
    *,
    field_name: str,
    allowed_values: set[str],
) -> str | None:
    normalized = _validate_optional_query(value, field_name=field_name, max_length=100)
    if normalized is None:
        return None
    if normalized not in allowed_values:
        allowed = ", ".join(sorted(allowed_values))
        raise ValueError(f"{field_name} must be one of: {allowed}.")
    return normalized


def _validate_choice(
    value: str,
    *,
    field_name: str,
    allowed_values: set[str],
) -> str:
    normalized = _validate_required_text(value, field_name=field_name, max_length=100)
    if normalized not in allowed_values:
        allowed = ", ".join(sorted(allowed_values))
        raise ValueError(f"{field_name} must be one of: {allowed}.")
    return normalized
