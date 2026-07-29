"""Integration tests for version CRUD operations."""

from __future__ import annotations

import dataclasses
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


async def test_list_versions_search_walks_every_server_page(
    client: OpenProjectClient, test_project: str, version_ids: list[int]
) -> None:
    """Regression: list_versions' search branch fetched a single server page
    capped at settings.max_page_size and filtered client-side, on the
    assumption that real result counts never exceed one page -- any
    matching version beyond that first page was silently unreachable.

    settings.max_page_size doubles as BOTH the server page size AND the
    final result-slicing limit (_resolve_limit clamps to it), so shrinking
    it also shrinks limit= -- a single list_versions() call can therefore
    never observe more than max_page_size results regardless of the fix.
    Instead, call list_versions() itself multiple times (its own offset=
    pagination, walking RESULT pages, not server pages) with a tiny
    max_page_size, and take the union: every one of the few created
    versions must show up across those calls, proving _fetch_all_pages
    (invoked fresh on every one of these calls) doesn't lose any of them to
    a single-server-page cap on its own end.
    """
    shared_marker = uuid.uuid4().hex[:8]
    created_ids = []
    for i in range(3):
        name = f"[integration-test-search] {shared_marker} {i}"
        result = await client.create_version(project=test_project, name=name, confirm=True)
        assert result.ready, result.validation_errors
        created_ids.append(result.version_id)
        version_ids.append(result.version_id)

    tiny_page_settings = dataclasses.replace(client.settings, max_page_size=1)
    tiny_page_client = OpenProjectClient(tiny_page_settings)
    await tiny_page_client.initialize()

    found_ids: set[int] = set()
    result_offset = 1
    for _ in range(len(created_ids) + 2):  # bounded: len(created_ids) pages + margin, never infinite
        page = await tiny_page_client.list_versions(project=test_project, search=shared_marker, offset=result_offset)
        found_ids.update(v.id for v in page.results)
        if page.next_offset is None:
            break
        result_offset = page.next_offset

    assert found_ids == set(created_ids)


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
