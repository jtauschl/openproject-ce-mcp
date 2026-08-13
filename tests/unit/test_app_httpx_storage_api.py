from __future__ import annotations

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_storage_api import (
    HttpxStorageApi,
    normalize_storage,
    normalize_storage_detail,
)
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"

# Live-captured GET /api/v3/storages/1 payload from the Nextcloud Docker
# fixture (feature/nextcloud-docker-storage-fixture), pasted verbatim.
LIVE_NEXTCLOUD_PAYLOAD: dict = {
    "_type": "Storage",
    "id": 1,
    "name": "Seed Nextcloud Storage",
    "configured": False,
    "hasApplicationPassword": False,
    "forbiddenFileNameCharacters": '<>:"\\/|?*',
    "createdAt": "2026-08-13T10:00:00Z",
    "updatedAt": "2026-08-13T10:00:00Z",
    "_links": {
        "self": {"href": "/api/v3/storages/1"},
        "type": {"href": "urn:openproject-org:api:v3:storages:Nextcloud", "title": "Nextcloud"},
        "origin": {"href": "http://nextcloud/"},
        "authenticationMethod": {"href": "urn:openproject-org:api:v3:storages:authenticationMethod:TwoWayOAuth2"},
        "prepareUpload": [],
        "open": {"href": "/api/v3/storages/1/open"},
    },
}


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _one_drive_payload(storage_id: int = 2) -> dict:
    return {
        "id": storage_id,
        "name": "OneDrive Storage",
        "configured": True,
        "tenant_id": "11111111-1111-1111-1111-111111111111",
        "drive_id": "b!driveid1234567890",
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-06-01T00:00:00Z",
        "_links": {
            "self": {"href": f"/api/v3/storages/{storage_id}"},
            "type": {"href": "urn:openproject-org:api:v3:storages:OneDrive", "title": "OneDrive"},
            "authorizationState": {
                "href": "urn:openproject-org:api:v3:storages:authorization:FailedAuthorization",
                "title": "Authorization failed",
            },
        },
    }


def _sharepoint_payload(storage_id: int = 3) -> dict:
    return {
        "id": storage_id,
        "name": "Sharepoint Storage",
        "configured": True,
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-06-01T00:00:00Z",
        "_links": {
            "self": {"href": f"/api/v3/storages/{storage_id}"},
            "type": {"href": "urn:openproject-org:api:v3:storages:Sharepoint", "title": "Sharepoint"},
            "authorizationState": {
                "href": "urn:openproject-org:api:v3:storages:authorization:Connected",
                "title": "Connected",
            },
        },
    }


# --- normalize_storage: live-captured Nextcloud payload ----------------------


def test_normalize_storage_on_live_captured_nextcloud_payload() -> None:
    summary = normalize_storage(LIVE_NEXTCLOUD_PAYLOAD)

    assert summary.id == 1
    assert summary.name == "Seed Nextcloud Storage"
    assert summary.provider_type == "Nextcloud"
    assert summary.host == "http://nextcloud/"
    assert summary.configured is False
    assert summary.has_application_password is False
    assert summary.forbidden_file_name_characters == '<>:"\\/|?*'
    assert summary.tenant_id is None
    assert summary.drive_id is None


def test_normalize_storage_detail_on_live_captured_nextcloud_payload() -> None:
    detail = normalize_storage_detail(LIVE_NEXTCLOUD_PAYLOAD)

    assert detail.authentication_method == "two_way_oauth2"
    # authorizationState link is not present in this live capture at all
    # (only present once a real OAuth handshake has been attempted) -- must
    # normalize to None, not raise.
    assert detail.authorization_state is None


# --- normalize_storage: synthetic OneDrive / Sharepoint payloads -------------


def test_normalize_storage_one_drive_discriminator_routing() -> None:
    summary = normalize_storage(_one_drive_payload())

    assert summary.provider_type == "OneDrive"
    assert summary.tenant_id == "11111111-1111-1111-1111-111111111111"
    assert summary.drive_id == "b!driveid1234567890"
    # Nextcloud-only fields must be None for a non-Nextcloud provider.
    assert summary.has_application_password is None
    assert summary.forbidden_file_name_characters is None


def test_normalize_storage_detail_one_drive_authorization_state_and_no_auth_method() -> None:
    detail = normalize_storage_detail(_one_drive_payload())

    # authenticationMethod link is only rendered for Nextcloud.
    assert detail.authentication_method is None
    # PascalCase URN suffix "FailedAuthorization" -> snake_case.
    assert detail.authorization_state == "failed_authorization"


def test_normalize_storage_sharepoint_discriminator_routing() -> None:
    summary = normalize_storage(_sharepoint_payload())

    assert summary.provider_type == "Sharepoint"
    assert summary.tenant_id is None  # OneDrive-only field group
    assert summary.drive_id is None


def test_normalize_storage_detail_sharepoint_authorization_state_connected() -> None:
    detail = normalize_storage_detail(_sharepoint_payload())

    assert detail.authorization_state == "connected"


# --- HttpxStorageApi: HTTP verb/path wiring -----------------------------------


@pytest.mark.asyncio
async def test_list_all_requests_offset_and_page_size_but_server_ignores_them() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/storages"
        assert request.url.params.get("offset") == "1"
        assert request.url.params.get("pageSize") == "100"
        return httpx.Response(
            200, json={"total": 1, "_embedded": {"elements": [LIVE_NEXTCLOUD_PAYLOAD]}}, request=request
        )

    async with _client(handler) as http_client:
        api = HttpxStorageApi(HttpxTransport(http_client))
        records, total = await api.list_all(offset=1, page_size=100)

    assert total == 1
    assert records[0].summary.id == 1


@pytest.mark.asyncio
async def test_get_requests_single_storage_path() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/storages/1"
        assert request.method == "GET"
        return httpx.Response(200, json=LIVE_NEXTCLOUD_PAYLOAD, request=request)

    async with _client(handler) as http_client:
        api = HttpxStorageApi(HttpxTransport(http_client))
        record = await api.get(1)

    assert record.summary.provider_type == "Nextcloud"


@pytest.mark.asyncio
async def test_commit_create_posts_to_storages() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/storages"
        assert request.method == "POST"
        return httpx.Response(201, json=LIVE_NEXTCLOUD_PAYLOAD, request=request)

    async with _client(handler) as http_client:
        api = HttpxStorageApi(HttpxTransport(http_client))
        detail = await api.commit_create({"name": "New"})

    assert detail.id == 1


@pytest.mark.asyncio
async def test_commit_update_patches_single_storage_path() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/storages/1"
        assert request.method == "PATCH"
        return httpx.Response(200, json=LIVE_NEXTCLOUD_PAYLOAD, request=request)

    async with _client(handler) as http_client:
        api = HttpxStorageApi(HttpxTransport(http_client))
        detail = await api.commit_update(1, {"name": "Renamed"})

    assert detail.id == 1


@pytest.mark.asyncio
async def test_commit_delete_deletes_single_storage_path() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/storages/1"
        assert request.method == "DELETE"
        return httpx.Response(204, request=request)

    async with _client(handler) as http_client:
        api = HttpxStorageApi(HttpxTransport(http_client))
        await api.commit_delete(1)
