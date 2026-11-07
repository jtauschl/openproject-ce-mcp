"""The project columns OpenProject sorts by, and the release each needs.

A pure rule shared by the tool layer and `app/`, neither of which may import the other. Derived from the
order classes of `app/models/queries/projects/` on 16.0 to 17.9: the built-in keys below, `cf_<id>`
(a visible custom field, `text` format excluded by the server) and `project_phase_<id>`. A key an
older instance lacks is rejected by that instance, and `floors_used` names the release in the error.
There is no group-by for projects.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from . import column_floors

SORTABLE_FIELDS = frozenset(
    {
        "id",
        "identifier",
        "name",
        "public",
        "created_at",
        "updated_at",
        "latest_activity_at",
        "project_status",
        "required_disk_space",
        "lft",
        "typeahead",
    }
)

# The two key families with an id: a custom field and a project phase definition.
PATTERNS = (re.compile(r"cf_[1-9]\d*"), re.compile(r"project_phase_[1-9]\d*"))

COLUMN_FLOORS = {"updated_at": "16.5"}


def is_sortable(field: str) -> bool:
    return field in SORTABLE_FIELDS or any(pattern.fullmatch(field) for pattern in PATTERNS)


def floors_used(sort_fields: Iterable[str]) -> list[tuple[str, str]]:
    return column_floors.floors_used(sort_fields, COLUMN_FLOORS)


def sort_by_description() -> str:
    fields = ", ".join(sorted(SORTABLE_FIELDS))
    return (
        'Sort criteria as "field:direction" or "field-direction" (e.g. ["name:desc", "created_at-asc"]); '
        f"the direction defaults to asc. Fields: {fields}, a custom field's cf_<id> (not a text field), "
        "or project_phase_<id>. "
        f"Newer columns need an OpenProject release: {column_floors.describe_floors(COLUMN_FLOORS)}."
    )


# The result fields that show what a sort column orders by: a hidden field closes the column too. A
# column without an entry orders by a value no result field carries.
COLUMN_RESULT_FIELDS: dict[str, tuple[str, ...]] = {
    "id": ("id",),
    "identifier": ("identifier",),
    "name": ("name",),
    "typeahead": ("name",),
    "public": ("public",),
    "created_at": ("created_at",),
    "updated_at": ("updated_at",),
    "project_status": ("status",),
}

# The result field of each filter parameter of the list tool.
FILTER_RESULT_FIELDS: dict[str, tuple[str, ...]] = {
    "search": ("name", "identifier"),
    "custom_field_filters": ("custom_fields",),
}
