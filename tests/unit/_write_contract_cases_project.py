"""Write/delete-tool behavioral-contract cases for the "project"-scope tools
(OPM-209 / Phase D). See `_write_contract_cases_types.py` for the shared
`WriteToolCase` shape and `_write_contract_cases.py` for how this module's
output is merged with the other scopes.

Covers: create_project, update_project, delete_project, copy_project,
add_project_favorite, remove_project_favorite, create_news, update_news,
delete_news, update_document, create_grid, update_grid, delete_grid.
"""

from __future__ import annotations

import httpx
from _write_contract_cases_types import WriteToolCase

from openproject_ce_mcp.config import Settings


def _settings() -> Settings:
    return Settings(
        base_url="https://op.example.com",
        api_token="token",
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
        read_projects=("*",),
        write_projects=("*",),
    )


def _project_payload(project_id: int = 1, name: str = "Demo", identifier: str = "demo") -> dict:
    return {
        "_type": "Project",
        "id": project_id,
        "name": name,
        "identifier": identifier,
        "_links": {},
    }


def _unexpected(request: httpx.Request) -> None:
    raise AssertionError(f"Unexpected request: {request.method} {request.url}")


# --------------------------------------------------------------------------
# create_project: POST /api/v3/projects/form (preview) -> POST /api/v3/projects (write)
# --------------------------------------------------------------------------
def _create_project_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/projects/form" and request.method == "POST":
        return httpx.Response(
            200,
            json={
                "_embedded": {
                    "schema": {},
                    "payload": {"name": "Demo Project", "identifier": "demo-project"},
                    "validationErrors": {},
                }
            },
            request=request,
        )
    if request.url.path == "/api/v3/projects" and request.method == "POST":
        return httpx.Response(
            201, json=_project_payload(project_id=2, name="Demo Project", identifier="demo-project"), request=request
        )
    _unexpected(request)
    raise AssertionError  # pragma: no cover - _unexpected always raises


# --------------------------------------------------------------------------
# update_project: GET /api/v3/projects/{ref} (resolve) -> POST /api/v3/projects/{id}/form
# (preview) -> PATCH /api/v3/projects/{id} (write)
# --------------------------------------------------------------------------
def _update_project_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/projects/demo" and request.method == "GET":
        return httpx.Response(200, json=_project_payload(), request=request)
    if request.url.path == "/api/v3/projects/1/form" and request.method == "POST":
        return httpx.Response(
            200,
            json={"_embedded": {"payload": {"name": "Updated Demo"}, "validationErrors": {}}},
            request=request,
        )
    if request.url.path == "/api/v3/projects/1" and request.method == "PATCH":
        return httpx.Response(200, json=_project_payload(name="Updated Demo"), request=request)
    _unexpected(request)
    raise AssertionError  # pragma: no cover


# --------------------------------------------------------------------------
# delete_project: GET /api/v3/projects/{ref} (resolve, preview) -> DELETE /api/v3/projects/{id} (write)
# --------------------------------------------------------------------------
def _delete_project_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/projects/demo" and request.method == "GET":
        return httpx.Response(200, json=_project_payload(), request=request)
    if request.url.path == "/api/v3/projects/1" and request.method == "DELETE":
        return httpx.Response(204, request=request)
    _unexpected(request)
    raise AssertionError  # pragma: no cover


# --------------------------------------------------------------------------
# copy_project: GET /api/v3/projects/{source} (resolve) -> POST /api/v3/projects/form
# (internal schema fetch inside _build_project_write_payload, since project_id=None for a
# copy's destination) -> POST /api/v3/projects/{id}/copy/form (preview) ->
# POST /api/v3/projects/{id}/copy (write, 302 -> auto-followed GET job_statuses/{id} since
# the client is built with follow_redirects=True)
# --------------------------------------------------------------------------
def _copy_project_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/projects/demo" and request.method == "GET":
        return httpx.Response(200, json=_project_payload(), request=request)
    if request.url.path == "/api/v3/projects/form" and request.method == "POST":
        return httpx.Response(200, json={"_embedded": {"schema": {}}}, request=request)
    if request.url.path == "/api/v3/projects/1/copy/form" and request.method == "POST":
        return httpx.Response(
            200,
            json={
                "_embedded": {
                    "payload": {"name": "Demo Copy", "identifier": "demo-copy"},
                    "validationErrors": {},
                }
            },
            request=request,
        )
    if request.url.path == "/api/v3/projects/1/copy" and request.method == "POST":
        return httpx.Response(302, headers={"Location": "/api/v3/job_statuses/77"}, request=request)
    if request.url.path == "/api/v3/job_statuses/77" and request.method == "GET":
        return httpx.Response(200, json={"_type": "JobStatus", "id": 77}, request=request)
    _unexpected(request)
    raise AssertionError  # pragma: no cover


# --------------------------------------------------------------------------
# add_project_favorite / remove_project_favorite:
# GET /api/v3/projects/{ref} (resolve, preview) -> POST|DELETE /api/v3/workspaces/{id}/favorite (write)
# --------------------------------------------------------------------------
def _add_project_favorite_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/projects/demo" and request.method == "GET":
        return httpx.Response(200, json=_project_payload(), request=request)
    if request.url.path == "/api/v3/workspaces/1/favorite" and request.method == "POST":
        return httpx.Response(204, request=request)
    _unexpected(request)
    raise AssertionError  # pragma: no cover


def _remove_project_favorite_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/projects/demo" and request.method == "GET":
        return httpx.Response(200, json=_project_payload(), request=request)
    if request.url.path == "/api/v3/workspaces/1/favorite" and request.method == "DELETE":
        return httpx.Response(204, request=request)
    _unexpected(request)
    raise AssertionError  # pragma: no cover


# --------------------------------------------------------------------------
# create_news: GET /api/v3/projects/{ref} (resolve, preview) -> POST /api/v3/news (write)
# --------------------------------------------------------------------------
def _create_news_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/projects/demo" and request.method == "GET":
        return httpx.Response(200, json=_project_payload(), request=request)
    if request.url.path == "/api/v3/news" and request.method == "POST":
        return httpx.Response(
            201,
            json={
                "_type": "News",
                "id": 8,
                "title": "Release Notes",
                "summary": None,
                "description": {"raw": None},
                "createdAt": "2026-03-20T08:30:00Z",
                "_links": {
                    "self": {"href": "/api/v3/news/8"},
                    "project": {"href": "/api/v3/projects/1", "title": "Demo"},
                },
            },
            request=request,
        )
    _unexpected(request)
    raise AssertionError  # pragma: no cover


# --------------------------------------------------------------------------
# update_news: GET /api/v3/news/{id} (preview) -> PATCH /api/v3/news/{id} (write)
# --------------------------------------------------------------------------
def _news_detail_payload(news_id: int = 7, title: str = "Release Notes", summary: str = "Sprint 8 is out") -> dict:
    return {
        "_type": "News",
        "id": news_id,
        "title": title,
        "summary": summary,
        "description": {"raw": "Shipped the sprint"},
        "createdAt": "2026-03-20T08:00:00Z",
        "_links": {
            "self": {"href": f"/api/v3/news/{news_id}"},
            "project": {"href": "/api/v3/projects/1", "title": "Demo"},
            "updateImmediately": {"href": f"/api/v3/news/{news_id}", "method": "patch"},
            "delete": {"href": f"/api/v3/news/{news_id}", "method": "delete"},
        },
    }


def _update_news_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/news/7" and request.method == "GET":
        return httpx.Response(200, json=_news_detail_payload(), request=request)
    if request.url.path == "/api/v3/news/7" and request.method == "PATCH":
        return httpx.Response(200, json=_news_detail_payload(title="Updated Title"), request=request)
    _unexpected(request)
    raise AssertionError  # pragma: no cover


# --------------------------------------------------------------------------
# delete_news: GET /api/v3/news/{id} (preview) -> DELETE /api/v3/news/{id} (write)
# --------------------------------------------------------------------------
def _delete_news_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/news/7" and request.method == "GET":
        return httpx.Response(200, json=_news_detail_payload(), request=request)
    if request.url.path == "/api/v3/news/7" and request.method == "DELETE":
        return httpx.Response(202, request=request)
    _unexpected(request)
    raise AssertionError  # pragma: no cover


# --------------------------------------------------------------------------
# update_document: GET /api/v3/documents/{id} (preview) -> PATCH /api/v3/documents/{id} (write)
# --------------------------------------------------------------------------
def _document_payload(title: str = "Architecture") -> dict:
    return {
        "_type": "Document",
        "id": 5,
        "title": title,
        "description": {"raw": "System overview"},
        "createdAt": "2026-03-20T09:00:00Z",
        "_links": {
            "self": {"href": "/api/v3/documents/5"},
            "project": {"href": "/api/v3/projects/1", "title": "Demo"},
            "attachments": {"href": "/api/v3/documents/5/attachments"},
            "updateImmediately": {"href": "/api/v3/documents/5", "method": "patch"},
        },
        "_embedded": {"attachments": {"count": 0, "total": 0}},
    }


def _update_document_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/documents/5" and request.method == "GET":
        return httpx.Response(200, json=_document_payload(), request=request)
    if request.url.path == "/api/v3/documents/5" and request.method == "PATCH":
        return httpx.Response(200, json=_document_payload(title="Architecture Updated"), request=request)
    _unexpected(request)
    raise AssertionError  # pragma: no cover


# --------------------------------------------------------------------------
# create_grid: GET /api/v3/projects/{ref} (scope resolution) -> POST /api/v3/grids/form (preview)
# -> POST /api/v3/grids (write)
# --------------------------------------------------------------------------
def _grid_payload(grid_id: int = 55, name: str = "Demo Grid") -> dict:
    return {
        "_type": "Grid",
        "id": grid_id,
        "name": name,
        "rowCount": 2,
        "columnCount": 3,
        "createdAt": "2026-03-23T12:00:00Z",
        "updatedAt": "2026-03-23T12:00:00Z",
        "_links": {
            "scope": {"href": "/projects/demo"},
            "self": {"href": f"/api/v3/grids/{grid_id}"},
        },
    }


def _create_grid_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/projects/demo" and request.method == "GET":
        return httpx.Response(200, json=_project_payload(), request=request)
    if request.url.path == "/api/v3/grids/form" and request.method == "POST":
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
        return httpx.Response(201, json=_grid_payload(), request=request)
    _unexpected(request)
    raise AssertionError  # pragma: no cover


# --------------------------------------------------------------------------
# update_grid: GET /api/v3/grids/{id} -> GET /api/v3/projects/{ref} (scope resolution)
# -> POST /api/v3/grids/{id}/form (preview) -> PATCH /api/v3/grids/{id} (write)
# --------------------------------------------------------------------------
def _update_grid_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/grids/55" and request.method == "GET":
        return httpx.Response(200, json=_grid_payload(), request=request)
    if request.url.path == "/api/v3/projects/demo" and request.method == "GET":
        return httpx.Response(200, json=_project_payload(), request=request)
    if request.url.path == "/api/v3/grids/55/form" and request.method == "POST":
        return httpx.Response(
            200,
            json={
                "_embedded": {
                    "payload": {"name": "Renamed Grid", "_links": {"scope": {"href": "/projects/demo"}}},
                    "validationErrors": {},
                }
            },
            request=request,
        )
    if request.url.path == "/api/v3/grids/55" and request.method == "PATCH":
        return httpx.Response(200, json=_grid_payload(name="Renamed Grid"), request=request)
    _unexpected(request)
    raise AssertionError  # pragma: no cover


# --------------------------------------------------------------------------
# delete_grid: GET /api/v3/grids/{id} -> GET /api/v3/projects/{ref} (scope resolution, preview)
# -> DELETE /api/v3/grids/{id} (write)
# --------------------------------------------------------------------------
def _delete_grid_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/grids/55" and request.method == "GET":
        return httpx.Response(200, json=_grid_payload(), request=request)
    if request.url.path == "/api/v3/projects/demo" and request.method == "GET":
        return httpx.Response(200, json=_project_payload(), request=request)
    if request.url.path == "/api/v3/grids/55" and request.method == "DELETE":
        return httpx.Response(204, request=request)
    _unexpected(request)
    raise AssertionError  # pragma: no cover


PROJECT_CASES: dict[str, WriteToolCase] = {
    "create_project": WriteToolCase(
        tool="create_project",
        kwargs={"name": "Demo Project", "identifier": "demo-project"},
        settings=_settings(),
        write_scope="project",
        handler=_create_project_handler,
        write_request=("POST", "/api/v3/projects"),
    ),
    "update_project": WriteToolCase(
        tool="update_project",
        kwargs={"project": "demo", "name": "Updated Demo"},
        settings=_settings(),
        write_scope="project",
        handler=_update_project_handler,
        write_request=("PATCH", "/api/v3/projects/1"),
    ),
    "delete_project": WriteToolCase(
        tool="delete_project",
        kwargs={"project": "demo"},
        settings=_settings(),
        write_scope="project",
        handler=_delete_project_handler,
        write_request=("DELETE", "/api/v3/projects/1"),
    ),
    "copy_project": WriteToolCase(
        tool="copy_project",
        kwargs={"source_project": "demo", "name": "Demo Copy", "identifier": "demo-copy"},
        settings=_settings(),
        write_scope="project",
        handler=_copy_project_handler,
        write_request=("POST", "/api/v3/projects/1/copy"),
    ),
    "add_project_favorite": WriteToolCase(
        tool="add_project_favorite",
        kwargs={"project": "demo"},
        settings=_settings(),
        write_scope="project",
        handler=_add_project_favorite_handler,
        write_request=("POST", "/api/v3/workspaces/1/favorite"),
    ),
    "remove_project_favorite": WriteToolCase(
        tool="remove_project_favorite",
        kwargs={"project": "demo"},
        settings=_settings(),
        write_scope="project",
        handler=_remove_project_favorite_handler,
        write_request=("DELETE", "/api/v3/workspaces/1/favorite"),
    ),
    "create_news": WriteToolCase(
        tool="create_news",
        kwargs={"project": "demo", "title": "Release Notes"},
        settings=_settings(),
        write_scope="project",
        handler=_create_news_handler,
        write_request=("POST", "/api/v3/news"),
    ),
    "update_news": WriteToolCase(
        tool="update_news",
        kwargs={"news_id": 7, "title": "Updated Title"},
        settings=_settings(),
        write_scope="project",
        handler=_update_news_handler,
        write_request=("PATCH", "/api/v3/news/7"),
    ),
    "delete_news": WriteToolCase(
        tool="delete_news",
        kwargs={"news_id": 7},
        settings=_settings(),
        write_scope="project",
        handler=_delete_news_handler,
        write_request=("DELETE", "/api/v3/news/7"),
    ),
    "update_document": WriteToolCase(
        tool="update_document",
        kwargs={"document_id": 5, "title": "Architecture Updated"},
        settings=_settings(),
        write_scope="project",
        handler=_update_document_handler,
        write_request=("PATCH", "/api/v3/documents/5"),
    ),
    "create_grid": WriteToolCase(
        tool="create_grid",
        kwargs={"name": "Demo Grid", "scope": "/projects/demo", "row_count": 2, "column_count": 3},
        settings=_settings(),
        write_scope="project",
        handler=_create_grid_handler,
        write_request=("POST", "/api/v3/grids"),
    ),
    "update_grid": WriteToolCase(
        tool="update_grid",
        kwargs={"grid_id": 55, "name": "Renamed Grid"},
        settings=_settings(),
        write_scope="project",
        handler=_update_grid_handler,
        write_request=("PATCH", "/api/v3/grids/55"),
    ),
    "delete_grid": WriteToolCase(
        tool="delete_grid",
        kwargs={"grid_id": 55},
        settings=_settings(),
        write_scope="project",
        handler=_delete_grid_handler,
        write_request=("DELETE", "/api/v3/grids/55"),
    ),
}
