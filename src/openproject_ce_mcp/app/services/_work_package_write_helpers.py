"""Pure write-payload helpers extracted from WorkPackageService.

Only the genuinely self-free pieces of WorkPackageService's write path live
here: resolving a schema's allowed-values href for a field, normalizing a
custom-field key, resolving a custom field's link href(s), and the cache-
then-resolve wrapper around a name/id resolver callable. The remaining write-
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

from ..errors import InvalidInputError

_SUBJECT_LIMIT = 255


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


def resolve_schema_option_href(schema: dict[str, Any], key: str, raw_value: Any) -> str:
    field = schema.get(key)
    if not isinstance(field, dict):
        raise InvalidInputError(f"OpenProject schema does not expose field '{key}' for this work package.")
    allowed_values = field.get("_embedded", {}).get("allowedValues", [])
    if not isinstance(allowed_values, list):
        raise InvalidInputError(f"OpenProject schema does not expose allowed values for field '{key}'.")

    normalized = str(raw_value).strip()
    if not normalized:
        raise InvalidInputError(f"{key} must not be empty.")

    for item in allowed_values:
        href = item.get("_links", {}).get("self", {}).get("href")
        if not href:
            continue
        item_id = _id_from_href(href)
        title = _trim_text(item.get("name") or item.get("_links", {}).get("self", {}).get("title"))
        if normalized.isdigit() and item_id is not None and int(normalized) == item_id:
            return str(href)
        if title and title.casefold() == normalized.casefold():
            return str(href)
    raise InvalidInputError(f"OpenProject value '{raw_value}' is not allowed for field '{key}'.")


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
    for key, field in schema.items():
        if not key.startswith("customField") or not isinstance(field, dict):
            continue
        name = _trim_text(field.get("name"))
        if name and name.casefold() == normalized.casefold():
            return key
    raise InvalidInputError(f"OpenProject custom field '{raw_key}' is not available for this work package.")


def resolve_custom_field_links(field: dict[str, Any], raw_value: Any, key: str) -> builtins.list[str]:
    values = raw_value if isinstance(raw_value, list) else [raw_value]
    hrefs = [resolve_schema_option_href({key: field}, key, value) for value in values]
    if not hrefs:
        raise InvalidInputError(f"OpenProject custom field '{key}' requires at least one value.")
    return hrefs
