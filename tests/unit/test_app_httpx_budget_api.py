from __future__ import annotations

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_budget_api import HttpxBudgetApi
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _collection(*elements: dict) -> dict:
    return {"_type": "Collection", "total": len(elements), "count": len(elements), "_embedded": {"elements": elements}}


@pytest.mark.asyncio
async def test_list_for_project_requests_the_project_scoped_endpoint() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/v3/projects/6/budgets"
        return httpx.Response(200, json=_collection({"id": 3, "subject": "Q4 hardware"}), request=request)

    async with _client(handler) as http_client:
        budgets = await HttpxBudgetApi(HttpxTransport(http_client, redact_server_text=False)).list_for_project(
            6, project_name="Demo Project"
        )

    assert [(b.id, b.subject, b.project_id, b.project) for b in budgets] == [(3, "Q4 hardware", 6, "Demo Project")]


@pytest.mark.asyncio
async def test_list_for_project_trims_long_text_and_falls_back_to_a_placeholder_subject() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_collection({"id": 3, "subject": "s" * 400}, {"id": 4}), request=request)

    async with _client(handler) as http_client:
        budgets = await HttpxBudgetApi(HttpxTransport(http_client, redact_server_text=False)).list_for_project(
            6, project_name="n" * 400
        )

    assert len(budgets[0].subject) <= 255
    assert budgets[0].subject.endswith("…")
    assert budgets[0].project is not None and len(budgets[0].project) <= 255
    assert budgets[1].subject == "Unnamed budget"


@pytest.mark.asyncio
async def test_list_for_project_without_embedded_elements_is_empty() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={}, request=request)

    async with _client(handler) as http_client:
        budgets = await HttpxBudgetApi(HttpxTransport(http_client, redact_server_text=False)).list_for_project(
            6, project_name=None
        )

    assert budgets == []
