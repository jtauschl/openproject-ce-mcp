"""Integration tests for grid write operations."""

from __future__ import annotations

import dataclasses

import pytest

from openproject_ce_mcp.client import InvalidInputError, OpenProjectClient

from .conftest import disposable_project_identifier

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


async def test_update_grid_changes_dimensions(client: OpenProjectClient, project_refs: list[str]) -> None:
    """update_grid POSTs grids/{id}/form then PATCHes grids/{id} -- no live
    coverage previously exercised this write path, only create's hidden-field
    rejection and list's pagination. Uses a freshly created, disposable project
    for the grid's scope: OpenProject only allows one grid per scope, and
    test_project already has one (its own overview dashboard), so creating a
    second grid there fails with "Scope has already been taken". Cleanup of
    the grid itself happens implicitly when project_refs deletes the project
    (not via the grid_ids fixture, since that fixture's client is scoped only
    to test_project's write allowlist, not this disposable project)."""
    unrestricted_settings = dataclasses.replace(client.settings, read_projects=("*",), write_projects=("*",))
    unrestricted_client = OpenProjectClient(unrestricted_settings)
    await unrestricted_client.initialize()

    new_identifier = disposable_project_identifier()
    create_project_result = await unrestricted_client.create_project(
        name=f"[integration-test] {new_identifier}", identifier=new_identifier, confirm=True
    )
    assert create_project_result.ready, create_project_result.validation_errors
    project_refs.append(new_identifier)

    # rowCount/columnCount must be large enough to contain the server's
    # default project-overview widget layout (spans rows 1-4, columns 1-3) or
    # the form rejects the create with a widget-constraint validation error.
    create_result = await unrestricted_client.create_grid(
        name=f"[integration-test] {new_identifier}",
        scope=f"/projects/{new_identifier}",
        row_count=4,
        column_count=3,
        confirm=True,
    )
    assert create_result.ready, create_result.validation_errors
    grid_id = create_result.grid_id
    assert grid_id is not None

    updated = await unrestricted_client.update_grid(grid_id=grid_id, row_count=5, column_count=4, confirm=True)
    assert updated.confirmed
    assert updated.result is not None
    assert updated.result.row_count == 5
    assert updated.result.column_count == 4


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
