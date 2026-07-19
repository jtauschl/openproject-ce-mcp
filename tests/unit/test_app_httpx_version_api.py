from __future__ import annotations

import json

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_version_api import HttpxVersionApi
from openproject_ce_mcp.app.errors import (
    AuthenticationError,
    InvalidInputError,
    NotFoundError,
    OpenProjectServerError,
    PermissionDeniedError,
)
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler))


def _version_payload(version_id: int = 8, name: str = "Release 1") -> dict:
    return {
        "id": version_id,
        "name": name,
        "status": "open",
        "sharing": "none",
        "startDate": "2026-04-01",
        "endDate": "2026-04-30",
        "description": {"raw": "Initial rollout"},
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-02T00:00:00Z",
        "_links": {"definingProject": {"href": "/api/v3/projects/6", "title": "Demo"}},
    }


@pytest.mark.asyncio
async def test_list_for_project_hits_project_scoped_endpoint_with_offset_and_page_size() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/projects/6/versions"
        assert dict(request.url.params) == {"offset": "2", "pageSize": "10"}
        return httpx.Response(200, json={"total": 25, "_embedded": {"elements": [_version_payload()]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxVersionApi(HttpxTransport(http_client), base_url=BASE_URL)
        page = await api.list_for_project(6, offset=2, page_size=10)

    assert page.server_total == 25
    assert len(page.records) == 1
    record = page.records[0]
    assert record.summary.id == 8
    assert record.summary.name == "Release 1"
    assert record.defining_project_link == {"href": "/api/v3/projects/6", "title": "Demo"}


@pytest.mark.asyncio
async def test_list_global_hits_unscoped_endpoint_and_has_no_server_total() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/versions"
        assert dict(request.url.params) == {"offset": "1", "pageSize": "100"}
        return httpx.Response(200, json={"_embedded": {"elements": [_version_payload(version_id=2)]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxVersionApi(HttpxTransport(http_client), base_url=BASE_URL)
        page = await api.list_global(offset=1, page_size=100)

    assert page.server_total is None
    assert page.records[0].summary.id == 2


@pytest.mark.asyncio
async def test_get_fetches_by_id() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/versions/8"
        return httpx.Response(200, json=_version_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxVersionApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.get(8)

    assert record.summary.id == 8
    assert record.summary.defining_project == "Demo"


@pytest.mark.asyncio
async def test_create_form_posts_to_form_endpoint_and_reports_validation_errors() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/versions/form"
        assert request.method == "POST"
        body = json.loads(request.content)
        assert body == {"name": "Release 1"}
        return httpx.Response(
            200,
            json={"_embedded": {"payload": body, "validationErrors": {"name": {"message": "too short"}}}},
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxVersionApi(HttpxTransport(http_client), base_url=BASE_URL)
        form = await api.create_form({"name": "Release 1"})

    assert form.payload == {"name": "Release 1"}
    assert form.validation_errors == {"name": "too short"}


@pytest.mark.asyncio
async def test_update_form_uses_post_not_patch() -> None:
    # The /form endpoint is always POST even for updates -- must not regress to PATCH.
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/versions/8/form"
        assert request.method == "POST"
        body = json.loads(request.content)
        return httpx.Response(200, json={"_embedded": {"payload": body, "validationErrors": {}}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxVersionApi(HttpxTransport(http_client), base_url=BASE_URL)
        form = await api.update_form(8, {"name": "Release 1.1"})

    assert form.validation_errors == {}


@pytest.mark.asyncio
async def test_commit_create_posts_and_returns_normalized_detail() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/versions"
        assert request.method == "POST"
        return httpx.Response(201, json=_version_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxVersionApi(HttpxTransport(http_client), base_url=BASE_URL)
        detail = await api.commit_create({"name": "Release 1"})

    assert detail.id == 8
    assert detail.name == "Release 1"


@pytest.mark.asyncio
async def test_commit_update_patches_and_returns_normalized_detail() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/versions/8"
        assert request.method == "PATCH"
        return httpx.Response(200, json=_version_payload(name="Release 1.1"), request=request)

    async with _client(handler) as http_client:
        api = HttpxVersionApi(HttpxTransport(http_client), base_url=BASE_URL)
        detail = await api.commit_update(8, {"name": "Release 1.1"})

    assert detail.name == "Release 1.1"


@pytest.mark.asyncio
async def test_delete_issues_delete_request() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/versions/8"
        assert request.method == "DELETE"
        return httpx.Response(204, request=request)

    async with _client(handler) as http_client:
        api = HttpxVersionApi(HttpxTransport(http_client), base_url=BASE_URL)
        await api.delete(8)  # must not raise


@pytest.mark.asyncio
async def test_get_survives_explicit_null_links_at_top_level() -> None:
    """OPM-190: HttpxTransport._request_json normalizes an explicit
    `"_links": null` to `{}` before any adapter code sees it -- without that,
    `_record`'s `payload.get("_links", {}).get("definingProject")` would
    raise AttributeError on the `.get("definingProject")` call.
    """
    payload = _version_payload()
    payload["_links"] = None

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/versions/8"
        return httpx.Response(200, json=payload, request=request)

    async with _client(handler) as http_client:
        api = HttpxVersionApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.get(8)

    assert record.summary.id == 8
    assert record.summary.defining_project is None
    assert record.defining_project_link is None


@pytest.mark.asyncio
async def test_list_global_survives_explicit_null_links_nested_in_a_collection_element() -> None:
    """Proves HttpxTransport actually exercises hal.normalize_links'
    recursion through this layer, not just its top level -- `list_global`'s
    elements live under `_embedded.elements[i]`, not at the response's own
    top level.
    """
    element = _version_payload(version_id=3)
    element["_links"] = None

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/versions"
        return httpx.Response(200, json={"_embedded": {"elements": [element]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxVersionApi(HttpxTransport(http_client), base_url=BASE_URL)
        page = await api.list_global(offset=1, page_size=100)

    assert len(page.records) == 1
    record = page.records[0]
    assert record.summary.id == 3
    assert record.summary.defining_project is None
    assert record.defining_project_link is None


@pytest.mark.parametrize(
    ("status_code", "body", "expected_exception"),
    [
        (401, {}, AuthenticationError),
        (403, {"message": "invalid token"}, AuthenticationError),
        (403, {"message": "not allowed"}, PermissionDeniedError),
        (404, {}, NotFoundError),
        (422, {"message": "bad input"}, InvalidInputError),
        (500, {}, OpenProjectServerError),
    ],
)
@pytest.mark.asyncio
async def test_status_mapping_table(status_code, body, expected_exception) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=body, request=request)

    async with _client(handler) as http_client:
        api = HttpxVersionApi(HttpxTransport(http_client), base_url=BASE_URL)
        with pytest.raises(expected_exception):
            await api.get(8)
