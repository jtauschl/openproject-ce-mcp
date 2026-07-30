"""Integration tests for emoji reactions on work-package activities.

Emoji reactions have no dedicated create-activity endpoint of their own.
Regression note: the "created" system journal entry a work package
generates automatically does NOT support emoji reactions (confirmed live --
OpenProject rejects it with "This activity type does not support emoji
reactions"); a real user COMMENT activity (add_work_package_comment) does,
so tests here create a disposable work package and comment on it purely as a
vehicle for a real, reaction-capable activity id.
"""

from __future__ import annotations

import pytest

from openproject_ce_mcp.client import OpenProjectClient

pytestmark = pytest.mark.integration


async def _create_wp_and_comment_activity_id(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> tuple[int, int]:
    wp_result = await client.create_work_package(
        project=test_project, type="Task", subject="Integration test WP for emoji reactions", confirm=True
    )
    assert wp_result.ready, wp_result.validation_errors
    wp_id = wp_result.work_package_id
    assert wp_id is not None
    wp_ids.append(wp_id)

    comment_result = await client.add_work_package_comment(
        work_package_id=wp_id, comment="Integration test comment for emoji reactions", confirm=True
    )
    assert comment_result.ready, comment_result.validation_errors
    assert comment_result.result is not None
    return wp_id, comment_result.result.id


async def test_list_work_package_reactions(client: OpenProjectClient, test_project: str, wp_ids: list[int]) -> None:
    wp_result = await client.create_work_package(
        project=test_project, type="Task", subject="Integration test WP for reaction listing", confirm=True
    )
    assert wp_result.ready, wp_result.validation_errors
    wp_id = wp_result.work_package_id
    assert wp_id is not None
    wp_ids.append(wp_id)

    # A freshly created work package has no reactions at all yet -- `== 0` is
    # the actual, checkable expectation here, not `>= 0` (true of any
    # response, including a broken one).
    result = await client.list_work_package_reactions(wp_id)
    assert result.count == 0
    assert result.results == []


async def test_toggle_activity_emoji_reaction_adds_then_removes(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    _wp_id, activity_id = await _create_wp_and_comment_activity_id(client, test_project, wp_ids)

    added = await client.toggle_activity_emoji_reaction(activity_id, "thumbs_up", confirm=True)
    assert added.confirmed
    assert added.result is not None
    matches = [r for r in added.result.results if r.reaction == "thumbs_up"]
    assert len(matches) == 1
    assert matches[0].count >= 1

    # Toggling the same reaction again removes it.
    removed = await client.toggle_activity_emoji_reaction(activity_id, "thumbs_up", confirm=True)
    assert removed.confirmed
    assert removed.result is not None
    remaining = [r for r in removed.result.results if r.reaction == "thumbs_up"]
    assert remaining == []


async def test_toggle_activity_emoji_reaction_preview_does_not_write(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    wp_id, activity_id = await _create_wp_and_comment_activity_id(client, test_project, wp_ids)

    preview = await client.toggle_activity_emoji_reaction(activity_id, "heart", confirm=False)
    assert not preview.confirmed
    assert preview.requires_confirmation

    listed = await client.list_work_package_reactions(wp_id)
    assert all(r.reaction != "heart" for r in listed.results)
