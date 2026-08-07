"""Integration tests for Roles reads.

Roles has no single-item GET, no create/update/delete endpoint in the
OpenProject v3 API (admin-UI-only resource) -- GET list only.
"""

from __future__ import annotations

import pytest

from openproject_ce_mcp.client import OpenProjectClient

pytestmark = pytest.mark.integration


async def test_list_roles(client: OpenProjectClient) -> None:
    result = await client.list_roles()
    assert result is not None
    assert result.count > 0
    assert result.results[0].name


async def test_list_roles_paginates(client: OpenProjectClient) -> None:
    """Verifies /api/v3/roles honors offset/pageSize server-side -- an open
    question at migration time (see docs/architecture.md), since roles
    collections are typically small/admin-managed and the pre-migration
    client never sent these params at all. OpenProject ships several
    default roles out of the box (Member/Reader/...), so a fresh instance
    should always have enough to prove real pagination.
    """
    unfiltered = await client.list_roles(limit=100)
    if unfiltered.total < 2:
        pytest.skip("Not enough roles on this instance to prove pagination")

    first_page = await client.list_roles(limit=1)
    assert first_page.count == 1
    assert first_page.truncated
    assert first_page.next_offset == 2

    second_page = await client.list_roles(limit=1, offset=2)
    assert second_page.count == 1
    assert second_page.results[0].id != first_page.results[0].id
