"""The instances of a hidden value in a read result, one by one: what a caller sees in a read result once the field that owns a copy is hidden.

The scan (`test_read_results_hide_values_everywhere.py`) counts the copies; these goldens pin the shape: the member
that goes, the member that stays, the correlation `index` of a batch item, the rows of `children` and `ancestors`.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from _read_tool_harness import sentinel_id
from test_read_results_hide_values_everywhere import ARGUMENT_ID, DISPLAY_ID, _run_probe

from openproject_ce_mcp import models
from openproject_ce_mcp.app.services._payload_masking import stamp_result
from openproject_ce_mcp.presentation import _to_payload


async def _payload(tool: str, arguments: dict[str, Any], hidden: dict[str, tuple[str, ...]] | None = None) -> Any:
    run = await _run_probe(tool, arguments, hidden)
    assert run is not None, "the call is refused"
    return run[0], run[1]


@pytest.mark.asyncio
async def test_a_batch_item_keeps_its_position_when_the_reference_is_hidden() -> None:
    """`ids=[ref, ref again, other]` is read once per reference; the position is the first occurrence, 0 and 2."""
    ids = [DISPLAY_ID, DISPLAY_ID, "DEMO-93"]
    _, shown = await _payload("get_work_packages", {"ids": ids})
    assert [(item["id"], item["index"]) for item in shown["results"]] == [(DISPLAY_ID, 0), ("DEMO-93", 2)]

    for owner in ("id", "display_id"):
        _, hidden = await _payload("get_work_packages", {"ids": ids}, {"work_package": (owner,)})
        assert [item["index"] for item in hidden["results"]] == [0, 2]
        assert all("id" not in item for item in hidden["results"])


@pytest.mark.asyncio
async def test_a_batch_item_loses_its_id_under_select_as_well() -> None:
    body, _ = await _payload("get_work_packages", {"ids": [DISPLAY_ID]}, {"work_package": ("display_id",)})
    shown = _to_payload(body, select=frozenset({"subject"}), elide_none=True)

    assert shown["results"][0]["index"] == 0
    assert "id" not in shown["results"][0]


@pytest.mark.asyncio
@pytest.mark.parametrize("owner", ["id", "display_id"])
async def test_the_costs_of_a_display_id_do_not_name_the_resolved_id(owner: str) -> None:
    body, shown = await _payload("get_work_package_costs_by_type", {"work_package_id": DISPLAY_ID})
    assert shown["work_package_id"] == body.work_package_id

    _, hidden = await _payload(
        "get_work_package_costs_by_type", {"work_package_id": DISPLAY_ID}, {"work_package": (owner,)}
    )
    assert "work_package_id" not in hidden


@pytest.mark.asyncio
async def test_an_occurrence_loses_the_meeting_id_with_the_meeting_and_the_series_id_with_either_owner() -> None:
    tool, arguments = "list_recurring_meeting_occurrences", {"recurring_meeting_id": ARGUMENT_ID}
    _, shown = await _payload(tool, arguments)
    assert shown["recurring_meeting_id"] == ARGUMENT_ID
    assert all("meeting_id" in row and "start_time" in row for row in shown["results"])

    _, hidden = await _payload(tool, arguments, {"meeting": ("id",)})
    assert all("meeting_id" not in row and "start_time" in row for row in hidden["results"])
    assert hidden["recurring_meeting_id"] == ARGUMENT_ID, "the series id is the recurring meeting's, not the meeting's"

    for entity, field in (("recurring_meeting", "id"), ("meeting", "recurring_meeting_id")):
        _, hidden = await _payload(tool, arguments, {entity: (field,)})
        assert "recurring_meeting_id" not in hidden


@pytest.mark.asyncio
async def test_an_attachment_url_and_its_content_result_leave_with_the_attachment_id() -> None:
    _, shown = await _payload("get_attachment", {"attachment_id": ARGUMENT_ID})
    assert shown["download_url"]
    _, hidden = await _payload("get_attachment", {"attachment_id": ARGUMENT_ID}, {"attachment": ("id",)})
    assert "download_url" not in hidden and "id" not in hidden

    _, content = await _payload("get_attachment_content", {"attachment_id": ARGUMENT_ID})
    assert "attachment_id" in content
    _, content = await _payload("get_attachment_content", {"attachment_id": ARGUMENT_ID}, {"attachment": ("id",)})
    assert "attachment_id" not in content


def _hrefs(rows: list[dict[str, Any]] | None) -> list[str | None]:
    return [row.get("href") for row in rows or []]


@pytest.mark.asyncio
async def test_the_rows_of_children_and_ancestors_follow_the_fields_of_the_work_package() -> None:
    arguments = {"work_package_id": ARGUMENT_ID}
    body, shown = await _payload("get_work_package", arguments)
    assert all({"href", "title", "display_id"} <= set(row) for row in shown["children"] + shown["ancestors"])

    _, no_title = await _payload("get_work_package", arguments, {"work_package": ("subject",)})
    assert all("title" not in row and "href" in row for row in no_title["children"] + no_title["ancestors"])

    _, no_display = await _payload("get_work_package", arguments, {"work_package": ("display_id",)})
    assert all(
        "display_id" not in row and "href" not in row for row in no_display["children"] + no_display["ancestors"]
    )
    assert all(row["title"] for row in no_display["children"])

    _, no_id = await _payload("get_work_package", arguments, {"work_package": ("id",)})
    assert all("href" not in row for row in no_id["children"] + no_id["ancestors"])
    assert body.children is not None and body.children[0]["href"], "the data of the record is not edited"


@pytest.mark.asyncio
async def test_a_row_with_no_value_left_is_dropped_and_a_member_with_no_row_left_reads_as_unset() -> None:
    hidden = {"work_package": ("id", "display_id", "subject")}
    _, shown = await _payload("get_work_package", {"work_package_id": ARGUMENT_ID}, hidden)

    assert "children" not in shown and "ancestors" not in shown


@pytest.mark.asyncio
async def test_the_parent_row_of_the_ancestors_leaves_with_the_parent_fields_only() -> None:
    arguments = {"work_package_id": ARGUMENT_ID}
    body, shown = await _payload("get_work_package", arguments)
    parent = next(row for row in shown["ancestors"] if row["href"].rsplit("/", 1)[-1] == str(body.parent_id))
    other = next(row for row in shown["ancestors"] if row is not parent)

    _, no_parent = await _payload("get_work_package", arguments, {"work_package": ("parent_id", "parent_display_id")})
    parent_row = next(row for row in no_parent["ancestors"] if row.get("title") == parent["title"])
    assert "href" not in parent_row and "display_id" not in parent_row
    assert any(row == other for row in no_parent["ancestors"]), "another ancestor keeps all its keys"


@pytest.mark.asyncio
async def test_the_ancestors_of_a_project_follow_the_name_and_the_id_and_the_parent_row_its_parent_fields() -> None:
    body, shown = await _payload("get_project", {"project": "demo"})
    assert [row["title"] for row in shown["ancestors"]]

    _, no_name = await _payload("get_project", {"project": "demo"}, {"project": ("name",)})
    assert all("title" not in row for row in no_name["ancestors"])

    _, no_parent = await _payload("get_project", {"project": "demo"}, {"project": ("parent_id", "parent_name")})
    last = body.ancestors[-1]["title"]
    assert last not in {row.get("title") for row in no_parent["ancestors"]} | {
        row.get("href") for row in no_parent["ancestors"]
    }
    assert len(no_parent["ancestors"]) == len(body.ancestors) - 1, "the row of the parent carries no value left"


def test_the_table_stamp_keeps_the_keys_an_entity_stamp_set_before() -> None:
    from _client_test_helpers import _base_settings

    settings = dataclasses.replace(_base_settings(), hidden_fields={"work_package": ("display_id",)})
    item = models.BatchWorkPackageReadItemResult(id="DEMO-1", index=0, success=False, work_package=None, error="x")
    item._hidden_keys = frozenset({"error"})  # type: ignore[attr-defined]

    stamp_result(item, settings=settings)
    stamp_result(item, settings=settings)

    assert item._hidden_keys == frozenset({"error", "id"})  # type: ignore[attr-defined]


def test_the_parent_row_is_found_when_the_href_ends_with_a_slash() -> None:
    from _client_test_helpers import _base_settings
    from test_trimming import _wp_detail

    detail = _wp_detail()
    detail.parent_id = 8
    detail.ancestors = [
        {"href": "/api/v3/work_packages/7/", "title": "grandparent", "display_id": "P-7"},
        {"href": "/api/v3/work_packages/8/", "title": "parent", "display_id": "P-8"},
    ]
    settings = dataclasses.replace(_base_settings(), hidden_fields={"work_package": ("parent_id", "parent_display_id")})

    shown = _to_payload(stamp_result(detail, settings=settings), elide_none=True)

    assert shown["ancestors"][0] == {"href": "/api/v3/work_packages/7/", "title": "grandparent", "display_id": "P-7"}
    assert shown["ancestors"][1] == {"title": "parent"}


@pytest.mark.asyncio
@pytest.mark.parametrize(("entity", "field"), [("relation", "type"), ("relation", "from_id"), ("relation", "to_id")])
async def test_the_perspective_of_a_relation_goes_with_the_type_and_the_ends(entity: str, field: str) -> None:
    arguments = {"work_package_id": sentinel_id("WorkPackage", 5)}  # the end `from` of the fake's relations
    _, shown = await _payload("get_work_package_relations", arguments)
    assert all("queried_perspective" in row for row in shown["results"]), "no baseline"

    _, hidden = await _payload("get_work_package_relations", arguments, {entity: (field,)})
    assert all("queried_perspective" not in row for row in hidden["results"])


@pytest.mark.asyncio
async def test_a_project_row_follows_the_project_id_and_only_the_parent_row_follows_the_parent_id() -> None:
    arguments = {"project": "demo"}
    body, shown = await _payload("get_project", arguments)
    parent_href = body.ancestors[-1]["href"]

    _, no_id = await _payload("get_project", arguments, {"project": ("id",)})
    assert all("href" not in row and "title" in row for row in no_id["ancestors"])

    _, no_parent_id = await _payload("get_project", arguments, {"project": ("parent_id",)})
    assert [row.get("href") for row in no_parent_id["ancestors"]] == [shown["ancestors"][0]["href"], None]
    assert parent_href not in [row.get("href") for row in no_parent_id["ancestors"]]
    assert [row["title"] for row in no_parent_id["ancestors"]] == [row["title"] for row in shown["ancestors"]]
