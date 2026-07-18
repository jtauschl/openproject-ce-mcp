# Sibling test files import from this module as `from _client_test_helpers import
# ...` (no package prefix), which relies on pytest's default rootless import mode
# adding this directory to sys.path. Revisit if the project ever switches to
# `--import-mode=importlib` (e.g. as part of the OPM-26 test-architecture work).
from __future__ import annotations

import httpx

from openproject_ce_mcp.config import Settings


def make_settings() -> Settings:
    # Permissive project scope by default: this factory is for tests exercising
    # something other than project-scope enforcement. Tests that specifically test
    # scope enforcement override read_projects/write_projects explicitly.
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


def _membership_settings() -> Settings:
    return Settings(
        base_url="https://op.example.com",
        api_token="token",
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
        read_projects=("demo-id",),
        write_projects=("demo-id",),
        enable_membership_write=True,
    )


def _empty_scope_settings() -> Settings:
    return Settings(
        base_url="https://op.example.com",
        api_token="token",
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
    )


def _no_request_handler(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"no request must be issued when read_projects is empty: {request.method} {request.url}")


def _make_grid_settings(extra: dict | None = None) -> Settings:
    base = {
        "base_url": "https://op.example.com",
        "api_token": "token",
        "timeout": 12,
        "verify_ssl": True,
        "default_page_size": 20,
        "max_page_size": 50,
        "max_results": 100,
        "log_level": "WARNING",
        "read_projects": ("demo",),
        "write_projects": ("demo",),
        "enable_project_write": True,
    }
    if extra:
        base.update(extra)
    return Settings(**base)


def _make_grid_payload(grid_id: int = 55) -> dict:
    return {
        "_type": "Grid",
        "id": grid_id,
        "rowCount": 2,
        "columnCount": 3,
        "createdAt": "2026-03-23T12:00:00Z",
        "updatedAt": "2026-03-23T12:00:00Z",
        "_links": {
            "scope": {"href": "/projects/demo"},
            "self": {"href": f"/api/v3/grids/{grid_id}"},
        },
    }


def _make_wp_form_response(request: httpx.Request, body: dict) -> httpx.Response:
    return httpx.Response(
        200,
        json={"_type": "Form", "_embedded": {"payload": body, "validationErrors": {}}},
        request=request,
    )


def _make_project_response(request: httpx.Request, project_id: int = 1) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "_type": "Project",
            "id": project_id,
            "name": "Demo",
            "identifier": "demo",
            "_links": {"versions": {"href": f"/api/v3/projects/{project_id}/versions"}},
        },
        request=request,
    )


def _wp_detail_payload_with_description(wp_id: int, display_id: str, description_raw: str) -> dict:
    payload = _wp_detail_payload(wp_id, display_id)
    payload["description"] = {"raw": description_raw, "html": "<p>ignored</p>"}
    return payload


def _wp_detail_payload(wp_id: int, display_id: str) -> dict:
    return {
        "id": wp_id,
        "subject": "Sample",
        "displayId": display_id,
        "_links": {
            "project": {"title": "Demo"},
            "status": {"title": "New"},
            "type": {"title": "Task"},
            "activities": {"href": f"/api/v3/work_packages/{wp_id}/activities"},
            "relations": {"href": f"/api/v3/work_packages/{wp_id}/relations"},
        },
    }


def _write_enabled_settings() -> Settings:
    import dataclasses

    return dataclasses.replace(make_settings(), enable_work_package_write=True)


def _personal_write_enabled_settings() -> Settings:
    import dataclasses

    return dataclasses.replace(make_settings(), enable_personal_write=True)


def _personal_read_and_write_enabled_settings() -> Settings:
    import dataclasses

    return dataclasses.replace(make_settings(), enable_personal_read=True, enable_personal_write=True)


def _notification_payload(
    notification_id: int,
    *,
    project_href: str | None = None,
    project_title: str = "Demo",
    resource_href: str | None = None,
) -> dict:
    links: dict = {}
    if project_href is not None:
        links["project"] = {"href": project_href, "title": project_title}
    if resource_href is not None:
        links["resource"] = {"href": resource_href, "title": "Task"}
    return {
        "id": notification_id,
        "subject": "Something happened",
        "readIAN": False,
        "createdAt": "2026-01-01T00:00:00Z",
        "_links": links,
    }


def _base_settings(**overrides) -> Settings:
    base = {
        "base_url": "https://op.example.com",
        "api_token": "token",
        "timeout": 12,
        "verify_ssl": True,
        "default_page_size": 20,
        "max_page_size": 50,
        "max_results": 100,
        "log_level": "WARNING",
        "read_projects": ("*",),
        "write_projects": ("*",),
    }
    base.update(overrides)
    return Settings(**base)


def _projects_search_handler(matches: list[dict], *, page_size: int = 50):
    """Simulate GET /api/v3/projects, paginating an in-memory match list by offset/pageSize."""

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params.get("offset", "1"))
        size = int(request.url.params.get("pageSize", str(page_size)))
        start = (offset - 1) * size
        page_items = matches[start : start + size]
        elements = [
            {"_type": "Project", "id": m["id"], "name": m["name"], "identifier": m.get("identifier")}
            for m in page_items
        ]
        return httpx.Response(200, json={"total": len(matches), "_embedded": {"elements": elements}}, request=request)

    return handler
