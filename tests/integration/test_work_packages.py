"""Integration tests for work package CRUD operations."""
from __future__ import annotations

import pytest

from openproject_ce_mcp.client import OpenProjectClient

pytestmark = pytest.mark.integration

_SUBJECT = "[integration-test] temp WP"
_SUBJECT_BULK = "[integration-test] bulk WP"


async def test_list_work_packages(client: OpenProjectClient, test_project: str) -> None:
    result = await client.list_work_packages(project=test_project)
    assert result is not None
    assert result.count >= 0


async def test_search_work_packages(client: OpenProjectClient) -> None:
    result = await client.search_work_packages(query="test")
    assert result is not None


async def test_list_my_open_work_packages(client: OpenProjectClient) -> None:
    result = await client.list_my_open_work_packages()
    assert result is not None


async def test_create_get_update_delete_work_package(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    # Create
    result = await client.create_work_package(
        project=test_project,
        type="Task",
        subject=_SUBJECT,
        confirm=True,
    )
    assert result.ready, result.validation_errors
    wp_id = result.work_package_id
    assert wp_id > 0
    wp_ids.append(wp_id)

    # Read
    wp = await client.get_work_package(wp_id)
    assert wp.subject == _SUBJECT
    assert wp.id == wp_id

    # Update
    update_result = await client.update_work_package(
        work_package_id=wp_id,
        subject=f"{_SUBJECT} updated",
        confirm=True,
    )
    assert update_result.ready, update_result.validation_errors

    updated = await client.get_work_package(wp_id)
    assert "updated" in updated.subject

    # Delete (cleanup fixture also deletes, but we verify delete works)
    delete_result = await client.delete_work_package(work_package_id=wp_id, confirm=True)
    assert delete_result.ready and delete_result.confirmed
    wp_ids.remove(wp_id)  # already deleted, don't try again in fixture


async def test_create_subtask(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    # Create parent
    parent = await client.create_work_package(
        project=test_project,
        type="Task",
        subject=f"{_SUBJECT} parent",
        confirm=True,
    )
    assert parent.ready
    wp_ids.append(parent.work_package_id)

    # Create subtask
    child = await client.create_subtask(
        parent_work_package_id=parent.work_package_id,
        type="Task",
        subject=f"{_SUBJECT} child",
        confirm=True,
    )
    assert child.ready
    wp_ids.append(child.work_package_id)

    wp = await client.get_work_package(child.work_package_id)
    assert wp.subject


async def test_add_work_package_comment(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    result = await client.create_work_package(
        project=test_project,
        type="Task",
        subject=f"{_SUBJECT} comment-test",
        confirm=True,
    )
    assert result.ready
    wp_ids.append(result.work_package_id)

    comment = await client.add_work_package_comment(
        work_package_id=result.work_package_id,
        comment="Integration test comment",
        confirm=True,
    )
    assert comment is not None

    activities = await client.get_work_package_activities(result.work_package_id)
    assert activities.count > 0


async def test_bulk_create_work_packages(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    items = [
        {"project": test_project, "type": "Task", "subject": f"{_SUBJECT_BULK} 1"},
        {"project": test_project, "type": "Task", "subject": f"{_SUBJECT_BULK} 2"},
    ]
    result = await client.bulk_create_work_packages(items=items, confirm=True)
    assert result.total == 2

    for item in result.items:
        if item.success and item.result and item.result.work_package_id:
            wp_ids.append(item.result.work_package_id)

    assert result.succeeded >= 1  # at least one should succeed


async def test_list_work_package_watchers(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    result = await client.create_work_package(
        project=test_project,
        type="Task",
        subject=f"{_SUBJECT} watcher-test",
        confirm=True,
    )
    assert result.ready
    wp_ids.append(result.work_package_id)

    watchers = await client.list_work_package_watchers(result.work_package_id)
    assert watchers is not None
