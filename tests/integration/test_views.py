"""Integration tests for view reads.

Views has no create/update/delete endpoint in the OpenProject v3 API (list +
single-item GET only). get_view is exercised against a pre-existing view
sourced via list_views -- if the test project has none, that test is
skipped rather than failed, since there's no API to seed one.
"""

from __future__ import annotations

import pytest

from openproject_ce_mcp.client import OpenProjectClient

pytestmark = pytest.mark.integration


async def test_list_views(client: OpenProjectClient, test_project: str) -> None:
    result = await client.list_views(project=test_project)
    assert result is not None
    assert result.count >= 0


async def test_get_view(client: OpenProjectClient, test_project: str) -> None:
    existing = await client.list_views(project=test_project)
    if existing.count == 0:
        pytest.skip("no existing view in the test project to read (no create_view API to seed one)")

    view_id = existing.results[0].id

    view = await client.get_view(view_id)
    assert view.id == view_id
