from __future__ import annotations

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_project_storage_api import (
    HttpxProjectStorageApi,
    normalize_project_storage,
    normalize_project_storage_detail,
)
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"

# Live-captured GET /api/v3/project_storages payload element from the
# Nextcloud Docker fixture (feature/nextcloud-docker-storage-fixture), pasted
# verbatim.
LIVE_PROJECT_STORAGE_PAYLOAD: dict = {
    "_type": "ProjectStorage",
    "id": 1,
    "projectFolderMode": "inactive",
    "createdAt": "2026-08-13T10:00:00Z",
    "updatedAt": "2026-08-13T10:00:00Z",
    "_links": {
        "self": {"href": "/api/v3/project_storages/1"},
        "open": {"href": "/api/v3/project_storages/1/open"},
        "openWithConnectionEnsured": {"href": "/api/v3/project_storages/1/open?confirmConnection=true"},
        "storage": {"href": "/api/v3/storages/1", "title": "Seed Nextcloud Storage"},
        "project": {"href": "/api/v3/projects/3", "title": "TST Test"},
        "creator": {"href": "/api/v3/users/4", "title": "OpenProject Admin"},
    },
}


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def test_normalize_project_storage_on_live_captured_payload() -> None:
    summary = normalize_project_storage(LIVE_PROJECT_STORAGE_PAYLOAD)

    assert summary.id == 1
    assert summary.project_id == 3
    assert summary.project == "TST Test"
    assert summary.storage_id == 1
    assert summary.storage_name == "Seed Nextcloud Storage"
    assert summary.project_folder_mode == "inactive"


def test_normalize_project_storage_detail_creator_extraction() -> None:
    detail = normalize_project_storage_detail(LIVE_PROJECT_STORAGE_PAYLOAD)

    assert detail.creator_id == 4
    assert detail.creator == "OpenProject Admin"


@pytest.mark.asyncio
async def test_list_all_requests_offset_and_page_size_but_server_ignores_them() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/project_storages"
        assert request.url.params.get("offset") == "1"
        assert request.url.params.get("pageSize") == "100"
        return httpx.Response(
            200, json={"total": 1, "_embedded": {"elements": [LIVE_PROJECT_STORAGE_PAYLOAD]}}, request=request
        )

    async with _client(handler) as http_client:
        api = HttpxProjectStorageApi(HttpxTransport(http_client))
        records, total = await api.list_all(offset=1, page_size=100)

    assert total == 1
    assert records[0].summary.id == 1
    assert records[0].project_link == {"href": "/api/v3/projects/3", "title": "TST Test"}


@pytest.mark.asyncio
async def test_get_requests_single_project_storage_path() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/project_storages/1"
        assert request.method == "GET"
        return httpx.Response(200, json=LIVE_PROJECT_STORAGE_PAYLOAD, request=request)

    async with _client(handler) as http_client:
        api = HttpxProjectStorageApi(HttpxTransport(http_client))
        record = await api.get(1)

    assert record.summary.project == "TST Test"
