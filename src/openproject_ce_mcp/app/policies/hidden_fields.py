"""Hidden-field masking policy (ADR 0001). Pure, no I/O."""

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
