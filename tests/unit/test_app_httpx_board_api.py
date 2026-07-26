from __future__ import annotations

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_board_api import HttpxBoardApi
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _board_payload(board_id: int = 1, *, long_name: bool = False) -> dict:
    return {
        "id": board_id,
        "name": "x" * 400 if long_name else "Sprint Board",
        "_links": {
            "project": {"href": "/api/v3/projects/6", "title": "Demo"},
            "update": {"href": f"/api/v3/queries/{board_id}/form"},
            "delete": {"href": f"/api/v3/queries/{board_id}"},
            "groupBy": {"href": "/api/v3/queries/group_bys/status", "title": "Status"},
            "columns": [
                {"href": "/api/v3/queries/columns/id", "title": "ID"},
                {"href": "/api/v3/queries/columns/subject", "title": "Subject"},
            ],
        },
        "public": True,
        "hidden": False,
        "starred": False,
        "includeSubprojects": False,
        "showHierarchies": False,
        "timelineVisible": False,
        "timelineZoomLevel": "days",
        "highlightingMode": "none",
        "timestamps": ["oneDayAgo"],
        "filters": [],
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-02T00:00:00Z",
    }


@pytest.mark.asyncio
async def test_list_all_requests_a_bounded_page_and_builds_records() -> None:
    # Regression: the original client.py's _fetch_bounded_and_paginate always
    # sent offset=1&pageSize=settings.max_results for its bounded fetch --
    # an earlier version of this adapter omitted both params entirely,
    # silently falling back to the server's (much smaller) default page
    # size and truncating client-side-filtered results, exactly the
    # "pageSize-omission bug" client.py's own docstring warns about.
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/queries"
        assert dict(request.url.params) == {"offset": "1", "pageSize": "100"}
        return httpx.Response(200, json={"_embedded": {"elements": [_board_payload()]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxBoardApi(HttpxTransport(http_client), base_url=BASE_URL)
        records = await api.list_all(page_size=100)

    assert len(records) == 1
    summary = records[0].summary
    assert summary.id == 1
    assert summary.name == "Sprint Board"
    assert summary.project == "Demo"
    assert summary.project_id == 6
    assert summary.url == f"{BASE_URL}/work_packages?query_id=1"
    assert records[0].project_link == {"href": "/api/v3/projects/6", "title": "Demo"}


@pytest.mark.asyncio
async def test_list_page_sends_offset_and_page_size_and_reports_total() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/queries"
        assert dict(request.url.params) == {"offset": "2", "pageSize": "10"}
        return httpx.Response(200, json={"_embedded": {"elements": [_board_payload()]}, "total": 42}, request=request)

    async with _client(handler) as http_client:
        api = HttpxBoardApi(HttpxTransport(http_client), base_url=BASE_URL)
        records, total = await api.list_page(offset=2, limit=10)

    assert len(records) == 1
    assert total == 42


@pytest.mark.asyncio
async def test_get_builds_record_with_eager_detail_from_summary() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/queries/1"
        return httpx.Response(200, json=_board_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxBoardApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.get(1)

    assert record.summary.id == 1
    assert record.detail.id == record.summary.id
    assert record.detail.name == record.summary.name
    assert record.detail.group_by == "Status"
    assert record.detail.columns == ["ID", "Subject"]
    assert record.detail.can_update is True
    assert record.detail.can_delete is True


@pytest.mark.asyncio
async def test_summary_and_detail_diverge_only_by_detail_only_fields_not_double_normalization() -> None:
    # Regression: an eager `detail` built by re-running normalize_board on the raw
    # payload a second time would still produce the same values here (both read the
    # same raw payload) -- this test alone can't distinguish double-normalization
    # from field-copy, but it does pin that summary/detail agree on every shared
    # field, which a broken field-copy (wrong source field) would violate.
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_board_payload(long_name=True), request=request)

    async with _client(handler) as http_client:
        api = HttpxBoardApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.get(1)

    assert record.summary.name == record.detail.name
    assert record.summary.project == record.detail.project
    assert record.summary.url == record.detail.url


@pytest.mark.asyncio
async def test_create_form_returns_payload_and_validation_errors() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/queries/form"
        return httpx.Response(
            200,
            json={
                "_embedded": {
                    "payload": {"name": "My Board", "_links": {"project": {"href": "/api/v3/projects/6"}}},
                    "validationErrors": {"name": {"message": "is invalid"}},
                }
            },
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxBoardApi(HttpxTransport(http_client), base_url=BASE_URL)
        result = await api.create_form({"name": "My Board"})

    assert result.validation_errors == {"name": "is invalid"}
    assert result.payload["name"] == "My Board"


@pytest.mark.asyncio
async def test_update_form_posts_to_the_board_scoped_form_endpoint() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/queries/1/form"
        return httpx.Response(
            200, json={"_embedded": {"payload": {"name": "Renamed"}, "validationErrors": {}}}, request=request
        )

    async with _client(handler) as http_client:
        api = HttpxBoardApi(HttpxTransport(http_client), base_url=BASE_URL)
        result = await api.update_form(1, {"name": "Renamed"})

    assert result.validation_errors == {}
    assert result.payload["name"] == "Renamed"


@pytest.mark.asyncio
async def test_commit_create_posts_and_returns_detail() -> None:
    # Regression: BoardApi.commit_create must return a BoardDetail (matching
    # BoardWriteResult.result's declared type in models.py), not a bare
    # BoardSummary -- a BoardSummary is missing every detail-only field
    # (group_by/columns/sort_by/highlighted_attributes/filters/timestamps/
    # timeline_zoom_level/highlighting_mode), which would fail to serialize
    # against the BoardDetail schema on the MCP structured-output path.
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/queries"
        assert request.method == "POST"
        return httpx.Response(201, json=_board_payload(board_id=42), request=request)

    async with _client(handler) as http_client:
        api = HttpxBoardApi(HttpxTransport(http_client), base_url=BASE_URL)
        detail = await api.commit_create({"name": "My Board"})

    assert detail.id == 42
    assert detail.group_by == "Status"
    assert detail.columns == ["ID", "Subject"]


@pytest.mark.asyncio
async def test_commit_update_patches_and_returns_detail() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/queries/1"
        assert request.method == "PATCH"
        return httpx.Response(200, json=_board_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxBoardApi(HttpxTransport(http_client), base_url=BASE_URL)
        detail = await api.commit_update(1, {"name": "Renamed"})

    assert detail.id == 1
    assert detail.group_by == "Status"
    assert detail.columns == ["ID", "Subject"]


@pytest.mark.asyncio
async def test_delete_sends_delete_request() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/queries/1"
        assert request.method == "DELETE"
        return httpx.Response(204, request=request)

    async with _client(handler) as http_client:
        api = HttpxBoardApi(HttpxTransport(http_client), base_url=BASE_URL)
        await api.delete(1)


@pytest.mark.asyncio
async def test_get_handles_missing_project_link() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = _board_payload()
        payload["_links"] = {}
        return httpx.Response(200, json=payload, request=request)

    async with _client(handler) as http_client:
        api = HttpxBoardApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.get(1)

    assert record.project_link is None
    assert record.summary.project is None
    assert record.summary.project_id is None
