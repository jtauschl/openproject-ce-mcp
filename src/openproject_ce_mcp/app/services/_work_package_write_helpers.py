"""Pure write-payload helpers extracted from WorkPackageService.

Only the genuinely self-free pieces of WorkPackageService's write path live
here: resolving a schema's allowed-values href for a field, normalizing a
custom-field key, resolving a custom field's link href(s), naming a form's
offered status values in its status error, and the cache-then-resolve
wrapper around a name/id resolver callable. The remaining write-
payload helpers (`_get_write_schema`, `_apply_custom_fields`,
`_build_write_payload`, `_to_write_result`) stay on WorkPackageService itself
-- they are genuinely coupled to `self._api`, five resolver methods,
`self._settings` (hidden-fields policy checks), and `self._api_prefix`, so
extracting them would either thread 8-10 extra parameters through every call
or require a near-duplicate of WorkPackageService's own constructor
dependencies. Not worth it for line-count reduction alone.
"""

from __future__ import annotations

import builtins
from typing import Any

from ...work_package_reference import is_numeric_ref
from ..errors import InvalidInputError

_SUBJECT_LIMIT = 255

# OpenProject does not cap how many statuses a workflow offers, and the list
# lands in an error message the client reads into its context.
_OFFERED_VALUES_LIMIT = 20


def _trim_text(value: Any, *, limit: int = _SUBJECT_LIMIT) -> str | None:
    """Local, deliberately duplicated (Services cannot import from Adapters
    -- matches `app/services/project_service.py`'s own local copy)."""
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _id_from_href(href: str) -> int | None:
    """Local, deliberately duplicated (matches `app/policies/scope.py`'s
    `id_from_href` -- Services cannot import from a sibling policy module's
    private helper)."""
    tail = href.rstrip("/").rsplit("/", 1)[-1]
    return int(tail) if tail.isdigit() else None


async def resolve_wp_ref_id(
    kind: str,
    ref: str,
    *,
    project: str,
    cache: Any | None,
    resolve: Any,
) -> str:
    """Cache-then-resolve wrapper around resolve_type_id/resolve_version_id/
    resolve_sprint_id. When `cache` is shared across a bulk call's items,
    a repeated name->id lookup for the same (project, kind, ref) is
    skipped instead of re-querying OpenProject once per item."""
    if cache is not None:
        cached = cache.get_id(kind, project, ref)
        if cached is not None:
            return cached
    resolved = await resolve()
    if cache is not None:
        cache.store_id(kind, project, ref, resolved)
    return resolved


def _allowed_options(
    schema: dict[str, Any], key: str, raw_value: Any
) -> tuple[str, list[tuple[str, int | None, str | None]]]:
    """The normalized reference and each allowed value's (href, id, title)."""
    field = schema.get(key)
    if not isinstance(field, dict):
        raise InvalidInputError(f"OpenProject schema does not expose field '{key}' for this work package.")
    allowed_values = field.get("_embedded", {}).get("allowedValues", [])
    if not isinstance(allowed_values, list):
        raise InvalidInputError(f"OpenProject schema does not expose allowed values for field '{key}'.")

    normalized = str(raw_value).strip()
    if not normalized:
        raise InvalidInputError(f"{key} must not be empty.")

    options = []
    for item in allowed_values:
        href = item.get("_links", {}).get("self", {}).get("href")
        if not href:
            continue
        options.append((str(href), _id_from_href(href), _option_title(item)))
    return normalized, options


def _option_title(item: dict[str, Any]) -> str | None:
    return _trim_text(item.get("name") or item.get("_links", {}).get("self", {}).get("title"))


def _offered_titles(field: Any) -> str | None:
    allowed_values = field.get("_embedded", {}).get("allowedValues") if isinstance(field, dict) else None
    if not isinstance(allowed_values, list):
        return None
    titles = [title for title in map(_option_title, allowed_values) if title]
    if not titles:
        return None
    offered = ", ".join(titles[:_OFFERED_VALUES_LIMIT])
    if len(titles) > _OFFERED_VALUES_LIMIT:
        offered += f", … (+{len(titles) - _OFFERED_VALUES_LIMIT} more)"
    return offered


def with_offered_status_values(validation_errors: dict[str, str], schema: dict[str, Any]) -> dict[str, str]:
    """Append the status values the update form offers to its `status` error.

    OpenProject's own message only says the transition is invalid, which
    does not tell a workflow gap from a missing role; the same form's schema
    carries the statuses the workflow allows for this user's roles (plus the
    current status), which settles it."""
    message = validation_errors.get("status")
    if message is None:
        return validation_errors
    offered = _offered_titles(schema.get("status"))
    if offered is None:
        return validation_errors
    return {
        **validation_errors,
        "status": f"{message} Statuses OpenProject offers for this work package (including its current one): {offered}.",
    }


VERSION_ERROR_KEYS = ("version", "targetVersions")


def with_offered_version_values(validation_errors: dict[str, str], schema: dict[str, Any]) -> dict[str, str]:
    """Append the versions the form offers to a `version` or `targetVersions` error.

    OpenProject's message only says the value is not allowed, in the instance language; it does not say that a
    closed or locked version can never be assigned. The caller passes a schema whose options the read scope covers."""
    enriched = validation_errors
    for key in VERSION_ERROR_KEYS:
        message = enriched.get(key)
        offered = _offered_titles(schema.get(key)) if message is not None else None
        if offered is not None:
            enriched = {
                **enriched,
                key: f"{message} Versions OpenProject offers for this work package: {offered}. "
                "A closed or locked version cannot be assigned.",
            }
    return enriched


def _not_allowed(raw_value: Any, key: str) -> InvalidInputError:
    return InvalidInputError(f"OpenProject value '{raw_value}' is not allowed for field '{key}'.")


def _title_matches(options: builtins.list[tuple[str, int | None, str | None]], normalized: str) -> builtins.list[str]:
    return list(
        dict.fromkeys(href for href, _item_id, title in options if title and title.casefold() == normalized.casefold())
    )


def _ambiguous(raw_value: Any, key: str, hrefs: builtins.list[str]) -> InvalidInputError:
    ids = ", ".join(str(_id_from_href(href) or href) for href in hrefs)
    return InvalidInputError(
        f"OpenProject value '{raw_value}' is ambiguous for field '{key}' (matches {ids}). Pass a numeric id."
    )


def resolve_schema_option_href(schema: dict[str, Any], key: str, raw_value: Any) -> str:
    """A built-in field's allowed value: digits are its id, anything else its title; a title that
    several allowed values share is ambiguous, because writing the first one would be a guess."""
    normalized, options = _allowed_options(schema, key, raw_value)
    if is_numeric_ref(normalized):
        matches = [href for href, item_id, _title in options if item_id == int(normalized)]
    else:
        matches = _title_matches(options, normalized)
    if not matches:
        raise _not_allowed(raw_value, key)
    if len(matches) > 1:
        raise _ambiguous(raw_value, key, matches)
    return matches[0]


def _resolve_custom_field_option_href(field: dict[str, Any], key: str, raw_value: Any) -> str:
    """A custom field's allowed value, matched by id or title in option order:
    an option list such as story points has titles made of digits. Several options with the same
    title are ambiguous."""
    normalized, options = _allowed_options({key: field}, key, raw_value)
    title_matches = _title_matches(options, normalized)
    numeric = is_numeric_ref(normalized)
    if len(title_matches) > 1:
        # An id names one option, so it settles a clash between titles that look like it.
        by_id = [href for href, item_id, _title in options if numeric and item_id == int(normalized)]
        if not by_id:
            raise _ambiguous(raw_value, key, title_matches)
        return by_id[0]
    for href, item_id, title in options:
        if numeric and item_id == int(normalized):
            return href
        if title and title.casefold() == normalized.casefold():
            return href
    raise _not_allowed(raw_value, key)


def resolve_custom_field_key(schema: dict[str, Any], raw_key: str) -> str:
    normalized = str(raw_key).strip()
    if not normalized:
        raise InvalidInputError("custom field keys must not be empty.")
    if normalized in schema:
        return normalized
    if normalized.casefold().startswith("customfield") and normalized[11:].isdigit():
        candidate = f"customField{normalized[11:]}"
        if candidate in schema:
            return candidate
    named = [
        key
        for key, field in schema.items()
        if key.startswith("customField")
        and isinstance(field, dict)
        and (name := _trim_text(field.get("name")))
        and name.casefold() == normalized.casefold()
    ]
    if len(named) > 1:
        raise InvalidInputError(
            f"OpenProject custom field '{raw_key}' is ambiguous for this work package (matches {', '.join(named)}). "
            "Use the customField key."
        )
    if named:
        return named[0]
    raise InvalidInputError(f"OpenProject custom field '{raw_key}' is not available for this work package.")


def resolve_custom_field_links(field: dict[str, Any], raw_value: Any, key: str) -> builtins.list[str]:
    values = raw_value if isinstance(raw_value, list) else [raw_value]
    hrefs = [_resolve_custom_field_option_href(field, key, value) for value in values]
    if not hrefs:
        raise InvalidInputError(f"OpenProject custom field '{key}' requires at least one value.")
    return hrefs
