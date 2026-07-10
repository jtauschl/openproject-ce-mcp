"""Integration tests for group read operations.

Requires admin write: group create/delete is instance-wide, not project-scoped
(unlike every other integration test file here, which stays within
``test_project``). Only run this against a disposable Docker test instance —
never against a real, actively-used OpenProject instance.
"""

from __future__ import annotations

import pytest

from openproject_ce_mcp.client import OpenProjectClient

pytestmark = pytest.mark.integration


async def test_get_group_normalizes_visible_members_admin(client: OpenProjectClient, group_ids: list[int]) -> None:
    me = await client.get_current_user()

    create_result = await client.create_group(name="MCP integration test group", user_ids=[me.id], confirm=True)
    assert create_result.ready, create_result.validation_errors
    group_id = create_result.group_id
    assert group_id is not None
    group_ids.append(group_id)

    group = await client.get_group(group_id)

    # The critical assertion: OpenProject's real API renders _embedded.members
    # as a bare array, not a {count, elements} collection.
    assert isinstance(group.members, list), "members should be a list"
    assert me.name in group.members
