"""Integration tests for Statuses/Priorities/Types reads.

All three are admin-UI-only resources -- no create/update/delete endpoint in
the OpenProject v3 API.
"""

from __future__ import annotations

import dataclasses

import pytest

from openproject_ce_mcp.client import OpenProjectClient

pytestmark = pytest.mark.integration


async def test_list_statuses(client: OpenProjectClient) -> None:
    result = await client.status_priority_type.list_statuses()
    assert result.count > 0
    assert result.results[0].name


async def test_list_priorities(client: OpenProjectClient) -> None:
    result = await client.status_priority_type.list_priorities()
    assert result.count > 0
    assert result.results[0].name


async def test_list_priorities_stamps_hidden_field_for_masking(client: OpenProjectClient, open_client) -> None:
    """Regression: priority/notification/file_link/emoji_reaction were
    missing from HIDE_FIELD_ENV_BY_ENTITY entirely, so _apply_hidden_fields
    never stamped a _hidden_keys marker on their results, unlike every other
    read-normalized entity -- the actual masking happens one layer up, in
    presentation._to_payload, which reads that marker to drop the field from
    the MCP response entirely. This client-layer test proves the stamp itself
    is present against a live payload; the drop-from-response behavior is
    already covered by the tool layer's own unit tests (mocked client)."""
    hidden_settings = dataclasses.replace(client.settings, hidden_fields={"priority": ("color",)})
    hidden_client = await open_client(hidden_settings)

    result = await hidden_client.status_priority_type.list_priorities()
    assert result.count > 0
    assert all(getattr(p, "_hidden_keys", None) == frozenset({"color"}) for p in result.results)


async def test_list_types(client: OpenProjectClient) -> None:
    result = await client.status_priority_type.list_types()
    assert result.count > 0
    assert result.results[0].name
