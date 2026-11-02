"""Integration tests for wiki page link CRUD operations.

Version floors (OpenProject sources, confirmed live on 17.5/17.6/17.7):
`GET work_packages/{id}/wiki_page_links` exists from 17.5, `DELETE
wiki_page_links/{id}` from 17.6 and `POST work_packages/{id}/wiki_page_links`
from 17.7; create-path tests skip themselves below 17.7.

KNOWN SERVER BUG (OP-19928, upstream fix opf/openproject#24770, unfixed
through 17.9.1): `Wikis::PageLinkMetadataService` joins each link to its
resolved page title via `LEFT JOIN (VALUES ...)`; when none of the work
package's links resolves, the list is empty and the SQL becomes `LEFT JOIN
(VALUES )`, a 500. The internal provider resolves `identifier` as the numeric
id of a wiki page the user can see (`PageInfo#call`:
`WikiPage.visible(user).find_by(id: ...)`), so a slug such as "wiki" never
resolves. 17.7 added a `relation.any?` guard, so on 17.5/17.6 even a work
package without links 500s.

`delete()` lists the work package's links first to check that `link_id`
belongs to it (an authorization check, see the Service docstring), so delete
works exactly when the list does. Deleting a work package leaves its links
behind, so every test removes the links it creates. A link that does not
resolve cannot be removed through `delete()` on an affected server; those
tests remove it with a raw `DELETE wiki_page_links/{id}` instead, which keeps
them independent of the Rails side channel. Only the full create, list and
delete round trip needs a resolving identifier, the seeded wiki page's id,
and with it `OPENPROJECT_DOCKER_SERVICE`.
"""

from __future__ import annotations

import dataclasses
import uuid

import pytest

from openproject_ce_mcp.client import (
    InvalidInputError,
    NotFoundError,
    OpenProjectClient,
    OpenProjectServerError,
    PermissionDeniedError,
)

from ._write_ref import write_ref

pytestmark = pytest.mark.integration

_PROVIDER = "internal"


async def _delete_link_bypassing_the_list(client: OpenProjectClient, link_id: int) -> None:
    response = await client._http.delete(f"wiki_page_links/{link_id}")
    assert response.status_code == 204, response.text


async def test_create_list_and_delete_a_resolving_wiki_page_link(
    client: OpenProjectClient, test_project: str, wp_ids: list[int], seed_wiki_page_id: int
) -> None:
    wp_result = await client.work_package.create(
        project=test_project,
        type="Task",
        subject=f"[integration-test] wiki link {uuid.uuid4().hex[:8]}",
        confirm=True,
    )
    assert wp_result.ready, wp_result.validation_errors
    work_package_id = wp_result.work_package_id
    wp_ids.append(work_package_id)
    identifier = str(seed_wiki_page_id)

    try:
        create_result = await client.wiki_page_link.create(
            await write_ref(client, work_package_id), identifier=identifier, provider=_PROVIDER, confirm=True
        )
    except NotFoundError:
        pytest.skip("POST work_packages/{id}/wiki_page_links not available (requires OpenProject 17.7+)")
    link_id = create_result.link_id
    assert link_id is not None
    deleted = False
    try:
        assert create_result.state == "confirmed", create_result.validation_errors
        listed = await client.wiki_page_link.list_for_work_package(work_package_id)
        assert [(link.id, link.identifier) for link in listed.results] == [(link_id, identifier)]

        delete_result = await client.wiki_page_link.delete(
            await write_ref(client, work_package_id), link_id, confirm=True
        )
        deleted = True
        assert delete_result.state == "confirmed"
        assert (await client.wiki_page_link.list_for_work_package(work_package_id)).results == []
    finally:
        if not deleted:
            await _delete_link_bypassing_the_list(client, link_id)


async def test_delete_rejects_an_inline_link_from_the_work_package_description(
    client: OpenProjectClient,
    test_project: str,
    wp_ids: list[int],
    internal_wiki_provider_id: int,
    seed_wiki_page_id: int,
) -> None:
    wp_result = await client.work_package.create(
        project=test_project,
        type="Task",
        subject=f"[integration-test] inline wiki link {uuid.uuid4().hex[:8]}",
        description=f"See [[[{internal_wiki_provider_id}:{seed_wiki_page_id}]]]",
        confirm=True,
    )
    assert wp_result.ready, wp_result.validation_errors
    work_package_id = wp_result.work_package_id
    wp_ids.append(work_package_id)

    try:
        try:
            listed = await client.wiki_page_link.list_for_work_package(work_package_id)
        except NotFoundError:
            pytest.skip("GET work_packages/{id}/wiki_page_links not available (requires OpenProject 17.5+)")
        assert [(link.identifier, link.link_type) for link in listed.results] == [(str(seed_wiki_page_id), "inline")]
        link_id = listed.results[0].id

        with pytest.raises(InvalidInputError) as exc_info:
            await client.wiki_page_link.delete(await write_ref(client, work_package_id), link_id, confirm=True)

        assert str(exc_info.value) == (
            f"Wiki page link {link_id} on work package {work_package_id} is an inline link: OpenProject "
            "derives it from a wiki link in the work package's description or from a wiki page that "
            "mentions the work package, and offers no API to delete it. Remove the link from that text instead."
        )
        listed_after = await client.wiki_page_link.list_for_work_package(work_package_id)
        assert [link.id for link in listed_after.results] == [link_id]
    finally:
        # Deleting the work package would leave its inline link behind; clearing
        # the description removes it through OpenProject's own sync.
        update_result = await client.work_package.update(
            work_package_id=await write_ref(client, work_package_id), description="", confirm=True
        )
        assert update_result.ready, update_result.validation_errors


async def test_create_wiki_page_link(client: OpenProjectClient, test_project: str, wp_ids: list[int]) -> None:
    wp_result = await client.work_package.create(
        project=test_project,
        type="Task",
        subject=f"[integration-test] wiki link create {uuid.uuid4().hex[:8]}",
        confirm=True,
    )
    assert wp_result.ready, wp_result.validation_errors
    work_package_id = wp_result.work_package_id
    wp_ids.append(work_package_id)

    try:
        create_result = await client.wiki_page_link.create(
            await write_ref(client, work_package_id), identifier="wiki", provider=_PROVIDER, confirm=True
        )
    except NotFoundError:
        pytest.skip("POST work_packages/{id}/wiki_page_links not available (requires OpenProject 17.7+)")
    link_id = create_result.link_id
    assert link_id is not None
    try:
        assert create_result.state == "confirmed", create_result.validation_errors
        assert create_result.result is not None
        assert (create_result.result.identifier, create_result.result.link_type) == ("wiki", "relation")
    finally:
        await _delete_link_bypassing_the_list(client, link_id)


async def test_create_wiki_page_link_preview_without_confirm_does_not_write(
    client: OpenProjectClient, test_project: str, wp_ids: list[int], openproject_version: tuple[int, int]
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
        await write_ref(client, work_package_id), identifier="wiki", provider=_PROVIDER, confirm=False
    )
    assert preview_result.state == "preview"
    assert preview_result.result is None

    # Zero links: 17.7's `relation.any?` guard handles this; on 17.5/17.6 it
    # 500s (see module docstring), and before 17.5 the route does not exist.
    try:
        listed = await client.wiki_page_link.list_for_work_package(work_package_id)
    except NotFoundError:
        pytest.skip("wiki_page_links endpoint not available (requires OpenProject 17.5+)")
    except OpenProjectServerError:
        # Known-broken only on 17.5/17.6 (no relation.any? guard, see module
        # docstring); 17.7 has the guard and should never 500 here.
        if openproject_version not in {(17, 5), (17, 6)}:
            raise
        pytest.skip(
            "GET work_packages/{id}/wiki_page_links 500s without links on this instance "
            "(known-broken on 17.5/17.6, see module docstring)"
        )
    assert listed.count == 0


async def test_create_wiki_page_link_denies_work_package_outside_write_allowlist(
    client: OpenProjectClient, test_project: str, wp_ids: list[int], open_client
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
    restricted_client = await open_client(restricted_settings)

    with pytest.raises(PermissionDeniedError):
        await restricted_client.wiki_page_link.create(
            await write_ref(client, work_package_id), identifier="wiki", provider=_PROVIDER, confirm=True
        )


@pytest.mark.xfail(
    raises=OpenProjectServerError,
    reason="Upstream OpenProject bug (OP-19928, opf/openproject#24770): listing 500s while none of a "
    "work package's links resolves to a wiki page (see module docstring). Un-xfail once a "
    "release with the fix is the oldest supported 17.7+ image.",
    strict=False,
)
async def test_list_work_package_wiki_links_with_only_an_unresolvable_link(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    wp_result = await client.work_package.create(
        project=test_project,
        type="Task",
        subject=f"[integration-test] wiki link list {uuid.uuid4().hex[:8]}",
        confirm=True,
    )
    assert wp_result.ready, wp_result.validation_errors
    work_package_id = wp_result.work_package_id
    wp_ids.append(work_package_id)

    try:
        create_result = await client.wiki_page_link.create(
            await write_ref(client, work_package_id), identifier="wiki", provider=_PROVIDER, confirm=True
        )
    except NotFoundError:
        pytest.skip("POST work_packages/{id}/wiki_page_links not available (requires OpenProject 17.7+)")
    link_id = create_result.link_id
    assert link_id is not None

    try:
        listed = await client.wiki_page_link.list_for_work_package(work_package_id)
        assert [link.id for link in listed.results] == [link_id]
    finally:
        await _delete_link_bypassing_the_list(client, link_id)
