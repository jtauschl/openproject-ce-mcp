"""Integration tests for grid CRUD operations.

Uses scope="/my/page" (the personal-dashboard carve-out) rather than a
project-scoped href -- it's writable for create/update regardless of
OPENPROJECT_WRITE_PROJECTS and needs no project resolution, keeping this
test independent of the test project's own configuration. Deletion is a
different story -- see test_create_get_update_delete_grid's delete step.
"""

from __future__ import annotations

import pytest

from openproject_ce_mcp.client import OpenProjectClient, PermissionDeniedError

pytestmark = pytest.mark.integration


async def test_list_grids(client: OpenProjectClient) -> None:
    result = await client.list_grids()
    assert result is not None
    assert result.count >= 0


async def test_create_get_update_delete_grid(client: OpenProjectClient, grid_ids: list[int]) -> None:
    # Create
    result = await client.create_grid(
        name="[integration-test] grid",
        scope="/my/page",
        row_count=4,
        column_count=6,
        confirm=True,
    )
    assert result.ready, result.validation_errors
    grid_id = result.grid_id
    assert grid_id is not None and grid_id > 0
    grid_ids.append(grid_id)

    # Read
    grid = await client.get_grid(grid_id)
    assert grid.id == grid_id
    assert grid.scope == "/my/page"

    # Update
    update_result = await client.update_grid(
        grid_id=grid_id,
        row_count=5,
        confirm=True,
    )
    assert update_result.ready, update_result.validation_errors

    updated = await client.get_grid(grid_id)
    assert updated.row_count == 5

    # Delete -- OpenProject rejects deletion of /my/page grids for every user,
    # including admin (OPM-323, verified against op-sources/17.6:
    # Grids::Grid#user_deletable? is hardcoded false, Grids::MyPage never
    # overrides it, and Grids::DeleteContract's delete_permission requires
    # model.user_deletable? -- only Boards::Grid overrides it to true). There
    # is no API path that deletes a /my/page grid; this grid is intentionally
    # left behind, same as every prior run of this test, not a cleanup gap.
    with pytest.raises(PermissionDeniedError):
        await client.delete_grid(grid_id=grid_id, confirm=True)
