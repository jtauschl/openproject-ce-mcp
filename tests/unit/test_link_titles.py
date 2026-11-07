from __future__ import annotations

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.link_titles import KEPT_LINK_NAMES, without_foreign_capable_titles
from openproject_ce_mcp.app.services._write_outcome import _finalize_write


def _link(name: str) -> dict:
    return {"href": f"/api/v3/{name}/1", "title": f"title of {name}", "displayId": f"{name}-1"}


def test_links_that_can_point_into_another_project_keep_only_their_href() -> None:
    payload = {
        "subject": "kept",
        "_links": {
            "parent": _link("parent"),
            "version": _link("version"),
            "targetVersions": [_link("v1"), _link("v2")],
            "sprint": _link("sprint"),
            "customField7": _link("custom"),
        },
    }

    shown = without_foreign_capable_titles(payload)

    assert shown["subject"] == "kept"
    assert shown["_links"]["parent"] == {"href": "/api/v3/parent/1"}
    assert shown["_links"]["version"] == {"href": "/api/v3/version/1"}
    assert shown["_links"]["targetVersions"] == [{"href": "/api/v3/v1/1"}, {"href": "/api/v3/v2/1"}]
    assert shown["_links"]["sprint"] == {"href": "/api/v3/sprint/1"}
    assert shown["_links"]["customField7"] == {"href": "/api/v3/custom/1"}


@pytest.mark.parametrize("name", sorted(KEPT_LINK_NAMES))
def test_links_to_resources_every_user_sees_alike_keep_their_title(name: str) -> None:
    payload = {"_links": {name: _link(name)}}

    assert without_foreign_capable_titles(payload) == payload


def test_a_filter_value_of_a_board_query_loses_its_title_but_the_filter_keeps_its_name() -> None:
    payload = {
        "filters": [
            {
                "_links": {
                    "filter": {"href": "/api/v3/queries/filters/project", "title": "Project"},
                    "operator": {"href": "/api/v3/queries/operators/=", "title": "is"},
                    "values": [{"href": "/api/v3/projects/9", "title": "Secret project"}],
                }
            }
        ]
    }

    shown = without_foreign_capable_titles(payload)["filters"][0]["_links"]

    assert shown["filter"]["title"] == "Project"
    assert shown["operator"]["title"] == "is"
    assert shown["values"] == [{"href": "/api/v3/projects/9"}]


def test_the_original_payload_is_left_alone() -> None:
    payload = {"_links": {"parent": _link("parent")}}

    without_foreign_capable_titles(payload)

    assert payload["_links"]["parent"]["title"] == "title of parent"


def test_scalars_and_empty_links_pass_through() -> None:
    assert without_foreign_capable_titles({"_links": {}, "n": 1, "none": None}) == {"_links": {}, "n": 1, "none": None}
    assert without_foreign_capable_titles({"_links": {"parent": {"href": None}}}) == {
        "_links": {"parent": {"href": None}}
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("confirm", "errors", "state"), [(False, {}, "preview"), (False, {"x": "bad"}, "rejected"), (True, {}, "confirmed")]
)
async def test_every_write_outcome_shows_the_reduced_payload_while_the_commit_gets_the_form_payload(
    confirm: bool, errors: dict, state: str
) -> None:
    payload = {"_links": {"parent": _link("parent")}}
    committed: list[dict] = []

    async def commit(sent: dict) -> str:
        committed.append(sent)
        return "detail"

    outcome = await _finalize_write(
        confirm=confirm,
        entity="project",
        settings=make_settings(),
        payload=payload,
        validation_errors=errors,
        identity={},
        ensure_write_enabled=lambda: None,
        commit=commit,
        committed_identity=lambda detail: {},
        rejected_message="r",
        preview_message="p",
        success_message="s",
    )

    assert outcome.state == state
    assert outcome.payload == {"_links": {"parent": {"href": "/api/v3/parent/1"}}}
    if confirm and not errors:
        assert committed == [payload]
        assert committed[0]["_links"]["parent"]["title"] == "title of parent"
