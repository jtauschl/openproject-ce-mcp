"""Hidden-field masking policy. Pure, no I/O."""

from __future__ import annotations

import dataclasses
import re
from dataclasses import fields as dataclass_fields
from dataclasses import is_dataclass
from fnmatch import fnmatchcase
from typing import Any, cast

from ...config import HIDE_FIELD_ENV_BY_ENTITY, Settings
from ..errors import InvalidInputError
from .identity_fields import (
    IDENTITY_BY_ACTION,
    IDENTITY_FIELDS,
    PARENT_ROW_KEYS,
    PAYLOAD_COPIES,
    READ_IDENTITY_FIELDS,
    ROW_KEYS,
)
from .payload_fields import COUPLED_FIELDS, NO_FIELD, PAYLOAD_KEYS


def normalize_hide_token(value: str) -> str:
    return value.casefold().replace("-", "_").replace(" ", "_")


def hidden_patterns(entity: str, *, settings: Settings) -> tuple[str, ...]:
    configured = tuple(settings.hidden_fields.get(entity, ()))
    legacy = {
        "project": settings.hide_project_fields,
        "work_package": settings.hide_work_package_fields,
        "activity": settings.hide_activity_fields,
    }.get(entity, ())
    if not configured:
        return legacy
    if not legacy:
        return configured
    combined = list(configured)
    for item in legacy:
        if item not in combined:
            combined.append(item)
    return tuple(combined)


def any_hide_active(settings: Settings) -> bool:
    """True when any hide setting is set: an entity's field list, a legacy list or a custom field pattern.
    A server error text can name a field of any entity, so this is the one predicate the error redaction uses
    (the registrar's own `hide_active` knows no custom field pattern and only decides about trimming)."""
    return bool(settings.hide_custom_fields) or any(
        hidden_patterns(entity, settings=settings) for entity in HIDE_FIELD_ENV_BY_ENTITY
    )


def field_hidden(entity: str, field_name: str, *, settings: Settings) -> bool:
    patterns = hidden_patterns(entity, settings=settings)
    if not patterns:
        return False
    normalized = normalize_hide_token(field_name)
    candidates = {normalized, normalized.replace("_", "")}
    return any(
        fnmatchcase(candidate, normalize_hide_token(pattern)) for pattern in patterns for candidate in candidates
    )


def field_or_coupled_hidden(entity: str, field_name: str, *, settings: Settings) -> bool:
    for group in COUPLED_FIELDS.get(entity, ()):
        if field_name in group:
            return any(field_hidden(entity, member, settings=settings) for member in group)
    return field_hidden(entity, field_name, settings=settings)


def payload_key_hidden(entity: str, key: str, *, settings: Settings) -> bool:
    """True for a key of a write form's `payload` that carries a field the settings hide.

    A key the entity's table does not know is hidden as soon as the entity has any hide pattern: the
    server renders keys the sources do not show (module patches, newer versions), and a key nobody
    classified must not be the way a hidden value leaves. `NO_FIELD` names the keys that carry no
    field and stay visible. Custom field keys are judged elsewhere (`without_hidden_custom_fields`)."""
    table = PAYLOAD_KEYS.get(entity)
    if table is None:
        return False
    carried_by = table.get(key)
    if carried_by is None:
        return key not in NO_FIELD[entity] and bool(hidden_patterns(entity, settings=settings))
    return any(field_or_coupled_hidden(entity, name, settings=settings) for name in carried_by)


def hidden_identity_keys(result_class: str, *, action: str | None = None, settings: Settings) -> frozenset[str]:
    """The members of a result of this class that repeat the value of a field the settings hide."""
    table = (
        IDENTITY_FIELDS.get(result_class, {})
        | READ_IDENTITY_FIELDS.get(result_class, {})
        | IDENTITY_BY_ACTION.get((result_class, action or ""), {})
    )
    if not table:
        return frozenset()
    return frozenset(
        member
        for member, owners in table.items()
        if any(field_or_coupled_hidden(entity, name, settings=settings) for entity, name in owners)
    )


def hidden_row_keys(result_class: str, member: str, *, parent_row: bool, settings: Settings) -> frozenset[str]:
    """The keys of a dict row of a list member (`children`, `ancestors`) that repeat a field the settings hide;
    `parent_row` adds the keys that repeat the parent fields of the record."""
    tables = [ROW_KEYS.get((result_class, member), {})]
    if parent_row:
        tables.append(PARENT_ROW_KEYS.get((result_class, member), {}))
    return frozenset(
        key
        for table in tables
        for key, owners in table.items()
        if any(field_or_coupled_hidden(entity, name, settings=settings) for entity, name in owners)
    )


def hidden_payload_copies(result_class: str, *, settings: Settings) -> frozenset[str]:
    """The keys of a hand-built payload of this write result class that copy a field the settings hide."""
    return frozenset(
        key
        for key, owners in PAYLOAD_COPIES.get(result_class, {}).items()
        if any(field_or_coupled_hidden(entity, name, settings=settings) for entity, name in owners)
    )


def _hidden_field_error(entity: str, field_name: str, consequence: str) -> InvalidInputError:
    env_name = HIDE_FIELD_ENV_BY_ENTITY.get(entity)
    source = env_name if env_name else "the configured hidden-field settings"
    return InvalidInputError(f"OpenProject field '{field_name}' is hidden by {source} and {consequence}.")


def ensure_field_writable(entity: str, field_name: str, *, settings: Settings) -> None:
    if field_hidden(entity, field_name, settings=settings):
        raise _hidden_field_error(entity, field_name, "cannot be written")


def ensure_field_options_readable(entity: str, field_name: str, *, settings: Settings) -> None:
    if field_hidden(entity, field_name, settings=settings):
        raise _hidden_field_error(entity, field_name, "its allowed values are not available")


_CUSTOM_KEY = re.compile(r"(customField|customComment)([1-9]\d*)")


def custom_field_key_hidden(key: str, *, entity: str, settings: Settings) -> bool:
    """True for a `customField<N>` or `customComment<N>` key the settings hide. A comment is part of its
    field, so it is judged by the field's key: the pairing cannot depend on the field's value being
    present next to it."""
    match = _CUSTOM_KEY.fullmatch(key)
    if match is None:
        return False
    kind, field_id = match.groups()
    if field_hidden(entity, "custom_fields", settings=settings):
        return True
    if kind == "customComment" and field_hidden(entity, "custom_comments", settings=settings):
        return True
    field_key = f"customField{field_id}"
    return custom_field_hidden(field_key, field_key, settings=settings)


def custom_field_hidden(field_name: str, key: str, *, settings: Settings) -> bool:
    """Matches BOTH the resolved schema field name and the raw input key against
    `settings.hide_custom_fields` glob patterns -- a caller might supply either
    "customField12" or the human-readable name, and either could match a
    configured hide pattern.
    """
    patterns = tuple(settings.hide_custom_fields)
    if not patterns:
        return False
    candidates = {normalize_hide_token(field_name), normalize_hide_token(key)}
    return any(
        fnmatchcase(candidate, normalize_hide_token(pattern)) for pattern in patterns for candidate in candidates
    )


def ensure_custom_field_input_writable(raw_key: str, *, settings: Settings) -> None:
    """Checked BEFORE schema resolution, using the raw caller-supplied key on
    both sides of the match (the schema key isn't known yet at this point in
    create/update)."""
    normalized = normalize_hide_token(str(raw_key).strip())
    if normalized and custom_field_hidden(raw_key, raw_key, settings=settings):
        raise InvalidInputError(
            f"OpenProject custom field '{raw_key}' is hidden by OPENPROJECT_HIDE_CUSTOM_FIELDS and cannot be written."
        )


def ensure_custom_field_writable(field_name: str, key: str, *, settings: Settings, typed: str) -> None:
    """Checked AFTER schema resolution, using the schema's own field name plus its resolved key. The refusal
    names what the caller typed (`typed`), never the schema's title: with a name pattern the title is the hidden
    field's name, which the caller did not pass."""
    if not custom_field_hidden(field_name, key, settings=settings):
        return
    raise InvalidInputError(
        f"OpenProject custom field '{typed}' is hidden by OPENPROJECT_HIDE_CUSTOM_FIELDS and cannot be written."
    )


def apply_hidden_fields_with_aliases(entity: str, value: Any, *, settings: Settings, aliases: dict[str, Any]) -> Any:
    """Like `apply_hidden_fields`, but for a set of field names that are
    coupled aliases of each other -- they read from and write to the same
    underlying server data (e.g. work package `version`/`target_versions`).
    Hiding any ONE of the aliased fields must hide all of them, or the
    others trivially leak the "hidden" one back out under a different name.

    `aliases` maps each coupled field's name to the value it should be reset
    to when the group is hidden (e.g. `{"version": None, "target_versions": []}`).
    If any field in `aliases` is hidden, every field in the group is zeroed
    to its given reset value AND tagged into `_hidden_keys` -- not just
    whichever one was actually configured, which is what plain
    `apply_hidden_fields` alone would do.
    """
    if not is_dataclass(value):
        return value
    if any(field_hidden(entity, name, settings=settings) for name in aliases):
        for name, reset_value in aliases.items():
            # is_dataclass() narrows value to DataclassInstance | type[...],
            # which dataclasses.replace()'s _DataclassT TypeVar can't accept
            # -- go through Any explicitly rather than suppressing the
            # narrowing with a broader ignore.
            value = dataclasses.replace(cast(Any, value), **{name: reset_value})
    value = apply_hidden_fields(entity, value, settings=settings)
    if any(field_hidden(entity, name, settings=settings) for name in aliases):
        value._hidden_keys = getattr(value, "_hidden_keys", frozenset()) | frozenset(aliases)  # type: ignore[union-attr]
    return value


def apply_hidden_fields(entity: str, value: Any, *, settings: Settings) -> Any:
    """Tag a result dataclass with the field names hidden for its entity.

    The names are stamped as a private ``_hidden_keys`` attribute (not a
    dataclass field, so it never appears in the schema/output). The
    serialization seam (presentation._to_payload) reads it and drops those
    keys entirely from the response — hidden fields cost neither their key
    name nor a null value. Stamping is possible because the response
    dataclasses are not frozen.
    """
    if not is_dataclass(value):
        return value
    hidden = frozenset(
        field_def.name
        for field_def in dataclass_fields(value)
        if field_hidden(entity, field_def.name, settings=settings)
    )
    if hidden:
        # Dynamic attribute, not a declared dataclass field (see docstring) —
        # mypy's DataclassInstance protocol has no way to express this.
        value._hidden_keys = hidden  # type: ignore[union-attr]
    return value


_CUSTOM_FIELD_COLUMN = re.compile(r"cf_([1-9]\d*)")


def custom_field_column_hidden(column: str, *, entity: str, settings: Settings) -> bool:
    """True when `column` is a `cf_<N>` sort, group or filter column of a custom field that is hidden:
    ordering by it would show its values one query at a time. With no schema, a hide pattern may be
    written in either spelling of the key, so both are checked."""
    match = _CUSTOM_FIELD_COLUMN.fullmatch(column)
    if match is None:
        return False
    return field_hidden(entity, "custom_fields", settings=settings) or custom_field_hidden(
        column, f"customField{match.group(1)}", settings=settings
    )


def ensure_custom_field_column_usable(column: str, use: str, *, entity: str, settings: Settings) -> None:
    if custom_field_column_hidden(column, entity=entity, settings=settings):
        raise InvalidInputError(
            f"OpenProject custom field '{column}' is hidden by OPENPROJECT_HIDE_CUSTOM_FIELDS "
            f"or by the custom_fields field of the {entity.replace('_', ' ')} hide setting and cannot be used to {use}."
        )
