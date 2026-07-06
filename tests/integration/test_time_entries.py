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
