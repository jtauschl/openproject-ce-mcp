"""A hidden field cannot be used to filter a list either.

The field is left out of every result, but a filter that selects by its value would still show it, one
query at a time (`list_users(search="@rival.com")` with the email hidden). Projects and work packages have
their own policies for this (`project_query_policy`, `work_package_query_policy`); this table covers every
other list. A parameter is a filter when it is optional on a list that also exists unfiltered; a
parameter the caller must give (a container, a path, a record id) selects nothing the argument did not
already name and is not in the table. Pure, no I/O.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ...config import HIDE_FIELD_ENV_BY_ENTITY, Settings
from ..errors import InvalidInputError
from . import hidden_fields


@dataclass(frozen=True)
class FilterRow:
    """The result fields a filter parameter selects by. `always`: the call selects by them whether or not
    the caller passed the parameter, because its default selects (the current year, `upcoming`, the server's
    default relation type). `also`: the (entity, field) pairs of other owners of the same value in the result,
    hidden through their own setting."""

    entity: str
    fields: tuple[str, ...]
    always: bool = False
    also: tuple[tuple[str, str], ...] = ()

    @property
    def owners(self) -> tuple[tuple[str, str], ...]:
        return tuple((self.entity, field) for field in self.fields) + self.also


_PROJECT_OF = ("project_id", "project")
_WORKSPACE_OF = ("defining_workspace_id", "defining_workspace")

FILTER_FIELDS: Mapping[tuple[str, str], FilterRow] = {
    ("list_users", "search"): FilterRow("user", ("name", "login", "email")),
    ("list_principals", "search"): FilterRow("principal", ("name",)),
    ("list_groups", "search"): FilterRow("group", ("name",)),
    ("list_boards", "project"): FilterRow("board", _PROJECT_OF),
    ("list_boards", "search"): FilterRow("board", ("name",)),
    ("list_documents", "project"): FilterRow("document", _PROJECT_OF),
    ("list_documents", "search"): FilterRow("document", ("title",)),
    ("list_news", "project"): FilterRow("news", _PROJECT_OF),
    ("list_news", "search"): FilterRow("news", ("title", "summary")),
    ("list_views", "project"): FilterRow("view", _PROJECT_OF),
    ("list_views", "type"): FilterRow("view", ("type",)),
    ("list_views", "search"): FilterRow("view", ("name",)),
    ("list_versions", "project"): FilterRow("version", ("defining_project", "sharing")),
    ("list_versions", "search"): FilterRow("version", ("name",)),
    ("list_sprints", "project"): FilterRow("sprint", _WORKSPACE_OF),
    ("list_sprints", "search"): FilterRow("sprint", ("name",)),
    ("list_backlog_buckets", "project"): FilterRow("backlog_bucket", _WORKSPACE_OF),
    ("list_backlog_buckets", "search"): FilterRow("backlog_bucket", ("name",)),
    ("get_category", "project"): FilterRow("category", _PROJECT_OF),
    ("list_grids", "scope"): FilterRow("grid", ("scope",)),
    ("list_work_package_attachments", "include_images"): FilterRow("attachment", ("content_type", "file_size_bytes")),
    ("list_project_storages", "project"): FilterRow("project_storage", _PROJECT_OF),
    ("list_time_entries", "project"): FilterRow("time_entry", ("project",)),
    ("list_time_entries", "work_package_id"): FilterRow("time_entry", ("entity_type", "entity_id")),
    ("list_time_entries", "user"): FilterRow("time_entry", ("user", "user_id")),
    ("list_time_entries", "spent_on_from"): FilterRow("time_entry", ("spent_on",)),
    ("list_time_entries", "spent_on_to"): FilterRow("time_entry", ("spent_on",)),
    ("list_meetings", "project"): FilterRow("meeting", _PROJECT_OF),
    ("list_meetings", "title"): FilterRow("meeting", ("title",), also=(("recurring_meeting", "title"),)),
    ("list_recurring_meetings", "project"): FilterRow("recurring_meeting", _PROJECT_OF),
    ("list_recurring_meeting_occurrences", "filter"): FilterRow(
        "recurring_meeting", ("start_time", "state"), always=True, also=(("meeting", "start_time"),)
    ),
    ("list_notifications", "unread_only"): FilterRow("notification", ("read",)),
    ("list_relations", "relation_type"): FilterRow("relation", ("type",)),
    # Required without `capability_id`, so structural by the rule above; it stays bound to `context` in both
    # of its branches so that the refusal does not depend on the combination of parameters.
    ("list_capabilities", "project"): FilterRow("capability", ("context",)),
    ("list_non_working_days", "year"): FilterRow("non_working_day", ("date",), always=True),
    ("list_user_non_working_times", "year"): FilterRow(
        "user_non_working_time", ("start_date", "end_date"), always=True
    ),
    # The typeahead filter of the server: the owners of the stored filter of that name (`stored_query_policy`).
    ("list_work_package_available_relation_candidates", "query"): FilterRow(
        "work_package",
        ("subject", "id", "display_id", "project", "type", "status"),
        also=(("status", "is_closed"),),
    ),
    # Without a type the server filters by `relatable` of type `relates`: the candidates leave out the work packages
    # that already have a relation or a hierarchy link to the anchor, so the list shows them.
    ("list_work_package_available_relation_candidates", "relation_type"): FilterRow(
        "relation",
        ("type", "from_id", "to_id"),
        always=True,
        also=(("work_package", "parent_id"), ("work_package", "ancestors"), ("work_package", "children")),
    ),
}


def _carries_a_value(value: Any) -> bool:
    return value is not None and value is not False and value != "" and value != []


def ensure_filter_allowed(tool: str, *, settings: Settings, **parameters: Any) -> None:
    """Raises when a parameter the caller supplied, or one whose default selects, filters by a hidden field.
    The first hidden field of a row that stands for several fields (`project_id` and `project`) refuses it."""
    for (row_tool, parameter), row in FILTER_FIELDS.items():
        if row_tool != tool or not (row.always or _carries_a_value(parameters.get(parameter))):
            continue
        for entity, field in row.owners:
            if hidden_fields.field_hidden(entity, field, settings=settings):
                raise InvalidInputError(
                    f"OpenProject {entity.replace('_', ' ')} field '{field}' is hidden by "
                    f"{HIDE_FIELD_ENV_BY_ENTITY[entity]} and cannot be used to filter ('{parameter}')."
                )
