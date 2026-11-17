"""A write result's `payload` shows no key that carries a field the hide settings name.

The server's form answer echoes every attribute the contract lets the caller write, sent or not, so a hidden
field's value would come back in a preview under its wire name. The tables of `app/policies/payload_fields.py` say
which model fields each key carries; the golden echoes below are written from the payload representers of
OpenProject 17.9 (not captured from a live instance: the key sets are "not verified live").
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp import models
from openproject_ce_mcp.app.policies import hidden_fields
from openproject_ce_mcp.app.policies.payload_fields import COUPLED_FIELDS, NO_FIELD, NOT_IN_PAYLOAD, PAYLOAD_KEYS
from openproject_ce_mcp.app.services._payload_masking import shown_payload
from openproject_ce_mcp.app.services._work_package_presentation import _VERSION_ALIASES
from openproject_ce_mcp.app.services.time_entry_service import _USER_ALIASES
from openproject_ce_mcp.app.services.user_service import _LOCK_STATE_ALIASES

_MODELS = {
    "user": ("UserSummary", "UserDetail"),
    "project": ("ProjectSummary", "ProjectDetail"),
    "version": ("VersionSummary", "VersionDetail"),
    "membership": ("MembershipSummary", "MembershipDetail"),
    "board": ("BoardSummary", "BoardDetail"),
    "grid": ("GridSummary", "GridDetail"),
    "meeting": ("MeetingSummary", "MeetingDetail"),
    "time_entry": ("TimeEntrySummary", "TimeEntryDetail"),
    "work_package": ("WorkPackageSummary", "WorkPackageDetail"),
}


def _model_fields(entity: str) -> set[str]:
    names: set[str] = set()
    for class_name in _MODELS[entity]:
        model = getattr(models, class_name, None)
        if model is not None:
            names |= {field.name for field in dataclasses.fields(model)}
    return names


def _settings(entity: str, *patterns: str):
    return dataclasses.replace(make_settings(), hidden_fields={entity: tuple(patterns)})


@pytest.mark.parametrize("entity", sorted(_MODELS))
def test_every_model_field_is_carried_by_a_key_or_listed_as_not_in_the_payload(entity: str) -> None:
    fields = _model_fields(entity)
    carried = {name for names in PAYLOAD_KEYS[entity].values() for name in names}
    not_in_payload = set(NOT_IN_PAYLOAD[entity])

    assert fields - carried - not_in_payload == set(), "a model field nobody classified"
    assert (carried | not_in_payload) - fields == set(), "a table names a field the models do not have"
    assert carried & not_in_payload == set()
    assert all(NOT_IN_PAYLOAD[entity].values()), "every entry needs its reason"


@pytest.mark.parametrize("entity", sorted(_MODELS))
def test_no_key_is_both_carried_and_listed_as_carrying_no_field(entity: str) -> None:
    assert set(PAYLOAD_KEYS[entity]) & NO_FIELD[entity] == set()
    assert all(names for names in PAYLOAD_KEYS[entity].values())


def test_the_coupled_groups_are_the_alias_groups_the_services_stamp() -> None:
    assert COUPLED_FIELDS["user"] == (frozenset(_LOCK_STATE_ALIASES),)
    assert COUPLED_FIELDS["work_package"] == (frozenset(_VERSION_ALIASES),)
    assert COUPLED_FIELDS["time_entry"] == (frozenset(_USER_ALIASES),)
    for entity, groups in COUPLED_FIELDS.items():
        assert all(group <= _model_fields(entity) for group in groups)


# The form echo of each entity, written from the payload representer of 17.9. Keys under `_links` are written as
# `_links.<rel>`; `unpack` below turns the flat form into the payload dict a service shows.
ECHO: dict[str, dict[str, Any]] = {
    "user": {
        "login": "ada",
        "admin": False,
        "firstName": "Ada",
        "lastName": "Lovelace",
        "email": "ada@example.com",
        "status": "locked",
        "identityUrl": "oidc:1",
        "language": "en",
    },
    "project": {
        "name": "Demo",
        "identifier": "demo",
        "description": {"raw": "text"},
        "public": False,
        "active": True,
        "statusExplanation": {"raw": "why"},
        "createdAt": "2026-01-01T00:00:00Z",
        "_meta": {"sendNotifications": False},
        "_links.parent": {"href": "/api/v3/projects/1", "title": "Root"},
        "_links.status": {"href": "/api/v3/project_statuses/on_track"},
    },
    "version": {
        "name": "0.1",
        "description": {"raw": "d"},
        "startDate": "2026-01-01",
        "endDate": "2026-02-01",
        "status": "open",
        "sharing": "none",
        "_links.definingProject": {"href": "/api/v3/projects/6", "title": "Demo"},
    },
    "membership": {
        "_meta": {"sendNotifications": False},
        "_links.project": {"href": "/api/v3/projects/6", "title": "Demo"},
        "_links.principal": {"href": "/api/v3/users/5", "title": "Ada"},
        "_links.roles": [{"href": "/api/v3/roles/3", "title": "Member"}],
    },
    "board": {
        "name": "Board",
        "public": False,
        "starred": False,
        "includeSubprojects": True,
        "showHierarchies": False,
        "timelineVisible": False,
        "timelineZoomLevel": "days",
        "highlightingMode": "inline",
        "timestamps": ["PT0S"],
        "filters": [],
        "_links.project": {"href": "/api/v3/projects/6", "title": "Demo"},
        "_links.columns": [{"href": "/api/v3/queries/columns/id"}],
        "_links.sortBy": [{"href": "/api/v3/queries/sort_bys/id-asc"}],
        "_links.groupBy": {"href": None},
        "_links.highlightedAttributes": [],
    },
    "grid": {
        "_type": "Grid",
        "id": 4,
        "rowCount": 2,
        "columnCount": 3,
        "_links.scope": {"href": "/projects/demo/boards"},
    },
    "meeting": {
        "title": "Weekly",
        "location": "Room 1",
        "duration": 1.0,
        "state": "open",
        "startTime": "2026-03-01T10:00:00Z",
        "template": False,
        "notify": True,
        "sharing": "none",
        "lockVersion": 2,
        "_links.author": {"href": "/api/v3/users/5", "title": "Ada"},
        "_links.project": {"href": "/api/v3/projects/6", "title": "Demo"},
        "_links.recurringMeeting": {"href": "/api/v3/recurring_meetings/1"},
        "_links.participants": [{"href": "/api/v3/users/7"}],
    },
    "time_entry": {
        "ongoing": False,
        "comment": {"raw": "c"},
        "spentOn": "2026-03-01",
        "hours": "PT2H",
        "startTime": "09:00",
        "_links.project": {"href": "/api/v3/projects/6", "title": "Demo"},
        "_links.entity": {"href": "/api/v3/work_packages/9", "title": "WP"},
        "_links.user": {"href": "/api/v3/users/5", "title": "Ada"},
        "_links.activity": {"href": "/api/v3/time_entries/activities/1"},
    },
    "work_package": {
        "subject": "S",
        "description": {"raw": "d"},
        "scheduleManually": False,
        "startDate": "2026-03-01",
        "dueDate": "2026-03-05",
        "date": "2026-03-01",
        "estimatedTime": "PT8H",
        "remainingTime": "PT4H",
        "duration": "P5D",
        "ignoreNonWorkingDays": False,
        "percentageDone": 10,
        "lockVersion": 3,
        "createdAt": "2026-03-01T00:00:00Z",
        "_meta": {},
        "_links.type": {"href": "/api/v3/types/1"},
        "_links.status": {"href": "/api/v3/statuses/1"},
        "_links.priority": {"href": "/api/v3/priorities/8"},
        "_links.category": {"href": None},
        "_links.project": {"href": "/api/v3/projects/6", "title": "Demo"},
        "_links.parent": {"href": "/api/v3/work_packages/2"},
        "_links.assignee": {"href": "/api/v3/users/5", "title": "Ada"},
        "_links.responsible": {"href": None},
        "_links.version": {"href": "/api/v3/versions/3"},
        "_links.targetVersions": [{"href": "/api/v3/versions/3"}],
        "_links.projectPhase": {"href": None},
        "_links.author": {"href": "/api/v3/users/5"},
        "_links.sprint": {"href": None},
    },
}

# For each field, the echo keys that disappear when only that field is hidden. Written by hand from the
# representers: it is the claim under test, independent of PAYLOAD_KEYS.
GONE: dict[str, dict[str, set[str]]] = {
    "user": {
        "login": {"login"},
        "admin": {"admin"},
        "firstname": {"firstName"},
        "lastname": {"lastName"},
        "name": {"firstName", "lastName"},
        "email": {"email"},
        "status": {"status"},
        "locked": {"status"},
        "identity_url": {"identityUrl"},
        "language": {"language"},
    },
    "project": {
        "name": {"name"},
        "identifier": {"identifier"},
        "description": {"description"},
        "public": {"public"},
        "active": {"active"},
        "status_explanation": {"statusExplanation"},
        "created_at": {"createdAt"},
        "parent_id": {"_links.parent"},
        "parent_name": {"_links.parent"},
        "status": {"_links.status"},
    },
    "version": {
        "name": {"name"},
        "description": {"description"},
        "start_date": {"startDate"},
        "end_date": {"endDate"},
        "status": {"status"},
        "sharing": {"sharing"},
        "defining_project": {"_links.definingProject"},
    },
    "membership": {
        "project_id": {"_links.project"},
        "project_name": {"_links.project"},
        "principal_id": {"_links.principal"},
        "principal_name": {"_links.principal"},
        "role_ids": {"_links.roles"},
        "role_names": {"_links.roles"},
    },
    "board": {
        "name": {"name"},
        "public": {"public"},
        "starred": {"starred"},
        "include_subprojects": {"includeSubprojects"},
        "show_hierarchies": {"showHierarchies"},
        "timeline_visible": {"timelineVisible"},
        "timeline_zoom_level": {"timelineZoomLevel"},
        "highlighting_mode": {"highlightingMode"},
        "timestamps": {"timestamps"},
        "filters": {"filters"},
        "project_id": {"_links.project"},
        "project": {"_links.project"},
        "columns": {"_links.columns"},
        "sort_by": {"_links.sortBy"},
        "group_by": {"_links.groupBy"},
        "highlighted_attributes": {"_links.highlightedAttributes"},
    },
    "grid": {
        "id": {"id"},
        "row_count": {"rowCount"},
        "column_count": {"columnCount"},
        "scope": {"_links.scope"},
    },
    "meeting": {
        "title": {"title"},
        "location": {"location"},
        "duration": {"duration"},
        "state": {"state"},
        "start_time": {"startTime"},
        "template": {"template"},
        "notify": {"notify"},
        "sharing": {"sharing"},
        "lock_version": {"lockVersion"},
        "author": {"_links.author"},
        "project_id": {"_links.project"},
        "project": {"_links.project"},
        "recurring_meeting_id": {"_links.recurringMeeting"},
        "participants": {"_links.participants"},
    },
    "time_entry": {
        "ongoing": {"ongoing"},
        "comment": {"comment"},
        "spent_on": {"spentOn"},
        "hours": {"hours"},
        "start_time": {"startTime"},
        "project": {"_links.project"},
        "entity_type": {"_links.entity"},
        "entity_id": {"_links.entity"},
        "entity_name": {"_links.entity"},
        "user": {"_links.user"},
        "user_id": {"_links.user"},
        "activity": {"_links.activity"},
    },
    "work_package": {
        "subject": {"subject"},
        "description": {"description"},
        "schedule_manually": {"scheduleManually"},
        "start_date": {"startDate", "date"},
        "due_date": {"dueDate", "date"},
        "estimated_time": {"estimatedTime"},
        "remaining_time": {"remainingTime"},
        "duration": {"duration"},
        "ignore_non_working_days": {"ignoreNonWorkingDays"},
        "percentage_done": {"percentageDone"},
        "lock_version": {"lockVersion"},
        "created_at": {"createdAt"},
        "type": {"_links.type"},
        "status": {"_links.status"},
        "priority": {"_links.priority"},
        "category": {"_links.category"},
        "project": {"_links.project"},
        "parent_id": {"_links.parent"},
        "parent_display_id": {"_links.parent"},
        "assignee": {"_links.assignee"},
        "responsible": {"_links.responsible"},
        "version": {"_links.version", "_links.targetVersions"},
        "target_versions": {"_links.version", "_links.targetVersions"},
        "project_phase": {"_links.projectPhase"},
        "author": {"_links.author"},
        "sprint": {"_links.sprint"},
    },
}


def _unpack(flat: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    links: dict[str, Any] = {}
    for key, value in flat.items():
        if key.startswith("_links."):
            links[key.removeprefix("_links.")] = value
        else:
            payload[key] = value
    return {**payload, "_links": links}


def _flat(payload: dict[str, Any]) -> set[str]:
    keys = {key for key in payload if key != "_links"}
    return keys | {f"_links.{rel}" for rel in payload.get("_links", {})}


def _cases() -> list[tuple[str, str]]:
    return [(entity, field) for entity, fields in GONE.items() for field in fields]


@pytest.mark.parametrize(("entity", "field"), _cases())
def test_hiding_one_field_removes_exactly_the_keys_that_carry_it(entity: str, field: str) -> None:
    echo = ECHO[entity]

    shown = shown_payload(_unpack(echo), entity=entity, settings=_settings(entity, field))

    assert _flat(shown) == set(echo) - GONE[entity][field]
    assert "_links" in shown


@pytest.mark.parametrize("entity", sorted(GONE))
def test_every_hide_able_field_of_the_entity_has_a_golden_row(entity: str) -> None:
    carried = {name for names in PAYLOAD_KEYS[entity].values() for name in names}
    assert carried == set(GONE[entity])


@pytest.mark.parametrize("entity", sorted(ECHO))
def test_nothing_is_removed_when_nothing_is_hidden(entity: str) -> None:
    payload = _unpack(ECHO[entity])

    assert shown_payload(payload, entity=entity, settings=make_settings()) == payload


@pytest.mark.parametrize("entity", sorted(ECHO))
def test_a_key_the_table_does_not_know_is_hidden_with_any_pattern_and_shown_without_one(entity: str) -> None:
    payload = _unpack({**ECHO[entity], "storyPoints": 5, "_links.backlogBucket": {"href": None}})

    assert _flat(shown_payload(payload, entity=entity, settings=make_settings())) >= {"storyPoints"}
    for pattern in ("zzz_no_such_field", "custom_field_*", "*"):
        shown = _flat(shown_payload(payload, entity=entity, settings=_settings(entity, pattern)))
        assert "storyPoints" not in shown and "_links.backlogBucket" not in shown, pattern


@pytest.mark.parametrize("entity", sorted(ECHO))
def test_a_key_that_carries_no_field_stays_visible(entity: str) -> None:
    payload = _unpack({**ECHO[entity], **{key: {} for key in NO_FIELD[entity]}})

    shown = shown_payload(payload, entity=entity, settings=_settings(entity, "*"))

    assert set(NO_FIELD[entity]) <= _flat(shown)
    assert "_links" in shown


@pytest.mark.parametrize("entity", ["project", "work_package", "time_entry", "version", "board"])
def test_a_custom_field_key_is_judged_by_the_custom_field_settings_alone(entity: str) -> None:
    flat = {**ECHO[entity], "customField5": "visible", "customComment5": "note", "_links.customField5": {}}
    static_field = next(iter(GONE[entity]))

    shown = shown_payload(_unpack(flat), entity=entity, settings=_settings(entity, static_field))

    assert {"customField5", "customComment5", "_links.customField5"} <= _flat(shown)
    hiding_custom = dataclasses.replace(make_settings(), hide_custom_fields=("customField5",))
    gone = _flat(shown_payload(_unpack(flat), entity=entity, settings=hiding_custom))
    assert not {"customField5", "customComment5", "_links.customField5"} & gone


def test_a_hide_pattern_of_another_entity_changes_nothing() -> None:
    payload = _unpack(ECHO["user"])

    assert shown_payload(payload, entity="user", settings=_settings("project", "*")) == payload


def test_a_legacy_project_hide_list_switches_the_unknown_key_rule_on() -> None:
    settings = dataclasses.replace(make_settings(), hide_project_fields=("status_explanation",))
    payload = _unpack({**ECHO["project"], "somethingNew": 1})

    shown = shown_payload(payload, entity="project", settings=settings)

    assert "somethingNew" not in shown and "statusExplanation" not in shown and "name" in shown


def test_payload_key_hidden_is_false_for_an_entity_without_a_table() -> None:
    assert not hidden_fields.payload_key_hidden("news", "title", settings=_settings("news", "*"))
