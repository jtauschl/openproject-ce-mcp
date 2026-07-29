"""Integration tests for Statuses/Priorities/Types reads (16th migrated
domain, OPM-1627).

All three are admin-UI-only resources -- GET list + GET single-item, no
create/update/delete endpoint in the OpenProject v3 API. Moved out of
test_meta.py's generic still-flat-metadata bucket now that this domain has
migrated to app/ (test_meta.py's own test_list_statuses/test_list_priorities/
test_list_types removed in the same commit as this file's addition).
"""

from __future__ import annotations

import dataclasses

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


async def test_list_priorities_stamps_hidden_field_for_masking(client: OpenProjectClient) -> None:
    """Regression: priority/notification/file_link/emoji_reaction were
    missing from HIDE_FIELD_ENV_BY_ENTITY entirely, so _apply_hidden_fields
    never stamped a _hidden_keys marker on their results, unlike every other
    read-normalized entity -- the actual masking happens one layer up, in
    tools._to_payload, which reads that marker to drop the field from the
    MCP response entirely. This client-layer test proves the stamp itself is
    present against a live payload; the drop-from-response behavior is
    already covered by tools.py's own unit tests (mocked client)."""
    hidden_settings = dataclasses.replace(client.settings, hidden_fields={"priority": ("color",)})
    hidden_client = OpenProjectClient(hidden_settings)
    await hidden_client.initialize()

    result = await hidden_client.list_priorities()
    assert result.count > 0
    assert all(getattr(p, "_hidden_keys", None) == frozenset({"color"}) for p in result.results)


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
