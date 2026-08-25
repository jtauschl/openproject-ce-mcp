"""Integration tests for wiki page link CRUD operations.

Requires OpenProject 17.5+ for the GET (list) endpoint -- it does not exist
on earlier versions (verified against op-sources: `work_package_wiki_page_
links_api.rb` is present starting at 17.5, absent at 17.4; only skips run
against 16.6/17.4). The POST (create) endpoint needs a further, separate
17.7+: verified against op-sources, `work_package_wiki_page_links_api.rb`'s
`resources :wiki_page_links` block on both 17.5 and 17.6 declares only
`get do`, no `post` handler at all -- confirmed live too (`POST .../
wiki_page_links` 404s directly via curl against a running 17.6 instance, no
client involved). Run explicitly against op-17-5/op-17-6/op-17-7;
create-path tests additionally skip themselves on 17.5/17.6.

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
   `metadata` (not `relation`) ended up empty. Neither 17.5's nor 17.6's
   `call` method (same file) has any such guard -- confirmed absent by
   reading the method directly in both op-sources checkouts and against a
   running 17.6 instance -- so on both 17.5 and 17.6 the endpoint 500s
   unconditionally, including the zero-links case; the partial fix is
   17.7-only.

Confirmed live (raw `rails runner` AND direct curl, no client involved) on
16.6, 17.6, AND 17.7.1, and via direct op-sources reading for 17.5 -- the
collection endpoint is unconditionally broken on every OpenProject version
tested whenever at least one page link exists for the queried work package,
regardless of whether its `identifier` is a made-up string or a real page
slug; on 17.5/17.6 specifically it is broken even with zero page links,
since those versions' `call` method has no emptiness guard of any kind.

list_work_package_wiki_links therefore only has integration coverage for the
zero-links case on 17.7+ (which does work, thanks to 17.7's partial fix --
skipped entirely on 17.5/17.6, where even zero-links 500s) and an explicit
xfail documenting the broken non-empty case -- create is fully covered and
functional on its own (17.7+ only, per the POST-availability note above).

delete_work_package_wiki_link is ALSO affected, indirectly: this MCP's own
`WikiPageLinkService.delete()` deliberately calls `list_for_work_package`
internally first, to verify the caller-supplied `link_id` actually belongs
to the caller-supplied `work_package_id` before deleting it (a genuine
authorization-bypass fix -- see the Service module's own docstring; without
this check, a caller with write access to an allowed work package could
delete an arbitrary link_id belonging to a disallowed project). That
verification call hits the exact same broken collection endpoint above, so
delete is currently unusable whenever a link actually exists to delete --
this is the correct tradeoff (fail closed/unavailable rather than silently
reintroducing the authorization bypass) and is expected to resolve itself
once OP-19928 is fixed upstream, with no client-side code change
needed.
"""

from __future__ import annotations

import dataclasses
import uuid

import pytest

from openproject_ce_mcp.client import (
    NotFoundError,
    OpenProjectClient,
    OpenProjectServerError,
    PermissionDeniedError,
)

pytestmark = pytest.mark.integration

_PROVIDER = "internal"


async def test_create_wiki_page_link(client: OpenProjectClient, test_project: str, wp_ids: list[int]) -> None:
    wp_result = await client.work_package.create(
        project=test_project,
        type="Task",
        subject=f"[integration-test] wiki link {uuid.uuid4().hex[:8]}",
        confirm=True,
    )
    assert wp_result.ready, wp_result.validation_errors
    work_package_id = wp_result.work_package_id
    wp_ids.append(work_package_id)

    try:
        create_result = await client.wiki_page_link.create(
            work_package_id, identifier="wiki", provider=_PROVIDER, confirm=True
        )
    except NotFoundError:
        pytest.skip("POST work_packages/{id}/wiki_page_links not available (requires OpenProject 17.7+)")
    assert create_result.ready and create_result.state == "confirmed", create_result.validation_errors
    link_id = create_result.link_id
    assert link_id is not None and link_id > 0

    # No cleanup via delete_work_package_wiki_link here -- see module
    # docstring, delete is currently unusable once a link exists (the same
    # OP-19928 upstream bug delete's own authorization-bypass fix depends on).


async def test_create_wiki_page_link_preview_without_confirm_does_not_write(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    wp_result = await client.work_package.create(
        project=test_project,
        type="Task",
        subject=f"[integration-test] wiki link preview {uuid.uuid4().hex[:8]}",
        confirm=True,
    )
    assert wp_result.ready, wp_result.validation_errors
    work_package_id = wp_result.work_package_id
    wp_ids.append(work_package_id)

    # confirm=False never reaches the real HTTP endpoint at all (see
    # WikiPageLinkService.create's own preview branch, which returns before
    # any API call) -- no 17.7+ skip needed here, unlike the confirmed-create
    # test above.
    preview_result = await client.wiki_page_link.create(
        work_package_id, identifier="wiki", provider=_PROVIDER, confirm=False
    )
    assert preview_result.state == "preview"
    assert preview_result.result is None

    # Zero links exist for this work package -- this is the one case
    # OpenProject 17.7's `if relation.any?` guard actually handles (see
    # module docstring); a non-empty list is xfailed below instead. On
    # 17.5/17.6 the guard doesn't exist at all, so even this zero-links case
    # 500s; on pre-17.5 instances the GET route doesn't exist at all
    # (NotFoundError).
    try:
        listed = await client.wiki_page_link.list_for_work_package(work_package_id)
    except NotFoundError:
        pytest.skip("wiki_page_links endpoint not available (requires OpenProject 17.5+)")
    except OpenProjectServerError:
        # Known-broken only on 17.5/17.6 (no relation.any? guard, see module
        # docstring) -- 17.7 has the guard and should never 500 here. This
        # except is intentionally version-blind (no version-detection API to
        # gate on directly, per this project's established pattern), so a
        # genuine NEW 17.7+ server regression would also be swallowed as a
        # skip instead of failing loudly; accepted risk, not a silent design
        # oversight.
        pytest.skip(
            "GET work_packages/{id}/wiki_page_links 500s unconditionally on this instance "
            "(known-broken on 17.5/17.6, see module docstring)"
        )
    assert listed.count == 0


async def test_create_wiki_page_link_denies_work_package_outside_write_allowlist(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    wp_result = await client.work_package.create(
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
        await restricted_client.wiki_page_link.create(
            work_package_id, identifier="wiki", provider=_PROVIDER, confirm=True
        )


@pytest.mark.xfail(
    reason="Upstream OpenProject bug: Wikis::PageLinkMetadataService#enrich_models "
    "raises a Postgres syntax error whenever at least one wiki page link exists "
    "for the queried work package (see module docstring). Reported upstream; "
    "un-xfail once fixed. strict=False: the 17.7.1 image tag appears mutable "
    "upstream, so a locally-pulled 17.7.1 can pass or fail this case depending "
    "on when it was pulled, until the fix's actual release is confirmed via the "
    "monitored PR (opf/openproject#24770 / OP-19928).",
    strict=False,
)
async def test_list_work_package_wiki_links_finds_created_link(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    """Documents this MCP server's own client code is correct -- the create
    request it sends is well-formed and round-trips cleanly (see
    test_create_wiki_page_link above); the list failure is entirely
    server-side. The delete call at the end of this test is expected to fail
    for the same underlying reason (see module docstring) -- this test
    doesn't clean up its own work package's link, which is fine since the
    seed project doesn't get reset between test runs and leftover links
    don't affect any other test."""
    wp_result = await client.work_package.create(
        project=test_project,
        type="Task",
        subject=f"[integration-test] wiki link list {uuid.uuid4().hex[:8]}",
        confirm=True,
    )
    assert wp_result.ready, wp_result.validation_errors
    work_package_id = wp_result.work_package_id
    wp_ids.append(work_package_id)

    create_result = await client.wiki_page_link.create(
        work_package_id, identifier="wiki", provider=_PROVIDER, confirm=True
    )
    assert create_result.ready, create_result.validation_errors
    link_id = create_result.link_id

    listed = await client.wiki_page_link.list_for_work_package(work_package_id)
    assert any(link.id == link_id for link in listed.results)

    await client.wiki_page_link.delete(work_package_id, link_id, confirm=True)
