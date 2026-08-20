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
        "_links": {
            "project": {"href": "/api/v3/projects/1", "title": "Demo Project"},
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
        api = HttpxWikiPageApi(HttpxTransport(http_client))
        record = await api.get(20)

    assert record.detail.id == 20
    assert record.detail.title == "Wiki Page"
    assert record.detail.project == "Demo Project"
    assert record.detail.project_id == 1
    assert not hasattr(record.detail, "content")
    assert not hasattr(record.detail, "attachments_url")
    assert not hasattr(record.detail, "url")
    assert record.project_link == {"href": "/api/v3/projects/1", "title": "Demo Project"}


@pytest.mark.asyncio
async def test_get_title_falls_back_to_placeholder_when_missing() -> None:
    payload = _wiki_page_payload()
    del payload["title"]

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    async with _client(handler) as http_client:
        api = HttpxWikiPageApi(HttpxTransport(http_client))
        record = await api.get(20)

    assert record.detail.title == "Wiki page 20"
