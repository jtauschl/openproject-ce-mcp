"""Integration tests for Statuses/Priorities/Types reads (16th migrated
domain, OPM-1627).

All three are admin-UI-only resources -- GET list + GET single-item, no
create/update/delete endpoint in the OpenProject v3 API. Moved out of
test_meta.py's generic still-flat-metadata bucket now that this domain has
migrated to app/ (test_meta.py's own test_list_statuses/test_list_priorities/
test_list_types removed in the same commit as this file's addition).
"""

from __future__ import annotations

import pytest

from openproject_ce_mcp.client import OpenProjectClient

pytestmark = pytest.mark.integration


async def test_list_statuses(client: OpenProjectClient) -> None:
    result = await client.list_statuses()
    assert result.count > 0
    assert result.results[0].name


async def test_get_status(client: OpenProjectClient) -> None:
    listed = await client.list_statuses()
    status_id = listed.results[0].id

    status = await client.get_status(status_id)

    assert status.id == status_id
    assert status.name


async def test_list_priorities(client: OpenProjectClient) -> None:
    result = await client.list_priorities()
    assert result.count > 0
    assert result.results[0].name


async def test_get_priority(client: OpenProjectClient) -> None:
    listed = await client.list_priorities()
    priority_id = listed.results[0].id

    priority = await client.get_priority(priority_id)

    assert priority.id == priority_id
    assert priority.name


async def test_list_types(client: OpenProjectClient) -> None:
    result = await client.list_types()
    assert result.count > 0
    assert result.results[0].name


async def test_get_type(client: OpenProjectClient) -> None:
    listed = await client.list_types()
    type_id = listed.results[0].id

    work_package_type = await client.get_type(type_id)

    assert work_package_type.id == type_id
    assert work_package_type.name
