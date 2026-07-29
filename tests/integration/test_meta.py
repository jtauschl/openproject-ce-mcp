"""Integration tests for stateless metadata endpoints."""

from __future__ import annotations

import json

import pytest

from openproject_ce_mcp.client import OpenProjectClient, OpenProjectError

pytestmark = pytest.mark.integration


async def test_get_current_user(client: OpenProjectClient) -> None:
    user = await client.get_current_user()
    assert user.login
    assert user.id > 0


async def test_get_instance_configuration(client: OpenProjectClient) -> None:
    config = await client.get_instance_configuration()
    assert config is not None


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


async def test_update_my_preferences_roundtrip(client: OpenProjectClient) -> None:
    """update_my_preferences PATCHes my_preferences, a 308-redirecting alias
    for users/me/preferences (confirmed live: the bare path returns 308/301,
    followed transparently since the client sets follow_redirects=True) -- no
    live coverage previously exercised the write path itself, only the read.

    Regression: a previous version of this client accepted a "lang" parameter
    here, but OpenProject's real UserPreferenceRepresenter has no "lang"
    property at all -- language is a User attribute (see update_user),
    not a preference. Verified live: PATCHing {"lang": ...} silently no-ops
    with a 200 and no validation error, even for a garbage value. This test
    exercises timeZone instead, a field the real representer does expose, and
    restores the token owner's original value afterwards since this mutates
    real, shared account state rather than disposable test data."""
    original = await client.get_my_preferences()
    original_time_zone = original.time_zone

    try:
        new_time_zone = "America/New_York" if original_time_zone != "America/New_York" else "Europe/Berlin"
        updated = await client.update_my_preferences(time_zone=new_time_zone, confirm=True)
        assert updated.confirmed
        assert updated.result is not None
        assert updated.result.time_zone == new_time_zone

        refetched = await client.get_my_preferences()
        assert refetched.time_zone == new_time_zone
    finally:
        if original_time_zone is not None:
            restored = await client.update_my_preferences(time_zone=original_time_zone, confirm=True)
            assert restored.result is not None
            assert restored.result.time_zone == original_time_zone
