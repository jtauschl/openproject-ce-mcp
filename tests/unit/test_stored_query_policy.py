"""A saved query that selects, orders or groups by a hidden field is refused.

The expectation is a literal table here, not read from `STORED_FILTER_OWNERS`: a removed or changed row fails a
test instead of removing its own case. Stated boundary: the names of the filters are those of the server sources of
every pinned release (the census in `test_query_filter_keys_oracle.py`); the operators that name a state were read
in the server sources of 17.9 (`status`: `o`, `c`; the version filters: `o`, `c`, `l`), the older releases were not
read per release; a sort and a group name the server may add are refused while a setting is active, not judged.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import InvalidInputError
from openproject_ce_mcp.app.policies.stored_query_policy import (
    NOT_HIDEABLE_FILTERS,
    STATE_OPERATOR_OWNERS,
    STORED_COLUMN_OWNERS,
    STORED_FILTER_OWNERS,
    ensure_stored_query_allowed,
)
from openproject_ce_mcp.app.policies.stored_query_policy import (
    OPERATORS_WITHOUT_OWNERS as POLICY_OPERATORS_WITHOUT_OWNERS,
)
from openproject_ce_mcp.app.stored_query import StoredFilter, StoredQuery, StoredSort
from openproject_ce_mcp.config import HIDE_FIELD_ENV_BY_ENTITY

WP = "work_package"
# A field of no entity: hiding it activates the entity's setting without closing any column or filter.
UNRELATED = "zzz_unrelated"
RELATION = (("relation", "type"), ("relation", "from_id"), ("relation", "to_id"))
PROJECT_HIERARCHY = (("project", "parent_id"), ("project", "parent_name"), ("project", "ancestors"))


def _wp(*fields: str) -> tuple[tuple[str, str], ...]:
    return tuple((WP, field) for field in fields)


WP_HIERARCHY = _wp("parent_id", "ancestors", "children")


FILTER_OWNERS = {
    "ancestor": WP_HIERARCHY,
    "assignedToRole": (
        *_wp("assignee"),
        ("membership", "principal_id"),
        ("membership", "role_ids"),
        ("membership", "role_names"),
    ),
    "assignee": _wp("assignee"),
    "assigneeOrGroup": (*_wp("assignee"), ("group", "members")),
    "attachmentFileName": (("attachment", "file_name"), ("attachment", "title")),
    "author": _wp("author"),
    "backlogBucket": (("backlog_bucket", "name"),),
    "backlogInbox": (*_wp("sprint"), ("backlog_bucket", "name")),
    "backlogsWorkPackageType": (*_wp("type"), *WP_HIERARCHY, *RELATION),
    "blocked": RELATION,
    "blocks": RELATION,
    "category": _wp("category"),
    "comment": (("activity", "comment"),),
    "createdAt": _wp("created_at"),
    "datesInterval": _wp("start_date", "due_date"),
    "description": _wp("description"),
    "dueDate": _wp("due_date"),
    "duplicated": RELATION,
    "duplicates": RELATION,
    "duration": (*_wp("duration", "type"), ("type", "is_milestone")),
    "estimatedTime": _wp("estimated_time"),
    "follows": RELATION,
    "id": _wp("id"),
    "includes": RELATION,
    "isMilestone": (*_wp("type"), ("type", "is_milestone")),
    "linkableToStorage": (("project_storage", "storage_id"), ("project_storage", "storage_name")),
    "linkableToStorageUrl": (("storage", "host"),),
    "memberOfGroup": (*_wp("assignee"), ("group", "members")),
    "observedInVersion": (("version", "name"),),
    "onlySubproject": (*_wp("project"), *PROJECT_HIERARCHY),
    "parent": _wp("parent_id", "children"),
    "partof": RELATION,
    "percentageDone": _wp("percentage_done"),
    "precedes": RELATION,
    "priority": _wp("priority"),
    "project": _wp("project"),
    "projectPhaseDefinition": _wp("project_phase"),
    "relatable": (*RELATION, *WP_HIERARCHY),
    "relates": RELATION,
    "required": RELATION,
    "requires": RELATION,
    "responsible": _wp("responsible"),
    "search": (
        *_wp("subject", "description", "custom_fields"),
        ("activity", "comment"),
        ("attachment", "file_name"),
        ("attachment", "title"),
    ),
    "sprint": _wp("sprint"),
    "startDate": _wp("start_date"),
    "status": _wp("status"),
    "storage": (("file_link", "storage_id"), ("file_link", "storage_name")),
    "storageUrl": (("storage", "host"),),
    "subject": _wp("subject"),
    "subjectOr": _wp("subject", "id"),
    "subprojectId": (*_wp("project"), *PROJECT_HIERARCHY),
    "targetVersion": _wp("version", "target_versions"),
    "type": _wp("type"),
    "typeahead": (*_wp("subject", "id", "display_id", "project", "type", "status"), ("status", "is_closed")),
    "updatedAt": _wp("updated_at"),
    "version": _wp("version", "target_versions"),
    "watcher": (("watcher", "id"), ("watcher", "name"), ("watcher", "login")),
}
NOT_HIDEABLE = {
    "attachmentContent",
    "bcfIssueAssociated",
    "budget",
    "fileLinkOrigin",
    "manualSort",
    "sharedWithMe",
    "sharedWithUser",
}
OPERATOR_OWNERS = {
    ("status", "o"): (("status", "is_closed"),),
    ("status", "c"): (("status", "is_closed"),),
    **{
        (key, operator): (("version", "status"),)
        for key in ("version", "targetVersion", "observedInVersion")
        for operator in ("o", "c", "l")
    },
}
OPERATORS_WITHOUT_OWNERS = {("subprojectId", "!*")}
# The API name of a sort or group column -> the pairs that show its value.
COLUMN_OWNERS = {
    "project": _wp("project"),
    "subject": _wp("subject"),
    "type": (*_wp("type"), ("type", "position")),
    "status": (*_wp("status"), ("status", "position")),
    "priority": (*_wp("priority"), ("priority", "position")),
    "author": (*_wp("author"), ("user", "id"), ("principal", "id")),
    "assignee": (*_wp("assignee"), ("user", "id"), ("group", "id"), ("principal", "id")),
    "responsible": (*_wp("responsible"), ("user", "id"), ("group", "id"), ("principal", "id")),
    "updatedAt": _wp("updated_at"),
    "category": _wp("category"),
    "version": _wp("version", "target_versions"),
    "targetVersions": _wp("version", "target_versions"),
    "observedInVersions": (("version", "name"),),
    "startDate": _wp("start_date"),
    "dueDate": _wp("due_date"),
    "estimatedTime": _wp("estimated_time"),
    "remainingTime": _wp("remaining_time"),
    "percentageDone": _wp("percentage_done"),
    "createdAt": _wp("created_at"),
    "duration": _wp("duration"),
    "projectPhase": _wp("project_phase"),
    "sprint": (*_wp("sprint"), ("sprint", "start_date"), ("sprint", "finish_date")),
    "backlogBucket": (("backlog_bucket", "name"),),
    "typeahead": _wp("updated_at"),
}
# `exactMatch` ranks by the term of a typeahead filter and is a constant without one; that filter is judged on its own.
COLUMNS_WITHOUT_OWNER = ("id", "storyPoints", "position", "manualSorting", "exactMatch")


def _hiding(entity: str, *fields: str):
    return dataclasses.replace(make_settings(), hidden_fields={entity: tuple(fields)})


def _definition(
    *,
    filters: tuple[StoredFilter, ...] = (),
    sort_by: tuple[StoredSort, ...] = (),
    group_by: str | None = None,
    include_subprojects: bool = False,
    project_scoped: bool = False,
) -> StoredQuery:
    return StoredQuery(
        filters=filters,
        sort_by=sort_by,
        group_by=group_by,
        include_subprojects=include_subprojects,
        project_scoped=project_scoped,
    )


def _refusal(entity: str, field: str, subject: str) -> str:
    return (
        f"OpenProject {entity.replace('_', ' ')} field '{field}' is hidden by {HIDE_FIELD_ENV_BY_ENTITY[entity]} "
        f"and cannot be used by the saved query ({subject})."
    )


def test_the_tables_are_the_ones_written_here() -> None:
    assert STORED_FILTER_OWNERS == FILTER_OWNERS
    assert set(NOT_HIDEABLE_FILTERS) == NOT_HIDEABLE
    assert STATE_OPERATOR_OWNERS == OPERATOR_OWNERS
    assert set(POLICY_OPERATORS_WITHOUT_OWNERS) == OPERATORS_WITHOUT_OWNERS
    assert STORED_COLUMN_OWNERS == {"typeahead": COLUMN_OWNERS["typeahead"]}
    assert all(NOT_HIDEABLE_FILTERS.values())
    assert not set(FILTER_OWNERS) & NOT_HIDEABLE


@pytest.mark.parametrize(
    ("key", "entity", "field"),
    [(key, entity, field) for key, pairs in sorted(FILTER_OWNERS.items()) for entity, field in pairs],
)
def test_a_filter_is_closed_by_each_field_that_shows_its_value(key: str, entity: str, field: str) -> None:
    definition = _definition(filters=(StoredFilter(key, "="),))

    with pytest.raises(InvalidInputError) as refusal:
        ensure_stored_query_allowed(definition, settings=_hiding(entity, field))

    assert str(refusal.value) == _refusal(entity, field, f"filter '{key}'")
    ensure_stored_query_allowed(definition, settings=_hiding(entity, UNRELATED))
    ensure_stored_query_allowed(definition, settings=make_settings())


@pytest.mark.parametrize(
    ("key", "operator", "entity", "field"), [(*k, *v[0]) for k, v in sorted(OPERATOR_OWNERS.items())]
)
def test_an_operator_that_names_a_state_is_closed_by_the_entity_that_shows_the_state(
    key: str, operator: str, entity: str, field: str
) -> None:
    settings = _hiding(entity, field)

    with pytest.raises(InvalidInputError) as refusal:
        ensure_stored_query_allowed(_definition(filters=(StoredFilter(key, operator),)), settings=settings)

    assert str(refusal.value) == _refusal(entity, field, f"filter '{key}'")
    ensure_stored_query_allowed(_definition(filters=(StoredFilter(key, "="),)), settings=settings)


@pytest.mark.parametrize("key", sorted(NOT_HIDEABLE))
def test_a_filter_no_entity_shows_passes_while_other_fields_are_hidden(key: str) -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={WP: ("*",), "status": ("*",)})

    ensure_stored_query_allowed(_definition(filters=(StoredFilter(key, "="),)), settings=settings)


@pytest.mark.parametrize(
    ("column", "entity", "field"),
    [(column, entity, field) for column, pairs in sorted(COLUMN_OWNERS.items()) for entity, field in pairs],
)
def test_a_sort_and_a_group_are_closed_by_each_field_that_shows_the_column(
    column: str, entity: str, field: str
) -> None:
    settings = _hiding(entity, field)

    with pytest.raises(InvalidInputError) as sort_refusal:
        ensure_stored_query_allowed(_definition(sort_by=(StoredSort(column, "desc"),)), settings=settings)
    with pytest.raises(InvalidInputError) as group_refusal:
        ensure_stored_query_allowed(_definition(group_by=column), settings=settings)

    assert str(sort_refusal.value) == _refusal(entity, field, f"sort '{column}'")
    assert str(group_refusal.value) == _refusal(entity, field, f"group '{column}'")
    ensure_stored_query_allowed(
        _definition(sort_by=(StoredSort(column, "asc"),), group_by=column), settings=_hiding(entity, UNRELATED)
    )


@pytest.mark.parametrize("column", COLUMNS_WITHOUT_OWNER)
def test_a_column_no_field_shows_passes_while_other_fields_are_hidden(column: str) -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={WP: ("*",)})

    ensure_stored_query_allowed(_definition(sort_by=(StoredSort(column, "asc"),), group_by=None), settings=settings)


# --- custom fields --------------------------------------------------------------------------------------------------


def _custom_field_refusal(column: str, subject: str) -> str:
    return (
        f"OpenProject custom field '{column}' is hidden by OPENPROJECT_HIDE_CUSTOM_FIELDS or by the custom_fields "
        f"field of the work package hide setting and cannot be used by the saved query ({subject})."
    )


@pytest.mark.parametrize(
    "settings",
    [
        dataclasses.replace(make_settings(), hide_custom_fields=("customField5",)),
        _hiding(WP, "custom_fields"),
    ],
    ids=["custom field pattern", "custom_fields field"],
)
def test_a_custom_field_filter_sort_and_group_are_closed_like_the_typed_columns(settings: Any) -> None:
    for definition, subject in (
        (_definition(filters=(StoredFilter("customField5", "="),)), "filter 'customField5'"),
        (_definition(sort_by=(StoredSort("customField5", "asc"),)), "sort 'customField5'"),
        (_definition(group_by="customField5"), "group 'customField5'"),
    ):
        with pytest.raises(InvalidInputError) as refusal:
            ensure_stored_query_allowed(definition, settings=settings)
        assert str(refusal.value) == _custom_field_refusal("cf_5", subject)


def test_another_custom_field_stays_usable_while_one_is_hidden() -> None:
    settings = dataclasses.replace(make_settings(), hide_custom_fields=("customField5",))

    ensure_stored_query_allowed(
        _definition(
            filters=(StoredFilter("customField6", "="),),
            sort_by=(StoredSort("customField6", "asc"),),
            group_by="customField6",
        ),
        settings=settings,
    )


# --- what the policy does not know ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("definition", "subject"),
    [
        (_definition(filters=(StoredFilter("somethingNew", "="),)), "filter 'somethingNew'"),
        (_definition(sort_by=(StoredSort("somethingNew", "asc"),)), "sort 'somethingNew'"),
        (_definition(group_by="somethingNew"), "group 'somethingNew'"),
    ],
)
def test_a_part_the_policy_does_not_know_is_refused_while_any_setting_is_active(
    definition: StoredQuery, subject: str
) -> None:
    for settings in (_hiding("status", "color"), dataclasses.replace(make_settings(), hide_custom_fields=("x",))):
        with pytest.raises(InvalidInputError) as refusal:
            ensure_stored_query_allowed(definition, settings=settings)
        assert subject in str(refusal.value) and "does not know" in str(refusal.value)
    ensure_stored_query_allowed(definition, settings=make_settings())


def test_a_definition_the_adapter_could_not_read_is_refused_while_any_setting_is_active() -> None:
    with pytest.raises(InvalidInputError, match="could not be read"):
        ensure_stored_query_allowed(None, settings=_hiding("status", "color"))
    ensure_stored_query_allowed(None, settings=make_settings())


def test_nothing_is_refused_while_nothing_is_hidden() -> None:
    everything = _definition(
        filters=tuple(StoredFilter(key, "o") for key in (*FILTER_OWNERS, *NOT_HIDEABLE, "somethingNew")),
        sort_by=tuple(StoredSort(column, "asc") for column in (*COLUMN_OWNERS, "somethingNew")),
        group_by="status",
        include_subprojects=True,
        project_scoped=True,
    )

    ensure_stored_query_allowed(everything, settings=make_settings())


# --- the flags that select or order without a filter ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("entity", "field"),
    [("project", "parent_id"), ("project", "parent_name"), ("project", "ancestors")],
)
@pytest.mark.parametrize(
    "definition",
    [
        _definition(include_subprojects=True, project_scoped=True),
        _definition(include_subprojects=True, filters=(StoredFilter("project", "="),)),
    ],
    ids=["project link", "project filter"],
)
def test_including_subprojects_is_closed_by_the_hierarchy_fields_of_a_project(
    definition: StoredQuery, entity: str, field: str
) -> None:
    with pytest.raises(InvalidInputError) as refusal:
        ensure_stored_query_allowed(definition, settings=_hiding(entity, field))

    assert str(refusal.value) == _refusal(entity, field, "it includes subprojects")


@pytest.mark.parametrize(
    "definition",
    [
        _definition(include_subprojects=False, project_scoped=True),
        _definition(include_subprojects=True),
        _definition(include_subprojects=True, filters=(StoredFilter("status", "="),)),
    ],
    ids=["flag off", "global query", "no project selection"],
)
def test_the_subproject_flag_selects_nothing_where_it_is_off_or_the_query_is_global(definition: StoredQuery) -> None:
    ensure_stored_query_allowed(definition, settings=_hiding("project", "parent_id"))


def test_the_subproject_filter_with_none_keeps_the_bound_project_alone_and_selects_by_no_hidden_value() -> None:
    settings = _hiding("project", "parent_id")

    ensure_stored_query_allowed(_definition(filters=(StoredFilter("subprojectId", "!*"),)), settings=settings)
    ensure_stored_query_allowed(
        _definition(include_subprojects=True, project_scoped=True, filters=(StoredFilter("subprojectId", "!*"),)),
        settings=settings,
    )
    for operator in ("*", "=", "!"):
        with pytest.raises(InvalidInputError) as refusal:
            ensure_stored_query_allowed(
                _definition(filters=(StoredFilter("subprojectId", operator),)), settings=settings
            )
        assert str(refusal.value) == _refusal("project", "parent_id", "filter 'subprojectId'")


def test_an_explicit_subproject_filter_takes_the_place_of_the_flag() -> None:
    definition = _definition(
        include_subprojects=True, project_scoped=True, filters=(StoredFilter("subprojectId", "*"),)
    )

    with pytest.raises(InvalidInputError) as refusal:
        ensure_stored_query_allowed(definition, settings=_hiding("project", "parent_id"))

    assert str(refusal.value) == _refusal("project", "parent_id", "filter 'subprojectId'")


@pytest.mark.parametrize(
    "settings",
    [dataclasses.replace(make_settings(), hide_custom_fields=("customField5",)), _hiding(WP, "custom_fields")],
    ids=["custom field pattern", "custom_fields field"],
)
def test_a_text_search_is_closed_by_any_hidden_custom_field(settings: Any) -> None:
    with pytest.raises(InvalidInputError):
        ensure_stored_query_allowed(_definition(filters=(StoredFilter("search", "**"),)), settings=settings)


def test_the_text_search_names_the_custom_field_setting_when_a_pattern_is_hidden() -> None:
    settings = dataclasses.replace(make_settings(), hide_custom_fields=("customField5",))

    with pytest.raises(InvalidInputError) as refusal:
        ensure_stored_query_allowed(_definition(filters=(StoredFilter("search", "**"),)), settings=settings)

    assert str(refusal.value) == (
        "OpenProject custom fields are hidden by OPENPROJECT_HIDE_CUSTOM_FIELDS and the saved query's text search "
        "(filter 'search') matches their values."
    )
    ensure_stored_query_allowed(
        _definition(filters=(StoredFilter("search", "**"),)),
        settings=dataclasses.replace(make_settings(), hidden_fields={WP: (UNRELATED,)}),
    )


def test_the_exact_match_sort_ranks_by_the_typeahead_term_and_adds_no_owner_of_its_own() -> None:
    settings = _hiding(WP, "display_id")
    sort = (StoredSort("exactMatch", "desc"),)

    ensure_stored_query_allowed(_definition(sort_by=sort), settings=settings)
    with pytest.raises(InvalidInputError) as refusal:
        ensure_stored_query_allowed(
            _definition(filters=(StoredFilter("typeahead", "**"),), sort_by=sort), settings=settings
        )
    assert str(refusal.value) == _refusal(WP, "display_id", "filter 'typeahead'")


# --- the project a query is bound to ----------------------------------------------------------------------------------


@pytest.mark.parametrize("include_subprojects", [False, True], ids=["flag off", "flag on"])
@pytest.mark.parametrize(
    "filters",
    [(), (StoredFilter("subprojectId", "!*"),)],
    ids=["no filter", "the bound project alone"],
)
def test_a_query_bound_to_a_project_selects_by_the_project_of_the_rows(
    include_subprojects: bool, filters: tuple[StoredFilter, ...]
) -> None:
    definition = _definition(project_scoped=True, include_subprojects=include_subprojects, filters=filters)

    with pytest.raises(InvalidInputError) as refusal:
        ensure_stored_query_allowed(definition, settings=_hiding(WP, "project"))

    assert str(refusal.value) == _refusal(WP, "project", "it is bound to a project")
    ensure_stored_query_allowed(definition, settings=_hiding(WP, UNRELATED))
    unbound = _definition(include_subprojects=include_subprojects)
    ensure_stored_query_allowed(unbound, settings=_hiding(WP, "project"))


@pytest.mark.parametrize(
    "definition",
    [
        _definition(
            include_subprojects=True,
            project_scoped=True,
            filters=(StoredFilter("subprojectId", "!*"), StoredFilter("project", "=")),
        ),
        _definition(
            include_subprojects=True,
            filters=(StoredFilter("subprojectId", "!*"), StoredFilter("project", "=")),
        ),
    ],
    ids=["bound and a project filter", "global and a project filter"],
)
def test_an_explicit_project_filter_expands_to_the_descendants_whatever_the_subproject_filter_says(
    definition: StoredQuery,
) -> None:
    with pytest.raises(InvalidInputError) as refusal:
        ensure_stored_query_allowed(definition, settings=_hiding("project", "parent_id"))

    assert str(refusal.value) == _refusal("project", "parent_id", "it includes subprojects")
