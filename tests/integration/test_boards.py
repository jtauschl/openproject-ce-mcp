"""Integration tests for board read operations."""

from __future__ import annotations

import dataclasses
import uuid

import pytest

from openproject_ce_mcp.client import OpenProjectClient, PermissionDeniedError

from .conftest import disposable_project_identifier

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


async def test_update_board_denies_reparent_into_write_restricted_project(
    client: OpenProjectClient, test_project: str, project_refs: list[str]
) -> None:
    """Regression: update_board's own current-project check only proved the
    BOARD's existing project was write-allowed -- the reparent target (a
    DIFFERENT project, passed via `project=`) was resolved for href-building
    only, with no write-allowlist check of its own, letting a caller move a
    board into a project outside OPENPROJECT_WRITE_PROJECTS."""
    unrestricted_settings = dataclasses.replace(
        client.settings,
        read_projects=("*",),
        write_projects=("*",),
    )
    unrestricted_client = OpenProjectClient(unrestricted_settings)
    await unrestricted_client.initialize()

    target_identifier = disposable_project_identifier()
    create_project_result = await unrestricted_client.create_project(
        name=f"[integration-test] {target_identifier}", identifier=target_identifier, confirm=True
    )
    assert create_project_result.ready, create_project_result.validation_errors
    project_refs.append(target_identifier)

    create_board_result = await client.create_board(
        name=f"[integration-test] {uuid.uuid4().hex[:8]}", project=test_project, confirm=True
    )
    assert create_board_result.ready, create_board_result.validation_errors
    board_id = create_board_result.board_id
    assert board_id is not None

    try:
        with pytest.raises(PermissionDeniedError):
            await client.update_board(board_id=board_id, project=target_identifier, confirm=True)
    finally:
        await client.delete_board(board_id=board_id, confirm=True)
