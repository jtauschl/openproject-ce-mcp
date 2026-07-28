from __future__ import annotations

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_work_package_lookup_api import HttpxWorkPackageLookupApi
from openproject_ce_mcp.app.errors import OpenProjectServerError
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _wp_payload(wp_id: int = 42) -> dict:
    return {
        "id": wp_id,
        "_type": "WorkPackage",
        "subject": "Demo work package",
        "_links": {"project": {"href": "/api/v3/projects/6", "title": "Demo"}},
    }


@pytest.mark.asyncio
async def test_get_fetches_by_numeric_ref() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/work_packages/42"
        return httpx.Response(200, json=_wp_payload(42), request=request)

    async with _client(handler) as http_client:
        api = HttpxWorkPackageLookupApi(HttpxTransport(http_client), base_url=BASE_URL)
        payload = await api.get("42")

    assert payload["id"] == 42


@pytest.mark.asyncio
async def test_get_url_encodes_a_semantic_reference() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/work_packages/PROJ-123"
        return httpx.Response(200, json=_wp_payload(7), request=request)

    async with _client(handler) as http_client:
        api = HttpxWorkPackageLookupApi(HttpxTransport(http_client), base_url=BASE_URL)
        payload = await api.get("PROJ-123")

    assert payload["id"] == 7


@pytest.mark.asyncio
async def test_get_url_encodes_special_characters_in_the_ref() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert b"/api/v3/work_packages/a%2Fb" in bytes(request.url.raw_path)
        return httpx.Response(200, json=_wp_payload(1), request=request)

    async with _client(handler) as http_client:
        api = HttpxWorkPackageLookupApi(HttpxTransport(http_client), base_url=BASE_URL)
        await api.get("a/b")


@pytest.mark.asyncio
async def test_get_by_href_translates_relative_href_to_api_path() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/work_packages/42"
        return httpx.Response(200, json=_wp_payload(42), request=request)

    async with _client(handler) as http_client:
        api = HttpxWorkPackageLookupApi(HttpxTransport(http_client), base_url=BASE_URL)
        payload = await api.get_by_href("/api/v3/work_packages/42")

    assert payload["id"] == 42


@pytest.mark.asyncio
async def test_get_by_href_translates_absolute_same_origin_href() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/work_packages/42"
        return httpx.Response(200, json=_wp_payload(42), request=request)

    async with _client(handler) as http_client:
        api = HttpxWorkPackageLookupApi(HttpxTransport(http_client), base_url=BASE_URL)
        payload = await api.get_by_href(f"{BASE_URL}/api/v3/work_packages/42")

    assert payload["id"] == 42


@pytest.mark.asyncio
async def test_get_by_href_rejects_foreign_origin_link_before_any_request() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"Unexpected request to foreign origin: {request.url}")

    async with _client(handler) as http_client:
        api = HttpxWorkPackageLookupApi(HttpxTransport(http_client), base_url=BASE_URL)
        with pytest.raises(OpenProjectServerError, match="unexpected link host"):
            await api.get_by_href("https://evil.example.com/api/v3/work_packages/42")
