"""Shared presentation-layer validation helpers for tools.py (MCP tool handlers).

tools.py stays presentation-only and never imports from `app/` — this module
is a plain sibling, imported by tools.py (and directly by some unit tests
exercising a validator in isolation), never the reverse.
"""

from __future__ import annotations

import datetime
import functools
import re
from collections.abc import Callable
from dataclasses import fields as dataclass_fields
from typing import Any

from .models import SortCriterion

PROJECT_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
# A project-based work package reference: a project identifier followed by "-<number>"
# (e.g. PROJ-123). The numeric form is handled separately before this pattern applies.
WORK_PACKAGE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}-\d+$")
RELATION_TYPE_RE = re.compile(
    r"^(relates|duplicates|duplicated|blocks|blocked|precedes|follows|includes|partof|requires|required)$"
)

# ISO 8601 date-time, e.g. 2026-12-01T09:00:00Z or with a +HH:MM offset. The
# fractional-second component is capped at 6 digits (microsecond precision) --
# datetime.fromisoformat() silently truncates anything beyond that, and
# tools.py's _duration_between relies on fromisoformat's parsed value being
# the caller's actual intent, not a silently-rounded approximation of a
# sub-microsecond value the regex would otherwise have let through.
DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$")
# Full ISO 8601 duration: either weeks alone ("P2W") or a year/month/day date part
# and/or a "T"-prefixed time part (hours/minutes/seconds) — the week designator
# cannot combine with anything else, per the ISO 8601 standard's own week-format
# rule. OpenProject accepts "P1D"/"P2W"/"P1Y"/"P1M"/"P1Y2M3D"/"P1DT18H" and
# echoes them back unchanged, while rejecting "P1W2D"/"P2WT3H" (week mixed
# with another designator) with a format error. The seconds component
# additionally allows an optional decimal fraction (e.g. "PT7H30M15.5S") —
# verified directly against the `iso8601` Ruby gem OpenProject uses server-side
# (ISO8601::Duration.new(...), see time_entry_representer.rb's `hours=` setter):
# its grammar permits a fractional value on any single non-zero component, as
# long as it's the last one, which our own H/M-integer-only + optionally-
# fractional-S shape always satisfies.
ISO8601_DURATION_RE = re.compile(
    r"^P(?:\d+W|(?=\d|T)(?:\d+Y)?(?:\d+M)?(?:\d+D)?(?:T(?=\d)(?:\d+H)?(?:\d+M)?(?:\d+(?:\.\d+)?S)?)?)$"
)


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


# Matches either "cf_<N>" (CustomField#column_name, the actual OpenProject
# filter key) or "customField<N>" (CustomField#attribute_name(:camel_case),
# the JSON/PATCH key used by the read/write value paths). Both forms are
# accepted transparently and always normalized to "cf_<N>" on the wire, so
# callers never need to know the two are different strings for the same
# field. The id itself must be a positive integer with no leading zero
# (OpenProject's own CustomField ids start at 1; "cf_0"/"cf_01" cannot refer
# to a real field, and left-padding could otherwise let "cf_01" and "cf_1"
# collide silently after normalization).
_CF_FILTER_KEY_PATTERN = re.compile(r"^(cf_|customField)([1-9]\d*)$", re.ASCII)

# Union of every operator symbol legal for AT LEAST ONE CE-realistic custom
# field format (see docs/filters.md's "Custom-Field Filters" section for the
# full per-format breakdown and source citations). This is intentionally the
# union, not a per-format set -- these presentation-layer validators are
# Settings-free and have no network access to look up a given cf_<N>'s actual
# field_format, so a symbol outside this union is rejected here (cheap,
# unambiguous), while an operator that IS in the union but illegal for the
# specific field's format is left to OpenProject's own validation (a clean
# 400, mapped to InvalidInputError by app/transport/errors.py) -- see
# work_package_service.py's _apply_custom_field_filters for the format-aware
# part of this split.
_CF_FILTER_OPERATOR_SYMBOLS = frozenset(
    {
        "=",
        "~",
        "!",
        "!~",
        ">=",
        "<=",
        "&=",
        "*",
        "!*",
        "<t+",
        ">t+",
        "t+",
        "t",
        "w",
        ">t-",
        "<t-",
        "t-",
        "=d",
        "<>d",
    }
)

_CF_FILTER_MAX_ENTRIES = 20
_CF_FILTER_MAX_VALUES = 100
_CF_FILTER_MAX_VALUE_LENGTH = 1_000


def _validate_custom_field_filters(
    value: dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, Any]] | None:
    """Validate custom_field_filters shape and normalize keys to cf_<N>.

    Accepts "cf_<N>" or "customField<N>" keys (both forms always accepted
    transparently) and rejects any other key shape immediately, before any
    network call. Each value must be {"operator": str, "values": list[str]},
    with the operator drawn from the union of all legal CE custom-field
    filter operators (see _CF_FILTER_OPERATOR_SYMBOLS above).

    This is deliberately syntax-only, matching every other validator in this
    module (see _validate_optional_custom_fields): per-field format/operator
    legality and OPENPROJECT_HIDE_CUSTOM_FIELDS rejection both require
    Settings and/or format knowledge this layer does not have, and happen in
    work_package_service.py's _apply_custom_field_filters instead.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(
            "custom_field_filters must be an object mapping 'cf_<N>'/'customField<N>' keys to filter specs."
        )
    if len(value) > _CF_FILTER_MAX_ENTRIES:
        raise ValueError(f"custom_field_filters must contain at most {_CF_FILTER_MAX_ENTRIES} entries.")
    normalized: dict[str, dict[str, Any]] = {}
    for raw_key, spec in value.items():
        if not isinstance(raw_key, str):
            raise ValueError(f"custom_field_filters keys must be strings, got {type(raw_key).__name__}.")
        match = _CF_FILTER_KEY_PATTERN.match(raw_key)
        if not match:
            raise ValueError(
                f"custom_field_filters key '{raw_key}' must be of the form 'cf_<N>' or 'customField<N>' "
                "(N a positive integer, no leading zero)."
            )
        cf_key = f"cf_{match.group(2)}"
        if cf_key in normalized:
            raise ValueError(
                f"custom_field_filters has two keys that both resolve to '{cf_key}' "
                "(cf_<N> and customField<N> forms cannot be combined for the same field)."
            )
        if not isinstance(spec, dict):
            raise ValueError(f"custom_field_filters['{raw_key}'] must be an object with 'operator' and 'values'.")
        extra_keys = set(spec) - {"operator", "values"}
        if extra_keys:
            raise ValueError(
                f"custom_field_filters['{raw_key}'] has unsupported key(s): {sorted(extra_keys)}. "
                "Only 'operator' and 'values' are accepted."
            )
        if "operator" not in spec or "values" not in spec:
            raise ValueError(f"custom_field_filters['{raw_key}'] must be an object with 'operator' and 'values'.")
        operator = spec["operator"]
        values = spec["values"]
        if not isinstance(operator, str) or not operator:
            raise ValueError(f"custom_field_filters['{raw_key}'].operator must be a non-empty string.")
        if operator not in _CF_FILTER_OPERATOR_SYMBOLS:
            raise ValueError(
                f"custom_field_filters['{raw_key}'].operator '{operator}' is not a recognized "
                f"custom-field filter operator. Valid operators: {sorted(_CF_FILTER_OPERATOR_SYMBOLS)}."
            )
        if not isinstance(values, list):
            raise ValueError(f"custom_field_filters['{raw_key}'].values must be a list of strings.")
        if len(values) > _CF_FILTER_MAX_VALUES:
            raise ValueError(
                f"custom_field_filters['{raw_key}'].values must contain at most {_CF_FILTER_MAX_VALUES} items."
            )
        for item in values:
            if not isinstance(item, str):
                raise ValueError(f"custom_field_filters['{raw_key}'].values must be a list of strings.")
            if len(item) > _CF_FILTER_MAX_VALUE_LENGTH:
                raise ValueError(
                    f"custom_field_filters['{raw_key}'].values items must be at most "
                    f"{_CF_FILTER_MAX_VALUE_LENGTH} characters."
                )
        normalized[cf_key] = {"operator": operator, "values": list(values)}
    return normalized


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


def _validate_optional_project_ref(value: str | None) -> str | None:
    if value is None:
        return None
    return _validate_project_ref(value)


def _validate_optional_project_identifier(value: str | None) -> str | None:
    if value is None:
        return None
    return _validate_project_identifier(value)


def _validate_project_ref(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("project is required.")
    if normalized.isdigit():
        _validate_positive_int(int(normalized), field_name="project")
        return normalized
    if PROJECT_REF_RE.fullmatch(normalized):
        return normalized
    # Not identifier-shaped (e.g. contains spaces) — pass through as a display-name
    # candidate. Resolution (including "not found"/"ambiguous" errors) happens
    # server-side in OpenProjectClient._resolve_project_ref, which can actually check.
    if len(normalized) > 255:
        raise ValueError("project must be 255 characters or fewer.")
    return normalized


def _validate_project_identifier(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("identifier is required.")
    if not PROJECT_REF_RE.fullmatch(normalized):
        raise ValueError("identifier must be a valid project identifier.")
    return normalized


def _validate_work_package_ref(value: int | str, *, field_name: str = "work_package_id") -> str:
    normalized = " ".join(str(value).split())
    if not normalized:
        raise ValueError(f"{field_name} is required.")
    if normalized.isdigit():
        _validate_positive_int(int(normalized), field_name=field_name)
        return normalized
    if not WORK_PACKAGE_REF_RE.fullmatch(normalized):
        raise ValueError(
            f"{field_name}: use internal id (e.g., 952) or display_id (e.g., 'PROJ-51'), "
            f"not UI display number (e.g., 51)."
        )
    return normalized


def _validate_optional_work_package_ref(value: int | str | None, *, field_name: str = "work_package_id") -> str | None:
    if value is None:
        return None
    return _validate_work_package_ref(value, field_name=field_name)


def _validate_relation_type(value: str) -> str:
    normalized = _validate_required_query(value, field_name="relation_type", max_length=20).casefold()
    if not RELATION_TYPE_RE.fullmatch(normalized):
        raise ValueError(
            "relation_type must be one of: relates, duplicates, duplicated, blocks, blocked, precedes, follows, includes, partof, requires, required."
        )
    return normalized


def _validate_optional_datetime(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if not DATETIME_RE.fullmatch(normalized):
        raise ValueError(f"{field_name} must be an ISO 8601 date-time, e.g. 2026-12-01T09:00:00Z.")
    return normalized


def _validate_required_datetime(value: str, *, field_name: str) -> str:
    normalized = _validate_optional_datetime(value, field_name=field_name)
    if not normalized:
        raise ValueError(f"{field_name} is required.")
    return normalized


def _validate_optional_duration(value: str | None, *, field_name: str) -> str | None:
    normalized = _validate_optional_query(value, field_name=field_name, max_length=50)
    if normalized is None:
        return None
    if not ISO8601_DURATION_RE.fullmatch(normalized):
        raise ValueError(f"{field_name} must use a simple ISO 8601 duration like PT1H30M.")
    return normalized


def _validate_required_duration(value: str, *, field_name: str) -> str:
    normalized = _validate_optional_duration(value, field_name=field_name)
    if not normalized:
        raise ValueError(f"{field_name} is required.")
    return normalized


# Cross-checked against OpenProject's own query property/project-phase select
# definitions -- these are the standard (non-custom-field) attributes
# OpenProject actually accepts via GET /work_packages?sortBy=.../groupBy=...,
# not a guess at plausible names. assignee/assignedTo/
# percentage_done etc. are accepted aliases alongside the canonical Rails
# attribute name; both are included here rather than normalized, since the
# client sends the field straight through unchanged.
_SORTABLE_WORK_PACKAGE_FIELDS = frozenset(
    {
        "id",
        "project",
        "subject",
        "type",
        "status",
        "priority",
        "author",
        "assigned_to",
        "assignee",
        "responsible",
        "updated_at",
        "category",
        "version",
        "start_date",
        "due_date",
        "estimated_hours",
        "estimated_time",
        "remaining_hours",
        "remaining_time",
        "done_ratio",
        "percentage_done",
        "created_at",
        "duration",
        "project_phase",
        "story_points",
    }
)

# Subset of _SORTABLE_WORK_PACKAGE_FIELDS that OpenProject also accepts for
# groupBy -- confirmed by live-testing every entry above (e.g. due_date and
# estimated_hours/estimated_time sort fine but reject with "Can't group by"
# on group_by; parent/subject/id/created_at/updated_at/duration/start_date
# have no groupable column at all in property_select.rb).
_GROUPABLE_WORK_PACKAGE_FIELDS = frozenset(
    {
        "project",
        "type",
        "status",
        "priority",
        "author",
        "assigned_to",
        "assignee",
        "responsible",
        "category",
        "version",
        "done_ratio",
        "percentage_done",
        "project_phase",
    }
)

# A custom field's wire identifier is cf_<id> (the numeric id assigned when the
# field was created on this instance, per CustomField#column_name) -- inherently
# instance-specific and impossible to enumerate statically, so this pattern is
# allowed through without membership-checking against the sets above. Whether a
# given custom field is actually sortable/groupable (its field_format and other
# per-field settings determine that server-side) is left to OpenProject's own
# validation.
_CUSTOM_FIELD_PATTERN = re.compile(r"cf_\d+")


def _describe_valid_fields(allowed: frozenset[str]) -> str:
    return ", ".join(sorted(allowed)) + ", or a custom field's cf_<id> identifier"


def _validate_sort_by(values: list[str] | None) -> list[SortCriterion] | None:
    """Validate and parse sort_by list into list of SortCriterion objects.

    Validates format, field name pattern, and parses each item.
    Returns None if input is None.
    Raises ValueError if any item is invalid.
    """
    if values is None:
        return None
    if not isinstance(values, list):
        raise ValueError("sort_by must be a list of strings")

    result = []
    for i, item in enumerate(values):
        if not isinstance(item, str):
            raise ValueError(f"sort_by[{i}] must be a string, got {type(item).__name__}")

        item = item.strip()
        if not item:
            raise ValueError(f"sort_by[{i}] cannot be empty")

        if ":" in item:
            parts = item.split(":", 1)
            field = parts[0].strip()
            direction = parts[1].strip().lower()

            if not field:
                raise ValueError(f"sort_by[{i}]: field name cannot be empty")
            if direction not in ("asc", "desc"):
                raise ValueError(f"sort_by[{i}]: direction must be 'asc' or 'desc', got '{direction}'")
        else:
            field = item
            direction = "asc"

        if not field.replace("_", "").replace(".", "").isalnum():
            raise ValueError(
                f"sort_by[{i}]: field name '{field}' contains invalid characters "
                "(only alphanumeric, underscore, and dot allowed)"
            )
        if field not in _SORTABLE_WORK_PACKAGE_FIELDS and not _CUSTOM_FIELD_PATTERN.fullmatch(field):
            raise ValueError(
                f"sort_by[{i}]: unknown field '{field}'. "
                f"Valid fields are: {_describe_valid_fields(_SORTABLE_WORK_PACKAGE_FIELDS)}."
            )

        result.append(SortCriterion(field=field, direction=direction))

    return result if result else None


def _validate_group_by(value: str | None) -> str | None:
    """Validate group_by against OpenProject's actual groupable work-package columns."""
    normalized = _validate_optional_query(value, field_name="group_by", max_length=120)
    if normalized is None:
        return None
    if normalized not in _GROUPABLE_WORK_PACKAGE_FIELDS and not _CUSTOM_FIELD_PATTERN.fullmatch(normalized):
        raise ValueError(
            f"group_by: unknown field '{normalized}'. "
            f"Valid fields are: {_describe_valid_fields(_GROUPABLE_WORK_PACKAGE_FIELDS)}."
        )
    return normalized


def _validate_optional_version(
    value: str | None, *, sentinel: object, field_name: str = "version"
) -> str | object | None:
    """Validate a version argument, mapping 'none' (any case) to ``sentinel``.

    Returns None to leave the version unchanged, ``sentinel`` to unassign it, or
    the validated version name/id. Mirrors the parent 'none' un-parenting sentinel.
    ``sentinel`` has no default here (unlike ``_clearable``'s generic form) since
    every real caller needs the field-specific CLEAR_VERSION object, not the
    generic CLEAR one, to distinguish which field was cleared.
    """
    return _clearable(
        value,
        functools.partial(_validate_optional_query, field_name=field_name, max_length=100),
        sentinel=sentinel,
    )


def _clearable(value: str | None, validate: Callable[[str], Any], *, sentinel: object) -> str | object | None:
    """Map a nullable optional argument to a clear sentinel or a validated value.

    Returns None (leave unchanged), ``sentinel`` (clear the field, for 'none' in any
    case), or the result of ``validate(value)``. Shared by any field that supports
    clearing via 'none' — both HAL-link associations (assignee, responsible, category,
    project_phase, sprint, project parent) and plain scalar fields (estimated_time,
    remaining_time, duration); ``validate`` decides what a non-'none' value means.
    ``sentinel`` has no default and must always be passed explicitly by the caller
    (e.g. the generic CLEAR, or a field-specific one like CLEAR_VERSION) — those
    sentinel objects are canonically defined at the app/ layer, which this module
    never imports from, so this presentation-layer helper only ever receives one as
    an opaque object, never defines or imports one itself. Use ``_clearable_ref``
    instead for a field whose validator genuinely accepts a numeric value too
    (currently only work-package refs).

    ``value`` is declared str-only: every real caller's field is str-typed at the MCP
    tool boundary. A non-str scalar (e.g. a bare JSON number) can still reach here
    from bulk_update_work_packages' untyped ``items: list[dict[str, Any]]`` — the
    ``isinstance`` check below is a runtime safety net for that case (mypy sees `Any`
    there and can't catch it statically), not something this function's own str-only
    contract needs to express. The validator itself (e.g. `_validate_optional_query`)
    is responsible for rejecting a non-str value cleanly if one slips through.
    """
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() == "none":
        return sentinel
    return validate(value)


def _clearable_ref(
    value: int | str | None, validate: Callable[[int | str], Any], *, sentinel: object
) -> str | object | None:
    """Like ``_clearable``, but for a validator that accepts a numeric ref directly.

    Only ``_validate_work_package_ref`` needs this today (parent/
    parent_work_package_id can legitimately be a JSON int, not just a display-id
    string) — everything else goes through the str-only ``_clearable``.
    """
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() == "none":
        return sentinel
    return validate(value)


def _clearable_duration(value: str | None, *, field_name: str, sentinel: object) -> str | object | None:
    """Validate a duration argument, mapping 'none' (any case) to ``sentinel``.

    Returns None to leave the field unchanged, ``sentinel`` to clear it, or the
    validated ISO 8601 duration. Shared by estimated_time/remaining_time/duration
    on update_work_package and bulk_update_work_packages.
    """
    return _clearable(value, lambda v: _validate_optional_duration(v, field_name=field_name), sentinel=sentinel)


def _validate_select(select: list[str] | None, *, row_type: type) -> list[str] | None:
    """Validate a field-selection list against a result-row dataclass.

    Called in the tool body so invalid field names raise [validation_error] before
    the client call. Returns the cleaned list (or None). The trimming wrapper
    (tools_runtime._normalize_select) reads the same ``select`` kwarg and applies
    it after the result resolves.
    """
    if select is None:
        return None
    valid = {f.name for f in dataclass_fields(row_type)}
    chosen: list[str] = []
    for raw in select:
        name = str(raw).strip()
        if name not in valid:
            allowed = ", ".join(sorted(valid))
            raise ValueError(f"select field '{name}' is not a valid {row_type.__name__} field. Allowed: {allowed}.")
        if name not in chosen:
            chosen.append(name)
    if not chosen:
        raise ValueError("select must contain at least one field name.")
    return chosen
