"""Integration tests for stateless metadata endpoints."""

from __future__ import annotations

import json

import pytest

from openproject_ce_mcp.client import OpenProjectClient, OpenProjectError

pytestmark = pytest.mark.integration


async def test_get_current_user(client: OpenProjectClient) -> None:
    user = await client.get_current_user()
    # seed.rb always mints the primary integration test token for the admin
    # user (User.admin.active.first), so login is deterministic here.
    assert user.login == "admin"
    assert user.id > 0


async def test_get_instance_configuration(client: OpenProjectClient) -> None:
    config = await client.get_instance_configuration()
    assert config is not None
    assert config.host_name
    if config.maximum_api_v3_page_size is None:
        # OpenProject 16.6's GET /api/v3/configuration response has no
        # maximumAPIV3PageSize field at all -- confirmed present on 17.4+
        # via raw curl against all four op-sources Docker test instances
        # (17.4/17.5/17.6/17.7 all return it, 16.6 does not). A real
        # version-floor on the server's own response shape, not a client
        # parsing bug -- our field name/casing round-trips correctly on
        # every version that actually sends the field.
        pytest.skip("maximumAPIV3PageSize is absent from GET /configuration on OpenProject 16.6")
    assert config.maximum_api_v3_page_size > 0


async def test_list_time_entry_activities(client: OpenProjectClient) -> None:
    result = await client.list_time_entry_activities()
    # A fresh OpenProject instance ships default time entry activities
    # (Development, Management, ...) -- this is instance-wide config, not
    # seed data, so it's always non-empty on a real install.
    assert result.count > 0
    assert result.results[0].name


async def test_render_text(client: OpenProjectClient) -> None:
    try:
        result = await client.render_text(text="**hello**", format="markdown")
    except (OpenProjectError, json.JSONDecodeError):
        pytest.skip("render_text endpoint not available on this instance")
    assert result.html
    assert "hello" in result.html


async def test_list_working_days(client: OpenProjectClient) -> None:
    result = await client.list_working_days()
    # A default OpenProject instance's working-day config is Mon-Fri; weekends
    # are absent. Not asserting a fixed set of specific days here since this
    # is instance-configurable, but the shape must be non-empty and each
    # entry must carry a real day identifier.
    assert result.count > 0
    assert all(day.name for day in result.results)
    # Default OpenProject config: weekdays working, weekends not.
    working_by_name = {day.name: day.working for day in result.results}
    assert working_by_name.get("Saturday") is False
    assert working_by_name.get("Sunday") is False
    assert working_by_name.get("Monday") is True


async def test_get_my_preferences(client: OpenProjectClient) -> None:
    prefs = await client.get_my_preferences()
    assert prefs is not None
    assert prefs.time_zone is not None


async def test_update_my_preferences_roundtrip(client: OpenProjectClient) -> None:
    """update_my_preferences PATCHes my_preferences, a 308-redirecting alias
    for users/me/preferences (confirmed live: the bare path returns 308/301,
    followed transparently since the client sets follow_redirects=True).

    OpenProject's real UserPreferenceRepresenter has no "lang" property at
    all -- language is a User attribute (see update_user), not a preference.
    Verified live: PATCHing {"lang": ...} silently no-ops with a 200 and no
    validation error, even for a garbage value. This test exercises timeZone
    instead, a field the real representer does expose, and restores the
    token owner's original value afterwards since this mutates real, shared
    account state rather than disposable test data."""
    original = await client.get_my_preferences()
    original_time_zone = original.time_zone

    try:
        new_time_zone = "America/New_York" if original_time_zone != "America/New_York" else "Europe/Berlin"
        updated = await client.update_my_preferences(time_zone=new_time_zone, confirm=True)
        assert updated.state == "confirmed"
        assert updated.result is not None
        assert updated.result.time_zone == new_time_zone

        refetched = await client.get_my_preferences()
        assert refetched.time_zone == new_time_zone
    finally:
        if original_time_zone is not None:
            restored = await client.update_my_preferences(time_zone=original_time_zone, confirm=True)
            assert restored.result is not None
            assert restored.result.time_zone == original_time_zone
