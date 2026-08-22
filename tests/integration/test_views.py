"""Integration tests for view reads.

This MCP server exposes list/get only (no create/update/delete tool for
views). OpenProject's own API does have a real create route --
`POST /api/v3/views/{type_name}` (only "work_packages_table" is registered
as a type; `modules/backlogs` does not add a Sprint-backed view type),
gated on a `query` link -- creating a query via `POST /api/v3/queries` then
a view via `POST /api/v3/views/work_packages_table` with `_links.query`
pointing at it succeeds and returns a real view id. This client has no create_query
tool at all, so there is currently no way to drive view creation through
this server's own tool surface -- the earlier claim that views have no
create endpoint anywhere was wrong (that only holds for THIS client, not
OpenProject's API). get_view is exercised against a pre-existing view
sourced via list_views -- if the test project has none, that test is
skipped rather than failed, since this server has no create_view/
create_query tool to seed one through.
"""

from __future__ import annotations

import dataclasses

import pytest

from openproject_ce_mcp.client import OpenProjectClient

pytestmark = pytest.mark.integration


async def test_list_views(client: OpenProjectClient, test_project: str) -> None:
    result = await client.list_views(project=test_project)
    assert result is not None
    if result.count == 0:
        pytest.skip("no existing view in the test project (no create_view API to seed one)")
    assert result.results[0].id


async def test_get_view(client: OpenProjectClient, test_project: str) -> None:
    existing = await client.list_views(project=test_project)
    if existing.count == 0:
        pytest.skip("no existing view in the test project to read (no create_view API to seed one)")

    view_id = existing.results[0].id

    view = await client.get_view(view_id)
    assert view.id == view_id


async def test_list_views_paginates_beyond_a_single_page(client: OpenProjectClient) -> None:
    """Regression: list_views never sent offset/pageSize to OpenProject at
    all, so a limit smaller than the total available views silently
    returned everything the server happened to include in that first page
    rather than genuinely paginating. This server has no create_view tool
    (see module docstring), so this relies on the instance's pre-existing
    views rather than creating new ones -- unfiltered (no project=), same
    as test_list_grids_paginates_beyond_a_single_page. Uses an unrestricted
    client (read_projects=("*",)): the pre-existing views live under
    OpenProject's own demo "Scrum project" seed data, not the integration
    test project, so the default project-scoped client fixture would see
    zero of them regardless of how many actually exist on the instance."""
    unrestricted_settings = dataclasses.replace(client.settings, read_projects=("*",), write_projects=("*",))
    unrestricted_client = OpenProjectClient(unrestricted_settings)
    await unrestricted_client.initialize()

    unfiltered = await unrestricted_client.list_views(limit=100)
    if unfiltered.total < 2:
        pytest.skip("Not enough views on this instance to prove pagination")

    first_page = await unrestricted_client.list_views(limit=1)
    assert first_page.count == 1
    assert first_page.truncated
    assert first_page.next_offset == 2

    second_page = await unrestricted_client.list_views(limit=1, offset=2)
    assert second_page.count == 1
    assert second_page.results[0].id != first_page.results[0].id
