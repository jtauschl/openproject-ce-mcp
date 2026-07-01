"""Integration tests for board read operations."""
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
