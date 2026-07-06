"""Integration tests for membership and user read operations."""

from __future__ import annotations

import pytest

from openproject_ce_mcp.client import OpenProjectClient, PermissionDeniedError

pytestmark = pytest.mark.integration


async def test_list_project_memberships(client: OpenProjectClient, test_project: str) -> None:
    result = await client.list_project_memberships(test_project)
    assert result is not None
    assert result.count >= 0


async def test_list_users(client: OpenProjectClient) -> None:
    try:
        result = await client.list_users()
    except PermissionDeniedError:
        pytest.skip("Instance requires admin rights to list users")
    assert result.count > 0
    assert result.results[0].login


async def test_get_user_me(client: OpenProjectClient) -> None:
    me = await client.get_current_user()
    user = await client.get_user(str(me.id))
    assert user.id == me.id
    assert user.login == me.login


async def test_list_roles(client: OpenProjectClient) -> None:
    result = await client.list_roles()
    assert result.count > 0


async def test_list_groups(client: OpenProjectClient) -> None:
    result = await client.list_groups()
    assert result is not None
    assert result.count >= 0
