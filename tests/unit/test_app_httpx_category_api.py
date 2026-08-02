from __future__ import annotations

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_category_api import HttpxCategoryApi
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _category_payload(category_id: int = 1) -> dict:
    return {
        "id": category_id,
        "name": "Bugs",
        "isDefault": True,
        "_links": {
            "defaultAssignee": {"href": "/api/v3/users/9", "title": "Ada Lovelace"},
        },
    }


@pytest.mark.asyncio
async def test_list_for_project_requests_the_project_scoped_endpoint() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/projects/6/categories"
        assert request.method == "GET"
        return httpx.Response(200, json={"_embedded": {"elements": [_category_payload()]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxCategoryApi(HttpxTransport(http_client), base_url=BASE_URL)
        records = await api.list_for_project(6, project_name="Demo Project")

    assert len(records) == 1
    summary = records[0].summary
    assert summary.id == 1
    assert summary.name == "Bugs"
    assert summary.project_id == 6
    assert summary.project == "Demo Project"
    assert summary.is_default is True
    assert summary.default_assignee_id == 9
    assert summary.default_assignee == "Ada Lovelace"
    assert summary.url == f"{BASE_URL}/api/v3/categories/1"


@pytest.mark.asyncio
async def test_list_for_project_trims_a_too_long_project_name() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"_embedded": {"elements": [_category_payload()]}}, request=request)

    long_name = "x" * 300
    async with _client(handler) as http_client:
        api = HttpxCategoryApi(HttpxTransport(http_client), base_url=BASE_URL)
        records = await api.list_for_project(6, project_name=long_name)

    assert records[0].summary.project is not None
    assert len(records[0].summary.project) <= 255
    assert records[0].summary.project.endswith("…")


@pytest.mark.asyncio
async def test_list_for_project_missing_embedded_elements_returns_empty_list() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={}, request=request)

    async with _client(handler) as http_client:
        api = HttpxCategoryApi(HttpxTransport(http_client), base_url=BASE_URL)
        records = await api.list_for_project(6, project_name="Demo Project")

    assert records == []


@pytest.mark.asyncio
async def test_list_for_project_falls_back_to_placeholder_name_when_missing() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = _category_payload()
        del payload["name"]
        return httpx.Response(200, json={"_embedded": {"elements": [payload]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxCategoryApi(HttpxTransport(http_client), base_url=BASE_URL)
        records = await api.list_for_project(6, project_name=None)

    assert records[0].summary.name == "Category 1"
    assert records[0].summary.project is None


@pytest.mark.asyncio
async def test_list_for_project_handles_missing_default_assignee() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = _category_payload()
        payload["_links"] = {}
        return httpx.Response(200, json={"_embedded": {"elements": [payload]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxCategoryApi(HttpxTransport(http_client), base_url=BASE_URL)
        records = await api.list_for_project(6, project_name="Demo Project")

    assert records[0].summary.default_assignee_id is None
    assert records[0].summary.default_assignee is None


@pytest.mark.asyncio
async def test_get_requests_the_real_single_category_endpoint() -> None:
    """Regression: OpenProject's v3 API DOES have GET /api/v3/categories/{id}
    (verified against OpenProject's own API implementation), and its
    CategoryRepresenter DOES embed _links.project -- an earlier version of
    this adapter/port incorrectly claimed neither existed."""

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/categories/1"
        assert request.method == "GET"
        payload = _category_payload()
        payload["_links"]["project"] = {"href": "/api/v3/projects/6", "title": "Demo Project"}
        return httpx.Response(200, json=payload, request=request)

    async with _client(handler) as http_client:
        api = HttpxCategoryApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.get(1)

    assert record.summary.id == 1
    assert record.summary.project_id == 6
    assert record.summary.project == "Demo Project"
    assert record.project_link == {"href": "/api/v3/projects/6", "title": "Demo Project"}


@pytest.mark.asyncio
async def test_get_handles_missing_project_link() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_category_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxCategoryApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.get(1)

    assert record.summary.project_id is None
    assert record.summary.project is None
    assert record.project_link is None
