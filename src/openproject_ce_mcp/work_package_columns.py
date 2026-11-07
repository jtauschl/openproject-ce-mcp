"""The work-package columns OpenProject sorts and groups by, and the release each needs.

A pure rule shared by the tool layer and `app/`, neither of which may import the other.
The names are OpenProject's own (its parser also accepts camelCase and the aliases noted
below). The sets are the union over the supported releases: a column an older instance
lacks is rejected by that instance, and `floors_used` names the release in the error.
"""

from __future__ import annotations

from collections.abc import Iterable

from . import column_floors

# assignee, estimated_time, remaining_time and percentage_done are OpenProject's
# aliases of assigned_to, estimated_hours, remaining_hours and done_ratio.
SORTABLE_FIELDS = frozenset(
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
        "target_versions",
        "observed_in_versions",
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
        "position",
        "sprint",
        "backlog_bucket",
    }
)

# The columns with one database value per group; the id, text, dates, hours, duration,
# story_points and position sort but cannot be grouped by.
GROUPABLE_FIELDS = frozenset(
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
        "target_versions",
        "observed_in_versions",
        "done_ratio",
        "percentage_done",
        "project_phase",
        "sprint",
        "backlog_bucket",
    }
)

# Where a column first exists. sprint is sortable from 17.4 although writing a sprint
# is possible from 17.3: the query column came one release later. target_versions
# is `version` under its newer name (17.8 translates either name to the active one).
COLUMN_FLOORS = {
    "project_phase": "16.1",
    "sprint": "17.4",
    "backlog_bucket": "17.6",
    "target_versions": "17.8",
    "observed_in_versions": "17.9",
}


def floors_used(sort_fields: Iterable[str], group_field: str | None) -> list[tuple[str, str]]:
    """The (column, release) pairs a request uses, oldest release first."""
    return column_floors.floors_used((*sort_fields, group_field), COLUMN_FLOORS)


def describe_floors() -> str:
    return column_floors.describe_floors(COLUMN_FLOORS)


def sort_by_description() -> str:
    fields = ", ".join(sorted(SORTABLE_FIELDS))
    return (
        'Sort criteria as "field:direction" or "field-direction" (e.g. ["status:desc", "priority-asc"]); '
        f"the direction defaults to asc. Fields: {fields}, or a custom field's cf_<id>. "
        f"Newer columns need an OpenProject release: {describe_floors()}; target_versions is version under its newer name. "
        "sprint and backlog_bucket also need the Backlogs module in a project where you may view sprints."
    )


def group_by_description() -> str:
    fields = ", ".join(sorted(GROUPABLE_FIELDS))
    return (
        f"One field to group the results by: {fields}, or a custom field's cf_<id>. "
        f"Newer columns need an OpenProject release: {describe_floors()}; target_versions is version under its newer name. "
        "sprint and backlog_bucket also need the Backlogs module in a project where you may view sprints."
    )


# The result fields that show what a sort or group column orders or labels by. Ordering or grouping
# by a field shows its values just as the field does, so a hidden field closes the column too. A
# column without an entry names a value no result field carries and nothing can hide.
COLUMN_RESULT_FIELDS: dict[str, tuple[str, ...]] = {
    "project": ("project",),
    "subject": ("subject",),
    "type": ("type",),
    "status": ("status",),
    "priority": ("priority",),
    "author": ("author",),
    "assigned_to": ("assignee",),
    "assignee": ("assignee",),
    "responsible": ("responsible",),
    "updated_at": ("updated_at",),
    "category": ("category",),
    "version": ("version", "target_versions"),
    "target_versions": ("version", "target_versions"),
    "observed_in_versions": ("observed_in_versions",),
    "start_date": ("start_date",),
    "due_date": ("due_date",),
    "estimated_hours": ("estimated_time",),
    "estimated_time": ("estimated_time",),
    "remaining_hours": ("remaining_time",),
    "remaining_time": ("remaining_time",),
    "done_ratio": ("percentage_done",),
    "percentage_done": ("percentage_done",),
    "created_at": ("created_at",),
    "duration": ("duration",),
    "project_phase": ("project_phase",),
    "sprint": ("sprint",),
}
COLUMNS_WITHOUT_RESULT_FIELD = frozenset({"id", "story_points", "position", "backlog_bucket"})

# The same for the filter parameters of the list and search tools.
FILTER_RESULT_FIELDS: dict[str, tuple[str, ...]] = {
    "project": ("project",),
    "search": ("subject",),
    "custom_field_filters": ("custom_fields",),
    "type": ("type",),
    "version": ("version", "target_versions"),
    "version_status": ("version", "target_versions"),
    "observed_in_version": ("observed_in_versions",),
    "open_only": ("status",),
    "assignee_me": ("assignee",),
    "assignee": ("assignee",),
    "status": ("status",),
    "priority": ("priority",),
    "created_on": ("created_at",),
    "created_between": ("created_at",),
    "updated_on": ("updated_at",),
    "updated_between": ("updated_at",),
    "due_on": ("due_date",),
    "due_between": ("due_date",),
    "overdue_only": ("due_date", "status"),
    "due_within_days": ("due_date",),
}
