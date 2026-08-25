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

import dataclasses

import pytest

from openproject_ce_mcp.client import OpenProjectClient, PermissionDeniedError

pytestmark = pytest.mark.integration


async def test_get_post(client: OpenProjectClient, seed_post_id: int) -> None:
    post = await client.post.get(seed_post_id)
    assert post.id == seed_post_id
    assert post.subject


async def test_get_post_denied_outside_read_allowlist(client: OpenProjectClient, seed_post_id: int) -> None:
    """Posts has no write tools -- this is a read-allowlist test, mirroring
    test_work_packages.py's inline read-denial idiom
    (test_list_work_package_watchers_denies_anchor_outside_read_allowlist),
    not the shared write-only denied_client fixture. The seeded post always
    belongs to test_project (docker/test/seed.rb creates its Forum/Message
    unconditionally against the seed script's own `project`), so excluding
    test_project from read_projects is sufficient to deny it."""
    read_denied_settings = dataclasses.replace(
        client.settings, read_projects=("no-such-project-for-integration-tests",)
    )
    read_denied_client = OpenProjectClient(read_denied_settings)
    await read_denied_client.initialize()

    with pytest.raises(PermissionDeniedError):
        await read_denied_client.post.get(seed_post_id)
