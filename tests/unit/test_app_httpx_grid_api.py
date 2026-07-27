from __future__ import annotations

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_grid_api import HttpxGridApi
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _grid_payload(grid_id: int = 1, *, scope_href: str = "/projects/6") -> dict:
    return {
        "id": grid_id,
        "rowCount": 4,
        "columnCount": 6,
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-02T00:00:00Z",
        "_links": {
            "scope": {"href": scope_href},
        },
    }


@pytest.mark.asyncio
async def test_list_all_requests_grids_without_filter_by_default() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/grids"
        params = dict(request.url.params)
        assert "filters" not in params
        assert params["offset"] == "1"
        assert params["pageSize"] == "200"
        return httpx.Response(200, json={"_embedded": {"elements": [_grid_payload()]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxGridApi(HttpxTransport(http_client), api_prefix="/api/v3/")
        records = await api.list_all(scope_filter=None, page_size=200)

    assert len(records) == 1
    summary = records[0].summary
    assert summary.id == 1
    assert summary.row_count == 4
    assert summary.column_count == 6
    assert summary.scope == "/projects/6"
    assert summary.url == "/api/v3/grids/1"
    assert records[0].scope_link == {"href": "/projects/6"}


@pytest.mark.asyncio
async def test_list_all_sends_scope_filter_when_given() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        assert params["filters"] == '[{"scope":{"operator":"=","values":["/my/page"]}}]'
        return httpx.Response(200, json={"_embedded": {"elements": []}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxGridApi(HttpxTransport(http_client), api_prefix="/api/v3/")
        records = await api.list_all(scope_filter="/my/page", page_size=200)

    assert records == []


@pytest.mark.asyncio
async def test_list_all_missing_embedded_elements_returns_empty_list() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={}, request=request)

    async with _client(handler) as http_client:
        api = HttpxGridApi(HttpxTransport(http_client), api_prefix="/api/v3/")
        records = await api.list_all(scope_filter=None, page_size=200)

    assert records == []


@pytest.mark.asyncio
async def test_get_builds_record_with_raw_scope_link() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/grids/1"
        return httpx.Response(200, json=_grid_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxGridApi(HttpxTransport(http_client), api_prefix="/api/v3/")
        record = await api.get(1)

    assert record.summary.id == 1
    assert record.scope_link == {"href": "/projects/6"}


@pytest.mark.asyncio
async def test_create_form_returns_payload_and_validation_errors() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/grids/form"
        return httpx.Response(
            200,
            json={
                "_embedded": {
                    "payload": {"name": "My Grid", "_links": {"scope": {"href": "/my/page"}}},
                    "validationErrors": {"name": {"message": "is invalid"}},
                }
            },
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxGridApi(HttpxTransport(http_client), api_prefix="/api/v3/")
        result = await api.create_form({"name": "My Grid", "_links": {"scope": {"href": "/my/page"}}})

    assert result.validation_errors == {"name": "is invalid"}
    assert result.payload["name"] == "My Grid"


@pytest.mark.asyncio
async def test_update_form_posts_to_the_grid_scoped_form_endpoint() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/grids/1/form"
        return httpx.Response(
            200, json={"_embedded": {"payload": {"name": "Renamed"}, "validationErrors": {}}}, request=request
        )

    async with _client(handler) as http_client:
        api = HttpxGridApi(HttpxTransport(http_client), api_prefix="/api/v3/")
        result = await api.update_form(1, {"name": "Renamed"})

    assert result.validation_errors == {}
    assert result.payload["name"] == "Renamed"


@pytest.mark.asyncio
async def test_commit_create_posts_and_returns_summary() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/grids"
        assert request.method == "POST"
        return httpx.Response(201, json=_grid_payload(grid_id=42), request=request)

    async with _client(handler) as http_client:
        api = HttpxGridApi(HttpxTransport(http_client), api_prefix="/api/v3/")
        summary = await api.commit_create({"name": "My Grid", "_links": {"scope": {"href": "/projects/6"}}})

    assert summary.id == 42


@pytest.mark.asyncio
async def test_commit_update_patches_and_returns_summary() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/grids/1"
        assert request.method == "PATCH"
        return httpx.Response(200, json=_grid_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxGridApi(HttpxTransport(http_client), api_prefix="/api/v3/")
        summary = await api.commit_update(1, {"name": "Renamed"})

    assert summary.id == 1


@pytest.mark.asyncio
async def test_delete_sends_delete_request() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/grids/1"
        assert request.method == "DELETE"
        return httpx.Response(204, request=request)

    async with _client(handler) as http_client:
        api = HttpxGridApi(HttpxTransport(http_client), api_prefix="/api/v3/")
        await api.delete(1)


@pytest.mark.asyncio
async def test_get_handles_missing_scope_link() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = _grid_payload()
        payload["_links"] = {}
        return httpx.Response(200, json=payload, request=request)

    async with _client(handler) as http_client:
        api = HttpxGridApi(HttpxTransport(http_client), api_prefix="/api/v3/")
        record = await api.get(1)

    assert record.scope_link is None
    assert record.summary.scope is None
