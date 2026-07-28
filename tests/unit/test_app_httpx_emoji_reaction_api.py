from __future__ import annotations

import json

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_emoji_reaction_api import (
    HttpxEmojiReactionApi,
    normalize_emoji_reaction,
    normalize_emoji_reactions,
)
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _reaction_payload(*, reaction: str = "thumbs_up", count: int = 2) -> dict:
    return {
        "reaction": reaction,
        "emoji": "\U0001f44d",
        "reactionsCount": count,
        "_links": {"reactingUsers": [{"title": "Ada Lovelace"}, {"title": "Alan Turing"}]},
    }


@pytest.mark.asyncio
async def test_list_for_work_package_requests_activities_emoji_reactions() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/work_packages/9/activities_emoji_reactions"
        return httpx.Response(200, json={"_embedded": {"elements": [_reaction_payload()]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxEmojiReactionApi(HttpxTransport(http_client))
        summaries = await api.list_for_work_package(9)

    assert len(summaries) == 1
    assert summaries[0].reaction == "thumbs_up"
    assert summaries[0].count == 2
    assert summaries[0].users == ["Ada Lovelace", "Alan Turing"]


@pytest.mark.asyncio
async def test_list_for_work_package_missing_embedded_elements_returns_empty_list() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={}, request=request)

    async with _client(handler) as http_client:
        api = HttpxEmojiReactionApi(HttpxTransport(http_client))
        summaries = await api.list_for_work_package(9)

    assert summaries == []


@pytest.mark.asyncio
async def test_get_activity_requests_single_activity() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/activities/1988"
        return httpx.Response(
            200, json={"id": 1988, "_links": {"workPackage": {"href": "/api/v3/work_packages/42"}}}, request=request
        )

    async with _client(handler) as http_client:
        api = HttpxEmojiReactionApi(HttpxTransport(http_client))
        activity = await api.get_activity(1988)

    assert activity["_links"]["workPackage"]["href"] == "/api/v3/work_packages/42"


@pytest.mark.asyncio
async def test_toggle_patches_and_returns_normalized_reactions() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/activities/1988/emoji_reactions"
        assert request.method == "PATCH"
        payload = json.loads(request.content)
        assert payload == {"reaction": "thumbs_up"}
        return httpx.Response(200, json={"_embedded": {"elements": [_reaction_payload()]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxEmojiReactionApi(HttpxTransport(http_client))
        summaries = await api.toggle(1988, "thumbs_up")

    assert len(summaries) == 1
    assert summaries[0].reaction == "thumbs_up"


def test_normalize_emoji_reaction_drops_blank_user_titles() -> None:
    payload = _reaction_payload()
    payload["_links"]["reactingUsers"].append({"title": None})

    summary = normalize_emoji_reaction(payload)

    assert summary.users == ["Ada Lovelace", "Alan Turing"]


def test_normalize_emoji_reaction_defaults_count_to_zero() -> None:
    payload = _reaction_payload()
    del payload["reactionsCount"]

    summary = normalize_emoji_reaction(payload)

    assert summary.count == 0


def test_normalize_emoji_reactions_ignores_non_dict_elements() -> None:
    summaries = normalize_emoji_reactions({"_embedded": {"elements": [_reaction_payload(), "not-a-dict"]}})

    assert len(summaries) == 1
