"""What the work package adapter keeps of a link into a version or sprint, and of the others."""

from __future__ import annotations

import pytest

from openproject_ce_mcp.app.adapters._custom_fields import CUSTOM_FIELD_LIST_ITEM_LIMIT
from openproject_ce_mcp.app.adapters.httpx_work_package_api import (
    HttpxWorkPackageApi,
    collect_references,
    normalize_work_package_summary,
)
from openproject_ce_mcp.app.ports.scoped_reference import ScopedReference, VisibleReferences, reference_of_link
from openproject_ce_mcp.app.resource_href import ResourceLinks
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

LINKS = ResourceLinks("https://op.example.com")
SECRET = ScopedReference("version", 7)
OWN = ScopedReference("version", 8)
SPRINT = ScopedReference("sprint", 3)
NOTHING = VisibleReferences.only(())


def _version(version_id: int, title: str) -> dict:
    return {"href": f"/api/v3/versions/{version_id}", "title": title}


def _payload(**links: object) -> dict:
    return {"id": 6, "subject": "WP", "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}, **links}}


def _summary(payload: dict, visible: VisibleReferences):
    return normalize_work_package_summary(payload, text_limit=None, visible=visible, resource_links=LINKS)


@pytest.mark.parametrize(
    ("href", "expected"),
    [
        ("/api/v3/versions/7", SECRET),
        ("https://op.example.com/api/v3/versions/7", SECRET),
        ("/api/v3/sprints/3", SPRINT),
        ("/api/v3/backlog_buckets/4", ScopedReference("backlog_bucket", 4)),
        ("/api/v3/versions/no_version", None),
        ("/api/v3/versions/07", None),
        ("/api/v3/versions/7/", None),
        ("/api/v3/versions/7?x=1", None),
        ("/api/v3/versions/7#x", None),
        ("/api/v3/versions/%37", None),
        ("/api/v3/../v3/versions/7", None),
        ("/api/v3/projects/7/versions/7", None),
        ("/openproject/api/v3/versions/7", None),
        ("/api/v4/versions/7", None),
        ("/xxxxxxxx/versions/7", None),
        ("https://evil.example.com/api/v3/versions/7", None),
        ("http://op.example.com/api/v3/versions/7", None),
        ("https://user@op.example.com/api/v3/versions/7", None),
        ("/api/v3/projects/7", None),
        ("/api/v3/statuses/1", None),
        ("/api/v3/versions/99999999999999999999", None),
        ("versions/7", None),
        ("versions", None),
        (None, None),
    ],
)
def test_a_link_is_a_reference_only_in_the_exact_shape_of_this_instance(href, expected) -> None:
    assert reference_of_link({"href": href, "title": "x"}, LINKS) == expected


def test_a_link_follows_the_root_path_of_the_instance() -> None:
    links = ResourceLinks("https://op.example.com/openproject")

    assert reference_of_link({"href": "/openproject/api/v3/versions/7"}, links) == SECRET
    assert reference_of_link({"href": "/api/v3/versions/7"}, links) is None


def test_a_target_version_title_is_kept_only_for_a_visible_reference_and_in_server_order() -> None:
    payload = _payload(targetVersions=[_version(8, "Own"), _version(7, "Secret"), _version(9, "Other")])

    summary = _summary(payload, VisibleReferences.only([OWN, ScopedReference("version", 9)]))

    assert summary.target_versions == ["Own", "Other"]
    assert summary.version is None


def test_the_version_alias_names_the_version_only_when_the_whole_assignment_is_that_one_visible_version() -> None:
    visible = VisibleReferences.only([OWN])

    assert _summary(_payload(targetVersions=[_version(8, "Own")]), visible).version == "Own"
    assert _summary(_payload(targetVersions=[_version(8, "Own"), _version(7, "Secret")]), visible).version is None
    assert _summary(_payload(targetVersions=[_version(7, "Secret")]), visible).version is None


def test_the_legacy_version_link_is_reduced_like_the_target_versions() -> None:
    payload = _payload(version=_version(7, "Secret"))

    assert (_summary(payload, NOTHING).version, _summary(payload, NOTHING).target_versions) == (None, [])
    assert _summary(payload, VisibleReferences.only([SECRET])).version == "Secret"


def test_a_sprint_title_is_kept_only_for_a_visible_sprint() -> None:
    payload = _payload(sprint={"href": "/api/v3/sprints/3", "title": "Sprint 3"})

    assert _summary(payload, NOTHING).sprint is None
    assert _summary(payload, VisibleReferences.only([SPRINT])).sprint == "Sprint 3"


def test_every_title_is_kept_under_everything() -> None:
    payload = _payload(targetVersions=[_version(7, "Secret")], sprint={"href": "/api/v3/sprints/3", "title": "S"})

    summary = _summary(payload, VisibleReferences.everything())

    assert (summary.target_versions, summary.sprint) == (["Secret"], "S")


def test_a_single_version_custom_field_is_none_when_the_version_is_not_visible() -> None:
    payload = _payload(customField5=_version(7, "Secret"), customField6=_version(8, "Own"))

    summary = _summary(payload, VisibleReferences.only([OWN]))

    assert summary.custom_fields == {"customField5": None, "customField6": "Own"}


def test_a_multi_value_version_custom_field_drops_hidden_entries_before_the_item_cap() -> None:
    visible_ids = list(range(100, 100 + CUSTOM_FIELD_LIST_ITEM_LIMIT))
    links = [_version(7, "Secret"), *(_version(i, f"v{i}") for i in visible_ids)]
    visible = VisibleReferences.only(ScopedReference("version", i) for i in visible_ids)

    summary = _summary(_payload(customField5=links), visible)

    assert summary.custom_fields == {"customField5": [f"v{i}" for i in visible_ids]}
    assert summary.custom_fields_truncated is False


def test_custom_field_titles_of_resources_without_a_project_are_kept() -> None:
    payload = _payload(
        customField1={"href": "/api/v3/custom_options/4", "title": "High"},
        customField2={"href": "/api/v3/users/9", "title": "Ada"},
        customField3=[{"href": "/api/v3/groups/2", "title": "Team"}],
    )

    assert _summary(payload, NOTHING).custom_fields == {
        "customField1": "High",
        "customField2": "Ada",
        "customField3": ["Team"],
    }


@pytest.mark.parametrize(
    "link",
    [
        {"href": "/api/v3/projects/9", "title": "Secret project"},
        {"href": "/api/v3/something/9", "title": "Unknown"},
        {"href": None, "title": "No href"},
        {"title": "No href key"},
        {"href": "/api/v3/versions/latest", "title": "Unparseable"},
    ],
)
def test_a_custom_field_link_into_any_other_resource_loses_its_title(link) -> None:
    assert _summary(_payload(customField1=link), VisibleReferences.everything()).custom_fields == {"customField1": None}


def test_the_references_of_a_payload_are_listed_per_result_field() -> None:
    payload = _payload(
        version=_version(7, "Secret"),
        targetVersions=[_version(7, "Secret"), _version(8, "Own")],
        sprint={"href": "/api/v3/sprints/3", "title": "S"},
        customField5=[_version(9, "In list")],
        customField6={"href": "/api/v3/custom_options/4", "title": "High"},
    )

    assert collect_references(payload, LINKS) == {
        "version": frozenset({SECRET}),
        "target_versions": frozenset({SECRET, OWN}),
        "sprint": frozenset({SPRINT}),
        "customField5": frozenset({ScopedReference("version", 9)}),
    }


def test_a_record_names_nothing_until_it_is_asked_for_a_summary_with_a_decision() -> None:
    api = HttpxWorkPackageApi(HttpxTransport(None), base_url="https://op.example.com")  # type: ignore[arg-type]
    payload = _payload(targetVersions=[_version(7, "Secret")])

    record = api.to_record(payload, text_limit=None)

    assert record.references == {"target_versions": frozenset({SECRET})}
    assert record.scoped_summary(visible=NOTHING).target_versions == []
    assert record.scoped_summary(visible=VisibleReferences.only([SECRET])).target_versions == ["Secret"]
    assert record.scoped_detail(visible=NOTHING).target_versions == []
