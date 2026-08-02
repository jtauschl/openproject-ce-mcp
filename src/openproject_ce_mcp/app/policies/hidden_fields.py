"""Hidden-field masking policy. Pure, no I/O."""

from __future__ import annotations

from dataclasses import fields as dataclass_fields
from dataclasses import is_dataclass
from fnmatch import fnmatchcase
from typing import Any

from ...config import HIDE_FIELD_ENV_BY_ENTITY, Settings
from ..errors import InvalidInputError


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


def field_hidden(entity: str, field_name: str, *, settings: Settings) -> bool:
    patterns = hidden_patterns(entity, settings=settings)
    if not patterns:
        return False
    normalized = normalize_hide_token(field_name)
    candidates = {normalized, normalized.replace("_", "")}
    return any(
        fnmatchcase(candidate, normalize_hide_token(pattern)) for pattern in patterns for candidate in candidates
    )


def ensure_field_writable(entity: str, field_name: str, *, settings: Settings) -> None:
    if not field_hidden(entity, field_name, settings=settings):
        return
    env_name = HIDE_FIELD_ENV_BY_ENTITY.get(entity)
    source = env_name if env_name else "the configured hidden-field settings"
    raise InvalidInputError(f"OpenProject field '{field_name}' is hidden by {source} and cannot be written.")


def custom_field_hidden(field_name: str, key: str, *, settings: Settings) -> bool:
    """Ported from client.py's `_custom_field_hidden` (kept there too, still used
    by the still-flat `get_project_work_package_context` -- a deliberate
    duplication, not a delete-and-redirect).

    Matches BOTH the resolved schema field name and the raw input key against
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
    create/update). Ported from client.py's `_ensure_custom_field_input_writable`."""
    normalized = normalize_hide_token(str(raw_key).strip())
    if normalized and custom_field_hidden(raw_key, raw_key, settings=settings):
        raise InvalidInputError(
            f"OpenProject custom field '{raw_key}' is hidden by OPENPROJECT_HIDE_CUSTOM_FIELDS and cannot be written."
        )


def ensure_custom_field_writable(field_name: str, key: str, *, settings: Settings) -> None:
    """Checked AFTER schema resolution, using the schema's own field name plus
    its resolved key. Ported from client.py's `_ensure_custom_field_writable`."""
    if not custom_field_hidden(field_name, key, settings=settings):
        return
    raise InvalidInputError(
        f"OpenProject custom field '{field_name}' is hidden by OPENPROJECT_HIDE_CUSTOM_FIELDS and cannot be written."
    )


def apply_hidden_fields(entity: str, value: Any, *, settings: Settings) -> Any:
    """Tag a result dataclass with the field names hidden for its entity.

    The names are stamped as a private ``_hidden_keys`` attribute (not a
    dataclass field, so it never appears in the schema/output). The
    serialization seam (tools._to_payload) reads it and drops those keys
    entirely from the response — hidden fields cost neither their key name nor
    a null value. Stamping is possible because the response dataclasses
    are not frozen.
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
