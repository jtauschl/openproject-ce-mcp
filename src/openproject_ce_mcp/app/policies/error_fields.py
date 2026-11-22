"""Which entry of a server error names a field the settings hide. Pure data and one function, no I/O.

OpenProject answers a rejected write with errors that carry the API attribute they are about
(`_embedded.details.attribute`: `status`, `effectiveDate`, `customField5`) and a message in the language of the
token's account, which names that attribute or quotes a value (`Status is invalid`). Only the attribute can be
judged. The attribute names are the API's, not the payload's (`_links.status` is `status` here), so they
come from `payload_fields.PAYLOAD_KEYS` with the `_links.` prefix removed and `EXTRA_ERROR_KEYS`, the names
only an error uses.

The rule for one entry, in this order (`error_entry_hidden`):
- a code whose text is a constant sentence of the server (`VERBATIM_CODES`) is never hidden;
- an entry without attribute is hidden while any hide setting is active: its text can name a field of any entity;
- a custom field key is judged by the existing custom field rule, and by the field's name where the form handed
  its schema over (`names`); where no name is known a name pattern hides the entry (fail closed);
- `base` is hidden when a field in `BASE_FIELDS[entity]` is hidden, and as an unknown attribute where the
  entity has no such row;
- a known attribute is hidden when one of its fields is hidden, coupled fields included, or one of the fields its
  message can quote (`QUOTES`);
- an attribute the table does not know is hidden while any hide setting is active.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from ...config import Settings
from ..errors import VERBATIM_CODES, ServerErrorEntry
from . import hidden_fields
from .payload_fields import PAYLOAD_KEYS

# Attributes an error can name that no payload key carries, with the model fields they are about.
EXTRA_ERROR_KEYS: dict[str, dict[str, tuple[str, ...]]] = {
    "work_package": {
        "percentageDone": ("percentage_done",),
        "estimatedTime": ("estimated_time",),
        "remainingTime": ("remaining_time",),
        "assignee": ("assignee",),
        "responsible": ("responsible",),
        "parent": ("parent_id", "parent_display_id"),
        "version": ("version", "target_versions"),
        "targetVersions": ("version", "target_versions"),
        "lockVersion": (),
        "derivedPercentageDone": ("derived_percentage_done",),
        "derivedEstimatedTime": ("derived_estimated_time",),
        "derivedEstimatedHours": ("derived_estimated_time",),
        "derivedRemainingTime": ("derived_remaining_time",),
        "derivedRemainingHours": ("derived_remaining_time",),
        "projectPhaseDefinition": ("project_phase",),
    },
    "version": {"effectiveDate": ("end_date",), "project": ("defining_project",)},
    "project": {"statusCode": ("status",)},
    "time_entry": {"comments": ("comment",), "workPackage": ("work_package", "entity_id"), "entity": ("entity_id",)},
    "membership": {"user": ("principal_id", "principal_name"), "principal": ("principal_id", "principal_name")},
    "meeting": {"startDate": ("start_time",), "startTimeHour": ("start_time",), "recurrenceStartTime": ("start_time",)},
    "relation": {"from": ("from_id", "to_id")},
}

# (entity, attribute) -> the fields whose value the message of that attribute can quote, beside the attribute's own: the
# date errors of a work package (`startDate`, `dueDate`) quote the soonest start the relations allow, the finish of a
# predecessor or its start when it has no finish (`work_package.attributes.start_date.violates_relationships`).
QUOTES: dict[tuple[str, str], tuple[str, ...]] = {
    ("work_package", "startDate"): ("start_date", "due_date"),
    ("work_package", "dueDate"): ("start_date", "due_date"),
}

# The fields a `base` error of an entity can describe: the server adds a base error where a rule involves
# several attributes (a closed version, a read-only status). The runtime has the text and the error class, not
# the Ruby symbol, so `base` is hidden when any of them is.
BASE_FIELDS: dict[str, frozenset[str]] = {
    "work_package": frozenset(
        {"status", "version", "target_versions", "parent_id", "parent_display_id", "project", "type"}
    ),
}

_CUSTOM_KEY = re.compile(r"(customField|customComment)([1-9]\d*)")
_RAW_KEY_PATTERN = re.compile(r"custom(?:field|comment)\d+")
_GLOB = re.compile(r"[*?\[]")


def _build_error_keys() -> dict[str, dict[str, tuple[str, ...]]]:
    keys: dict[str, dict[str, tuple[str, ...]]] = {}
    for entity, table in PAYLOAD_KEYS.items():
        keys[entity] = {key.removeprefix("_links."): fields for key, fields in table.items()}
    for entity, table in EXTRA_ERROR_KEYS.items():
        keys.setdefault(entity, {}).update(table)
    return keys


ERROR_KEYS: dict[str, dict[str, tuple[str, ...]]] = _build_error_keys()


def _name_patterns(settings: Settings) -> list[str]:
    """The custom field patterns that are not a raw key (`customField5`) written out: `Secret`, `custom*`, `*`."""
    return [
        pattern
        for pattern in settings.hide_custom_fields
        if _GLOB.search(pattern) or not _RAW_KEY_PATTERN.fullmatch(hidden_fields.normalize_hide_token(pattern))
    ]


def _custom_entry_hidden(attribute: str, *, entity: str, settings: Settings, names: Mapping[str, str] | None) -> bool:
    if hidden_fields.custom_field_key_hidden(attribute, entity=entity, settings=settings):
        return True
    match = _CUSTOM_KEY.fullmatch(attribute)
    field_key = f"customField{match.group(2)}" if match else attribute
    name = (names or {}).get(field_key)
    if name is not None:
        return hidden_fields.custom_field_hidden(name, field_key, settings=settings)
    return bool(_name_patterns(settings))


def error_entry_hidden(
    entry: ServerErrorEntry, *, entity: str, settings: Settings, names: Mapping[str, str] | None = None
) -> bool:
    """True when the entry of a server error of `entity` names a field the settings hide (module docstring)."""
    if entry.code in VERBATIM_CODES:
        return False
    attribute = entry.attribute
    if attribute is None:
        return hidden_fields.any_hide_active(settings)
    if _CUSTOM_KEY.fullmatch(attribute):
        return _custom_entry_hidden(attribute, entity=entity, settings=settings, names=names)
    if attribute == "base":
        base_fields = BASE_FIELDS.get(entity)
        if base_fields is None:
            return hidden_fields.any_hide_active(settings)
        return any(hidden_fields.field_or_coupled_hidden(entity, name, settings=settings) for name in base_fields)
    known = ERROR_KEYS.get(entity, {}).get(attribute)
    if known is None:
        return hidden_fields.any_hide_active(settings)
    named = (*known, *QUOTES.get((entity, attribute), ()))
    return any(hidden_fields.field_or_coupled_hidden(entity, name, settings=settings) for name in named)
