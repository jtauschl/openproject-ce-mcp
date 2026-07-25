from __future__ import annotations

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_view_api import HttpxViewApi
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _view_payload(view_id: int = 1, *, with_project: bool = True) -> dict:
    links = {
        "query": {"href": "/api/v3/queries/9", "title": "My Query"},
    }
    if with_project:
        links["project"] = {"href": "/api/v3/projects/6", "title": "Demo Project"}
    return {
        "id": view_id,
        "_type": "Team planner view",
        "name": "Team Planner",
        "public": True,
        "starred": False,
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-02T00:00:00Z",
        "_links": links,
    }


@pytest.mark.asyncio
async def test_list_all_requests_the_views_endpoint() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/views"
        assert dict(request.url.params) == {"offset": "1", "pageSize": "50"}
        return httpx.Response(200, json={"_embedded": {"elements": [_view_payload()]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxViewApi(HttpxTransport(http_client), base_url=BASE_URL)
        records = await api.list_all(page_size=50)

    assert len(records) == 1
    summary = records[0].summary
    assert summary.id == 1
    assert summary.type == "Team planner view"
    assert summary.name == "Team Planner"
    assert summary.project_id == 6
    assert summary.project == "Demo Project"
    assert summary.query_id == 9
    assert summary.query == "My Query"
    assert summary.public is True
    assert summary.starred is False
    assert summary.url == f"{BASE_URL}/api/v3/views/1"
    assert records[0].project_link == {"href": "/api/v3/projects/6", "title": "Demo Project"}


@pytest.mark.asyncio
async def test_list_all_normalizes_a_view_without_a_project_link() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"_embedded": {"elements": [_view_payload(with_project=False)]}}, request=request
        )

    async with _client(handler) as http_client:
        api = HttpxViewApi(HttpxTransport(http_client), base_url=BASE_URL)
        records = await api.list_all(page_size=50)

    summary = records[0].summary
    assert summary.project_id is None
    assert summary.project is None
    assert records[0].project_link is None


@pytest.mark.asyncio
async def test_list_all_missing_embedded_elements_returns_empty_list() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={}, request=request)

    async with _client(handler) as http_client:
        api = HttpxViewApi(HttpxTransport(http_client), base_url=BASE_URL)
        records = await api.list_all(page_size=50)

    assert records == []


@pytest.mark.asyncio
async def test_get_requests_the_single_view_endpoint() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/views/1"
        assert request.method == "GET"
        return httpx.Response(200, json=_view_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxViewApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.get(1)

    assert record.summary.id == 1
    assert record.detail.id == 1


@pytest.mark.asyncio
async def test_detail_reuses_every_summary_field_and_adds_sorted_links() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_view_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxViewApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.get(1)

    detail = record.detail
    summary = record.summary
    assert detail.id == summary.id
    assert detail.type == summary.type
    assert detail.name == summary.name
    assert detail.project_id == summary.project_id
    assert detail.project == summary.project
    assert detail.query_id == summary.query_id
    assert detail.query == summary.query
    assert detail.public == summary.public
    assert detail.starred == summary.starred
    assert detail.url == summary.url
    assert detail.links == sorted(["query", "project"])
