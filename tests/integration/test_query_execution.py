"""Integration tests for executing a saved query and returning resolved work packages.

Uses a Board's underlying Query resource as the target -- Boards ARE
OpenProject Query resources (`_type: "Query"`), so a board's id doubles as a
valid query_id with a real, server-resolvable filter set (its default,
unfiltered board query matches every work package in the project).
"""

from __future__ import annotations

import dataclasses
import uuid

import pytest

from openproject_ce_mcp.client import OpenProjectClient

pytestmark = pytest.mark.integration


async def test_execute_query_returns_resolved_work_packages(
    client: OpenProjectClient, test_project: str, wp_ids: list[int], board_ids: list[int]
) -> None:
    wp_result = await client.create_work_package(
        project=test_project,
        type="Task",
        subject=f"[integration-test] execute_query {uuid.uuid4().hex[:8]}",
        confirm=True,
    )
    assert wp_result.ready, wp_result.validation_errors
    wp_ids.append(wp_result.work_package_id)

    board_result = await client.create_board(
        name=f"[integration-test] query {uuid.uuid4().hex[:8]}",
        project=test_project,
        public=False,
        confirm=True,
    )
    assert board_result.ready, board_result.validation_errors
    board_ids.append(board_result.board_id)

    result = await client.execute_query(board_result.board_id)
    assert any(wp.id == wp_result.work_package_id for wp in result.results)


async def test_execute_query_filters_results_against_read_allowlist(
    client: OpenProjectClient, test_project: str, wp_ids: list[int], board_ids: list[int]
) -> None:
    """A query executes with the API token's full server-side permissions --
    this MCP must still filter the resolved work packages against its own
    OPENPROJECT_READ_PROJECTS allowlist before returning them."""
    wp_result = await client.create_work_package(
        project=test_project,
        type="Task",
        subject=f"[integration-test] execute_query denial {uuid.uuid4().hex[:8]}",
        confirm=True,
    )
    assert wp_result.ready, wp_result.validation_errors
    wp_ids.append(wp_result.work_package_id)

    board_result = await client.create_board(
        name=f"[integration-test] query denial {uuid.uuid4().hex[:8]}",
        project=test_project,
        public=False,
        confirm=True,
    )
    assert board_result.ready, board_result.validation_errors
    board_ids.append(board_result.board_id)

    restricted_settings = dataclasses.replace(client.settings, read_projects=("no-such-project",))
    restricted_client = OpenProjectClient(restricted_settings)
    await restricted_client.initialize()

    result = await restricted_client.execute_query(board_result.board_id)
    assert not any(wp.id == wp_result.work_package_id for wp in result.results)
