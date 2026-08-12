from __future__ import annotations

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_meeting_section_api import HttpxMeetingSectionApi, normalize_meeting_section
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _section_payload(*, section_id: int = 41, title: str = "Backlog") -> dict:
    return {
        "id": section_id,
        "title": title,
        "position": 1,
        "backlog": True,
        "createdAt": "2026-08-01T00:00:00Z",
        "updatedAt": "2026-08-02T00:00:00Z",
        "_links": {"meeting": {"href": "/api/v3/meetings/12", "title": "Sprint Planning"}},
    }


def test_normalize_meeting_section_extracts_all_fields() -> None:
    summary = normalize_meeting_section(_section_payload())
    assert summary.id == 41
    assert summary.title == "Backlog"
    assert summary.position == 1
    assert summary.backlog is True
    assert summary.meeting_id == 12
    assert summary.created_at == "2026-08-01T00:00:00Z"
    assert summary.updated_at == "2026-08-02T00:00:00Z"


@pytest.mark.asyncio
async def test_list_for_meeting_requests_the_meeting_scoped_endpoint() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/meetings/12/sections"
        return httpx.Response(200, json={"_embedded": {"elements": [_section_payload()]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxMeetingSectionApi(HttpxTransport(http_client))
        records = await api.list_for_meeting(12)

    assert [r.summary.id for r in records] == [41]


@pytest.mark.asyncio
async def test_get_requests_the_section_id() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/meeting_sections/41"
        return httpx.Response(200, json=_section_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxMeetingSectionApi(HttpxTransport(http_client))
        record = await api.get(41)

    assert record.summary.id == 41


@pytest.mark.asyncio
async def test_create_posts_to_global_meeting_sections() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/meeting_sections"
        assert request.method == "POST"
        return httpx.Response(201, json=_section_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxMeetingSectionApi(HttpxTransport(http_client))
        record = await api.create({"title": "Backlog"})

    assert record.summary.id == 41


@pytest.mark.asyncio
async def test_update_patches_the_section_id() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/meeting_sections/41"
        assert request.method == "PATCH"
        return httpx.Response(200, json=_section_payload(title="Updated"), request=request)

    async with _client(handler) as http_client:
        api = HttpxMeetingSectionApi(HttpxTransport(http_client))
        record = await api.update(41, {"title": "Updated"})

    assert record.summary.title == "Updated"


@pytest.mark.asyncio
async def test_delete_requests_the_section_id() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert request.url.path == "/api/v3/meeting_sections/41"
        return httpx.Response(204, request=request)

    async with _client(handler) as http_client:
        api = HttpxMeetingSectionApi(HttpxTransport(http_client))
        await api.delete(41)
