"""Which columns the project list sorts by, the release each needs, and what a hidden field closes."""

from __future__ import annotations

import dataclasses
import inspect

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp import column_floors
from openproject_ce_mcp.app.errors import InvalidInputError
from openproject_ce_mcp.app.policies import hidden_fields
from openproject_ce_mcp.app.policies.project_query_policy import ensure_query_allowed
from openproject_ce_mcp.app.services.project_service import ProjectService
from openproject_ce_mcp.models import ProjectSummary
from openproject_ce_mcp.project_columns import (
    COLUMN_FLOORS,
    COLUMN_RESULT_FIELDS,
    FILTER_RESULT_FIELDS,
    SORTABLE_FIELDS,
    floors_used,
    is_sortable,
    sort_by_description,
)
from openproject_ce_mcp.tools_validation import _validate_project_sort_by

# The keys the order classes of app/models/queries/projects/ register on OpenProject 16.0 to 17.9
# (tools/api-check/check_api.py proves each against the sources of every pinned release).
_SERVER_KEYS = {
    "id",
    "identifier",
    "created_at",
    "public",
    "lft",
    "name",
    "latest_activity_at",
    "project_status",
    "required_disk_space",
    "typeahead",
    "updated_at",
}
_NOT_FILTERS = {"self", "offset", "limit", "sort_by"}


def test_the_sortable_columns_are_the_keys_of_the_servers_order_classes() -> None:
    assert SORTABLE_FIELDS == _SERVER_KEYS


def test_only_updated_at_needs_a_release_after_the_first_supported_one() -> None:
    assert COLUMN_FLOORS == {"updated_at": "16.5"}
    assert set(COLUMN_FLOORS) <= SORTABLE_FIELDS


@pytest.mark.parametrize("field", sorted(_SERVER_KEYS) + ["cf_1", "cf_120", "project_phase_3", "project_phase_77"])
def test_a_server_key_or_an_id_key_is_sortable(field: str) -> None:
    assert is_sortable(field)
    assert [c.field for c in _validate_project_sort_by([f"{field}:desc"]) or []] == [field]


@pytest.mark.parametrize(
    "field",
    ["description", "status", "cf_0", "cf_01", "cf_", "cf_x", "project_phase_", "project_phase_0", "customField1"],
)
def test_any_other_column_is_refused_with_the_valid_set(field: str) -> None:
    assert not is_sortable(field)
    with pytest.raises(ValueError, match=f"sort_by\\[0\\]: unknown field '{field}'.*name.*cf_<id>.*project_phase_<id>"):
        _validate_project_sort_by([field])


def test_the_sort_criteria_grammar_and_the_empty_list_follow_the_work_package_tool() -> None:
    assert _validate_project_sort_by(None) is None
    assert _validate_project_sort_by([]) is None
    assert [
        (c.field, c.direction) for c in _validate_project_sort_by(["name", "created_at-desc", "cf_2:asc"]) or []
    ] == [
        ("name", "asc"),
        ("created_at", "desc"),
        ("cf_2", "asc"),
    ]
    with pytest.raises(ValueError, match="direction must be"):
        _validate_project_sort_by(["name:sideways"])


def test_floors_used_names_only_the_columns_that_have_one_oldest_first() -> None:
    assert floors_used(["name", "updated_at", "cf_1"]) == [("updated_at", "16.5")]
    assert floors_used(["name"]) == []
    assert column_floors.floors_used(["b", "a", None], {"a": "17.1", "b": "16.5"}) == [("b", "16.5"), ("a", "17.1")]


def test_the_description_names_every_column_the_family_keys_and_the_floor() -> None:
    description = sort_by_description()

    for field in SORTABLE_FIELDS:
        assert field in description
    assert "cf_<id>" in description and "project_phase_<id>" in description and "updated_at 16.5+" in description
    assert "text" in description


def test_every_sort_column_is_classified_as_a_result_field_or_without_one() -> None:
    without_result_field = {"lft", "latest_activity_at", "required_disk_space"}

    assert set(COLUMN_RESULT_FIELDS) | without_result_field == SORTABLE_FIELDS
    assert not set(COLUMN_RESULT_FIELDS) & without_result_field


def test_every_filter_parameter_of_the_list_is_classified() -> None:
    parameters = set(inspect.signature(ProjectService.list).parameters) - _NOT_FILTERS

    assert set(FILTER_RESULT_FIELDS) == parameters


def test_every_named_result_field_exists_on_the_project_summary() -> None:
    summary_fields = {field.name for field in dataclasses.fields(ProjectSummary)}
    named = {f for fields in (*COLUMN_RESULT_FIELDS.values(), *FILTER_RESULT_FIELDS.values()) for f in fields}

    assert named <= summary_fields


def _hiding(**kwargs):
    return dataclasses.replace(make_settings(), **kwargs)


@pytest.mark.parametrize(
    ("hidden", "filters", "sort"),
    [
        ("name", [], ["name"]),
        ("name", [], ["typeahead"]),
        ("name", ["search"], []),
        ("identifier", ["search"], []),
        ("identifier", [], ["identifier"]),
        ("id", [], ["id"]),
        ("public", [], ["public"]),
        ("created_at", [], ["created_at"]),
        ("updated_at", [], ["updated_at"]),
        ("status", [], ["project_status"]),
        ("custom_fields", ["custom_field_filters"], []),
        ("custom_fields", [], ["cf_4"]),
    ],
)
def test_a_hidden_project_field_closes_its_filters_and_columns(hidden: str, filters, sort) -> None:
    with pytest.raises(InvalidInputError, match="hidden by OPENPROJECT_HIDE"):
        ensure_query_allowed(settings=_hiding(hidden_fields={"project": (hidden,)}), filters=filters, sort_fields=sort)


def test_columns_without_a_result_field_stay_open_under_any_hide_setting() -> None:
    settings = _hiding(hidden_fields={"project": ("name", "identifier", "status", "public", "id")})

    ensure_query_allowed(
        settings=settings,
        filters=[],
        sort_fields=["lft", "latest_activity_at", "required_disk_space", "project_phase_2"],
    )


@pytest.mark.parametrize("pattern", ["customField4", "cf_4", "customField*"])
def test_a_hidden_custom_field_closes_its_sort_column_under_either_spelling_of_the_pattern(pattern: str) -> None:
    with pytest.raises(InvalidInputError, match="custom field 'cf_4' is hidden"):
        ensure_query_allowed(settings=_hiding(hide_custom_fields=(pattern,)), filters=[], sort_fields=["cf_4"])


def test_another_custom_field_stays_open() -> None:
    ensure_query_allowed(settings=_hiding(hide_custom_fields=("customField4",)), filters=[], sort_fields=["cf_5"])


def test_the_column_check_matches_cf_columns_only() -> None:
    settings = _hiding(hide_custom_fields=("customField*",))

    assert hidden_fields.custom_field_column_hidden("cf_4", entity="project", settings=settings)
    assert not hidden_fields.custom_field_column_hidden("name", entity="project", settings=settings)
    assert not hidden_fields.custom_field_column_hidden("cf_0", entity="project", settings=settings)
    assert not hidden_fields.custom_field_column_hidden("xcf_4", entity="project", settings=settings)
