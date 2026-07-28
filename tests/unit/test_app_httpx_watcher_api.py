from __future__ import annotations

import json

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_watcher_api import HttpxWatcherApi, normalize_watcher
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _watcher_payload(user_id: int = 5, *, name: str = "Ada Lovelace", login: str | None = "ada") -> dict:
    payload: dict = {"id": user_id, "name": name}
    if login is not None:
        payload["login"] = login
    return payload


@pytest.mark.asyncio
async def test_list_for_work_package_requests_watchers_sub_collection() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/work_packages/9/watchers"
        return httpx.Response(200, json={"_embedded": {"elements": [_watcher_payload()]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxWatcherApi(HttpxTransport(http_client), base_url=BASE_URL)
        summaries = await api.list_for_work_package(9)

    assert len(summaries) == 1
    assert summaries[0].id == 5
    assert summaries[0].name == "Ada Lovelace"
    assert summaries[0].login == "ada"
    assert summaries[0].url == f"{BASE_URL}/users/5"


@pytest.mark.asyncio
async def test_list_for_work_package_missing_embedded_elements_returns_empty_list() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={}, request=request)

    async with _client(handler) as http_client:
        api = HttpxWatcherApi(HttpxTransport(http_client), base_url=BASE_URL)
        summaries = await api.list_for_work_package(9)

    assert summaries == []


@pytest.mark.asyncio
async def test_get_user_requests_single_user() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/users/5"
        return httpx.Response(200, json=_watcher_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxWatcherApi(HttpxTransport(http_client), base_url=BASE_URL)
        watcher = await api.get_user(5)

    assert watcher.id == 5
    assert watcher.name == "Ada Lovelace"


@pytest.mark.asyncio
async def test_add_posts_user_link_and_returns_normalized_watcher() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/work_packages/9/watchers"
        assert request.method == "POST"
        payload = json.loads(request.content)
        assert payload == {"_links": {"user": {"href": "/api/v3/users/5"}}}
        return httpx.Response(201, json=_watcher_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxWatcherApi(HttpxTransport(http_client), base_url=BASE_URL, api_prefix="/api/v3/")
        watcher = await api.add(9, 5)

    assert watcher.id == 5


@pytest.mark.asyncio
async def test_remove_sends_delete_request() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/work_packages/9/watchers/5"
        assert request.method == "DELETE"
        return httpx.Response(204, request=request)

    async with _client(handler) as http_client:
        api = HttpxWatcherApi(HttpxTransport(http_client), base_url=BASE_URL)
        await api.remove(9, 5)


def test_normalize_watcher_falls_back_to_generated_name_when_missing() -> None:
    payload = _watcher_payload()
    del payload["name"]

    summary = normalize_watcher(payload, base_url=BASE_URL)

    assert summary.name == "User 5"


def test_normalize_watcher_handles_missing_login() -> None:
    summary = normalize_watcher(_watcher_payload(login=None), base_url=BASE_URL)

    assert summary.login is None


def test_normalize_watcher_trims_long_name() -> None:
    summary = normalize_watcher(_watcher_payload(name="x" * 300), base_url=BASE_URL)

    assert len(summary.name) == 255
    assert summary.name.endswith("…")
