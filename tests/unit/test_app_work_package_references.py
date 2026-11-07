"""The decision which versions and sprints a work package result may name."""

from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import TransportError
from openproject_ce_mcp.app.ports.scoped_reference import ScopedReference, VisibleReferences
from openproject_ce_mcp.app.ports.work_package_api import WorkPackageGroupRecord, WorkPackageRecord
from openproject_ce_mcp.app.resource_href import ResourceLinks
from openproject_ce_mcp.app.services._scoped_references import field_with_visible_options
from openproject_ce_mcp.app.services._work_package_references import (
    HIDDEN_GROUP_LABEL,
    groups_for_result,
    hidden_references_replaced,
    visible_references,
)

SECRET = ScopedReference("version", 7)
OWN = ScopedReference("version", 8)
SPRINT = ScopedReference("sprint", 3)


def _record(references: dict[str, frozenset[ScopedReference]]) -> WorkPackageRecord:
    return WorkPackageRecord(
        id=1,
        project="Demo",
        references=references,
        payload={},
        summary_factory=lambda _visible: None,  # type: ignore[arg-type,return-value]
        detail_factory=lambda _visible: None,  # type: ignore[arg-type,return-value]
    )


class _Check:
    def __init__(self, outcomes: dict[ScopedReference, bool | Exception]) -> None:
        self._outcomes = outcomes
        self.calls: list[list[ScopedReference]] = []

    async def __call__(self, references):
        asked = list(references)
        self.calls.append(asked)
        return {reference: self._outcomes[reference] for reference in asked}


def _settings(**changes):
    return dataclasses.replace(make_settings(), read_projects=("demo",), **changes)


@pytest.mark.asyncio
async def test_everything_is_visible_under_a_wildcard_scope_without_a_request() -> None:
    check = _Check({})
    settings = dataclasses.replace(make_settings(), read_projects=("*",))

    visible = await visible_references(
        records=[_record({"target_versions": frozenset({SECRET})})], settings=settings, check=check
    )

    assert visible.contains(SECRET) and visible.contains(SPRINT)
    assert check.calls == []


@pytest.mark.asyncio
async def test_only_the_references_the_check_allows_are_visible() -> None:
    check = _Check({SECRET: False, OWN: True})

    visible = await visible_references(
        records=[_record({"target_versions": frozenset({SECRET, OWN})})], settings=_settings(), check=check
    )

    assert (visible.contains(SECRET), visible.contains(OWN), visible.contains(SPRINT)) == (False, True, False)


@pytest.mark.asyncio
async def test_a_reference_of_several_records_is_asked_once() -> None:
    check = _Check({SECRET: True})

    await visible_references(
        records=[_record({"version": frozenset({SECRET})}), _record({"target_versions": frozenset({SECRET})})],
        settings=_settings(),
        check=check,
    )

    assert check.calls == [[SECRET]]


@pytest.mark.asyncio
async def test_no_check_is_made_when_no_record_names_a_reference() -> None:
    check = _Check({})

    visible = await visible_references(records=[_record({})], settings=_settings(), check=check)

    assert not visible.contains(SECRET)
    assert check.calls == []


@pytest.mark.asyncio
async def test_a_failed_check_fails_the_whole_decision() -> None:
    check = _Check({SECRET: True, OWN: TransportError("timeout")})

    with pytest.raises(TransportError):
        await visible_references(
            records=[_record({"target_versions": frozenset({SECRET, OWN})})], settings=_settings(), check=check
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("hidden", "field"),
    [
        ({"hide_work_package_fields": ("version",)}, "target_versions"),
        ({"hide_work_package_fields": ("target_versions",)}, "version"),
        ({"hide_work_package_fields": ("sprint",)}, "sprint"),
        ({"hide_work_package_fields": ("custom_fields",)}, "customField5"),
        ({"hide_custom_fields": ("customField5",)}, "customField5"),
    ],
)
async def test_a_field_a_hide_setting_removes_costs_no_check_and_cannot_fail_the_read(hidden, field) -> None:
    check = _Check({SECRET: TransportError("timeout")})

    visible = await visible_references(
        records=[_record({field: frozenset({SECRET})})], settings=_settings(**hidden), check=check
    )

    assert check.calls == []
    assert not visible.contains(SECRET)


@pytest.mark.asyncio
async def test_a_shown_field_next_to_a_hidden_one_is_still_checked() -> None:
    check = _Check({SECRET: True, OWN: True})

    await visible_references(
        records=[_record({"sprint": frozenset({SECRET}), "customField5": frozenset({OWN})})],
        settings=_settings(hide_work_package_fields=("sprint",)),
        check=check,
    )

    assert check.calls == [[OWN]]


@pytest.mark.asyncio
async def test_the_references_of_groups_are_checked_with_those_of_the_records() -> None:
    check = _Check({SECRET: False, OWN: True})
    group = WorkPackageGroupRecord(value="Secret", count=1, sums=None, references=frozenset({SECRET}))

    visible = await visible_references(
        records=[_record({"target_versions": frozenset({OWN})})], groups=[group], settings=_settings(), check=check
    )

    assert check.calls == [[OWN, SECRET]]
    assert not visible.contains(SECRET)


def _group(value, *references: ScopedReference) -> WorkPackageGroupRecord:
    return WorkPackageGroupRecord(value=value, count=2, sums={"estimatedTime": "P1D"}, references=frozenset(references))


def test_groups_are_returned_as_the_server_sent_them_when_every_label_is_visible() -> None:
    groups = groups_for_result(
        [_group("Own", OWN), _group(None)], group_by="version", visible=VisibleReferences.only([OWN])
    )

    assert [(g.value, g.count, g.sums) for g in groups] == [
        ("Own", 2, {"estimatedTime": "P1D"}),
        (None, 2, {"estimatedTime": "P1D"}),
    ]


@pytest.mark.parametrize("group_by", ["version", "target_versions", "sprint", "status", None])
def test_a_group_named_after_a_reference_that_is_not_visible_keeps_its_totals_under_a_neutral_label(group_by) -> None:
    groups = groups_for_result(
        [_group("Own", OWN), _group("Secret", SECRET)], group_by=group_by, visible=VisibleReferences.only([OWN])
    )

    assert [(g.value, g.count, g.sums) for g in groups] == [
        ("Own", 2, {"estimatedTime": "P1D"}),
        (HIDDEN_GROUP_LABEL, 2, {"estimatedTime": "P1D"}),
    ]


@pytest.mark.parametrize("group_by", ["version", "target_versions", "observed_in_versions", "sprint", "backlog_bucket"])
def test_a_label_of_a_reference_column_without_a_link_to_check_is_relabelled(group_by) -> None:
    (group,) = groups_for_result([_group("Mystery")], group_by=group_by, visible=VisibleReferences.everything())

    assert (group.value, group.count) == (HIDDEN_GROUP_LABEL, 2)


@pytest.mark.parametrize("group_by", ["version", "backlog_bucket"])
def test_nothing_is_relabelled_when_the_label_names_a_visible_reference_or_no_value(group_by) -> None:
    bucket = ScopedReference("backlog_bucket", 4)
    groups = groups_for_result(
        [_group("Bucket", bucket), _group(None)], group_by=group_by, visible=VisibleReferences.only([bucket])
    )

    assert [g.value for g in groups] == ["Bucket", None]


@pytest.mark.parametrize("group_by", ["status", "assignee", "project", "category", None])
def test_a_label_without_a_link_is_kept_in_a_column_that_names_no_version_sprint_or_bucket(group_by) -> None:
    groups = groups_for_result([_group("Open")], group_by=group_by, visible=VisibleReferences.only([]))

    assert [g.value for g in groups] == ["Open"]


def _holding(**references: frozenset[ScopedReference]) -> WorkPackageRecord:
    return _record(references)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("links", "expected"),
    [
        (["targetVersions"], 1),
        (["version"], 1),
        (["sprint"], 1),
        (["observedInVersions"], 1),
        (["customField5"], 1),
        (["targetVersions", "version"], 1),
        (["targetVersions", "sprint", "customField5"], 3),
        (["observedInVersions", "sprint"], 2),
        (["subject", "status", "customField7"], 0),
        ([], 0),
    ],
)
async def test_a_write_replaces_the_hidden_assignments_of_the_fields_it_sets_and_no_others(links, expected) -> None:
    record = _holding(
        target_versions=frozenset({SECRET, OWN}),
        version=frozenset({SECRET}),
        sprint=frozenset({SPRINT}),
        observed_in_versions=frozenset({ScopedReference("version", 11)}),
        customField5=frozenset({ScopedReference("version", 9)}),
        customField6=frozenset({ScopedReference("version", 10)}),
    )
    check = _Check(
        {
            SECRET: False,
            OWN: True,
            SPRINT: False,
            ScopedReference("version", 11): False,
            ScopedReference("version", 9): False,
            ScopedReference("version", 10): False,
        }
    )

    assert await hidden_references_replaced(record, links, settings=_settings(), check=check) == expected


@pytest.mark.asyncio
async def test_a_write_replaces_nothing_hidden_under_a_wildcard_scope() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",))

    assert (
        await hidden_references_replaced(
            _holding(target_versions=frozenset({SECRET})), ["targetVersions"], settings=settings, check=_Check({})
        )
        == 0
    )


@pytest.mark.asyncio
async def test_a_failed_check_fails_the_write_check() -> None:
    check = _Check({SECRET: TransportError("timeout")})

    with pytest.raises(TransportError):
        await hidden_references_replaced(
            _holding(target_versions=frozenset({SECRET})), ["targetVersions"], settings=_settings(), check=check
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(("link", "carried"), [("version", "target_versions"), ("targetVersions", "version")])
async def test_version_and_target_versions_write_the_same_data_so_either_link_replaces_what_the_other_shows(
    link: str, carried: str
) -> None:
    record = _holding(**{carried: frozenset({SECRET})})

    assert await hidden_references_replaced(record, [link], settings=_settings(), check=_Check({SECRET: False})) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("hidden", "link", "field"),
    [
        ({"hide_work_package_fields": ("custom_fields",)}, "customField5", "customField5"),
        ({"hide_custom_fields": ("customField5",)}, "customField5", "customField5"),
        ({"hide_work_package_fields": ("sprint",)}, "sprint", "sprint"),
    ],
)
async def test_the_write_check_does_not_depend_on_what_a_hide_setting_removes_from_results(hidden, link, field) -> None:
    """A field the results do not show can still be written, and writing it still removes the assignment."""
    record = _holding(**{field: frozenset({SECRET})})

    count = await hidden_references_replaced(
        record, [link], settings=_settings(**hidden), check=_Check({SECRET: False})
    )
    covered = await hidden_references_replaced(
        record, [link], settings=_settings(**hidden), check=_Check({SECRET: True})
    )

    assert (count, covered) == (1, 0)


def _option(href: str, name: str) -> dict:
    return {"name": name, "_links": {"self": {"href": href}}}


def _version_field(*options: dict) -> dict:
    return {"name": "Target", "location": "_links", "_embedded": {"allowedValues": list(options)}}


_LINKS = ResourceLinks("https://op.example.com")
_OPTIONS = (
    _option("/api/v3/versions/7", "Secret release"),
    _option("/api/v3/versions/8", "Own release"),
    _option("/api/v3/custom_options/5", "Plain option"),
)


@pytest.mark.asyncio
async def test_a_field_loses_the_allowed_values_naming_a_reference_outside_the_scope() -> None:
    check = _Check({SECRET: False, OWN: True})

    field = await field_with_visible_options(_version_field(*_OPTIONS), links=_LINKS, settings=_settings(), check=check)

    assert [option["name"] for option in field["_embedded"]["allowedValues"]] == ["Own release", "Plain option"]
    assert check.calls == [[SECRET, OWN]]


@pytest.mark.asyncio
async def test_a_field_is_unchanged_under_a_wildcard_scope_and_without_a_request() -> None:
    check = _Check({})
    original = _version_field(*_OPTIONS)

    field = await field_with_visible_options(
        original, links=_LINKS, settings=dataclasses.replace(make_settings(), read_projects=("*",)), check=check
    )

    assert field is original
    assert check.calls == []


@pytest.mark.asyncio
async def test_a_field_without_references_among_its_values_asks_for_no_check() -> None:
    check = _Check({})
    original = _version_field(_OPTIONS[2])

    field = await field_with_visible_options(original, links=_LINKS, settings=_settings(), check=check)

    assert field is original
    assert check.calls == []


@pytest.mark.asyncio
async def test_a_failed_check_of_an_option_is_raised() -> None:
    check = _Check({SECRET: TransportError("down"), OWN: True})

    with pytest.raises(TransportError):
        await field_with_visible_options(_version_field(*_OPTIONS), links=_LINKS, settings=_settings(), check=check)
