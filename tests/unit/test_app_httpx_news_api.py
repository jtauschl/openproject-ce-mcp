from __future__ import annotations

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_news_api import HttpxNewsApi
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _news_payload(news_id: int = 1) -> dict:
    return {
        "id": news_id,
        "title": "New feature",
        "summary": "Short summary",
        "description": {"format": "markdown", "raw": "Detailed news description content"},
        "_links": {
            "project": {"href": "/api/v3/projects/6", "title": "Demo Project"},
            "author": {"href": "/api/v3/users/9", "title": "Ada Lovelace"},
            "update": {"href": f"/api/v3/news/{news_id}"},
        },
        "createdAt": "2026-01-01T00:00:00Z",
    }


@pytest.mark.asyncio
async def test_list_all_sends_bounded_page_and_builds_records() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/news"
        params = dict(request.url.params)
        assert params["offset"] == "1"
        assert params["pageSize"] == "50"
        return httpx.Response(200, json={"_embedded": {"elements": [_news_payload()]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxNewsApi(HttpxTransport(http_client), base_url=BASE_URL)
        records = await api.list_all(page_size=50)

    assert len(records) == 1
    assert records[0].summary.id == 1
    assert records[0].summary.title == "New feature"
    assert records[0].project_link == {"href": "/api/v3/projects/6", "title": "Demo Project"}
    # to_detail() is lazy -- list_all()'s per-row records must still be able
    # to produce a correct NewsDetail on demand (e.g. if a future caller
    # needs it), it's just never called by NewsService.list() today.
    assert records[0].to_detail().id == 1


@pytest.mark.asyncio
async def test_list_all_missing_embedded_elements_returns_empty_list() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={}, request=request)

    async with _client(handler) as http_client:
        api = HttpxNewsApi(HttpxTransport(http_client), base_url=BASE_URL)
        records = await api.list_all(page_size=50)

    assert records == []


@pytest.mark.asyncio
async def test_get_builds_record_with_detail_shaped_description_and_raw_project_link() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/news/1"
        return httpx.Response(200, json=_news_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxNewsApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.get(1)

    assert record.summary.id == 1
    detail = record.to_detail()
    assert detail.id == 1
    # summary and detail both delimit the same raw description here (short
    # enough to survive both SUBJECT_LIMIT and FORMATTABLE_LIMIT uncut) --
    # the two-limit divergence itself is covered by the truncation test below.
    assert record.summary.description == "<user-content>Detailed news description content</user-content>"
    assert detail.description == "<user-content>Detailed news description content</user-content>"
    assert record.project_link == {"href": "/api/v3/projects/6", "title": "Demo Project"}


@pytest.mark.asyncio
async def test_get_summary_and_detail_apply_different_truncation_limits_to_same_raw_description() -> None:
    long_text = "x" * 2_000  # longer than SUBJECT_LIMIT (255) and FORMATTABLE_LIMIT (1200)
    payload = _news_payload()
    payload["description"] = {"format": "markdown", "raw": long_text}

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    async with _client(handler) as http_client:
        api = HttpxNewsApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.get(1)

    detail = record.to_detail()
    assert record.summary.description is not None
    assert detail.description is not None
    assert len(record.summary.description) < len(detail.description)


@pytest.mark.asyncio
async def test_commit_create_posts_and_returns_detail() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/news"
        assert request.method == "POST"
        return httpx.Response(201, json=_news_payload(news_id=42), request=request)

    async with _client(handler) as http_client:
        api = HttpxNewsApi(HttpxTransport(http_client), base_url=BASE_URL)
        detail = await api.commit_create({"title": "New feature"})

    assert detail.id == 42


@pytest.mark.asyncio
async def test_commit_update_patches_and_returns_detail() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/news/1"
        assert request.method == "PATCH"
        return httpx.Response(200, json=_news_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxNewsApi(HttpxTransport(http_client), base_url=BASE_URL)
        detail = await api.commit_update(1, {"title": "Updated"})

    assert detail.id == 1


@pytest.mark.asyncio
async def test_delete_sends_delete_request() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/news/1"
        assert request.method == "DELETE"
        return httpx.Response(204, request=request)

    async with _client(handler) as http_client:
        api = HttpxNewsApi(HttpxTransport(http_client), base_url=BASE_URL)
        await api.delete(1)
