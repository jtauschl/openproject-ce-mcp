"""Integration tests for wiki page link CRUD operations.

Requires OpenProject 17.6+ -- the wiki_page_links endpoint does not exist on
earlier versions (verified against op-sources: 17.4/17.5 carry only the
representer, no reachable route; only skips run against those instances).
Run explicitly against op-17-6/op-17-7 only.

KNOWN SERVER BUG (reported upstream, not a client issue), two bugs chained
together:

1. `Wikis::Adapters::Providers::Internal::Queries::PageInfo#call`
   (modules/wikis/app/services/wikis/adapters/providers/internal/queries/
   page_info.rb:62) resolves a page link's `identifier` via
   `WikiPage.visible(user).find_by(id: input_data.identifier)` -- i.e. it
   treats `identifier` as the wiki page's numeric database id, NOT its slug,
   despite the API representer describing `identifier` as an opaque,
   provider-defined string. A caller passing the actual page slug (e.g.
   "wiki", the seeded project's real wiki page) gets `not_found` -- confirmed
   live with `rails runner`, no client involved.

2. `Wikis::PageLinkMetadataService` (modules/wikis/app/services/wikis/
   page_link_metadata_service.rb) builds a SQL `LEFT JOIN (VALUES
   #{placeholders})` clause from a `metadata` array populated by resolving
   each link through bug 1's adapter; `filter_map` silently drops every link
   whose lookup fails. Because bug 1 makes essentially every real-world
   `identifier` fail to resolve, `metadata` ends up empty even when the
   `page_links` relation itself is non-empty. `Array.new(0, "(?,?)").join(",")`
   is an empty string, producing the invalid `LEFT JOIN (VALUES ) AS
   metadata(...)` and a Postgres syntax error (500). 17.7 added an `if
   relation.any?` guard (call, line 41) that fixes the trivial zero-links
   case, but checks the wrong emptiness -- it needed to check whether
   `metadata` (not `relation`) ended up empty.

Confirmed live (raw `rails runner`, no client involved) on 16.6, 17.6, AND
17.7.1 -- the collection endpoint is unconditionally broken on every
OpenProject version tested whenever at least one page link exists for the
queried work package, regardless of whether its `identifier` is a made-up
string or a real page slug.

list_work_package_wiki_links therefore only has integration coverage for the
zero-links case (which does work, thanks to 17.7's partial fix) and an
explicit xfail documenting the broken non-empty case -- create/delete are
otherwise fully covered and functional.
"""

from __future__ import annotations

import dataclasses
import uuid

import pytest

from openproject_ce_mcp.client import OpenProjectClient, PermissionDeniedError

pytestmark = pytest.mark.integration

_PROVIDER = "internal"


async def test_create_and_delete_wiki_page_link(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    wp_result = await client.create_work_package(
        project=test_project,
        type="Task",
        subject=f"[integration-test] wiki link {uuid.uuid4().hex[:8]}",
        confirm=True,
    )
    assert wp_result.ready, wp_result.validation_errors
    work_package_id = wp_result.work_package_id
    wp_ids.append(work_package_id)

    create_result = await client.create_work_package_wiki_link(
        work_package_id, identifier="wiki", provider=_PROVIDER, confirm=True
    )
    assert create_result.ready and create_result.state == "confirmed", create_result.validation_errors
    link_id = create_result.link_id
    assert link_id is not None and link_id > 0

    delete_result = await client.delete_work_package_wiki_link(work_package_id, link_id, confirm=True)
    assert delete_result.ready and delete_result.state == "confirmed"


async def test_create_wiki_page_link_preview_without_confirm_does_not_write(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    wp_result = await client.create_work_package(
        project=test_project,
        type="Task",
        subject=f"[integration-test] wiki link preview {uuid.uuid4().hex[:8]}",
        confirm=True,
    )
    assert wp_result.ready, wp_result.validation_errors
    work_package_id = wp_result.work_package_id
    wp_ids.append(work_package_id)

    preview_result = await client.create_work_package_wiki_link(
        work_package_id, identifier="wiki", provider=_PROVIDER, confirm=False
    )
    assert preview_result.state == "preview"
    assert preview_result.result is None

    # Zero links exist for this work package -- this is the one case
    # OpenProject 17.7's `if relation.any?` guard actually handles (see
    # module docstring); a non-empty list is xfailed below instead.
    listed = await client.list_work_package_wiki_links(work_package_id)
    assert listed.count == 0


async def test_create_wiki_page_link_denies_work_package_outside_write_allowlist(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    wp_result = await client.create_work_package(
        project=test_project,
        type="Task",
        subject=f"[integration-test] wiki link denial {uuid.uuid4().hex[:8]}",
        confirm=True,
    )
    assert wp_result.ready, wp_result.validation_errors
    work_package_id = wp_result.work_package_id
    wp_ids.append(work_package_id)

    restricted_settings = dataclasses.replace(client.settings, write_projects=("no-such-project",))
    restricted_client = OpenProjectClient(restricted_settings)
    await restricted_client.initialize()

    with pytest.raises(PermissionDeniedError):
        await restricted_client.create_work_package_wiki_link(
            work_package_id, identifier="wiki", provider=_PROVIDER, confirm=True
        )


@pytest.mark.xfail(
    reason="Upstream OpenProject bug: Wikis::PageLinkMetadataService#enrich_models "
    "raises a Postgres syntax error whenever at least one wiki page link exists "
    "for the queried work package (see module docstring). Reported upstream; "
    "un-xfail once fixed.",
    strict=True,
)
async def test_list_work_package_wiki_links_finds_created_link(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    """Documents this MCP server's own client code is correct -- the request
    it sends is well-formed and create/delete both round-trip cleanly (see
    the passing tests above); the list failure is entirely server-side."""
    wp_result = await client.create_work_package(
        project=test_project,
        type="Task",
        subject=f"[integration-test] wiki link list {uuid.uuid4().hex[:8]}",
        confirm=True,
    )
    assert wp_result.ready, wp_result.validation_errors
    work_package_id = wp_result.work_package_id
    wp_ids.append(work_package_id)

    create_result = await client.create_work_package_wiki_link(
        work_package_id, identifier="wiki", provider=_PROVIDER, confirm=True
    )
    assert create_result.ready, create_result.validation_errors
    link_id = create_result.link_id

    listed = await client.list_work_package_wiki_links(work_package_id)
    assert any(link.id == link_id for link in listed.results)

    await client.delete_work_package_wiki_link(work_package_id, link_id, confirm=True)
