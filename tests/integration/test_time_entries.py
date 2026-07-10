"""Integration tests for time entry CRUD operations."""

from __future__ import annotations

import datetime

import pytest

from openproject_ce_mcp.client import OpenProjectClient

pytestmark = pytest.mark.integration


async def _first_activity_name(client: OpenProjectClient) -> str:
    activities = await client.list_time_entry_activities()
    if activities.count == 0:
        pytest.skip("Instance has no time entry activities configured")
    return activities.results[0].name


async def _first_wp_id(client: OpenProjectClient, test_project: str) -> int | None:
    result = await client.list_work_packages(project=test_project, limit=1)
    if result.count == 0:
        return None
    return result.results[0].id


async def test_list_time_entry_activities(client: OpenProjectClient) -> None:
    result = await client.list_time_entry_activities()
    assert result.count >= 0


async def test_list_time_entries(client: OpenProjectClient, test_project: str) -> None:
    result = await client.list_time_entries(project=test_project)
    assert result is not None
    assert result.count >= 0


async def test_create_get_update_delete_time_entry(
    client: OpenProjectClient, test_project: str, time_entry_ids: list[int]
) -> None:
    activity = await _first_activity_name(client)
    wp_id = await _first_wp_id(client, test_project)
    spent_on = datetime.date.today().isoformat()

    # Create
    result = await client.create_time_entry(
        activity=activity,
        hours="PT1H30M",
        spent_on=spent_on,
        project=test_project,
        work_package_id=wp_id,
        comment="Integration test time entry",
        confirm=True,
    )
    assert result.ready, result.validation_errors
    te_id = result.time_entry_id
    assert te_id > 0
    time_entry_ids.append(te_id)

    # Read
    te = await client.get_time_entry(te_id)
    assert te.id == te_id

    # Update
    update_result = await client.update_time_entry(
        time_entry_id=te_id,
        hours="PT2H",
        confirm=True,
    )
    assert update_result.ready, update_result.validation_errors

    # Delete
    delete_result = await client.delete_time_entry(time_entry_id=te_id, confirm=True)
    assert delete_result.ready and delete_result.confirmed
    time_entry_ids.remove(te_id)


async def test_create_time_entry_with_semantic_work_package_ref(
    client: OpenProjectClient, test_project: str, wp_ids: list[int], time_entry_ids: list[int]
) -> None:
    activity = await _first_activity_name(client)
    spent_on = datetime.date.today().isoformat()

    wp_result = await client.create_work_package(
        project=test_project, type="Task", subject="Integration test WP for semantic time entry", confirm=True
    )
    assert wp_result.ready, wp_result.validation_errors
    wp_id = wp_result.work_package_id
    assert wp_id is not None
    wp_ids.append(wp_id)
    wp = await client.get_work_package(wp_id)
    display_id = wp.display_id or ""
    # Semantic identifiers (project-prefixed, e.g. "TST-105") only exist on 17.5+
    # in semantic mode. On 16.x display_id is absent (added in 17.4); on classic
    # 17.x it's the numeric id as a string. Same detection as
    # test_semantic_identifiers.py::test_reference_resolution_matches_instance_mode.
    is_semantic = "-" in display_id and not display_id.isdigit()
    if not is_semantic:
        pytest.skip("instance is not in semantic identifier mode; nothing to resolve")

    # The numeric-HAL-link-from-semantic-ref resolution path (client.py
    # _work_package_ref) — passing the display_id string, not the numeric id.
    result = await client.create_time_entry(
        activity=activity,
        hours="PT1H",
        spent_on=spent_on,
        work_package_id=display_id,
        confirm=True,
    )
    assert result.ready, result.validation_errors
    te_id = result.time_entry_id
    assert te_id > 0
    time_entry_ids.append(te_id)

    te = await client.get_time_entry(te_id)
    # entity_id is the proof that the semantic ref resolved to the right numeric
    # work package via the HAL entity link. entityType is not reliably present
    # on the live response (unlike the hand-built payloads in the unit tests),
    # so it isn't asserted here.
    assert te.entity_id == wp_id
