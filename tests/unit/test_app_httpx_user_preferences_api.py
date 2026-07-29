from __future__ import annotations

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_user_preferences_api import (
    HttpxUserPreferencesApi,
    normalize_user_preferences,
)
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _preferences_payload() -> dict:
    return {
        "timeZone": "Europe/Berlin",
        "commentSortDescending": True,
        "warnOnLeavingUnsaved": False,
        "autoHidePopups": True,
    }


def test_normalize_user_preferences_maps_all_fields() -> None:
    preferences = normalize_user_preferences(_preferences_payload())

    assert preferences.time_zone == "Europe/Berlin"
    assert preferences.comment_sort_descending is True
    assert preferences.warn_on_leaving_unsaved is False
    assert preferences.auto_hide_popups is True


@pytest.mark.asyncio
async def test_get_sends_get_my_preferences_and_builds_record() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/v3/my_preferences"
        return httpx.Response(200, json=_preferences_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxUserPreferencesApi(HttpxTransport(http_client))
        record = await api.get()

    assert record.detail.time_zone == "Europe/Berlin"


@pytest.mark.asyncio
async def test_commit_update_patches_my_preferences_with_given_payload() -> None:
    import json

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        assert request.url.path == "/api/v3/my_preferences"
        body = json.loads(request.content)
        assert body == {
            "timeZone": "UTC",
            "commentSortDescending": False,
            "warnOnLeavingUnsaved": True,
            "autoHidePopups": False,
        }
        return httpx.Response(200, json=_preferences_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxUserPreferencesApi(HttpxTransport(http_client))
        payload = {
            "timeZone": "UTC",
            "commentSortDescending": False,
            "warnOnLeavingUnsaved": True,
            "autoHidePopups": False,
        }
        result = await api.commit_update(payload)

    assert result.time_zone == "Europe/Berlin"  # response reflects the server's normalized payload
