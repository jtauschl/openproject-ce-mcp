from __future__ import annotations

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_sprint_api import HttpxSprintApi
from openproject_ce_mcp.app.errors import NotFoundError
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _sprint_payload(sprint_id: int = 1, *, with_link: bool = True, with_embedded: bool = False) -> dict:
    links: dict = {
        "status": {"href": "urn:openproject-org:api:v3:sprints:status:in_planning", "title": "In Planning"},
    }
    embedded: dict = {}
    if with_link:
        links["definingWorkspace"] = {"href": "/api/v3/projects/7", "title": "Demo"}
    if with_embedded:
        embedded["definingWorkspace"] = {
            "_type": "Project",
            "id": 7,
            "identifier": "demo",
            "name": "Demo",
            "_links": {"self": {"href": "/api/v3/projects/7", "title": "Demo"}},
        }
    payload = {
        "id": sprint_id,
        "_type": "Sprint",
        "name": "Sprint 1",
        "startDate": "2026-07-09",
        "finishDate": "2026-07-10",
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-02T00:00:00Z",
        "_links": links,
    }
    if embedded:
        payload["_embedded"] = embedded
    return payload


@pytest.mark.asyncio
async def test_list_all_requests_the_sprints_endpoint() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/sprints"
        assert dict(request.url.params) == {"offset": "1", "pageSize": "50"}
        return httpx.Response(200, json={"_embedded": {"elements": [_sprint_payload()]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxSprintApi(HttpxTransport(http_client), base_url=BASE_URL)
        records = await api.list_all(page_size=50)

    assert len(records) == 1
    summary = records[0].summary
    assert summary.id == 1
    assert summary.name == "Sprint 1"
    assert summary.status == "In Planning"
    assert summary.start_date == "2026-07-09"
    assert summary.finish_date == "2026-07-10"
    assert summary.defining_workspace_id == 7
    assert summary.defining_workspace == "Demo"
    assert summary.url == f"{BASE_URL}/sprints/1"
    assert records[0].defining_workspace_link == {"href": "/api/v3/projects/7", "title": "Demo"}
    assert records[0].defining_workspace_payload is None


@pytest.mark.asyncio
async def test_url_is_a_web_ui_url_not_an_api_path() -> None:
    """Sprints' url field is built like client.py's `_web_url` (base_url +
    relative path, no `api/v3` prefix) -- unlike Views' adapter, which builds
    an API path. This is the one field where copying Views' pattern verbatim
    would be wrong.
    """

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_sprint_payload(sprint_id=42), request=request)

    async with _client(handler) as http_client:
        api = HttpxSprintApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.get(42)

    assert record.summary.url == f"{BASE_URL}/sprints/42"


@pytest.mark.asyncio
async def test_list_all_missing_embedded_elements_returns_empty_list() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={}, request=request)

    async with _client(handler) as http_client:
        api = HttpxSprintApi(HttpxTransport(http_client), base_url=BASE_URL)
        records = await api.list_all(page_size=50)

    assert records == []


@pytest.mark.asyncio
async def test_list_for_project_requests_the_project_scoped_endpoint() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/projects/7/sprints"
        assert dict(request.url.params) == {"offset": "1", "pageSize": "50"}
        return httpx.Response(200, json={"_embedded": {"elements": [_sprint_payload()]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxSprintApi(HttpxTransport(http_client), base_url=BASE_URL)
        records = await api.list_for_project(7, page_size=50)

    assert len(records) == 1
    assert records[0].summary.id == 1


@pytest.mark.asyncio
async def test_list_for_project_page_returns_records_and_total() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/projects/7/sprints"
        assert dict(request.url.params) == {"offset": "2", "pageSize": "20"}
        return httpx.Response(
            200,
            json={"total": 5, "_embedded": {"elements": [_sprint_payload(1), _sprint_payload(2)]}},
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxSprintApi(HttpxTransport(http_client), base_url=BASE_URL)
        records, total = await api.list_for_project_page(7, offset=2, page_size=20)

    assert [r.summary.id for r in records] == [1, 2]
    assert total == 5


@pytest.mark.asyncio
async def test_get_requests_the_single_sprint_endpoint() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/sprints/1"
        assert request.method == "GET"
        return httpx.Response(200, json=_sprint_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxSprintApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.get(1)

    assert record.summary.id == 1
    assert record.detail.id == 1


@pytest.mark.asyncio
async def test_detail_reuses_every_summary_field_verbatim() -> None:
    """SprintDetail is a bare subclass of SprintSummary with zero added
    fields -- unlike Views' detail, which adds `links`."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_sprint_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxSprintApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.get(1)

    detail = record.detail
    summary = record.summary
    assert detail.id == summary.id
    assert detail.name == summary.name
    assert detail.status == summary.status
    assert detail.start_date == summary.start_date
    assert detail.finish_date == summary.finish_date
    assert detail.defining_workspace_id == summary.defining_workspace_id
    assert detail.defining_workspace == summary.defining_workspace
    assert detail.created_at == summary.created_at
    assert detail.updated_at == summary.updated_at
    assert detail.url == summary.url


@pytest.mark.asyncio
async def test_defining_workspace_link_falls_back_to_embedded_self_link() -> None:
    """Verbatim port of client.py's `_sprint_workspace_link` fallback: when
    only `_embedded.definingWorkspace` is present (no top-level
    `_links.definingWorkspace`), synthesize a link from the embedded
    object's own `_links.self` (+ name as a title fallback).
    """

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_sprint_payload(with_link=False, with_embedded=True), request=request)

    async with _client(handler) as http_client:
        api = HttpxSprintApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.get(1)

    assert record.defining_workspace_link == {"href": "/api/v3/projects/7", "title": "Demo"}
    assert record.defining_workspace_payload == {
        "_type": "Project",
        "id": 7,
        "identifier": "demo",
        "name": "Demo",
        "_links": {"self": {"href": "/api/v3/projects/7", "title": "Demo"}},
    }
    assert record.summary.defining_workspace_id == 7
    assert record.summary.defining_workspace == "Demo"


@pytest.mark.asyncio
async def test_no_defining_workspace_at_all_yields_none_link_and_payload() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_sprint_payload(with_link=False, with_embedded=False), request=request)

    async with _client(handler) as http_client:
        api = HttpxSprintApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.get(1)

    assert record.defining_workspace_link is None
    assert record.defining_workspace_payload is None
    assert record.summary.defining_workspace_id is None
    assert record.summary.defining_workspace is None


@pytest.mark.asyncio
async def test_not_found_propagates_unwrapped_from_the_adapter() -> None:
    """NotFoundError propagates as the generic transport error here -- the
    three distinct "Backlogs module" messages are a Service-layer concern
    (see test_app_sprint_service.py), not the adapter's.
    """

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not found"}, request=request)

    async with _client(handler) as http_client:
        api = HttpxSprintApi(HttpxTransport(http_client), base_url=BASE_URL)
        with pytest.raises(NotFoundError, match="OpenProject resource not found."):
            await api.list_all(page_size=50)
