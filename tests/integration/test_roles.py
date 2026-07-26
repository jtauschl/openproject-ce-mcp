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
    """Verifies whether /api/v3/roles honors offset/pageSize server-side --
    an open question at migration time (see docs/architecture.md), since
    roles collections are typically small/admin-managed and the pre-migration
    client never sent these params at all.
    """
    result = await client.list_roles(limit=1)
    assert result is not None
    assert result.limit == 1
    assert len(result.results) <= 1
