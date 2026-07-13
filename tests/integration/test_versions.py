"""Integration tests for version CRUD operations."""

from __future__ import annotations

import uuid

import pytest

from openproject_ce_mcp.client import OpenProjectClient

pytestmark = pytest.mark.integration


async def test_list_versions(client: OpenProjectClient, test_project: str) -> None:
    result = await client.list_versions(project=test_project)
    assert result is not None
    assert result.count >= 0


async def test_list_versions_with_search(client: OpenProjectClient, test_project: str, version_ids: list[int]) -> None:
    name = f"[integration-test-search] {uuid.uuid4().hex[:8]}"
    result = await client.create_version(project=test_project, name=name, confirm=True)
    assert result.ready, result.validation_errors
    version_id = result.version_id
    version_ids.append(version_id)

    found = await client.list_versions(project=test_project, search=name)
    assert [v.id for v in found.results] == [version_id]

    no_match = await client.list_versions(project=test_project, search=uuid.uuid4().hex)
    assert no_match.results == []


async def test_create_get_update_delete_version(
    client: OpenProjectClient, test_project: str, version_ids: list[int]
) -> None:
    name = f"[integration-test] {uuid.uuid4().hex[:8]}"

    # Create
    result = await client.create_version(
        project=test_project,
        name=name,
        confirm=True,
    )
    assert result.ready, result.validation_errors
    version_id = result.version_id
    assert version_id > 0
    version_ids.append(version_id)

    # Read
    version = await client.get_version(version_id)
    assert version.name == name
    assert version.id == version_id

    # Update
    update_result = await client.update_version(
        version_id=version_id,
        name=f"{name} updated",
        confirm=True,
    )
    assert update_result.ready, update_result.validation_errors

    updated = await client.get_version(version_id)
    assert "updated" in updated.name

    # Delete
    delete_result = await client.delete_version(version_id=version_id, confirm=True)
    assert delete_result.ready and delete_result.confirmed
    version_ids.remove(version_id)
