from __future__ import annotations

import json

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_action_capability_api import HttpxActionCapabilityApi
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _action_payload() -> dict:
    return {
        "name": "update",
        "description": "Update resource",
        "_links": {"self": {"href": "/api/v3/actions/update"}},
    }


def _capability_payload() -> dict:
    return {
        "name": "canUpdate",
        "_links": {
            "self": {"href": "/api/v3/capabilities/update-project"},
            "action": {"href": "/api/v3/actions/update", "title": "update"},
            "principal": {"href": "/api/v3/users/5", "title": "Alice"},
            "context": {"href": "/api/v3/projects/1", "title": "Demo"},
        },
    }


@pytest.mark.asyncio
async def test_list_actions_requests_offset_and_page_size() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/actions"
        assert request.url.params.get("offset") == "1"
        assert request.url.params.get("pageSize") == "20"
        return httpx.Response(200, json={"total": 1, "_embedded": {"elements": [_action_payload()]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxActionCapabilityApi(HttpxTransport(http_client), base_url=BASE_URL)
        records, total = await api.list_actions(offset=1, page_size=20)

    assert total == 1
    assert len(records) == 1
    summary = records[0].summary
    assert summary.id == "update"
    assert summary.url == f"{BASE_URL}/api/v3/actions/update"


@pytest.mark.asyncio
async def test_list_actions_missing_embedded_elements_returns_empty_list() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"total": 0}, request=request)

    async with _client(handler) as http_client:
        api = HttpxActionCapabilityApi(HttpxTransport(http_client), base_url=BASE_URL)
        records, total = await api.list_actions(offset=1, page_size=20)

    assert records == []
    assert total == 0


@pytest.mark.asyncio
async def test_list_capabilities_sends_filters_as_json() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/capabilities"
        assert request.url.params.get("filters") == '[{"context":{"operator":"=","values":["w1"]}}]'
        return httpx.Response(
            200, json={"total": 1, "_embedded": {"elements": [_capability_payload()]}}, request=request
        )

    filters = [{"context": {"operator": "=", "values": ["w1"]}}]
    async with _client(handler) as http_client:
        api = HttpxActionCapabilityApi(HttpxTransport(http_client), base_url=BASE_URL)
        records, total = await api.list_capabilities(filters=filters, offset=1, page_size=20)

    assert total == 1
    assert len(records) == 1
    summary = records[0].summary
    assert summary.id == "update-project"
    assert summary.action_id == "update"
    assert summary.principal_id == 5
    assert summary.principal_name == "Alice"
    assert summary.context == "Demo"
    assert summary.url == f"{BASE_URL}/api/v3/capabilities/update-project"
    assert records[0].context_link == {"href": "/api/v3/projects/1", "title": "Demo"}


@pytest.mark.asyncio
async def test_get_capability_requests_single_item_endpoint() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/capabilities/update-project"
        return httpx.Response(200, json=_capability_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxActionCapabilityApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.get_capability("update-project")

    assert record.summary.id == "update-project"
    assert record.context_link == {"href": "/api/v3/projects/1", "title": "Demo"}


@pytest.mark.asyncio
async def test_list_capabilities_missing_embedded_elements_returns_empty_list() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"total": 0}, request=request)

    async with _client(handler) as http_client:
        api = HttpxActionCapabilityApi(HttpxTransport(http_client), base_url=BASE_URL)
        records, total = await api.list_capabilities(filters=[], offset=1, page_size=20)

    assert records == []
    assert total == 0


@pytest.mark.asyncio
async def test_list_capabilities_handles_missing_action_and_principal_links() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = _capability_payload()
        payload["_links"] = {"self": {"href": "/api/v3/capabilities/update-project"}}
        return httpx.Response(200, json={"total": 1, "_embedded": {"elements": [payload]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxActionCapabilityApi(HttpxTransport(http_client), base_url=BASE_URL)
        records, _total = await api.list_capabilities(filters=[], offset=1, page_size=20)

    summary = records[0].summary
    assert summary.action_id is None
    assert summary.principal_id is None
    assert summary.principal_name is None
    assert summary.context is None


def test_json_dumps_matches_expected_separator_style() -> None:
    # Guards the compact-JSON encoding (no spaces) the mock handler assertions above rely on.
    filters = [{"id": {"operator": "=", "values": ["update-project"]}}]
    assert json.dumps(filters, separators=(",", ":")) == '[{"id":{"operator":"=","values":["update-project"]}}]'
