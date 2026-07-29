"""Integration tests for grid write operations."""

from __future__ import annotations

import dataclasses

import pytest

from openproject_ce_mcp.client import InvalidInputError, OpenProjectClient

pytestmark = pytest.mark.integration


async def test_create_grid_rejects_hidden_name_field(client: OpenProjectClient, test_project: str) -> None:
    """Regression: create_grid/update_grid bypassed OPENPROJECT_HIDE_GRID_FIELDS
    entirely on writes -- the "grid" entity was missing from
    HIDE_FIELD_ENV_BY_ENTITY altogether, so no grid field could ever be
    hidden on a write, unlike every other write-capable entity."""
    hidden_settings = dataclasses.replace(client.settings, hidden_fields={"grid": ("name",)})
    hidden_client = OpenProjectClient(hidden_settings)
    await hidden_client.initialize()

    with pytest.raises(InvalidInputError, match="OPENPROJECT_HIDE_GRID_FIELDS"):
        await hidden_client.create_grid(
            name="[integration-test] hidden field",
            scope=f"/projects/{test_project}",
            confirm=False,
        )


async def test_list_grids_paginates_beyond_a_single_page(client: OpenProjectClient) -> None:
    """Regression: list_grids never sent offset/pageSize to OpenProject at
    all (always requesting the server's own default page), so a limit
    smaller than the total available grids silently returned everything the
    server happened to include in that first page rather than genuinely
    paginating. OpenProject only allows one grid per scope, so this relies
    on the instance's pre-existing grids (dashboards/project overviews are
    themselves grids) rather than creating multiple new ones."""
    unfiltered = await client.list_grids(limit=100)
    if unfiltered.total < 2:
        pytest.skip("Not enough grids on this instance to prove pagination")

    first_page = await client.list_grids(limit=1)
    assert first_page.count == 1
    assert first_page.truncated
    assert first_page.next_offset == 2

    second_page = await client.list_grids(limit=1, offset=2)
    assert second_page.count == 1
    assert second_page.results[0].id != first_page.results[0].id
