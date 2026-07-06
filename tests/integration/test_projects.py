"""Integration tests for project read operations."""

from __future__ import annotations

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
