"""Integration tests for category reads.

Categories has no create/update/delete endpoint in the OpenProject v3 API
(GET list, GET single only -- and "GET single" is itself synthesized by
list_categories + filter, not a distinct endpoint). get_category is
exercised against a pre-existing category in the test project, sourced via
list_categories -- if the test project has none, that test is skipped
rather than failed, since there's no API to seed one.
"""

from __future__ import annotations

import pytest

from openproject_ce_mcp.client import OpenProjectClient

pytestmark = pytest.mark.integration


async def test_list_categories(client: OpenProjectClient, test_project: str) -> None:
    result = await client.list_categories(test_project)
    assert result is not None
    assert result.count >= 0


async def test_get_category(client: OpenProjectClient, test_project: str) -> None:
    existing = await client.list_categories(test_project)
    if existing.count == 0:
        pytest.skip("no existing category in the test project to read (no create_category API to seed one)")

    category_id = existing.results[0].id

    category = await client.get_category(project_ref=test_project, category_id=category_id)
    assert category.id == category_id
