"""A filter parameter that selects by a hidden field is refused, and the table says by which fields.

`filter_policy.FILTER_FIELDS` maps a (tool, parameter) to the entity and the result fields the parameter selects
by. The rows are written out a second time here, independent of the module, so a dropped or wrong field fails.
"""

from __future__ import annotations

import dataclasses

import pytest

from openproject_ce_mcp import models
from openproject_ce_mcp.app.errors import InvalidInputError
from openproject_ce_mcp.app.policies import filter_policy
from openproject_ce_mcp.app.policies.identity_fields import READ_IDENTITY_FIELDS
from openproject_ce_mcp.app.policies.payload_fields import COUPLED_FIELDS
from openproject_ce_mcp.config import HIDE_FIELD_ENV_BY_ENTITY

# (tool, parameter) -> (entity, the fields it selects by, whether the default selects too)
EXPECTED: dict[tuple[str, str], tuple[str, tuple[str, ...], bool]] = {
    ("list_users", "search"): ("user", ("name", "login", "email"), False),
    ("list_principals", "search"): ("principal", ("name",), False),
    ("list_groups", "search"): ("group", ("name",), False),
    ("list_boards", "project"): ("board", ("project_id", "project"), False),
    ("list_boards", "search"): ("board", ("name",), False),
    ("list_documents", "project"): ("document", ("project_id", "project"), False),
    ("list_documents", "search"): ("document", ("title",), False),
    ("list_news", "project"): ("news", ("project_id", "project"), False),
    ("list_news", "search"): ("news", ("title", "summary"), False),
    ("list_views", "project"): ("view", ("project_id", "project"), False),
    ("list_views", "type"): ("view", ("type",), False),
    ("list_views", "search"): ("view", ("name",), False),
    ("list_versions", "project"): ("version", ("defining_project", "sharing"), False),
    ("list_versions", "search"): ("version", ("name",), False),
    ("list_sprints", "project"): ("sprint", ("defining_workspace_id", "defining_workspace"), False),
    ("list_sprints", "search"): ("sprint", ("name",), False),
    ("list_backlog_buckets", "project"): ("backlog_bucket", ("defining_workspace_id", "defining_workspace"), False),
    ("list_backlog_buckets", "search"): ("backlog_bucket", ("name",), False),
    ("get_category", "project"): ("category", ("project_id", "project"), False),
    ("list_grids", "scope"): ("grid", ("scope",), False),
    ("list_project_storages", "project"): ("project_storage", ("project_id", "project"), False),
    ("list_time_entries", "project"): ("time_entry", ("project",), False),
    ("list_time_entries", "work_package_id"): ("time_entry", ("entity_type", "entity_id"), False),
    ("list_time_entries", "user"): ("time_entry", ("user", "user_id"), False),
    ("list_time_entries", "spent_on_from"): ("time_entry", ("spent_on",), False),
    ("list_time_entries", "spent_on_to"): ("time_entry", ("spent_on",), False),
    ("list_meetings", "project"): ("meeting", ("project_id", "project"), False),
    ("list_recurring_meetings", "project"): ("recurring_meeting", ("project_id", "project"), False),
    ("list_recurring_meeting_occurrences", "filter"): ("recurring_meeting", ("start_time", "state"), True),
    ("list_notifications", "unread_only"): ("notification", ("read",), False),
    ("list_relations", "relation_type"): ("relation", ("type",), False),
    ("list_capabilities", "project"): ("capability", ("context",), False),
    ("list_non_working_days", "year"): ("non_working_day", ("date",), True),
    ("list_user_non_working_times", "year"): ("user_non_working_time", ("start_date", "end_date"), True),
}

# The other owners of the same value in the result: the start time of an occurrence is also the meeting's.
ALSO: dict[tuple[str, str], tuple[tuple[str, str], ...]] = {
    ("list_recurring_meeting_occurrences", "filter"): (("meeting", "start_time"),),
}

# A value that makes the parameter carry a value for the tool, for the cases that call the policy directly.
VALUE = {
    "search": "x",
    "project": "demo",
    "type": "wiki",
    "scope": "/my/page",
    "work_package_id": 5,
    "user": "7",
    "spent_on_from": "2030-01-01",
    "spent_on_to": "2030-12-31",
    "filter": "upcoming",
    "unread_only": True,
    "relation_type": "blocks",
    "year": 2030,
}

# The dataclass that carries the fields of each entity here; the occurrences are rows of their own.
RECORD_OF = {
    ("user", "list_users"): "UserSummary",
    ("principal", "list_principals"): "PrincipalSummary",
    ("group", "list_groups"): "GroupSummary",
    ("board", "list_boards"): "BoardSummary",
    ("document", "list_documents"): "DocumentSummary",
    ("news", "list_news"): "NewsSummary",
    ("view", "list_views"): "ViewSummary",
    ("version", "list_versions"): "VersionSummary",
    ("sprint", "list_sprints"): "SprintSummary",
    ("backlog_bucket", "list_backlog_buckets"): "BacklogBucketSummary",
    ("category", "get_category"): "CategorySummary",
    ("grid", "list_grids"): "GridSummary",
    ("project_storage", "list_project_storages"): "ProjectStorageSummary",
    ("time_entry", "list_time_entries"): "TimeEntrySummary",
    ("meeting", "list_meetings"): "MeetingSummary",
    ("recurring_meeting", "list_recurring_meetings"): "RecurringMeetingSummary",
    ("recurring_meeting", "list_recurring_meeting_occurrences"): "RecurringMeetingOccurrenceSummary",
    ("notification", "list_notifications"): "NotificationSummary",
    ("relation", "list_relations"): "RelationSummary",
    ("capability", "list_capabilities"): "CapabilitySummary",
    ("non_working_day", "list_non_working_days"): "NonWorkingDay",
    ("user_non_working_time", "list_user_non_working_times"): "UserNonWorkingTimeSummary",
}


def _hiding(entity: str, *fields: str):
    from _client_test_helpers import _base_settings

    return dataclasses.replace(_base_settings(), hidden_fields={entity: tuple(fields)})


def test_the_table_is_the_one_written_here() -> None:
    actual = {key: (row.entity, row.fields, row.always) for key, row in filter_policy.FILTER_FIELDS.items()}

    assert actual == EXPECTED
    assert {key: row.also for key, row in filter_policy.FILTER_FIELDS.items() if row.also} == ALSO


def test_every_row_names_a_hide_entity_and_fields_of_the_record_it_filters() -> None:
    for (tool, parameter), (entity, fields, _) in EXPECTED.items():
        assert entity in HIDE_FIELD_ENV_BY_ENTITY, (tool, parameter)
        record = getattr(models, RECORD_OF[(entity, tool)])
        known = {field.name for field in dataclasses.fields(record)}
        assert set(fields) <= known, (tool, parameter, sorted(set(fields) - known))


@pytest.mark.parametrize(
    ("tool", "parameter", "field"),
    [(tool, parameter, field) for (tool, parameter), (_, fields, _) in EXPECTED.items() for field in fields],
)
def test_a_field_hidden_alone_refuses_the_parameter_with_the_exact_text(tool: str, parameter: str, field: str) -> None:
    entity = EXPECTED[(tool, parameter)][0]
    settings = _hiding(entity, field)

    with pytest.raises(InvalidInputError) as refusal:
        filter_policy.ensure_filter_allowed(tool, settings=settings, **{parameter: VALUE[parameter]})

    assert str(refusal.value) == (
        f"OpenProject {entity.replace('_', ' ')} field '{field}' is hidden by {HIDE_FIELD_ENV_BY_ENTITY[entity]} "
        f"and cannot be used to filter ('{parameter}')."
    )


@pytest.mark.parametrize(("tool", "parameter"), sorted(EXPECTED))
def test_another_hidden_field_of_the_entity_or_nothing_hidden_refuses_nothing(tool: str, parameter: str) -> None:
    from _client_test_helpers import _base_settings

    entity, fields, _ = EXPECTED[(tool, parameter)]
    record = getattr(models, RECORD_OF[(entity, tool)])
    others = [f.name for f in dataclasses.fields(record) if f.name not in fields]
    assert others, (tool, parameter)

    filter_policy.ensure_filter_allowed(tool, settings=_base_settings(), **{parameter: VALUE[parameter]})
    filter_policy.ensure_filter_allowed(tool, settings=_hiding(entity, others[0]), **{parameter: VALUE[parameter]})


@pytest.mark.parametrize(("tool", "parameter"), sorted(EXPECTED))
def test_a_parameter_that_carries_no_value_refuses_nothing_unless_its_default_selects(
    tool: str, parameter: str
) -> None:
    entity, fields, always = EXPECTED[(tool, parameter)]
    settings = _hiding(entity, *fields)

    for empty in (None, "", [], False):
        if always:
            with pytest.raises(InvalidInputError):
                filter_policy.ensure_filter_allowed(tool, settings=settings, **{parameter: empty})
        else:
            filter_policy.ensure_filter_allowed(tool, settings=settings, **{parameter: empty})


def test_the_wildcard_refuses_every_row() -> None:
    from _client_test_helpers import _base_settings

    for (tool, parameter), (entity, _, _) in EXPECTED.items():
        settings = dataclasses.replace(_base_settings(), hidden_fields={entity: ("*",)})
        with pytest.raises(InvalidInputError):
            filter_policy.ensure_filter_allowed(tool, settings=settings, **{parameter: VALUE[parameter]})


def test_the_key_is_the_tool_and_the_parameter_not_the_entity_or_the_name() -> None:
    category = _hiding("category", "project_id")
    meeting = _hiding("recurring_meeting", "start_time")

    # `list_categories.project` is a required container and not in the table; `get_category.project` is a filter.
    filter_policy.ensure_filter_allowed("list_categories", settings=category, project="demo")
    with pytest.raises(InvalidInputError):
        filter_policy.ensure_filter_allowed("get_category", settings=category, project="demo")
    # The occurrences select by their default; the lists of meetings of the same entity select by nothing here.
    filter_policy.ensure_filter_allowed("list_recurring_meetings", settings=meeting)
    with pytest.raises(InvalidInputError):
        filter_policy.ensure_filter_allowed("list_recurring_meeting_occurrences", settings=meeting)


def test_a_coupled_pair_refuses_when_either_member_is_hidden() -> None:
    for hidden in ("user", "user_id"):
        with pytest.raises(InvalidInputError, match=f"field '{hidden}'"):
            filter_policy.ensure_filter_allowed("list_time_entries", settings=_hiding("time_entry", hidden), user="7")


@pytest.mark.parametrize(
    ("tool", "parameter", "entity", "field"),
    [(tool, parameter, entity, field) for (tool, parameter), owners in ALSO.items() for entity, field in owners],
)
def test_another_owner_of_the_same_value_refuses_the_parameter_too(
    tool: str, parameter: str, entity: str, field: str
) -> None:
    with pytest.raises(InvalidInputError) as refusal:
        filter_policy.ensure_filter_allowed(tool, settings=_hiding(entity, field), **{parameter: VALUE[parameter]})

    assert f"OpenProject {entity.replace('_', ' ')} field '{field}' is hidden by" in str(refusal.value)


def test_every_owner_of_a_field_the_result_repeats_refuses_the_parameter() -> None:
    """A field of a row that the result class lists in `READ_IDENTITY_FIELDS` has more owners than its entity: each
    one hides the value from the result, so each one has to close the filter that selects by it."""
    for (tool, parameter), (entity, fields, _) in EXPECTED.items():
        owners = {(entity, field) for field in fields} | set(ALSO.get((tool, parameter), ()))
        for field in fields:
            repeated = READ_IDENTITY_FIELDS.get(RECORD_OF[(entity, tool)], {}).get(field, ())
            assert set(repeated) <= owners, (tool, parameter, field, sorted(set(repeated) - owners))


def test_a_coupled_group_of_the_entity_that_touches_a_row_is_whole_in_the_row() -> None:
    for (tool, parameter), (entity, fields, _) in EXPECTED.items():
        for group in COUPLED_FIELDS.get(entity, ()):
            if set(group) & set(fields):
                assert set(group) <= set(fields), (tool, parameter, group)
