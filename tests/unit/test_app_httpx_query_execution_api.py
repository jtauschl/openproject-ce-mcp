from __future__ import annotations

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_query_execution_api import HttpxQueryExecutionApi
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _query_response(elements: list[dict], *, raw_total: int | None = None) -> dict:
    results: dict = {"_embedded": {"elements": elements}}
    if raw_total is not None:
        results["total"] = raw_total
    return {
        "_type": "Query",
        "id": 7,
        "_embedded": {"results": results},
    }


@pytest.mark.asyncio
async def test_execute_requests_offset_and_page_size() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/queries/7"
        assert request.url.params["offset"] == "2"
        assert request.url.params["pageSize"] == "10"
        return httpx.Response(200, json=_query_response([{"id": 5}]), request=request)

    async with _client(handler) as http_client:
        api = HttpxQueryExecutionApi(HttpxTransport(http_client))
        page = await api.execute(7, offset=2, page_size=10)

    assert page.raw_elements == [{"id": 5}]


@pytest.mark.asyncio
async def test_execute_returns_empty_list_when_no_results_embedded() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"_type": "Query", "id": 7}, request=request)

    async with _client(handler) as http_client:
        api = HttpxQueryExecutionApi(HttpxTransport(http_client))
        page = await api.execute(7, offset=1, page_size=10)

    assert page.raw_elements == []


@pytest.mark.asyncio
async def test_execute_ignores_non_dict_elements() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_query_response([{"id": 1}, "not-a-dict", None]), request=request)

    async with _client(handler) as http_client:
        api = HttpxQueryExecutionApi(HttpxTransport(http_client))
        page = await api.execute(7, offset=1, page_size=10)

    assert page.raw_elements == [{"id": 1}]
