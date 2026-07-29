"""Integration tests for project read operations."""

from __future__ import annotations

import dataclasses
import uuid

import pytest

from openproject_ce_mcp.client import NotFoundError, OpenProjectClient

pytestmark = pytest.mark.integration


async def test_list_projects(client: OpenProjectClient) -> None:
    result = await client.list_projects()
    assert result.count > 0
    assert result.results[0].name


async def test_get_project(client: OpenProjectClient, test_project: str) -> None:
    project = await client.get_project(test_project)
    assert project.identifier == test_project
    assert project.name


async def test_get_project_admin_context(client: OpenProjectClient, test_project: str) -> None:
    ctx = await client.get_project_admin_context(test_project)
    assert ctx is not None


async def test_get_project_admin_context_filters_parent_candidates_by_read_allowlist(
    client: OpenProjectClient, test_project: str, project_refs: list[str]
) -> None:
    """Regression: available_parent_projects previously returned every
    candidate OpenProject considers a valid parent, regardless of
    OPENPROJECT_READ_PROJECTS -- a project outside the allowlist leaked its
    name/identifier through this picklist. The fixture's client is
    restricted to read_projects=(test_project,), so a freshly created,
    differently-named project must NOT appear as a parent candidate.

    Creating that second project requires its own, unrestricted client:
    the fixture's client's read_projects/write_projects are both scoped to
    (test_project,) alone, so create_project's own allowlist check would
    reject a differently-named project before this test ever reaches the
    available_parent_projects assertion it's meant to exercise.
    """
    unrestricted_settings = dataclasses.replace(
        client.settings,
        read_projects=("*",),
        write_projects=("*",),
    )
    unrestricted_client = OpenProjectClient(unrestricted_settings)
    await unrestricted_client.initialize()

    identifier = f"integration-test-{uuid.uuid4().hex[:8]}"
    create_result = await unrestricted_client.create_project(
        name=f"[integration-test] {identifier}", identifier=identifier, confirm=True
    )
    assert create_result.ready, create_result.validation_errors
    project_refs.append(identifier)

    ctx = await client.get_project_admin_context(test_project)

    candidate_identifiers = {ref.identifier for ref in ctx.available_parent_projects}
    assert identifier not in candidate_identifiers


async def test_get_project_configuration(client: OpenProjectClient, test_project: str) -> None:
    # The project configuration endpoint was added in 17.4; older instances 404.
    try:
        config = await client.get_project_configuration(test_project)
    except NotFoundError:
        pytest.skip("project configuration endpoint requires OpenProject 17.4+")
    assert config is not None


async def test_list_types_scoped_to_project(client: OpenProjectClient, test_project: str) -> None:
    result = await client.list_types(project=test_project)
    assert result.count > 0


async def test_list_categories(client: OpenProjectClient, test_project: str) -> None:
    result = await client.list_categories(test_project)
    assert result is not None


async def test_get_my_project_access(client: OpenProjectClient, test_project: str) -> None:
    access = await client.get_my_project_access(test_project)
    assert access is not None


async def test_list_principals(client: OpenProjectClient) -> None:
    result = await client.list_principals()
    assert result.count >= 0  # may be empty on minimal instance
