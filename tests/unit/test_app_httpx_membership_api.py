from __future__ import annotations

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_membership_api import HttpxMembershipApi
from openproject_ce_mcp.app.errors import OpenProjectServerError
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _membership_payload(membership_id: int = 1) -> dict:
    return {
        "id": membership_id,
        "_links": {
            "project": {"href": "/api/v3/projects/6", "title": "Demo Project"},
            "principal": {"href": "/api/v3/users/9", "title": "Ada Lovelace"},
            "roles": [{"href": "/api/v3/roles/1", "title": "Member"}],
            "update": {"href": f"/api/v3/memberships/{membership_id}"},
        },
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-02T00:00:00Z",
    }


@pytest.mark.asyncio
async def test_list_for_project_merges_offset_and_page_size_into_existing_filter_query() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/memberships"
        params = dict(request.url.params)
        # The pre-existing "filters" query param from the href must survive
        # the offset/pageSize merge, not be dropped or overwritten.
        assert params["filters"] == '[{"project":{"operator":"=","values":["6"]}}]'
        assert params["offset"] == "2"
        assert params["pageSize"] == "10"
        return httpx.Response(
            200, json={"total": 1, "_embedded": {"elements": [_membership_payload()]}}, request=request
        )

    href = '/api/v3/memberships?filters=[{"project":{"operator":"=","values":["6"]}}]'
    async with _client(handler) as http_client:
        api = HttpxMembershipApi(HttpxTransport(http_client), base_url=BASE_URL)
        page = await api.list_for_project(href, offset=2, page_size=10)

    assert page.server_total == 1
    assert page.records[0].summary.id == 1
    assert page.records[0].project_link == {"href": "/api/v3/projects/6", "title": "Demo Project"}


@pytest.mark.asyncio
async def test_list_for_project_accepts_relative_href() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/memberships"
        return httpx.Response(200, json={"total": 0, "_embedded": {"elements": []}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxMembershipApi(HttpxTransport(http_client), base_url=BASE_URL)
        page = await api.list_for_project("memberships", offset=1, page_size=10)

    assert page.records == []


@pytest.mark.asyncio
async def test_list_for_project_accepts_absolute_same_origin_href() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/memberships"
        return httpx.Response(200, json={"total": 0, "_embedded": {"elements": []}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxMembershipApi(HttpxTransport(http_client), base_url=BASE_URL)
        page = await api.list_for_project(f"{BASE_URL}/api/v3/memberships", offset=1, page_size=10)

    assert page.records == []


@pytest.mark.asyncio
async def test_list_for_project_rejects_foreign_origin_href_before_any_request() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"Unexpected request to foreign origin: {request.url}")

    async with _client(handler) as http_client:
        api = HttpxMembershipApi(HttpxTransport(http_client), base_url=BASE_URL)
        with pytest.raises(OpenProjectServerError, match="unexpected link host"):
            await api.list_for_project("https://evil.example.com/api/v3/memberships", offset=1, page_size=10)


@pytest.mark.asyncio
async def test_list_for_project_missing_embedded_elements_returns_empty_records() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"total": 0}, request=request)

    async with _client(handler) as http_client:
        api = HttpxMembershipApi(HttpxTransport(http_client), base_url=BASE_URL)
        page = await api.list_for_project("memberships", offset=1, page_size=10)

    assert page.records == []
    assert page.server_total == 0


@pytest.mark.asyncio
async def test_get_builds_record_with_raw_project_link() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/memberships/1"
        return httpx.Response(200, json=_membership_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxMembershipApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.get(1)

    assert record.summary.id == 1
    assert record.summary.principal_name == "Ada Lovelace"
    assert record.summary.role_names == ["Member"]
    assert record.project_link == {"href": "/api/v3/projects/6", "title": "Demo Project"}


@pytest.mark.asyncio
async def test_commit_create_returns_summary_without_project_link() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/memberships"
        assert request.method == "POST"
        return httpx.Response(201, json=_membership_payload(membership_id=42), request=request)

    async with _client(handler) as http_client:
        api = HttpxMembershipApi(HttpxTransport(http_client), base_url=BASE_URL)
        summary = await api.commit_create({"_links": {}})

    assert summary.id == 42
    assert not hasattr(summary, "project_link")


@pytest.mark.asyncio
async def test_commit_update_patches_and_returns_summary() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/memberships/1"
        assert request.method == "PATCH"
        return httpx.Response(200, json=_membership_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxMembershipApi(HttpxTransport(http_client), base_url=BASE_URL)
        summary = await api.commit_update(1, {"_links": {"roles": [{"href": "/api/v3/roles/1"}]}})

    assert summary.id == 1


@pytest.mark.asyncio
async def test_delete_sends_delete_request() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/memberships/1"
        assert request.method == "DELETE"
        return httpx.Response(204, request=request)

    async with _client(handler) as http_client:
        api = HttpxMembershipApi(HttpxTransport(http_client), base_url=BASE_URL)
        await api.delete(1)


@pytest.mark.asyncio
async def test_create_form_returns_payload_and_validation_errors() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/memberships/form"
        return httpx.Response(
            200,
            json={
                "_embedded": {
                    "payload": {"_links": {"roles": [{"href": "/api/v3/roles/1"}]}},
                    "validationErrors": {"roles": {"message": "is invalid"}},
                }
            },
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxMembershipApi(HttpxTransport(http_client), base_url=BASE_URL)
        result = await api.create_form({"_links": {}})

    assert result.validation_errors == {"roles": "is invalid"}
