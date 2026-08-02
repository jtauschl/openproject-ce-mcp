from __future__ import annotations

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_status_priority_type_api import (
    HttpxStatusPriorityTypeApi,
    normalize_priority,
    normalize_status,
    normalize_type,
)
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _status_payload(status_id: int = 1) -> dict:
    return {
        "id": status_id,
        "name": "In progress",
        "isDefault": False,
        "isClosed": False,
        "color": "#1A67A3",
        "position": 2,
        "isReadonly": False,
        "defaultDoneRatio": 30,
        "excludedFromTotals": False,
    }


def _priority_payload(priority_id: int = 1) -> dict:
    return {
        "id": priority_id,
        "name": "High",
        "isDefault": False,
        "isActive": True,
        "color": "#FF0000",
        "position": 3,
    }


def _type_payload(type_id: int = 1) -> dict:
    return {
        "id": type_id,
        "name": "Task",
        "color": "#1A67A3",
        "position": 1,
        "isDefault": True,
        "isMilestone": False,
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-06-01T00:00:00Z",
    }


def test_normalize_status_builds_relative_api_href() -> None:
    status = normalize_status(_status_payload(), api_prefix="/api/v3/")
    assert status.url == "/api/v3/statuses/1"
    assert status.is_closed is False
    assert status.default_done_ratio == 30


def test_normalize_priority_has_no_url_field() -> None:
    priority = normalize_priority(_priority_payload())
    assert priority.name == "High"
    assert priority.is_active is True
    assert not hasattr(priority, "url")


def test_normalize_type_builds_absolute_web_url() -> None:
    work_package_type = normalize_type(_type_payload(), base_url=BASE_URL)
    assert work_package_type.url == f"{BASE_URL}/types/1"
    assert work_package_type.is_milestone is False


@pytest.mark.asyncio
async def test_list_statuses_requests_statuses_collection() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/statuses"
        return httpx.Response(200, json={"_embedded": {"elements": [_status_payload()]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxStatusPriorityTypeApi(HttpxTransport(http_client), base_url=BASE_URL, api_prefix="/api/v3/")
        records = await api.list_statuses()

    assert len(records) == 1
    assert records[0].summary.id == 1


@pytest.mark.asyncio
async def test_list_statuses_missing_embedded_elements_returns_empty_list() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={}, request=request)

    async with _client(handler) as http_client:
        api = HttpxStatusPriorityTypeApi(HttpxTransport(http_client), base_url=BASE_URL, api_prefix="/api/v3/")
        records = await api.list_statuses()

    assert records == []


@pytest.mark.asyncio
async def test_get_status_requests_single_item_endpoint() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/statuses/7"
        return httpx.Response(200, json=_status_payload(7), request=request)

    async with _client(handler) as http_client:
        api = HttpxStatusPriorityTypeApi(HttpxTransport(http_client), base_url=BASE_URL, api_prefix="/api/v3/")
        record = await api.get_status(7)

    assert record.summary.id == 7


@pytest.mark.asyncio
async def test_list_priorities_requests_priorities_collection() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/priorities"
        return httpx.Response(200, json={"_embedded": {"elements": [_priority_payload()]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxStatusPriorityTypeApi(HttpxTransport(http_client), base_url=BASE_URL, api_prefix="/api/v3/")
        records = await api.list_priorities()

    assert len(records) == 1
    assert records[0].summary.name == "High"


@pytest.mark.asyncio
async def test_get_priority_requests_single_item_endpoint() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/priorities/3"
        return httpx.Response(200, json=_priority_payload(3), request=request)

    async with _client(handler) as http_client:
        api = HttpxStatusPriorityTypeApi(HttpxTransport(http_client), base_url=BASE_URL, api_prefix="/api/v3/")
        record = await api.get_priority(3)

    assert record.summary.id == 3


@pytest.mark.asyncio
async def test_list_types_without_project_id_requests_global_endpoint() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/types"
        return httpx.Response(200, json={"_embedded": {"elements": [_type_payload()]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxStatusPriorityTypeApi(HttpxTransport(http_client), base_url=BASE_URL, api_prefix="/api/v3/")
        records = await api.list_types(project_id=None)

    assert len(records) == 1


@pytest.mark.asyncio
async def test_list_types_with_project_id_requests_project_scoped_endpoint() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/projects/9/types"
        return httpx.Response(200, json={"_embedded": {"elements": [_type_payload()]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxStatusPriorityTypeApi(HttpxTransport(http_client), base_url=BASE_URL, api_prefix="/api/v3/")
        records = await api.list_types(project_id=9)

    assert len(records) == 1


@pytest.mark.asyncio
async def test_get_type_requests_single_item_endpoint() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/types/4"
        return httpx.Response(200, json=_type_payload(4), request=request)

    async with _client(handler) as http_client:
        api = HttpxStatusPriorityTypeApi(HttpxTransport(http_client), base_url=BASE_URL, api_prefix="/api/v3/")
        record = await api.get_type(4)

    assert record.summary.id == 4


@pytest.mark.asyncio
async def test_list_statuses_lookup_name_is_the_raw_name_not_the_display_fallback() -> None:
    """Codex-review regression test: lookup_name must be the raw payload
    name, never the synthetic display fallback normalize_status uses for
    summary.name -- see the port module's docstring for why the two must
    differ."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"_embedded": {"elements": [{"id": 7, "name": ""}]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxStatusPriorityTypeApi(HttpxTransport(http_client), base_url=BASE_URL, api_prefix="/api/v3/")
        records = await api.list_statuses()

    assert len(records) == 1
    assert records[0].summary.name == "Status 7"
    assert records[0].lookup_name == ""


@pytest.mark.asyncio
async def test_list_statuses_skips_an_element_with_a_missing_id() -> None:
    """Regression test: list_* must not raise on one malformed element among
    otherwise well-formed ones -- skip it, don't fail every other status."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"_embedded": {"elements": [{"name": "No id here"}, _status_payload(2)]}},
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxStatusPriorityTypeApi(HttpxTransport(http_client), base_url=BASE_URL, api_prefix="/api/v3/")
        records = await api.list_statuses()

    assert [record.summary.id for record in records] == [2]


@pytest.mark.asyncio
async def test_list_priorities_skips_an_element_with_a_non_numeric_id() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"_embedded": {"elements": [{"id": "not-a-number", "name": "Bad"}, _priority_payload(2)]}},
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxStatusPriorityTypeApi(HttpxTransport(http_client), base_url=BASE_URL, api_prefix="/api/v3/")
        records = await api.list_priorities()

    assert [record.summary.id for record in records] == [2]


@pytest.mark.asyncio
async def test_list_types_skips_a_non_dict_element() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"_embedded": {"elements": ["not-a-dict", _type_payload(2)]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxStatusPriorityTypeApi(HttpxTransport(http_client), base_url=BASE_URL, api_prefix="/api/v3/")
        records = await api.list_types(project_id=None)

    assert [record.summary.id for record in records] == [2]
