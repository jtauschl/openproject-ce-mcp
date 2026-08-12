from __future__ import annotations

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_post_api import HttpxPostApi
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _post_payload(post_id: int = 30, **extra) -> dict:
    payload = {
        "id": post_id,
        "subject": "Welcome to the forum",
        "_links": {
            "project": {"href": "/api/v3/projects/1", "title": "Demo Project"},
        },
    }
    payload.update(extra)
    return payload


@pytest.mark.asyncio
async def test_get_builds_record_with_normalized_detail_and_raw_project_link() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/posts/30"
        return httpx.Response(200, json=_post_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxPostApi(HttpxTransport(http_client))
        record = await api.get(30)

    assert record.detail.id == 30
    assert record.detail.subject == "Welcome to the forum"
    assert record.detail.project == "Demo Project"
    assert record.detail.project_id == 1
    assert not hasattr(record.detail, "content")
    assert record.project_link == {"href": "/api/v3/projects/1", "title": "Demo Project"}


@pytest.mark.asyncio
async def test_get_subject_falls_back_to_placeholder_when_missing() -> None:
    payload = _post_payload()
    del payload["subject"]

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    async with _client(handler) as http_client:
        api = HttpxPostApi(HttpxTransport(http_client))
        record = await api.get(30)

    assert record.detail.subject == "Post 30"


@pytest.mark.asyncio
async def test_get_handles_missing_project_link() -> None:
    payload = _post_payload()
    del payload["_links"]["project"]

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    async with _client(handler) as http_client:
        api = HttpxPostApi(HttpxTransport(http_client))
        record = await api.get(30)

    assert record.detail.project is None
    assert record.detail.project_id is None
    assert record.project_link is None
