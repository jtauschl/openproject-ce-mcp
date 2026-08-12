"""Integration tests for forum post reads.

Posts has no create/update/delete/list endpoint in the OpenProject v3 API
(GET /api/v3/posts/{id} is the only route -- verified against
op-sources/17.7/lib/api/v3/posts/posts_api.rb). get_post is exercised
against a post docker/test/seed.rb creates ahead of time (a Forum + one
Message, since a Message always requires a parent Forum), whose id is
resolved via the seed_post_id fixture (a Rails-runner side channel, since
there's no list endpoint to discover it through the API itself -- same
pattern as seed_wiki_page_id in test_wiki_pages.py).
"""

from __future__ import annotations

import pytest

from openproject_ce_mcp.client import OpenProjectClient

pytestmark = pytest.mark.integration


async def test_get_post(client: OpenProjectClient, seed_post_id: int) -> None:
    post = await client.get_post(seed_post_id)
    assert post.id == seed_post_id
    assert post.subject
