"""Integration tests for Actions & Capabilities reads.

Neither resource has a create/update/delete endpoint in the OpenProject v3
API (GET list only, no single-item GET for either). list_capabilities
requires the test project itself as its `project` filter (always present),
so no fixture-sourcing/skip logic is needed the way Categories' get_category
test needs one.
"""

from __future__ import annotations

import pytest

from openproject_ce_mcp.client import OpenProjectClient

pytestmark = pytest.mark.integration


async def test_list_actions(client: OpenProjectClient) -> None:
    result = await client.list_actions()
    assert result is not None
    assert result.count >= 0


async def test_list_capabilities_for_project(client: OpenProjectClient, test_project: str) -> None:
    result = await client.list_capabilities(project=test_project)
    assert result is not None
    assert result.count >= 0
