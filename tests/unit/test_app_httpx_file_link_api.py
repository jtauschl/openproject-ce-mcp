from __future__ import annotations

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_file_link_api import HttpxFileLinkApi, normalize_file_link
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _file_link_payload(file_link_id: int = 5, *, container_href: str | None = "/api/v3/work_packages/9") -> dict:
    payload: dict = {
        "id": file_link_id,
        "title": "spec.pdf",
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-02T00:00:00Z",
        "_links": {
            "storage": {"href": "/api/v3/storages/3", "title": "Nextcloud"},
        },
    }
    if container_href is not None:
        payload["_links"]["container"] = {"href": container_href}
    return payload


@pytest.mark.asyncio
async def test_list_for_work_package_requests_sub_collection_and_builds_records() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/work_packages/9/file_links"
        return httpx.Response(200, json={"_embedded": {"elements": [_file_link_payload()]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxFileLinkApi(HttpxTransport(http_client), api_prefix="/api/v3/")
        records = await api.list_for_work_package(9)

    assert len(records) == 1
    summary = records[0].summary
    assert summary.id == 5
    assert summary.title == "spec.pdf"
    assert summary.storage_id == 3
    assert summary.storage_name == "Nextcloud"
    assert summary.url == "/api/v3/file_links/5"
    assert records[0].container_link == {"href": "/api/v3/work_packages/9"}


@pytest.mark.asyncio
async def test_list_for_work_package_missing_embedded_elements_returns_empty_list() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={}, request=request)

    async with _client(handler) as http_client:
        api = HttpxFileLinkApi(HttpxTransport(http_client), api_prefix="/api/v3/")
        records = await api.list_for_work_package(9)

    assert records == []


@pytest.mark.asyncio
async def test_get_requests_single_file_link() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/file_links/5"
        return httpx.Response(200, json=_file_link_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxFileLinkApi(HttpxTransport(http_client), api_prefix="/api/v3/")
        record = await api.get(5)

    assert record.summary.id == 5
    assert record.container_link == {"href": "/api/v3/work_packages/9"}


@pytest.mark.asyncio
async def test_get_handles_missing_container_link() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_file_link_payload(container_href=None), request=request)

    async with _client(handler) as http_client:
        api = HttpxFileLinkApi(HttpxTransport(http_client), api_prefix="/api/v3/")
        record = await api.get(5)

    assert record.container_link is None


@pytest.mark.asyncio
async def test_delete_sends_delete_request() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/file_links/5"
        assert request.method == "DELETE"
        return httpx.Response(204, request=request)

    async with _client(handler) as http_client:
        api = HttpxFileLinkApi(HttpxTransport(http_client), api_prefix="/api/v3/")
        await api.delete(5)


def test_normalize_file_link_falls_back_to_origin_data_name_when_title_missing() -> None:
    payload = _file_link_payload()
    del payload["title"]
    payload["originData"] = {"name": "fallback-name.pdf"}

    summary = normalize_file_link(payload, api_prefix="/api/v3/")

    assert summary.title == "fallback-name.pdf"


def test_normalize_file_link_falls_back_to_generated_title_when_nothing_present() -> None:
    payload = _file_link_payload()
    del payload["title"]

    summary = normalize_file_link(payload, api_prefix="/api/v3/")

    assert summary.title == "File link 5"


def test_normalize_file_link_trims_long_title() -> None:
    payload = _file_link_payload()
    payload["title"] = "x" * 300

    summary = normalize_file_link(payload, api_prefix="/api/v3/")

    assert len(summary.title) == 255
    assert summary.title.endswith("…")


def test_normalize_file_link_handles_missing_storage_link() -> None:
    payload = _file_link_payload()
    del payload["_links"]["storage"]

    summary = normalize_file_link(payload, api_prefix="/api/v3/")

    assert summary.storage_id is None
    assert summary.storage_name is None
