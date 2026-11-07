"""Writing `custom_fields` into a form payload, one rule for every entity that has them.

A key is `customField<N>` or the field's name; the value is resolved against the schema of the form
that will be committed. Clearing follows the server's representer: a plain field takes `null`, a
link field `{"href": null}` (single value) or `[]` (multi value).

Functions only, in an underscore-prefixed module: every public class under app/services/ must be
named `*Service`/`*Resolver`.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ..errors import InvalidInputError
from ..policies import hidden_fields
from ..ports.scoped_reference import ScopedReferencesAllowedBulkCheck
from ..resource_href import ResourceLinks
from ._schema_write_helpers import _trim_text, resolve_custom_field_key, resolve_custom_field_links
from ._scoped_references import field_with_visible_options


def ensure_custom_fields_input_writable(entity: str, custom_fields: dict[str, Any], *, settings: Settings) -> None:
    """Before any schema is fetched: a hidden entity field or a hidden key refuses the whole input."""
    hidden_fields.ensure_field_writable(entity, "custom_fields", settings=settings)
    for raw_key in custom_fields:
        hidden_fields.ensure_custom_field_input_writable(raw_key, settings=settings)


def _is_multi_value(field: dict[str, Any]) -> bool:
    return str(field.get("type", "")).startswith("[]")


def _cleared_links(field: dict[str, Any]) -> list[Any] | dict[str, Any]:
    return [] if _is_multi_value(field) else {"href": None}


def _long_text_value(schema_key: str, value: Any) -> dict[str, str] | None:
    # OpenProject reads `fragment["raw"]` and stores empty text, with HTTP 200, for a plain string; a
    # number, boolean or list makes the request fail with a server error.
    if value is None:
        return None
    if isinstance(value, str):
        return {"raw": value}
    raise InvalidInputError(
        f"OpenProject custom field '{schema_key}' is long text: pass the text as a string or null to clear it."
    )


async def apply_custom_fields(
    payload: dict[str, Any],
    links: dict[str, Any],
    schema: dict[str, Any],
    custom_fields: dict[str, Any],
    *,
    subject: str,
    settings: Settings,
    resource_links: ResourceLinks,
    check: ScopedReferencesAllowedBulkCheck,
) -> None:
    for raw_key, raw_value in custom_fields.items():
        schema_key = resolve_custom_field_key(schema, raw_key, subject=subject)
        field = schema[schema_key]
        hidden_fields.ensure_custom_field_writable(
            _trim_text(field.get("name")) or schema_key, schema_key, settings=settings
        )
        if field.get("location") != "_links":
            payload[schema_key] = (
                _long_text_value(schema_key, raw_value) if field.get("type") == "Formattable" else raw_value
            )
            continue
        if raw_value is None or (raw_value == [] and _is_multi_value(field)):
            links[schema_key] = _cleared_links(field)
            continue
        if isinstance(raw_value, list) and any(value is None for value in raw_value):
            raise InvalidInputError(
                f"OpenProject custom field '{schema_key}' takes values or null as a whole, not null inside a list."
            )
        field = await field_with_visible_options(field, links=resource_links, settings=settings, check=check)
        hrefs = resolve_custom_field_links(field, raw_value, schema_key, subject=subject)
        if _is_multi_value(field):
            links[schema_key] = [{"href": href} for href in hrefs]
        elif len(hrefs) > 1:
            raise InvalidInputError(f"OpenProject custom field '{schema_key}' takes a single value.")
        else:
            links[schema_key] = {"href": hrefs[0]}
