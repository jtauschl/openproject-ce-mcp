from __future__ import annotations

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_role_api import HttpxRoleApi
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _role_payload(role_id: int = 8, name: str = "Project admin") -> dict:
    return {"id": role_id, "name": name}


@pytest.mark.asyncio
async def test_list_roles_requests_offset_and_page_size() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/roles"
        assert request.url.params.get("offset") == "1"
        assert request.url.params.get("pageSize") == "20"
        return httpx.Response(200, json={"total": 1, "_embedded": {"elements": [_role_payload()]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxRoleApi(HttpxTransport(http_client), base_url=BASE_URL)
        records, total = await api.list_roles(offset=1, page_size=20)

    assert total == 1
    assert len(records) == 1
    summary = records[0].summary
    assert summary.id == 8
    assert summary.name == "Project admin"
    assert summary.url == f"{BASE_URL}/roles/8"


@pytest.mark.asyncio
async def test_list_roles_missing_embedded_elements_returns_empty_list() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"total": 0}, request=request)

    async with _client(handler) as http_client:
        api = HttpxRoleApi(HttpxTransport(http_client), base_url=BASE_URL)
        records, total = await api.list_roles(offset=1, page_size=20)

    assert records == []
    assert total == 0


@pytest.mark.asyncio
async def test_list_roles_falls_back_to_a_placeholder_name_when_missing() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"total": 1, "_embedded": {"elements": [{"id": 3}]}},
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxRoleApi(HttpxTransport(http_client), base_url=BASE_URL)
        records, _total = await api.list_roles(offset=1, page_size=20)

    assert records[0].summary.name == "Role 3"


@pytest.mark.asyncio
async def test_list_roles_falls_back_to_record_count_when_total_missing() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"_embedded": {"elements": [_role_payload(), _role_payload(role_id=6, name="Member")]}},
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxRoleApi(HttpxTransport(http_client), base_url=BASE_URL)
        records, total = await api.list_roles(offset=1, page_size=20)

    assert total == 2
    assert len(records) == 2
