"""Integration tests for board CRUD operations."""

from __future__ import annotations

import pytest

from openproject_ce_mcp.client import OpenProjectClient

pytestmark = pytest.mark.integration


async def test_list_boards(client: OpenProjectClient, test_project: str) -> None:
    result = await client.list_boards(project=test_project)
    assert result is not None
    assert result.count >= 0


async def test_get_board(client: OpenProjectClient, test_project: str) -> None:
    result = await client.list_boards(project=test_project)
    if result.count == 0:
        pytest.skip("No boards in test project")
    board = await client.get_board(result.results[0].id)
    assert board.id > 0
    assert board.name


async def test_create_get_update_delete_board(
    client: OpenProjectClient, test_project: str, board_ids: list[int]
) -> None:
    # Create
    result = await client.create_board(
        name="[integration-test] board",
        project=test_project,
        public=False,
        confirm=True,
    )
    assert result.ready, result.validation_errors
    board_id = result.board_id
    assert board_id is not None and board_id > 0
    board_ids.append(board_id)

    # Read
    board = await client.get_board(board_id)
    assert board.id == board_id
    assert board.project is not None

    # Update
    update_result = await client.update_board(
        board_id=board_id,
        public=True,
        confirm=True,
    )
    assert update_result.ready, update_result.validation_errors

    updated = await client.get_board(board_id)
    assert updated.public is True

    # Delete
    delete_result = await client.delete_board(board_id=board_id, confirm=True)
    assert delete_result.ready and delete_result.confirmed
    board_ids.remove(board_id)
