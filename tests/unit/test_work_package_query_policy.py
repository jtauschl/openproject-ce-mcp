"""A hidden work package field cannot be used to filter, sort or group either."""

from __future__ import annotations

import dataclasses
import inspect

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import InvalidInputError
from openproject_ce_mcp.app.policies.work_package_query_policy import ensure_query_allowed
from openproject_ce_mcp.app.services.work_package_service import WorkPackageService
from openproject_ce_mcp.config import Settings
from openproject_ce_mcp.models import WorkPackageSummary
from openproject_ce_mcp.work_package_columns import (
    COLUMN_RESULT_FIELDS,
    COLUMNS_WITHOUT_RESULT_FIELD,
    FILTER_RESULT_FIELDS,
    GROUPABLE_FIELDS,
    SORTABLE_FIELDS,
)

NOT_FILTERS = {"self", "sort_by", "group_by", "offset", "limit", "include_sums"}


def _hiding(*fields: str):
    return dataclasses.replace(make_settings(), hidden_fields={"work_package": fields})


def test_every_sort_column_is_classified_as_a_result_field_or_as_without_one() -> None:
    assert set(COLUMN_RESULT_FIELDS) | COLUMNS_WITHOUT_RESULT_FIELD == SORTABLE_FIELDS
    assert not set(COLUMN_RESULT_FIELDS) & COLUMNS_WITHOUT_RESULT_FIELD
    assert GROUPABLE_FIELDS <= SORTABLE_FIELDS


def test_every_filter_parameter_of_the_list_and_search_tools_is_classified() -> None:
    list_parameters = set(inspect.signature(WorkPackageService.list).parameters) - NOT_FILTERS
    search_parameters = set(inspect.signature(WorkPackageService.search).parameters) - NOT_FILTERS

    assert set(FILTER_RESULT_FIELDS) == list_parameters | search_parameters


def test_every_named_result_field_exists() -> None:
    summary_fields = {field.name for field in dataclasses.fields(WorkPackageSummary)}
    named = {f for fields in (*COLUMN_RESULT_FIELDS.values(), *FILTER_RESULT_FIELDS.values()) for f in fields}

    assert named <= summary_fields


@pytest.mark.parametrize(("column", "fields"), sorted(COLUMN_RESULT_FIELDS.items()))
def test_a_column_of_a_hidden_field_is_refused_for_sorting(column: str, fields: tuple[str, ...]) -> None:
    for field in fields:
        with pytest.raises(InvalidInputError, match=f"'{field}' is hidden.*cannot be used to sort"):
            ensure_query_allowed(settings=_hiding(field), filters=[], sort_fields=[column], group_by=None)

    ensure_query_allowed(settings=_hiding("description"), filters=[], sort_fields=[column], group_by=None)


@pytest.mark.parametrize("column", sorted(GROUPABLE_FIELDS & set(COLUMN_RESULT_FIELDS)))
def test_a_column_of_a_hidden_field_is_refused_for_grouping(column: str) -> None:
    field = COLUMN_RESULT_FIELDS[column][0]

    with pytest.raises(InvalidInputError, match="cannot be used to group"):
        ensure_query_allowed(settings=_hiding(field), filters=[], sort_fields=[], group_by=column)


@pytest.mark.parametrize(("parameter", "fields"), sorted(FILTER_RESULT_FIELDS.items()))
def test_a_filter_on_a_hidden_field_is_refused(parameter: str, fields: tuple[str, ...]) -> None:
    for field in fields:
        with pytest.raises(InvalidInputError, match="cannot be used to filter"):
            ensure_query_allowed(settings=_hiding(field), filters=[parameter], sort_fields=[], group_by=None)


@pytest.mark.parametrize("column", sorted(COLUMNS_WITHOUT_RESULT_FIELD))
def test_a_column_no_result_field_carries_is_never_refused(column: str) -> None:
    settings = _hiding("*")

    ensure_query_allowed(settings=settings, filters=[], sort_fields=[column], group_by=None)


def test_nothing_is_refused_while_no_field_is_hidden() -> None:
    ensure_query_allowed(
        settings=make_settings(),
        filters=list(FILTER_RESULT_FIELDS),
        sort_fields=list(COLUMN_RESULT_FIELDS),
        group_by="version",
    )


def test_the_hide_setting_is_read_through_the_real_configuration() -> None:
    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token",
            "OPENPROJECT_HIDE_WORK_PACKAGE_FIELDS": "assign*",
        }
    )

    with pytest.raises(InvalidInputError, match="'assignee' is hidden"):
        ensure_query_allowed(settings=settings, filters=[], sort_fields=["assigned_to"], group_by=None)


SUMS = {
    "estimatedTime": "P1D",
    "remainingTime": "PT1H",
    "percentageDone": 40,
    "storyPoints": 8,
    "overallCosts": "0.00 EUR",
    "customField5": 3,
}


def test_the_sums_of_a_hidden_field_are_left_out_and_the_others_stay() -> None:
    from openproject_ce_mcp.app.policies.work_package_query_policy import sums_without_hidden_fields

    settings = _hiding("estimated_time", "percentage_done")

    assert sums_without_hidden_fields(SUMS, settings=settings) == {
        "remainingTime": "PT1H",
        "storyPoints": 8,
        "overallCosts": "0.00 EUR",
        "customField5": 3,
    }
    assert sums_without_hidden_fields(None, settings=settings) is None


@pytest.mark.parametrize(
    "settings",
    [
        dataclasses.replace(make_settings(), hide_custom_fields=("customField5",)),
        dataclasses.replace(make_settings(), hidden_fields={"work_package": ("custom_fields",)}),
    ],
)
def test_the_sum_of_a_hidden_custom_field_is_left_out(settings) -> None:
    from openproject_ce_mcp.app.policies.work_package_query_policy import sums_without_hidden_fields

    assert "customField5" not in sums_without_hidden_fields(SUMS, settings=settings)  # type: ignore[operator]
    assert "estimatedTime" in sums_without_hidden_fields(SUMS, settings=settings)  # type: ignore[operator]


@pytest.mark.parametrize("pattern", ["customField4", "cf_4", "customField*"])
@pytest.mark.parametrize(("sort", "group"), [(["cf_4"], None), ([], "cf_4")])
def test_a_hidden_custom_field_closes_its_sort_and_group_column(pattern: str, sort, group) -> None:
    settings = dataclasses.replace(make_settings(), hide_custom_fields=(pattern,))

    with pytest.raises(InvalidInputError, match="custom field 'cf_4' is hidden"):
        ensure_query_allowed(settings=settings, filters=[], sort_fields=sort, group_by=group)


def test_the_custom_fields_hide_setting_of_work_packages_closes_every_custom_field_column() -> None:
    with pytest.raises(InvalidInputError, match="custom field 'cf_9' is hidden"):
        ensure_query_allowed(settings=_hiding("custom_fields"), filters=[], sort_fields=["cf_9"], group_by=None)
