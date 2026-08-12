from __future__ import annotations

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_cost_api import (
    HttpxCostApi,
    normalize_cost_entry_raw,
    normalize_cost_type_raw,
    normalize_costs_by_type_raw,
)
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _cost_entry_payload(cost_entry_id: int = 9) -> dict:
    return {
        "id": cost_entry_id,
        "spentUnits": "3.5",
        "spentOn": "2026-03-20",
        "createdAt": "2026-03-20T10:00:00Z",
        "updatedAt": "2026-03-20T10:00:00Z",
        "_links": {
            "project": {"href": "/api/v3/projects/1", "title": "Demo"},
            "user": {"href": "/api/v3/users/1", "title": "Admin"},
            "costType": {"href": "/api/v3/cost_types/2", "title": "Labor costs"},
            "entity": {"href": "/api/v3/work_packages/42", "title": "Do the thing"},
        },
    }


@pytest.mark.asyncio
async def test_get_cost_entry_raw_requests_single_cost_entry() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/cost_entries/9"
        assert request.method == "GET"
        return httpx.Response(200, json=_cost_entry_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxCostApi(HttpxTransport(http_client))
        raw = await api.get_cost_entry_raw(9)

    assert raw["id"] == 9


@pytest.mark.asyncio
async def test_fetch_cost_entries_for_work_package_requests_the_sub_resource_and_extracts_elements() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/work_packages/42/cost_entries"
        assert request.method == "GET"
        assert not request.url.params
        return httpx.Response(
            200,
            json={"total": 1, "count": 1, "_embedded": {"elements": [_cost_entry_payload()]}},
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxCostApi(HttpxTransport(http_client))
        elements = await api.fetch_cost_entries_for_work_package(42)

    assert len(elements) == 1
    assert elements[0]["id"] == 9


@pytest.mark.asyncio
async def test_fetch_costs_by_type_requests_the_summarized_sub_resource() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/work_packages/42/summarized_costs_by_type"
        assert request.method == "GET"
        return httpx.Response(200, json={"total": 1, "count": 1, "_embedded": {"elements": []}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxCostApi(HttpxTransport(http_client))
        payload = await api.fetch_costs_by_type(42)

    assert payload["count"] == 1


@pytest.mark.asyncio
async def test_get_cost_type_raw_requests_single_cost_type() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/cost_types/2"
        assert request.method == "GET"
        return httpx.Response(
            200,
            json={"id": 2, "name": "Labor costs", "unit": "hour", "unitPlural": "hours", "isDefault": True},
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxCostApi(HttpxTransport(http_client))
        raw = await api.get_cost_type_raw(2)

    assert raw["id"] == 2


def test_normalize_cost_entry_raw_extracts_all_fields() -> None:
    entry = normalize_cost_entry_raw(_cost_entry_payload())

    assert entry.id == 9
    assert entry.project == "Demo"
    assert entry.user == "Admin"
    assert entry.cost_type == "Labor costs"
    assert entry.entity_id == 42
    assert entry.entity_name == "Do the thing"
    assert entry.spent_units == "3.5"
    assert entry.spent_on == "2026-03-20"
    assert entry.created_at == "2026-03-20T10:00:00Z"
    assert entry.updated_at == "2026-03-20T10:00:00Z"


def test_normalize_cost_entry_raw_handles_missing_entity_link() -> None:
    entry = normalize_cost_entry_raw({"id": 1, "_links": {}})

    assert entry.entity_id is None
    assert entry.entity_name is None


def test_normalize_cost_type_raw_extracts_fields_including_is_default_true() -> None:
    cost_type = normalize_cost_type_raw(
        {"id": 2, "name": "Labor costs", "unit": "hour", "unitPlural": "hours", "isDefault": True}
    )

    assert cost_type.id == 2
    assert cost_type.name == "Labor costs"
    assert cost_type.unit == "hour"
    assert cost_type.unit_plural == "hours"
    assert cost_type.is_default is True


def test_normalize_cost_type_raw_is_default_false_when_absent() -> None:
    cost_type = normalize_cost_type_raw({"id": 3, "name": "Material costs", "unit": "piece", "unitPlural": "pieces"})

    assert cost_type.is_default is False


def test_normalize_costs_by_type_raw_extracts_elements_and_trusts_raw_count() -> None:
    payload = {
        "total": 2,
        "count": 2,
        "_embedded": {
            "elements": [
                {
                    "spentUnits": "1.5",
                    "_links": {"costType": {"href": "/api/v3/cost_types/2", "title": "Labor costs"}},
                },
                {
                    "spentUnits": "4.0",
                    "_links": {"costType": {"href": "/api/v3/cost_types/3", "title": "Material costs"}},
                },
            ]
        },
    }

    result = normalize_costs_by_type_raw(payload, work_package_id=42)

    assert result.work_package_id == 42
    assert result.count == 2
    assert len(result.results) == 2
    assert result.results[0].cost_type == "Labor costs"
    assert result.results[0].cost_type_id == 2
    assert result.results[0].spent_units == "1.5"
    assert result.results[1].cost_type == "Material costs"
    assert result.results[1].cost_type_id == 3


def test_normalize_costs_by_type_raw_uses_raw_count_not_recomputed_length() -> None:
    """`count` on the raw payload is `cost_helper.summarized_cost_entries.size`
    (the number of distinct cost-type groups upstream) -- this must be trusted
    as-is, not recomputed from len(elements), even though in practice they
    always match for a well-formed payload."""
    payload = {"count": 5, "_embedded": {"elements": []}}

    result = normalize_costs_by_type_raw(payload, work_package_id=42)

    assert result.count == 5
    assert result.results == []
