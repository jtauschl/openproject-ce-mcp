from __future__ import annotations

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_wiki_page_api import HttpxWikiPageApi
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _wiki_page_payload(wiki_page_id: int = 20, **extra) -> dict:
    payload = {
        "id": wiki_page_id,
        "title": "Wiki Page",
        "text": {"format": "markdown", "raw": "Wiki page content"},
        "_links": {
            "project": {"href": "/api/v3/projects/1", "title": "Demo Project"},
            "attachments": {"href": f"/api/v3/wiki_pages/{wiki_page_id}/attachments"},
        },
    }
    payload.update(extra)
    return payload


@pytest.mark.asyncio
async def test_get_builds_record_with_normalized_detail_and_raw_project_link() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/wiki_pages/20"
        return httpx.Response(200, json=_wiki_page_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxWikiPageApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.get(20)

    assert record.detail.id == 20
    assert record.detail.title == "Wiki Page"
    assert record.detail.project == "Demo Project"
    assert record.detail.project_id == 1
    assert record.detail.content == "<user-content>Wiki page content</user-content>"
    assert record.detail.attachments_url == f"{BASE_URL}/api/v3/wiki_pages/20/attachments"
    assert record.detail.url == f"{BASE_URL}/wiki_pages/20"
    assert record.project_link == {"href": "/api/v3/projects/1", "title": "Demo Project"}


@pytest.mark.asyncio
async def test_get_falls_back_to_content_key_when_text_is_absent() -> None:
    payload = _wiki_page_payload()
    del payload["text"]
    payload["content"] = {"format": "markdown", "raw": "Fallback content"}

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    async with _client(handler) as http_client:
        api = HttpxWikiPageApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.get(20)

    assert record.detail.content == "<user-content>Fallback content</user-content>"


@pytest.mark.asyncio
async def test_get_title_falls_back_to_placeholder_when_missing() -> None:
    payload = _wiki_page_payload()
    del payload["title"]

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    async with _client(handler) as http_client:
        api = HttpxWikiPageApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.get(20)

    assert record.detail.title == "Wiki page 20"


@pytest.mark.asyncio
async def test_get_attachments_url_returns_none_for_foreign_origin_href() -> None:
    payload = _wiki_page_payload()
    payload["_links"]["attachments"] = {"href": "https://evil.example.com/attachments"}

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    async with _client(handler) as http_client:
        api = HttpxWikiPageApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.get(20)

    assert record.detail.attachments_url is None


@pytest.mark.asyncio
async def test_get_content_truncates_at_50000_chars() -> None:
    long_text = "x" * 60_000
    payload = _wiki_page_payload()
    payload["text"] = {"format": "markdown", "raw": long_text}

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    async with _client(handler) as http_client:
        api = HttpxWikiPageApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.get(20)

    assert record.detail.content is not None
    # Content is delimited (<user-content>...</user-content>, 25 extra chars) around
    # the truncated 50_000-char body -- assert the raw body was actually cut, not the
    # delimited wrapper's exact length.
    inner = record.detail.content.removeprefix("<user-content>").removesuffix("</user-content>")
    assert len(inner) == 50_000
    assert inner.endswith("…")
