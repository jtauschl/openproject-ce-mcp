"""Integration tests for executing a saved query and returning resolved work packages.

Uses a Board's underlying Query resource as the target -- Boards ARE
OpenProject Query resources (`_type: "Query"`), so a board's id doubles as a
valid query_id with a real, server-resolvable filter set (its default,
unfiltered board query matches every work package in the project, sorted
server-side -- oldest first, observed live -- unless a sort order is set
explicitly).
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
    wp_result = await client.work_package.create(
        project=test_project,
        type="Task",
        subject=f"[integration-test] execute_query {uuid.uuid4().hex[:8]}",
        confirm=True,
    )
    assert wp_result.ready, wp_result.validation_errors
    wp_ids.append(wp_result.work_package_id)

    # Sort newest-first: the shared test project accumulates work packages
    # across every integration-test run over time, and the server's own
    # default (unset) sort order returns oldest first -- a small page would
    # otherwise never include a work package just created here once the
    # project has grown past that page size (found live once the shared
    # project passed 60 work packages; an id-based filter was tried first
    # but the server rejects an "id" filter on a saved Query's own form,
    # even though the same filter works on the plain work-package list).
    # Sorting newest-first makes a small page reliable regardless of how
    # large the shared project grows.
    board_result = await client.board.create(
        name=f"[integration-test] query {uuid.uuid4().hex[:8]}",
        project=test_project,
        public=False,
        sort_by=["id:desc"],
        confirm=True,
    )
    assert board_result.ready, board_result.validation_errors
    board_ids.append(board_result.board_id)

    result = await client.query_execution.execute(board_result.board_id, limit=5)
    assert any(wp.id == wp_result.work_package_id for wp in result.results)


async def test_execute_query_filters_results_against_read_allowlist(
    client: OpenProjectClient, test_project: str, wp_ids: list[int], board_ids: list[int]
) -> None:
    """A query executes with the API token's full server-side permissions --
    this MCP must still filter the resolved work packages against its own
    OPENPROJECT_READ_PROJECTS allowlist before returning them."""
    wp_result = await client.work_package.create(
        project=test_project,
        type="Task",
        subject=f"[integration-test] execute_query denial {uuid.uuid4().hex[:8]}",
        confirm=True,
    )
    assert wp_result.ready, wp_result.validation_errors
    wp_ids.append(wp_result.work_package_id)

    board_result = await client.board.create(
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

    result = await restricted_client.query_execution.execute(board_result.board_id)
    assert not any(wp.id == wp_result.work_package_id for wp in result.results)
