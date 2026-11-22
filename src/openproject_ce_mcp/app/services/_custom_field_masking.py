"""Hide-on-read for the custom field values of any entity.

`OPENPROJECT_HIDE_<ENTITY>_FIELDS` naming `custom_fields` (or `custom_comments`) hides the whole dict;
`OPENPROJECT_HIDE_CUSTOM_FIELDS` removes single entries by the raw `customField<N>` key. The comment of
every field that is hidden goes with it: a comment is part of its field.

Functions only, in an underscore-prefixed module: every public class under app/services/ must be
named `*Service`/`*Resolver`.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any, TypeVar

from ...config import Settings
from ..policies import hidden_fields
from ..policies.hidden_fields import custom_field_key_hidden
from ..ports.custom_field_carrier import CustomFieldCarrier

T = TypeVar("T", bound=CustomFieldCarrier)


_KEY = re.compile(r"(customField|customComment)([1-9]\d*)")


def is_custom_field_key(key: str) -> bool:
    return _KEY.fullmatch(key) is not None


def is_custom_comment_key(key: str) -> bool:
    match = _KEY.fullmatch(key)
    return match is not None and match.group(1) == "customComment"


def _without_hidden(values: dict[str, Any] | None, *, entity: str, settings: Settings) -> dict[str, Any] | None:
    """Matched against the raw key only, never the friendly name. The write path matches both, so a
    pattern that names only the field has no effect on reads (docs/field-hiding.md).

    Returns the original object when nothing was removed."""
    if not values:
        return values
    filtered = {
        key: value
        for key, value in values.items()
        if not custom_field_key_hidden(key, entity=entity, settings=settings)
    }
    if len(filtered) == len(values):
        return values
    return filtered or None


def without_hidden_custom_fields(payload: dict[str, Any], *, entity: str, settings: Settings) -> dict[str, Any]:
    """A write payload as shown to the caller: the form echoes the whole entity, so a hidden field's value
    comes back in it, at the top level (plain formats) and under `_links` (link formats)."""
    shown = {
        key: value
        for key, value in payload.items()
        if not custom_field_key_hidden(key, entity=entity, settings=settings)
    }
    links = shown.get("_links")
    if isinstance(links, dict):
        shown["_links"] = {
            key: value
            for key, value in links.items()
            if not custom_field_key_hidden(key, entity=entity, settings=settings)
        }
    return shown


def custom_field_names(schema: dict[str, Any]) -> dict[str, str]:
    """`customField<N>` -> the field's name in the form schema the write already fetched: a hide pattern written
    as the name judges an error entry of the work package by it (the friendly name never reaches an error key)."""
    return {
        key: str(spec["name"])
        for key, spec in schema.items()
        if isinstance(spec, dict) and isinstance(spec.get("name"), str) and _KEY.fullmatch(key)
    }


def mask_custom_field_values(value: T, *, entity: str, settings: Settings) -> T:
    """Mask `custom_fields` and `custom_comments` of a summary or detail of `entity`, and reset their
    truncation flags when the whole field is hidden, so the flag does not describe hidden data. A flag left
    unchanged after a key-only mask describes data the caller configured the hide for, so it discloses
    nothing new."""
    custom_fields = _without_hidden(value.custom_fields, entity=entity, settings=settings)
    custom_comments = _without_hidden(value.custom_comments, entity=entity, settings=settings)
    fields_hidden = hidden_fields.field_hidden(entity, "custom_fields", settings=settings)
    comments_hidden = fields_hidden or hidden_fields.field_hidden(entity, "custom_comments", settings=settings)
    custom_fields_truncated = False if fields_hidden else value.custom_fields_truncated
    custom_comments_truncated = False if comments_hidden else value.custom_comments_truncated
    if (
        custom_fields is value.custom_fields
        and custom_comments is value.custom_comments
        and custom_fields_truncated == value.custom_fields_truncated
        and custom_comments_truncated == value.custom_comments_truncated
        and not comments_hidden
    ):
        return value
    return dataclasses.replace(
        value,  # type: ignore[type-var]
        custom_fields=custom_fields,
        custom_comments=None if fields_hidden else custom_comments,
        custom_fields_truncated=custom_fields_truncated,
        custom_comments_truncated=custom_comments_truncated,
    )
