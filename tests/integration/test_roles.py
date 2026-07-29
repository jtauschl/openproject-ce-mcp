"""Integration tests for Roles reads.

Roles has no single-item GET, no create/update/delete endpoint in the
OpenProject v3 API (admin-UI-only resource) -- GET list only.

Note: on this branch ``list_roles`` takes no parameters and returns every
role unpaginated (``RoleListResult`` here has only ``count``/``results``,
no ``limit``/``offset``/``total``). Pagination support for roles was added
later during the layered-architecture migration (0.4.0+), so the
``test_list_roles_paginates`` test from that branch is intentionally not
ported here -- it exercises a parameter/return-shape this branch's
``list_roles`` does not have, not a bug.
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
