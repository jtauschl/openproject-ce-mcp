"""Integration tests for wiki page reads.

Wiki Pages has no create/update/delete/list endpoint in the OpenProject v3
API (GET /api/v3/wiki_pages/{id} is the only route -- confirmed against
op-sources/lib/api/v3/wiki_pages/wiki_pages_api.rb). get_wiki_page is
exercised against a page docker/test/seed.rb creates ahead of time, whose id
is resolved via the seed_wiki_page_id fixture (a Rails-runner side channel,
since there's no list endpoint to discover it through the API itself).
"""

from __future__ import annotations

import pytest

from openproject_ce_mcp.client import OpenProjectClient

pytestmark = pytest.mark.integration


async def test_get_wiki_page(client: OpenProjectClient, seed_wiki_page_id: int) -> None:
    page = await client.get_wiki_page(seed_wiki_page_id)
    assert page.id == seed_wiki_page_id
    assert page.title
