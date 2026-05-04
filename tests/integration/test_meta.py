"""Integration tests for stateless metadata endpoints."""
from __future__ import annotations

import json

import pytest

from openproject_mcp.client import OpenProjectClient, OpenProjectError

pytestmark = pytest.mark.integration


async def test_get_current_user(client: OpenProjectClient) -> None:
    user = await client.get_current_user()
    assert user.login
    assert user.id > 0


async def test_get_instance_configuration(client: OpenProjectClient) -> None:
    config = await client.get_instance_configuration()
    assert config is not None


async def test_list_statuses(client: OpenProjectClient) -> None:
    result = await client.list_statuses()
    assert result.count > 0
    assert result.results[0].name


async def test_list_priorities(client: OpenProjectClient) -> None:
    result = await client.list_priorities()
    assert result.count > 0
    assert result.results[0].name


async def test_list_types(client: OpenProjectClient) -> None:
    result = await client.list_types()
    assert result.count > 0
    assert result.results[0].name


async def test_list_roles(client: OpenProjectClient) -> None:
    result = await client.list_roles()
    assert result.count > 0
    assert result.results[0].name


async def test_list_time_entry_activities(client: OpenProjectClient) -> None:
    result = await client.list_time_entry_activities()
    assert result.count >= 0


async def test_render_text(client: OpenProjectClient) -> None:
    try:
        result = await client.render_text(text="**hello**", format="markdown")
    except (OpenProjectError, json.JSONDecodeError):
        pytest.skip("render_text endpoint not available on this instance")
    assert result.html
    assert "hello" in result.html


async def test_list_working_days(client: OpenProjectClient) -> None:
    result = await client.list_working_days()
    assert result.count > 0


async def test_get_my_preferences(client: OpenProjectClient) -> None:
    prefs = await client.get_my_preferences()
    assert prefs is not None
