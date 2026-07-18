from __future__ import annotations

import json

import httpx
import pytest
from _client_test_helpers import _make_grid_payload, _make_grid_settings

from openproject_ce_mcp.client import (
    OpenProjectClient,
    PermissionDeniedError,
)
from openproject_ce_mcp.config import Settings


@pytest.mark.asyncio
async def test_list_boards_returns_empty_under_empty_read_projects() -> None:
    # Regression guard: use_client_side_filtering must not be gated on
    # `bool(allowed_projects)` — an empty (deny-all) scope must still filter,
    # not skip filtering and leak every board from every project unfiltered.
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/queries":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            {
                                "_type": "Query",
                                "id": 1,
                                "name": "Some Board",
                                "public": False,
                                "hidden": True,
                                "_links": {"project": {"href": "/api/v3/projects/6", "title": "Demo"}},
                            }
                        ]
                    }
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings(
        base_url="https://op.example.com",
        api_token="token",
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.list_boards()

    assert result.count == 0
    assert result.results == []

    await client.aclose()


@pytest.mark.asyncio
async def test_board_crud_uses_query_form_endpoints_and_project_filtering() -> None:
    def query_payload(
        *,
        query_id: int,
        name: str,
        project_title: str = "Demo",
        project_href: str = "/api/v3/projects/6",
        public: bool = False,
        hidden: bool = True,
        show_hierarchies: bool = True,
        timeline_visible: bool = False,
    ) -> dict[str, object]:
        return {
            "_type": "Query",
            "id": query_id,
            "name": name,
            "public": public,
            "hidden": hidden,
            "starred": False,
            "includeSubprojects": False,
            "showHierarchies": show_hierarchies,
            "timelineVisible": timeline_visible,
            "timelineZoomLevel": "auto",
            "highlightingMode": "inline",
            "timestamps": ["PT0S"],
            "createdAt": "2026-03-20T13:00:00Z",
            "updatedAt": "2026-03-20T13:00:00Z",
            "filters": [
                {
                    "_links": {
                        "filter": {"href": "/api/v3/queries/filters/status", "title": "Status"},
                        "operator": {"href": "/api/v3/queries/operators/o", "title": "open"},
                        "values": [],
                    }
                }
            ],
            "_links": {
                "self": {"href": f"/api/v3/queries/{query_id}", "title": name},
                "project": {"href": project_href, "title": project_title},
                "update": {"href": f"/api/v3/queries/{query_id}/form", "method": "post"},
                "updateImmediately": {"href": f"/api/v3/queries/{query_id}", "method": "patch"},
                "delete": {"href": f"/api/v3/queries/{query_id}", "method": "delete"},
                "groupBy": {"href": "/api/v3/queries/group_bys/status", "title": "Status"},
                "columns": [
                    {"href": "/api/v3/queries/columns/id", "title": "ID"},
                    {"href": "/api/v3/queries/columns/subject", "title": "Subject"},
                ],
                "sortBy": [
                    {"href": "/api/v3/queries/sort_bys/id-asc", "title": "ID (Ascending)"},
                ],
                "highlightedAttributes": [
                    {"href": "/api/v3/queries/columns/status", "title": "Status"},
                ],
            },
        }

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 6, "name": "Demo", "identifier": "demo"},
                request=request,
            )
        if request.url.path == "/api/v3/queries" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "total": 2,
                    "_embedded": {
                        "elements": [
                            query_payload(query_id=12, name="Sprint Board"),
                            query_payload(
                                query_id=13,
                                name="Other Board",
                                project_title="Other",
                                project_href="/api/v3/projects/9",
                            ),
                        ]
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/queries/12" and request.method == "GET":
            return httpx.Response(200, json=query_payload(query_id=12, name="Sprint Board"), request=request)
        if request.url.path == "/api/v3/queries/form":
            body = json.loads(request.content)
            assert body == {
                "name": "Sprint Board",
                "public": False,
                "timelineVisible": False,
                "showHierarchies": False,
                "_links": {
                    "project": {"href": "/api/v3/projects/6"},
                    "groupBy": {"href": "/api/v3/queries/group_bys/status"},
                    "columns": [
                        {"href": "/api/v3/queries/columns/id"},
                        {"href": "/api/v3/queries/columns/subject"},
                    ],
                    "sortBy": [{"href": "/api/v3/queries/sort_bys/id-asc"}],
                    "highlightedAttributes": [{"href": "/api/v3/queries/columns/status"}],
                },
            }
            return httpx.Response(
                200,
                json={"_embedded": {"payload": body, "validationErrors": {}}},
                request=request,
            )
        if request.url.path == "/api/v3/queries" and request.method == "POST":
            body = json.loads(request.content)
            assert body["name"] == "Sprint Board"
            return httpx.Response(201, json=query_payload(query_id=14, name="Sprint Board"), request=request)
        if request.url.path == "/api/v3/queries/12/form":
            body = json.loads(request.content)
            assert body == {"name": "Sprint Board Updated", "public": True}
            return httpx.Response(
                200,
                json={"_embedded": {"payload": body, "validationErrors": {}}},
                request=request,
            )
        if request.url.path == "/api/v3/queries/12" and request.method == "PATCH":
            body = json.loads(request.content)
            assert body == {"name": "Sprint Board Updated", "public": True}
            return httpx.Response(
                200,
                json=query_payload(query_id=12, name="Sprint Board Updated", public=True),
                request=request,
            )
        if request.url.path == "/api/v3/queries/12" and request.method == "DELETE":
            return httpx.Response(204, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings(
        base_url="https://op.example.com",
        api_token="token",
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
        read_projects=("demo",),
        write_projects=("demo",),
        enable_board_write=True,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    listed = await client.list_boards(project="demo")
    detail = await client.get_board(12)
    created = await client.create_board(
        name="Sprint Board",
        project="demo",
        public=False,
        timeline_visible=False,
        group_by="status",
        columns=["id", "subject"],
        sort_by=["id-asc"],
        highlighted_attributes=["status"],
        confirm=True,
    )
    updated = await client.update_board(board_id=12, name="Sprint Board Updated", public=True, confirm=True)
    deleted = await client.delete_board(board_id=12, confirm=True)

    assert listed.count == 1
    assert listed.results[0].name == "Sprint Board"
    assert detail.group_by == "Status"
    assert detail.columns == ["ID", "Subject"]
    assert detail.sort_by == ["ID (Ascending)"]
    assert created.board_id == 14
    assert created.result is not None
    assert created.result.project == "Demo"
    assert updated.result is not None
    assert updated.result.public is True
    assert deleted.board_id == 12

    await client.aclose()


@pytest.mark.asyncio
async def test_create_grid_uses_form_endpoint_and_project_scope() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 1, "name": "Demo", "identifier": "demo", "_links": {}},
                request=request,
            )
        if request.url.path == "/api/v3/grids/form":
            body = json.loads(request.content)
            assert body == {
                "name": "Demo Grid",
                "rowCount": 2,
                "columnCount": 3,
                "_links": {"scope": {"href": "/projects/demo"}},
            }
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "payload": {
                            "name": "Demo Grid",
                            "rowCount": 2,
                            "columnCount": 3,
                            "options": {},
                            "widgets": [],
                            "_links": {"scope": {"href": "/projects/demo"}},
                        },
                        "validationErrors": {},
                    }
                },
                request=request,
            )
        if request.url.path == "/api/v3/grids" and request.method == "POST":
            body = json.loads(request.content)
            assert body == {
                "name": "Demo Grid",
                "rowCount": 2,
                "columnCount": 3,
                "options": {},
                "widgets": [],
                "_links": {"scope": {"href": "/projects/demo"}},
            }
            return httpx.Response(
                200,
                json={
                    "_type": "Grid",
                    "id": 55,
                    "rowCount": 2,
                    "columnCount": 3,
                    "createdAt": "2026-03-23T12:00:00Z",
                    "updatedAt": "2026-03-23T12:00:00Z",
                    "_links": {
                        "scope": {"href": "/projects/demo"},
                        "self": {"href": "/api/v3/grids/55"},
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings(
        base_url="https://op.example.com",
        api_token="token",
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
        read_projects=("demo",),
        write_projects=("demo",),
        enable_project_write=True,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    created = await client.create_grid(
        name="Demo Grid",
        scope="/projects/demo",
        row_count=2,
        column_count=3,
        confirm=True,
    )

    assert created.grid_id == 55
    assert created.result is not None
    assert created.result.scope == "/projects/demo"

    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("read_projects", "project", "should_deny"),
    [
        ((), None, True),
        (("demo",), None, True),
        (("*",), None, False),
        (("demo",), "demo", False),
    ],
)
@pytest.mark.asyncio
async def test_create_board_global_requires_fully_open_scope(read_projects, project, should_deny) -> None:
    # An unscoped (global) board can only be verified when BOTH read
    # and write are fully open — write_projects=("*",) alone is not enough,
    # since write must still be a subset of read. A project-bound board is
    # unaffected by this stricter global-board rule.
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 1, "name": "Demo", "identifier": "demo", "_links": {}},
                request=request,
            )
        if request.url.path == "/api/v3/queries/form" and request.method == "POST":
            return httpx.Response(
                200,
                json={"_embedded": {"payload": {"name": "Board"}, "validationErrors": {}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings(
        base_url="https://op.example.com",
        api_token="token",
        enable_board_write=True,
        enable_project_write=True,
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
        read_projects=read_projects,
        write_projects=("*",),
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    if should_deny:
        with pytest.raises(PermissionDeniedError):
            await client.create_board(name="Board", project=project, confirm=False)
    else:
        result = await client.create_board(name="Board", project=project, confirm=False)
        assert result.ready is True

    await client.aclose()


@pytest.mark.asyncio
async def test_create_board_returns_preview_when_not_confirmed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/queries/form" and request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "payload": {"name": "My Board"},
                        "validationErrors": {},
                    }
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings(
        base_url="https://op.example.com",
        api_token="token",
        enable_board_write=True,
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
        read_projects=("*",),
        write_projects=("*",),
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.create_board(name="My Board", confirm=False)

    assert result.confirmed is False
    assert result.requires_confirmation is True
    assert result.ready is True
    assert result.validation_errors == {}

    await client.aclose()


@pytest.mark.asyncio
async def test_create_board_rejects_validation_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/queries/form" and request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "payload": {},
                        "validationErrors": {"name": {"message": "Name can't be blank."}},
                    }
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings(
        base_url="https://op.example.com",
        api_token="token",
        enable_board_write=True,
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
        read_projects=("*",),
        write_projects=("*",),
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.create_board(name="", confirm=True)

    assert result.ready is False
    assert result.confirmed is False
    assert "name" in result.validation_errors

    await client.aclose()


@pytest.mark.asyncio
async def test_list_grids_filters_disallowed_project_scope() -> None:
    # read_projects excludes "demo" — the project-scoped grid must be filtered out,
    # while a personal (/my/page) grid stays visible regardless of the allowlist.
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/grids" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            _make_grid_payload(grid_id=55),  # scope /projects/demo -> disallowed
                            {
                                "_type": "Grid",
                                "id": 56,
                                "rowCount": 1,
                                "columnCount": 1,
                                "_links": {"scope": {"href": "/my/page"}, "self": {"href": "/api/v3/grids/56"}},
                            },
                        ]
                    }
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _make_grid_settings({"read_projects": ("other",), "write_projects": ("other",)})
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))
    result = await client.list_grids()

    assert [g.id for g in result.results] == [56]
    assert result.count == 1

    await client.aclose()


@pytest.mark.asyncio
async def test_get_grid_returns_summary_for_allowed_project() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/grids/55" and request.method == "GET":
            return httpx.Response(200, json=_make_grid_payload(), request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_make_grid_settings(), transport=httpx.MockTransport(handler))
    result = await client.get_grid(55)

    assert result.id == 55

    await client.aclose()


@pytest.mark.asyncio
async def test_get_grid_denies_missing_or_malformed_scope_under_restrictive_allowlist() -> None:
    # Fail-closed: an unrecognized/missing scope must not default to "allowed"
    # under a restrictive (non-wildcard) allowlist.
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/grids/77" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "_type": "Grid",
                    "id": 77,
                    "rowCount": 1,
                    "columnCount": 1,
                    "_links": {"self": {"href": "/api/v3/grids/77"}},  # no "scope" link at all
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _make_grid_settings({"read_projects": ("demo",), "write_projects": ("demo",)})
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await client.get_grid(77)

    await client.aclose()


@pytest.mark.asyncio
async def test_update_grid_preview_mode() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/grids/55" and request.method == "GET":
            return httpx.Response(200, json=_make_grid_payload(), request=request)
        if request.url.path == "/api/v3/projects/demo":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 1, "name": "Demo", "identifier": "demo", "_links": {}},
                request=request,
            )
        if request.url.path == "/api/v3/grids/55/form":
            body = json.loads(request.content)
            return httpx.Response(200, json={"_embedded": {"payload": body, "validationErrors": {}}}, request=request)
        raise AssertionError(f"Unexpected: {request.method} {request.url}")

    client = OpenProjectClient(_make_grid_settings(), transport=httpx.MockTransport(handler))
    result = await client.update_grid(grid_id=55, name="Renamed Grid", confirm=False)

    assert result.action == "update"
    assert result.confirmed is False
    assert result.requires_confirmation is True
    assert result.grid_id == 55
    await client.aclose()


@pytest.mark.asyncio
async def test_update_grid_executes_with_confirm() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/grids/55" and request.method == "GET":
            return httpx.Response(200, json=_make_grid_payload(), request=request)
        if request.url.path == "/api/v3/projects/demo":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 1, "name": "Demo", "identifier": "demo", "_links": {}},
                request=request,
            )
        if request.url.path == "/api/v3/grids/55/form":
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "payload": {**body, "_links": {"scope": {"href": "/projects/demo"}}},
                        "validationErrors": {},
                    }
                },
                request=request,
            )
        if request.url.path == "/api/v3/grids/55" and request.method == "PATCH":
            return httpx.Response(200, json={**_make_grid_payload(), "name": "Renamed Grid"}, request=request)
        raise AssertionError(f"Unexpected: {request.method} {request.url}")

    client = OpenProjectClient(_make_grid_settings(), transport=httpx.MockTransport(handler))
    result = await client.update_grid(grid_id=55, name="Renamed Grid", confirm=True)

    assert result.confirmed is True
    assert result.grid_id == 55
    assert result.result is not None
    await client.aclose()


@pytest.mark.asyncio
async def test_delete_grid_preview_mode() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/grids/55" and request.method == "GET":
            return httpx.Response(200, json=_make_grid_payload(), request=request)
        if request.url.path == "/api/v3/projects/demo":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 1, "name": "Demo", "identifier": "demo", "_links": {}},
                request=request,
            )
        raise AssertionError(f"Unexpected: {request.method} {request.url}")

    client = OpenProjectClient(_make_grid_settings(), transport=httpx.MockTransport(handler))
    result = await client.delete_grid(grid_id=55, confirm=False)

    assert result.action == "delete"
    assert result.confirmed is False
    assert result.requires_confirmation is True
    assert result.grid_id == 55
    await client.aclose()


@pytest.mark.asyncio
async def test_delete_grid_executes_with_confirm() -> None:
    deleted = {"called": False}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/grids/55" and request.method == "GET":
            return httpx.Response(200, json=_make_grid_payload(), request=request)
        if request.url.path == "/api/v3/projects/demo":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 1, "name": "Demo", "identifier": "demo", "_links": {}},
                request=request,
            )
        if request.url.path == "/api/v3/grids/55" and request.method == "DELETE":
            deleted["called"] = True
            return httpx.Response(204, request=request)
        raise AssertionError(f"Unexpected: {request.method} {request.url}")

    client = OpenProjectClient(_make_grid_settings(), transport=httpx.MockTransport(handler))
    result = await client.delete_grid(grid_id=55, confirm=True)

    assert result.confirmed is True
    assert result.grid_id == 55
    assert deleted["called"] is True
    await client.aclose()
