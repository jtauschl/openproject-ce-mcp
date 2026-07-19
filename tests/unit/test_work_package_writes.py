from __future__ import annotations

import asyncio
import json
import logging

import httpx
import pytest
from _client_test_helpers import (
    _base_settings,
    _make_project_response,
    _make_wp_form_response,
    _write_enabled_settings,
    make_settings,
)

from openproject_ce_mcp.client import (
    CLEAR,
    CLEAR_PARENT,
    CLEAR_VERSION,
    InvalidInputError,
    OpenProjectClient,
    OpenProjectServerError,
    PermissionDeniedError,
)
from openproject_ce_mcp.config import Settings
from openproject_ce_mcp.tools import _to_payload


@pytest.mark.asyncio
async def test_create_work_package_returns_confirmation_preview_before_writing() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in {"/api/v3/projects/demo", "/api/v3/projects/1"}:
            return httpx.Response(
                200,
                json={
                    "_type": "Project",
                    "id": 1,
                    "name": "Demo",
                    "identifier": "demo",
                    "_links": {"versions": {"href": "/api/v3/projects/demo/versions"}},
                },
                request=request,
            )
        if request.url.path == "/api/v3/projects/1/types":
            return httpx.Response(
                200,
                json={"_embedded": {"elements": [{"id": 7, "name": "Feature"}]}},
                request=request,
            )
        if request.url.path == "/api/v3/projects/1/versions":
            return httpx.Response(
                200,
                json={"total": 1, "_embedded": {"elements": [{"id": 11, "name": "Q2", "_links": {}}]}},
                request=request,
            )
        if request.url.path == "/api/v3/projects/1/work_packages/form":
            assert request.method == "POST"
            assert request.content
            body = json.loads(request.content)
            assert body["subject"] == "Apple HealthKit Anbindung"
            assert body["description"] == {"format": "markdown", "raw": "Sync Apple Health data"}
            assert body["_links"]["type"]["href"] == "/api/v3/types/7"
            assert body["_links"]["version"]["href"] == "/api/v3/versions/11"
            return httpx.Response(
                200,
                json={"_type": "Form", "_embedded": {"payload": body, "validationErrors": {}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings(
        read_projects=("*",),
        write_projects=("*",),
        base_url="https://op.example.com",
        api_token="token",
        timeout=12,
        verify_ssl=True,
        default_page_size=1,
        max_page_size=1,
        max_results=10,
        log_level="WARNING",
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.create_work_package(
        project="demo",
        type="Feature",
        subject="Apple HealthKit Anbindung",
        description="Sync Apple Health data",
        version="Q2",
        confirm=False,
    )

    assert result.ready is True
    assert result.requires_confirmation is True
    assert result.confirmed is False
    assert result.result is None

    await client.aclose()


@pytest.mark.asyncio
async def test_update_work_package_writes_after_confirmation_when_enabled() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "subject": "Old title",
                    "lockVersion": 4,
                    "_links": {
                        "project": {"title": "Demo", "href": "/api/v3/projects/1"},
                        "status": {"title": "New"},
                        "type": {"title": "Feature"},
                        "activities": {"href": "/api/v3/work_packages/42/activities"},
                        "relations": {"href": "/api/v3/work_packages/42/relations"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/statuses":
            return httpx.Response(
                200,
                json={"_embedded": {"elements": [{"id": 9, "name": "In progress"}]}},
                request=request,
            )
        if request.url.path == "/api/v3/statuses/9":
            return httpx.Response(200, json={"id": 9, "name": "In progress", "isClosed": False}, request=request)
        if request.url.path == "/api/v3/work_packages/42/form":
            assert request.method == "POST"
            body = json.loads(request.content)
            assert body["lockVersion"] == 4
            assert body["subject"] == "New title"
            assert body["_links"]["status"]["href"] == "/api/v3/statuses/9"
            return httpx.Response(
                200,
                json={"_type": "Form", "_embedded": {"payload": body, "validationErrors": {}}},
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42" and request.method == "PATCH":
            body = json.loads(request.content)
            assert body["lockVersion"] == 4
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "subject": "New title",
                    "lockVersion": 5,
                    "_links": {
                        "project": {"title": "Demo"},
                        "status": {"title": "In progress"},
                        "type": {"title": "Feature"},
                        "activities": {"href": "/api/v3/work_packages/42/activities"},
                        "relations": {"href": "/api/v3/work_packages/42/relations"},
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = make_settings()
    settings = Settings(
        read_projects=("*",),
        write_projects=("*",),
        base_url=settings.base_url,
        api_token=settings.api_token,
        enable_work_package_write=True,
        timeout=settings.timeout,
        verify_ssl=settings.verify_ssl,
        default_page_size=settings.default_page_size,
        max_page_size=settings.max_page_size,
        max_results=settings.max_results,
        log_level=settings.log_level,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.update_work_package(
        work_package_id=42,
        subject="New title",
        status="In progress",
        confirm=True,
    )

    assert result.confirmed is True
    assert result.result is not None
    assert result.result.subject == "New title"
    assert result.result.status == "In progress"

    await client.aclose()


@pytest.mark.asyncio
async def test_update_work_package_schema_probe_includes_lock_version() -> None:
    # Regression: OpenProject 17.x rejects POST work_packages/{id}/form with a 409
    # unless the current lockVersion is included -- even for the schema-only probe
    # that runs when a schema-resolved field (priority, responsible, ...) is set.
    # Both form POSTs (the schema probe and the update form) must carry lockVersion.
    form_calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal form_calls
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "subject": "Old title",
                    "lockVersion": 4,
                    "_links": {
                        "project": {"title": "Demo", "href": "/api/v3/projects/1"},
                        "status": {"title": "New"},
                        "type": {"title": "Feature"},
                        "priority": {"title": "Normal"},
                        "activities": {"href": "/api/v3/work_packages/42/activities"},
                        "relations": {"href": "/api/v3/work_packages/42/relations"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42/form":
            assert request.method == "POST"
            body = json.loads(request.content)
            # The core assertion: every form POST -- including the schema probe --
            # must include the current lockVersion, otherwise OpenProject 17.x 409s.
            assert body["lockVersion"] == 4
            form_calls += 1
            return httpx.Response(
                200,
                json={
                    "_type": "Form",
                    "_embedded": {
                        "schema": {
                            "priority": {
                                "name": "Priority",
                                "type": "Priority",
                                "required": True,
                                "writable": True,
                                "location": "_links",
                                "_embedded": {
                                    "allowedValues": [
                                        {
                                            "id": 9,
                                            "name": "High",
                                            "_links": {"self": {"href": "/api/v3/priorities/9", "title": "High"}},
                                        }
                                    ]
                                },
                            },
                        },
                        "payload": {
                            "lockVersion": 4,
                            "_links": {"priority": {"href": "/api/v3/priorities/9"}},
                        },
                        "validationErrors": {},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42" and request.method == "PATCH":
            body = json.loads(request.content)
            assert body["lockVersion"] == 4
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "subject": "Old title",
                    "lockVersion": 5,
                    "_links": {
                        "project": {"title": "Demo"},
                        "status": {"title": "New"},
                        "type": {"title": "Feature"},
                        "priority": {"title": "High"},
                        "activities": {"href": "/api/v3/work_packages/42/activities"},
                        "relations": {"href": "/api/v3/work_packages/42/relations"},
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = make_settings()
    settings = Settings(
        read_projects=("*",),
        write_projects=("*",),
        base_url=settings.base_url,
        api_token=settings.api_token,
        enable_work_package_write=True,
        timeout=settings.timeout,
        verify_ssl=settings.verify_ssl,
        default_page_size=settings.default_page_size,
        max_page_size=settings.max_page_size,
        max_results=settings.max_results,
        log_level=settings.log_level,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.update_work_package(
        work_package_id=42,
        priority="High",
        confirm=True,
    )

    # The schema probe POST and the update-form POST both hit the form endpoint.
    assert form_calls >= 2
    assert result.confirmed is True
    assert result.result is not None
    assert result.result.priority == "High"

    await client.aclose()


@pytest.mark.asyncio
async def test_update_work_package_reparents_via_parent_link() -> None:
    # Re-parenting sends _links.parent as a numeric HAL href on the normal PATCH.
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "subject": "Child",
                    "lockVersion": 4,
                    "_links": {
                        "project": {"title": "Demo", "href": "/api/v3/projects/1"},
                        "status": {"title": "New"},
                        "type": {"title": "Feature"},
                        "activities": {"href": "/api/v3/work_packages/42/activities"},
                        "relations": {"href": "/api/v3/work_packages/42/relations"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/7" and request.method == "GET":
            # The new parent's own project must be allowlist-checked before
            # it can be linked.
            return httpx.Response(
                200,
                json={"id": 7, "_links": {"project": {"title": "Demo", "href": "/api/v3/projects/1"}}},
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42/form":
            body = json.loads(request.content)
            assert body["_links"]["parent"]["href"] == "/api/v3/work_packages/7"
            return httpx.Response(
                200,
                json={"_type": "Form", "_embedded": {"payload": body, "validationErrors": {}}},
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42" and request.method == "PATCH":
            body = json.loads(request.content)
            assert body["_links"]["parent"]["href"] == "/api/v3/work_packages/7"
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "subject": "Child",
                    "lockVersion": 5,
                    "_links": {
                        "project": {"title": "Demo"},
                        "status": {"title": "New"},
                        "type": {"title": "Feature"},
                        "parent": {"href": "/api/v3/work_packages/7", "title": "Parent"},
                        "activities": {"href": "/api/v3/work_packages/42/activities"},
                        "relations": {"href": "/api/v3/work_packages/42/relations"},
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = make_settings()
    settings = Settings(
        read_projects=("*",),
        write_projects=("*",),
        base_url=settings.base_url,
        api_token=settings.api_token,
        enable_work_package_write=True,
        timeout=settings.timeout,
        verify_ssl=settings.verify_ssl,
        default_page_size=settings.default_page_size,
        max_page_size=settings.max_page_size,
        max_results=settings.max_results,
        log_level=settings.log_level,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.update_work_package(
        work_package_id=42,
        parent_work_package_id=7,
        confirm=True,
    )

    assert result.confirmed is True
    assert result.result is not None
    assert result.result.parent_id == 7

    await client.aclose()


@pytest.mark.asyncio
async def test_update_work_package_unparents_with_null_href_through_schema_probe() -> None:
    # Un-parenting (CLEAR_PARENT) must send _links.parent = {"href": None}, and it must
    # survive the schema probe that fires when a schema-resolved field (priority) is
    # also set -- i.e. every form POST carries the null parent href without failing.
    form_calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal form_calls
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "subject": "Child",
                    "lockVersion": 4,
                    "_links": {
                        "project": {"title": "Demo", "href": "/api/v3/projects/1"},
                        "status": {"title": "New"},
                        "type": {"title": "Feature"},
                        "parent": {"href": "/api/v3/work_packages/7", "title": "Parent"},
                        "priority": {"title": "Normal"},
                        "activities": {"href": "/api/v3/work_packages/42/activities"},
                        "relations": {"href": "/api/v3/work_packages/42/relations"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42/form":
            body = json.loads(request.content)
            # The un-parent link rides along on every form POST, including the probe.
            assert "parent" in body["_links"]
            assert body["_links"]["parent"]["href"] is None
            form_calls += 1
            return httpx.Response(
                200,
                json={
                    "_type": "Form",
                    "_embedded": {
                        "schema": {
                            "priority": {
                                "name": "Priority",
                                "type": "Priority",
                                "required": True,
                                "writable": True,
                                "location": "_links",
                                "_embedded": {
                                    "allowedValues": [
                                        {
                                            "id": 9,
                                            "name": "High",
                                            "_links": {"self": {"href": "/api/v3/priorities/9", "title": "High"}},
                                        }
                                    ]
                                },
                            },
                        },
                        "payload": body,
                        "validationErrors": {},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42" and request.method == "PATCH":
            body = json.loads(request.content)
            assert body["_links"]["parent"]["href"] is None
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "subject": "Child",
                    "lockVersion": 5,
                    "_links": {
                        "project": {"title": "Demo"},
                        "status": {"title": "New"},
                        "type": {"title": "Feature"},
                        "parent": {"href": None},
                        "priority": {"title": "High"},
                        "activities": {"href": "/api/v3/work_packages/42/activities"},
                        "relations": {"href": "/api/v3/work_packages/42/relations"},
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = make_settings()
    settings = Settings(
        read_projects=("*",),
        write_projects=("*",),
        base_url=settings.base_url,
        api_token=settings.api_token,
        enable_work_package_write=True,
        timeout=settings.timeout,
        verify_ssl=settings.verify_ssl,
        default_page_size=settings.default_page_size,
        max_page_size=settings.max_page_size,
        max_results=settings.max_results,
        log_level=settings.log_level,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.update_work_package(
        work_package_id=42,
        parent_work_package_id=CLEAR_PARENT,
        priority="High",
        confirm=True,
    )

    assert form_calls >= 2
    assert result.confirmed is True
    assert result.result is not None
    assert result.result.parent_id is None


@pytest.mark.asyncio
async def test_update_work_package_clears_version_with_null_href() -> None:
    # CLEAR_VERSION must send _links.version = {"href": None} on the PATCH, unassigning
    # the version, and must not try to resolve "none" as a version name.
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "subject": "WP",
                    "lockVersion": 3,
                    "_links": {
                        "project": {"title": "Demo", "href": "/api/v3/projects/1"},
                        "status": {"title": "New"},
                        "type": {"title": "Task"},
                        "version": {"href": "/api/v3/versions/15", "title": "Backlog"},
                        "activities": {"href": "/api/v3/work_packages/42/activities"},
                        "relations": {"href": "/api/v3/work_packages/42/relations"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42/form":
            body = json.loads(request.content)
            assert body["_links"]["version"]["href"] is None
            return httpx.Response(
                200,
                json={
                    "_type": "Form",
                    "_embedded": {"schema": {}, "payload": body, "validationErrors": {}},
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42" and request.method == "PATCH":
            body = json.loads(request.content)
            assert body["_links"]["version"]["href"] is None
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "subject": "WP",
                    "lockVersion": 4,
                    "_links": {
                        "project": {"title": "Demo"},
                        "status": {"title": "New"},
                        "type": {"title": "Task"},
                        "version": {"href": None},
                        "activities": {"href": "/api/v3/work_packages/42/activities"},
                        "relations": {"href": "/api/v3/work_packages/42/relations"},
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = make_settings()
    settings = Settings(
        read_projects=("*",),
        write_projects=("*",),
        base_url=settings.base_url,
        api_token=settings.api_token,
        enable_work_package_write=True,
        timeout=settings.timeout,
        verify_ssl=settings.verify_ssl,
        default_page_size=settings.default_page_size,
        max_page_size=settings.max_page_size,
        max_results=settings.max_results,
        log_level=settings.log_level,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.update_work_package(
        work_package_id=42,
        version=CLEAR_VERSION,
        confirm=True,
    )

    assert result.confirmed is True
    assert result.result is not None
    assert result.result.version is None

    await client.aclose()


@pytest.mark.asyncio
async def test_update_work_package_clears_sprint_with_null_href() -> None:
    # Sprint uses the generic CLEAR sentinel (not a dedicated CLEAR_SPRINT), and
    # must send _links.sprint = {"href": None} without trying to resolve "none".
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "subject": "WP",
                    "lockVersion": 3,
                    "_links": {
                        "project": {"title": "Demo", "href": "/api/v3/projects/1"},
                        "status": {"title": "New"},
                        "type": {"title": "Task"},
                        "sprint": {"href": "/api/v3/sprints/1", "title": "Cleanup"},
                        "activities": {"href": "/api/v3/work_packages/42/activities"},
                        "relations": {"href": "/api/v3/work_packages/42/relations"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42/form":
            body = json.loads(request.content)
            assert body["_links"]["sprint"]["href"] is None
            return httpx.Response(
                200,
                json={
                    "_type": "Form",
                    "_embedded": {"schema": {}, "payload": body, "validationErrors": {}},
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42" and request.method == "PATCH":
            body = json.loads(request.content)
            assert body["_links"]["sprint"]["href"] is None
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "subject": "WP",
                    "lockVersion": 4,
                    "_links": {
                        "project": {"title": "Demo"},
                        "status": {"title": "New"},
                        "type": {"title": "Task"},
                        "sprint": {"href": None},
                        "activities": {"href": "/api/v3/work_packages/42/activities"},
                        "relations": {"href": "/api/v3/work_packages/42/relations"},
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings(
        read_projects=("*",),
        write_projects=("*",),
        base_url="https://op.example.com",
        api_token="token",
        enable_work_package_write=True,
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.update_work_package(
        work_package_id=42,
        sprint=CLEAR,
        confirm=True,
    )

    assert result.confirmed is True
    assert result.result is not None
    assert result.result.sprint is None

    await client.aclose()


@pytest.mark.asyncio
async def test_update_work_package_resolves_sprint_by_name() -> None:
    # A sprint name resolves to an id via list_project_sprints (the
    # work package's own project), mirroring how _resolve_version_id resolves
    # version names via list_versions.
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "subject": "WP",
                    "lockVersion": 3,
                    "_links": {
                        "project": {"title": "Demo", "href": "/api/v3/projects/7"},
                        "status": {"title": "New"},
                        "type": {"title": "Task"},
                        "activities": {"href": "/api/v3/work_packages/42/activities"},
                        "relations": {"href": "/api/v3/work_packages/42/relations"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/projects/7" and request.method == "GET":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 7, "identifier": "demo", "name": "Demo", "active": True},
                request=request,
            )
        if request.url.path == "/api/v3/projects/7/sprints" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "_type": "Collection",
                    "total": 1,
                    "count": 1,
                    "pageSize": 100,
                    "offset": 1,
                    "_embedded": {
                        "elements": [
                            {
                                "_type": "Sprint",
                                "id": 1,
                                "name": "Cleanup",
                                "_links": {},
                            }
                        ]
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42/form":
            body = json.loads(request.content)
            assert body["_links"]["sprint"]["href"] == "/api/v3/sprints/1"
            return httpx.Response(
                200,
                json={
                    "_type": "Form",
                    "_embedded": {"schema": {}, "payload": body, "validationErrors": {}},
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42" and request.method == "PATCH":
            body = json.loads(request.content)
            assert body["_links"]["sprint"]["href"] == "/api/v3/sprints/1"
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "subject": "WP",
                    "lockVersion": 4,
                    "_links": {
                        "project": {"title": "Demo"},
                        "status": {"title": "New"},
                        "type": {"title": "Task"},
                        "sprint": {"href": "/api/v3/sprints/1", "title": "Cleanup"},
                        "activities": {"href": "/api/v3/work_packages/42/activities"},
                        "relations": {"href": "/api/v3/work_packages/42/relations"},
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings(
        read_projects=("*",),
        write_projects=("*",),
        base_url="https://op.example.com",
        api_token="token",
        enable_work_package_write=True,
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.update_work_package(
        work_package_id=42,
        sprint="Cleanup",
        confirm=True,
    )

    assert result.confirmed is True
    assert result.result is not None
    assert result.result.sprint == "Cleanup"

    await client.aclose()


@pytest.mark.asyncio
async def test_update_work_package_clears_assignee_with_null_href() -> None:
    # CLEAR on the direct-path field (assignee) must send _links.assignee = {"href": None}
    # and must not resolve "none" as a user id.
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "subject": "WP",
                    "lockVersion": 2,
                    "_links": {
                        "project": {"title": "Demo", "href": "/api/v3/projects/1"},
                        "status": {"title": "New"},
                        "type": {"title": "Task"},
                        "assignee": {"href": "/api/v3/users/9", "title": "Bob"},
                        "activities": {"href": "/api/v3/work_packages/42/activities"},
                        "relations": {"href": "/api/v3/work_packages/42/relations"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42/form":
            body = json.loads(request.content)
            assert body["_links"]["assignee"]["href"] is None
            return httpx.Response(
                200,
                json={"_type": "Form", "_embedded": {"schema": {}, "payload": body, "validationErrors": {}}},
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42" and request.method == "PATCH":
            body = json.loads(request.content)
            assert body["_links"]["assignee"]["href"] is None
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "subject": "WP",
                    "lockVersion": 3,
                    "_links": {
                        "project": {"title": "Demo"},
                        "status": {"title": "New"},
                        "type": {"title": "Task"},
                        "assignee": {"href": None},
                        "activities": {"href": "/api/v3/work_packages/42/activities"},
                        "relations": {"href": "/api/v3/work_packages/42/relations"},
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = make_settings()
    settings = Settings(
        read_projects=("*",),
        write_projects=("*",),
        base_url=settings.base_url,
        api_token=settings.api_token,
        enable_work_package_write=True,
        timeout=settings.timeout,
        verify_ssl=settings.verify_ssl,
        default_page_size=settings.default_page_size,
        max_page_size=settings.max_page_size,
        max_results=settings.max_results,
        log_level=settings.log_level,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.update_work_package(work_package_id=42, assignee=CLEAR, confirm=True)

    assert result.confirmed is True
    assert result.result is not None
    assert result.result.assignee is None

    await client.aclose()


@pytest.mark.asyncio
async def test_update_work_package_clears_category_with_null_href() -> None:
    # CLEAR on a schema-backed field (category) must send _links.category = {"href": None}.
    # A null href needs no schema-option resolution — the "none" string is never resolved.
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "subject": "WP",
                    "lockVersion": 2,
                    "_links": {
                        "project": {"title": "Demo", "href": "/api/v3/projects/1"},
                        "status": {"title": "New"},
                        "type": {"title": "Task"},
                        "category": {"href": "/api/v3/categories/3", "title": "Bugs"},
                        "activities": {"href": "/api/v3/work_packages/42/activities"},
                        "relations": {"href": "/api/v3/work_packages/42/relations"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42/form":
            body = json.loads(request.content)
            assert body["_links"]["category"]["href"] is None
            return httpx.Response(
                200,
                json={"_type": "Form", "_embedded": {"schema": {}, "payload": body, "validationErrors": {}}},
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42" and request.method == "PATCH":
            body = json.loads(request.content)
            assert body["_links"]["category"]["href"] is None
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "subject": "WP",
                    "lockVersion": 3,
                    "_links": {
                        "project": {"title": "Demo"},
                        "status": {"title": "New"},
                        "type": {"title": "Task"},
                        "category": {"href": None},
                        "activities": {"href": "/api/v3/work_packages/42/activities"},
                        "relations": {"href": "/api/v3/work_packages/42/relations"},
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = make_settings()
    settings = Settings(
        read_projects=("*",),
        write_projects=("*",),
        base_url=settings.base_url,
        api_token=settings.api_token,
        enable_work_package_write=True,
        timeout=settings.timeout,
        verify_ssl=settings.verify_ssl,
        default_page_size=settings.default_page_size,
        max_page_size=settings.max_page_size,
        max_results=settings.max_results,
        log_level=settings.log_level,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.update_work_package(work_package_id=42, category=CLEAR, confirm=True)

    assert result.confirmed is True
    await client.aclose()


@pytest.mark.asyncio
async def test_delete_work_package_requires_confirmation_preview() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "subject": "Delete me",
                    "lockVersion": 4,
                    "_links": {
                        "project": {"title": "Demo"},
                        "status": {"title": "New"},
                        "type": {"title": "Task"},
                        "activities": {"href": "/api/v3/work_packages/42/activities"},
                        "relations": {"href": "/api/v3/work_packages/42/relations"},
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings(
        read_projects=("*",),
        write_projects=("*",),
        base_url="https://op.example.com",
        api_token="token",
        timeout=12,
        verify_ssl=True,
        default_page_size=1,
        max_page_size=1,
        max_results=10,
        log_level="WARNING",
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.delete_work_package(work_package_id=42, confirm=False)

    assert result.ready is True
    assert result.requires_confirmation is True
    assert result.confirmed is False
    assert result.result is not None
    assert result.result.subject == "Delete me"

    await client.aclose()


@pytest.mark.asyncio
async def test_delete_work_package_deletes_when_enabled_and_confirmed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "subject": "Delete me",
                    "lockVersion": 4,
                    "_links": {
                        "project": {"title": "Demo"},
                        "status": {"title": "New"},
                        "type": {"title": "Task"},
                        "activities": {"href": "/api/v3/work_packages/42/activities"},
                        "relations": {"href": "/api/v3/work_packages/42/relations"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42" and request.method == "DELETE":
            return httpx.Response(204, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = make_settings()
    settings = Settings(
        read_projects=("*",),
        write_projects=("*",),
        base_url=settings.base_url,
        api_token=settings.api_token,
        enable_work_package_write=True,
        timeout=settings.timeout,
        verify_ssl=settings.verify_ssl,
        default_page_size=settings.default_page_size,
        max_page_size=settings.max_page_size,
        max_results=settings.max_results,
        log_level=settings.log_level,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.delete_work_package(work_package_id=42, confirm=True)

    assert result.confirmed is True
    assert result.result is None
    assert result.message == "Work package deleted successfully."

    await client.aclose()


@pytest.mark.asyncio
async def test_delete_work_package_requires_write_enablement() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "subject": "Delete me",
                    "lockVersion": 4,
                    "_links": {
                        "project": {"title": "Demo"},
                        "status": {"title": "New"},
                        "type": {"title": "Task"},
                        "activities": {"href": "/api/v3/work_packages/42/activities"},
                        "relations": {"href": "/api/v3/work_packages/42/relations"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42" and request.method == "DELETE":
            return httpx.Response(204, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings(
        read_projects=("*",),
        write_projects=("*",),
        enable_work_package_write=False,
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

    with pytest.raises(PermissionDeniedError, match="write support is disabled"):
        await client.delete_work_package(work_package_id=42, confirm=True)

    await client.aclose()


@pytest.mark.asyncio
async def test_add_work_package_comment_writes_after_confirmation_when_enabled() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42/activities" and request.method == "POST":
            assert request.url.params["notify"] == "false"
            body = json.loads(request.content)
            assert body == {
                "comment": {"raw": "Please verify on staging."},
                "internal": False,
            }
            return httpx.Response(
                201,
                json={
                    "id": 77,
                    "_type": "Activity",
                    "version": 3,
                    "comment": {"raw": "Please verify on staging."},
                    "_links": {"user": {"title": "OpenProject Bot"}},
                    "createdAt": "2026-03-20T11:00:00Z",
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = make_settings()
    settings = Settings(
        read_projects=("*",),
        write_projects=("*",),
        base_url=settings.base_url,
        api_token=settings.api_token,
        enable_work_package_write=True,
        timeout=settings.timeout,
        verify_ssl=settings.verify_ssl,
        default_page_size=settings.default_page_size,
        max_page_size=settings.max_page_size,
        max_results=settings.max_results,
        log_level=settings.log_level,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.add_work_package_comment(
        work_package_id=42,
        comment="Please verify on staging.",
        notify=False,
        confirm=True,
    )

    assert result.confirmed is True
    assert result.result is not None
    assert result.result.comment == "<user-content>Please verify on staging.</user-content>"
    # created_at is suppressed unconditionally, even for this ordinary,
    # non-aggregated response with a plausible createdAt of its own - there is
    # no reliable way to tell an aggregated response from a fresh one, so this
    # deliberately sacrifices a correct timestamp in the common case too.
    assert result.result.created_at is None

    await client.aclose()


@pytest.mark.asyncio
async def test_add_work_package_comment_suppresses_aggregated_journal_details() -> None:
    """OpenProject can merge a new note into an existing journal (e.g. a prior
    status change), returning that journal's unrelated `details`/`createdAt`
    on the activities POST. The comment-add result must not surface either.
    """

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42/activities" and request.method == "POST":
            return httpx.Response(
                201,
                json={
                    "id": 78,
                    "_type": "Activity::Comment",
                    "version": 4,
                    "comment": {"raw": "Looks good to me."},
                    "_links": {"user": {"title": "OpenProject Bot"}},
                    "createdAt": "2026-01-01T09:00:00Z",
                    "details": [{"format": "custom", "raw": "New → In progress"}],
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = make_settings()
    settings = Settings(
        read_projects=("*",),
        write_projects=("*",),
        base_url=settings.base_url,
        api_token=settings.api_token,
        enable_work_package_write=True,
        timeout=settings.timeout,
        verify_ssl=settings.verify_ssl,
        default_page_size=settings.default_page_size,
        max_page_size=settings.max_page_size,
        max_results=settings.max_results,
        log_level=settings.log_level,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.add_work_package_comment(
        work_package_id=42,
        comment="Looks good to me.",
        confirm=True,
    )

    assert result.result is not None
    assert result.result.comment == "<user-content>Looks good to me.</user-content>"
    assert result.result.details is None
    assert result.result.details_truncated is False
    assert result.result.created_at is None

    await client.aclose()


@pytest.mark.asyncio
async def test_add_work_package_comment_fetches_missing_user_via_fallback() -> None:
    """OpenProject's activities POST response can omit _links.user entirely,
    even though the comment was saved correctly. When that happens and the
    response carries a usable id, the client re-fetches the canonical
    activity to fill in user.
    """

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42/activities" and request.method == "POST":
            return httpx.Response(
                201,
                json={
                    "id": 79,
                    "_type": "Activity::Comment",
                    "version": 5,
                    "comment": {"raw": "Looks good to me."},
                    "_links": {},
                },
                request=request,
            )
        if request.url.path == "/api/v3/activities/79" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 79, "_links": {"user": {"title": "Jane Reviewer"}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_base_settings(enable_work_package_write=True), transport=httpx.MockTransport(handler))

    result = await client.add_work_package_comment(
        work_package_id=42,
        comment="Looks good to me.",
        confirm=True,
    )

    assert result.confirmed is True
    assert result.result is not None
    assert result.result.user == "Jane Reviewer"

    await client.aclose()


@pytest.mark.asyncio
async def test_add_work_package_comment_fallback_get_also_missing_user_stays_none() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42/activities" and request.method == "POST":
            return httpx.Response(
                201,
                json={"id": 80, "_type": "Activity::Comment", "version": 5, "comment": {"raw": "Ok."}, "_links": {}},
                request=request,
            )
        if request.url.path == "/api/v3/activities/80" and request.method == "GET":
            return httpx.Response(200, json={"id": 80, "_links": {}}, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_base_settings(enable_work_package_write=True), transport=httpx.MockTransport(handler))

    result = await client.add_work_package_comment(work_package_id=42, comment="Ok.", confirm=True)

    assert result.confirmed is True
    assert result.result is not None
    assert result.result.user is None

    await client.aclose()


@pytest.mark.asyncio
async def test_add_work_package_comment_fallback_get_failure_does_not_fail_comment(caplog) -> None:
    """A failing fallback lookup (404/permission/timeout/...) must not turn an
    already-persisted comment into a reported tool error."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42/activities" and request.method == "POST":
            return httpx.Response(
                201,
                json={"id": 81, "_type": "Activity::Comment", "version": 5, "comment": {"raw": "Ok."}, "_links": {}},
                request=request,
            )
        if request.url.path == "/api/v3/activities/81" and request.method == "GET":
            return httpx.Response(404, json={"message": "not found"}, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_base_settings(enable_work_package_write=True), transport=httpx.MockTransport(handler))

    with caplog.at_level(logging.WARNING, logger="openproject_ce_mcp.client"):
        result = await client.add_work_package_comment(work_package_id=42, comment="Ok.", confirm=True)

    assert result.confirmed is True
    assert result.result is not None
    assert result.result.user is None
    assert any("fallback fetch of activity 81" in r.message for r in caplog.records)

    await client.aclose()


@pytest.mark.asyncio
async def test_add_work_package_comment_skips_fallback_without_usable_activity_id() -> None:
    """No id (or an unusable one) on the POST response must not trigger a
    fallback GET - normalize_activity() already requires a usable id and its
    existing behavior for that case is left untouched by this fix."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42/activities" and request.method == "POST":
            # No "id" key at all - a GET to /api/v3/activities/... would be a
            # protocol error, so the handler intentionally has no route for it.
            return httpx.Response(
                201,
                json={"_type": "Activity::Comment", "version": 5, "comment": {"raw": "Ok."}, "_links": {}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_base_settings(enable_work_package_write=True), transport=httpx.MockTransport(handler))

    with pytest.raises(KeyError):
        await client.add_work_package_comment(work_package_id=42, comment="Ok.", confirm=True)

    await client.aclose()


@pytest.mark.asyncio
async def test_add_work_package_comment_skips_fallback_fetch_when_user_hidden() -> None:
    """A configured OPENPROJECT_HIDE_ACTIVITY_FIELDS=user must still hide user
    on the result, and the fallback fetch must not even be attempted - it
    would just be discarded, so it's wasted work."""
    fallback_get_calls = {"count": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42/activities" and request.method == "POST":
            return httpx.Response(
                201,
                json={"id": 82, "_type": "Activity::Comment", "version": 5, "comment": {"raw": "Ok."}, "_links": {}},
                request=request,
            )
        if request.url.path == "/api/v3/activities/82" and request.method == "GET":
            fallback_get_calls["count"] += 1
            return httpx.Response(
                200,
                json={"id": 82, "_links": {"user": {"title": "Jane Reviewer"}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(enable_work_package_write=True, hide_activity_fields=("user",))
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.add_work_package_comment(work_package_id=42, comment="Ok.", confirm=True)

    assert result.confirmed is True
    payload = _to_payload(result)
    assert "user" not in payload["result"]
    assert fallback_get_calls["count"] == 0

    await client.aclose()


@pytest.mark.asyncio
async def test_add_work_package_comment_hides_other_configured_activity_fields() -> None:
    """The _hidden_keys re-stamp fix (needed because dataclasses.replace() drops
    it) must generalize to any hidden activity field, not just `user` - this
    covers `version` (not user-writable, so it's a clean field to test the
    read-side hiding independently of `_ensure_field_writable`'s separate
    write-guard, which `comment` would also trigger)."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42/activities" and request.method == "POST":
            return httpx.Response(
                201,
                json={
                    "id": 83,
                    "_type": "Activity::Comment",
                    "version": 5,
                    "comment": {"raw": "Secret note."},
                    "_links": {"user": {"title": "Jane Reviewer"}},
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(enable_work_package_write=True, hide_activity_fields=("version",))
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.add_work_package_comment(work_package_id=42, comment="Secret note.", confirm=True)

    assert result.confirmed is True
    payload = _to_payload(result)
    assert "version" not in payload["result"]
    assert payload["result"]["user"] == "Jane Reviewer"

    await client.aclose()


@pytest.mark.asyncio
async def test_create_subtask_uses_parent_link_in_form_payload() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "subject": "Parent feature",
                    "_links": {
                        "project": {"title": "Demo", "href": "/api/v3/projects/1"},
                        "status": {"title": "New"},
                        "type": {"title": "Feature"},
                        "activities": {"href": "/api/v3/work_packages/42/activities"},
                        "relations": {"href": "/api/v3/work_packages/42/relations"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/projects/1" and request.method == "GET":
            # Unlike create_work_package, create_subtask only knows the parent's
            # numeric project id from its link (no full payload up front), so its
            # ProjectResolutionContext (OPM-205) starts empty -- _resolve_type_id's
            # project fetch below is a real, still-necessary first request. It
            # would only be skipped on a *second* resolution of the same project
            # within this same call (e.g. if version were also given here).
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 1, "identifier": "demo", "name": "Demo"},
                request=request,
            )
        if request.url.path == "/api/v3/projects/1/types":
            return httpx.Response(
                200,
                json={"_embedded": {"elements": [{"id": 8, "name": "Task"}]}},
                request=request,
            )
        if request.url.path == "/api/v3/projects/1/work_packages/form" and request.method == "POST":
            body = json.loads(request.content)
            assert body["subject"] == "Implement API client"
            assert body["_links"]["type"]["href"] == "/api/v3/types/8"
            assert body["_links"]["parent"]["href"] == "/api/v3/work_packages/42"
            return httpx.Response(
                200,
                json={"_type": "Form", "_embedded": {"payload": body, "validationErrors": {}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings(
        read_projects=("*",),
        write_projects=("*",),
        base_url="https://op.example.com",
        api_token="token",
        timeout=12,
        verify_ssl=True,
        default_page_size=1,
        max_page_size=1,
        max_results=10,
        log_level="WARNING",
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.create_subtask(
        parent_work_package_id=42,
        type="Task",
        subject="Implement API client",
        confirm=False,
    )

    assert result.ready is True
    assert result.requires_confirmation is True
    assert result.payload["_links"]["parent"]["href"] == "/api/v3/work_packages/42"

    await client.aclose()


@pytest.mark.asyncio
async def test_create_work_package_resolves_schema_backed_fields_and_custom_fields() -> None:
    form_calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal form_calls
        if request.url.path == "/api/v3/projects/demo":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 1, "name": "Demo", "identifier": "demo"},
                request=request,
            )
        if request.url.path == "/api/v3/projects/1" and request.method == "GET":
            # Not actually hit anymore for this numeric project ref: create_work_package's
            # ProjectResolutionContext (OPM-205) is seeded from the initial project
            # resolution, so _resolve_type_id's own project fetch is served from that
            # cache instead of re-requesting it. Kept in the handler in case a future
            # change reintroduces the extra fetch.
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 1, "name": "Demo", "identifier": "demo"},
                request=request,
            )
        if request.url.path == "/api/v3/projects/1/types":
            return httpx.Response(
                200,
                json={"_embedded": {"elements": [{"id": 7, "name": "Feature"}]}},
                request=request,
            )
        if request.url.path == "/api/v3/projects/1/work_packages/form":
            form_calls += 1
            body = json.loads(request.content)
            if form_calls == 1:
                assert body["_links"]["type"]["href"] == "/api/v3/types/7"
                return httpx.Response(
                    200,
                    json={
                        "_type": "Form",
                        "_embedded": {
                            "schema": {
                                "priority": {
                                    "name": "Priority",
                                    "type": "Priority",
                                    "required": True,
                                    "writable": True,
                                    "hasDefault": True,
                                    "location": "_links",
                                    "_embedded": {
                                        "allowedValues": [
                                            {
                                                "id": 9,
                                                "name": "High",
                                                "_links": {"self": {"href": "/api/v3/priorities/9", "title": "High"}},
                                            }
                                        ]
                                    },
                                },
                                "projectPhase": {
                                    "name": "Project phase",
                                    "type": "ProjectPhase",
                                    "required": False,
                                    "writable": True,
                                    "hasDefault": False,
                                    "location": "_links",
                                    "_embedded": {
                                        "allowedValues": [
                                            {
                                                "id": 5,
                                                "name": "Executing",
                                                "_links": {
                                                    "self": {"href": "/api/v3/project_phases/5", "title": "Executing"}
                                                },
                                            }
                                        ]
                                    },
                                },
                                "customField10": {
                                    "name": "Story points",
                                    "type": "Integer",
                                    "required": False,
                                    "writable": True,
                                    "hasDefault": False,
                                },
                                "customField11": {
                                    "name": "Platform",
                                    "type": "List",
                                    "required": False,
                                    "writable": True,
                                    "hasDefault": False,
                                    "location": "_links",
                                    "_embedded": {
                                        "allowedValues": [
                                            {
                                                "id": 20,
                                                "name": "iOS",
                                                "_links": {
                                                    "self": {"href": "/api/v3/custom_options/20", "title": "iOS"}
                                                },
                                            }
                                        ]
                                    },
                                },
                            }
                        },
                    },
                    request=request,
                )
            assert body["_links"]["priority"]["href"] == "/api/v3/priorities/9"
            assert body["_links"]["projectPhase"]["href"] == "/api/v3/project_phases/5"
            assert body["customField10"] == 8
            assert body["_links"]["customField11"]["href"] == "/api/v3/custom_options/20"
            return httpx.Response(
                200,
                json={"_type": "Form", "_embedded": {"payload": body, "validationErrors": {}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))
    result = await client.create_work_package(
        project="demo",
        type="Feature",
        subject="Schema-backed create",
        priority="High",
        project_phase="Executing",
        custom_fields={"Story points": 8, "Platform": "iOS"},
        confirm=False,
    )

    assert result.ready is True
    assert result.requires_confirmation is True
    assert result.payload["_links"]["projectPhase"]["href"] == "/api/v3/project_phases/5"
    assert result.payload["customField10"] == 8
    assert result.payload["_links"]["customField11"]["href"] == "/api/v3/custom_options/20"

    await client.aclose()


@pytest.mark.asyncio
async def test_create_work_package_resolves_project_only_once_for_type_and_version_together() -> None:
    # OPM-205: before ProjectResolutionContext, create_work_package's own
    # project resolution, then _resolve_type_id's, then _resolve_version_id's
    # each independently re-fetched (and re-allowlist-checked) the same
    # already-resolved project. With both type and version given, this proves
    # exactly one GET for the project.
    project_get_calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal project_get_calls
        if request.url.path == "/api/v3/projects/demo":
            project_get_calls += 1
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 1, "name": "Demo", "identifier": "demo"},
                request=request,
            )
        if request.url.path == "/api/v3/projects/1" and request.method == "GET":
            project_get_calls += 1
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 1, "name": "Demo", "identifier": "demo"},
                request=request,
            )
        if request.url.path == "/api/v3/projects/1/types":
            return httpx.Response(200, json={"_embedded": {"elements": [{"id": 7, "name": "Task"}]}}, request=request)
        if request.url.path == "/api/v3/projects/1/versions":
            return httpx.Response(
                200,
                json={"total": 1, "_embedded": {"elements": [{"id": 3, "name": "v1.0"}]}},
                request=request,
            )
        if request.url.path == "/api/v3/projects/1/work_packages/form":
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={"_type": "Form", "_embedded": {"payload": body, "validationErrors": {}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))
    result = await client.create_work_package(
        project="demo",
        type="Task",
        version="v1.0",
        subject="Only one project fetch",
        confirm=False,
    )

    assert result.ready is True
    assert project_get_calls == 1

    await client.aclose()


@pytest.mark.asyncio
async def test_bulk_create_work_packages_preview_mode() -> None:
    call_count = {"form": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in {"/api/v3/projects/demo", "/api/v3/projects/1"}:
            return _make_project_response(request)
        if request.url.path == "/api/v3/projects/1/types":
            return httpx.Response(200, json={"_embedded": {"elements": [{"id": 7, "name": "Task"}]}}, request=request)
        if request.url.path == "/api/v3/projects/1/versions":
            return httpx.Response(200, json={"total": 0, "_embedded": {"elements": []}}, request=request)
        if request.url.path == "/api/v3/projects/1/work_packages/form":
            call_count["form"] += 1
            body = json.loads(request.content)
            return _make_wp_form_response(request, body)
        raise AssertionError(f"Unexpected: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))
    result = await client.bulk_create_work_packages(
        items=[
            {"project": "demo", "type": "Task", "subject": "WP 1"},
            {"project": "demo", "type": "Task", "subject": "WP 2"},
        ],
        confirm=False,
    )

    assert result.action == "bulk_create"
    assert result.confirmed is False
    assert result.requires_confirmation is True
    assert result.total == 2
    assert result.succeeded == 2
    assert result.failed == 0
    assert call_count["form"] == 2
    assert all(r.success for r in result.items)
    await client.aclose()


@pytest.mark.asyncio
async def test_bulk_create_work_packages_preview_forwards_duration_fields() -> None:
    # OPM-215: bulk_create_work_packages used to silently drop estimated_time/
    # remaining_time/duration instead of forwarding them to create_work_package.
    posted_bodies: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in {"/api/v3/projects/demo", "/api/v3/projects/1"}:
            return _make_project_response(request)
        if request.url.path == "/api/v3/projects/1/types":
            return httpx.Response(200, json={"_embedded": {"elements": [{"id": 7, "name": "Task"}]}}, request=request)
        if request.url.path == "/api/v3/projects/1/versions":
            return httpx.Response(200, json={"total": 0, "_embedded": {"elements": []}}, request=request)
        if request.url.path == "/api/v3/projects/1/work_packages/form":
            body = json.loads(request.content)
            posted_bodies.append(body)
            return _make_wp_form_response(request, body)
        raise AssertionError(f"Unexpected: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))
    result = await client.bulk_create_work_packages(
        items=[
            {
                "project": "demo",
                "type": "Task",
                "subject": "WP 1",
                "estimated_time": "PT8H",
                "remaining_time": "PT4H",
                "duration": "P2D",
            },
        ],
        confirm=False,
    )

    assert result.succeeded == 1
    assert posted_bodies[0]["estimatedTime"] == "PT8H"
    assert posted_bodies[0]["remainingTime"] == "PT4H"
    assert posted_bodies[0]["duration"] == "P2D"
    await client.aclose()


@pytest.mark.asyncio
async def test_bulk_create_work_packages_confirm_forwards_duration_fields() -> None:
    # OPM-215 follow-up: the preview test above only exercises confirm=False (the
    # form-probe POST). Assert the same fields also reach the actual mutating
    # create POST when confirm=True, and that the committed result reflects them
    # (not just the outgoing request).
    posted_create_bodies: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in {"/api/v3/projects/demo", "/api/v3/projects/1"}:
            return _make_project_response(request)
        if request.url.path == "/api/v3/projects/1/types":
            return httpx.Response(200, json={"_embedded": {"elements": [{"id": 7, "name": "Task"}]}}, request=request)
        if request.url.path == "/api/v3/projects/1/versions":
            return httpx.Response(200, json={"total": 0, "_embedded": {"elements": []}}, request=request)
        if request.url.path == "/api/v3/projects/1/work_packages/form":
            body = json.loads(request.content)
            return _make_wp_form_response(request, body)
        if request.url.path == "/api/v3/work_packages" and request.method == "POST":
            body = json.loads(request.content)
            posted_create_bodies.append(body)
            return httpx.Response(
                201,
                json={
                    "id": 99,
                    "subject": body.get("subject", ""),
                    "lockVersion": 1,
                    "estimatedTime": body.get("estimatedTime"),
                    "remainingTime": body.get("remainingTime"),
                    "duration": body.get("duration"),
                    "_links": {
                        "project": {"title": "Demo", "href": "/api/v3/projects/1"},
                        "status": {"title": "New"},
                        "type": {"title": "Task"},
                        "activities": {"href": "/api/v3/work_packages/99/activities"},
                        "relations": {"href": "/api/v3/work_packages/99/relations"},
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected: {request.method} {request.url}")

    settings = Settings(
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
        enable_work_package_write=True,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))
    result = await client.bulk_create_work_packages(
        items=[
            {
                "project": "demo",
                "type": "Task",
                "subject": "WP 1",
                "estimated_time": "PT8H",
                "remaining_time": "PT4H",
                "duration": "P2D",
            },
        ],
        confirm=True,
    )

    assert result.succeeded == 1
    assert posted_create_bodies[0]["estimatedTime"] == "PT8H"
    assert posted_create_bodies[0]["remainingTime"] == "PT4H"
    assert posted_create_bodies[0]["duration"] == "P2D"
    committed = result.items[0].result
    assert committed is not None and committed.result is not None
    assert committed.result.estimated_time == "PT8H"
    assert committed.result.remaining_time == "PT4H"
    assert committed.result.duration == "P2D"
    await client.aclose()


@pytest.mark.asyncio
async def test_bulk_create_work_packages_executes_with_confirm() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in {"/api/v3/projects/demo", "/api/v3/projects/1"}:
            return _make_project_response(request)
        if request.url.path == "/api/v3/projects/1/types":
            return httpx.Response(200, json={"_embedded": {"elements": [{"id": 7, "name": "Task"}]}}, request=request)
        if request.url.path == "/api/v3/projects/1/versions":
            return httpx.Response(200, json={"total": 0, "_embedded": {"elements": []}}, request=request)
        if request.url.path == "/api/v3/projects/1/work_packages/form":
            body = json.loads(request.content)
            return _make_wp_form_response(request, body)
        if request.url.path == "/api/v3/work_packages" and request.method == "POST":
            body = json.loads(request.content)
            return httpx.Response(
                201,
                json={
                    "id": 99,
                    "subject": body.get("subject", ""),
                    "lockVersion": 1,
                    "_links": {
                        "project": {"title": "Demo", "href": "/api/v3/projects/1"},
                        "status": {"title": "New"},
                        "type": {"title": "Task"},
                        "activities": {"href": "/api/v3/work_packages/99/activities"},
                        "relations": {"href": "/api/v3/work_packages/99/relations"},
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected: {request.method} {request.url}")

    settings = make_settings()
    settings = Settings(
        read_projects=("*",),
        write_projects=("*",),
        base_url=settings.base_url,
        api_token=settings.api_token,
        enable_work_package_write=True,
        timeout=settings.timeout,
        verify_ssl=settings.verify_ssl,
        default_page_size=settings.default_page_size,
        max_page_size=settings.max_page_size,
        max_results=settings.max_results,
        log_level=settings.log_level,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))
    result = await client.bulk_create_work_packages(
        items=[
            {"project": "demo", "type": "Task", "subject": "WP A"},
            {"project": "demo", "type": "Task", "subject": "WP B"},
        ],
        confirm=True,
    )

    assert result.confirmed is True
    assert result.succeeded == 2
    assert result.failed == 0
    await client.aclose()


@pytest.mark.asyncio
async def test_bulk_create_work_packages_partial_failure() -> None:
    call_count = {"form": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in {"/api/v3/projects/demo", "/api/v3/projects/1"}:
            return _make_project_response(request)
        if request.url.path == "/api/v3/projects/1/types":
            return httpx.Response(200, json={"_embedded": {"elements": [{"id": 7, "name": "Task"}]}}, request=request)
        if request.url.path == "/api/v3/projects/1/versions":
            return httpx.Response(200, json={"total": 0, "_embedded": {"elements": []}}, request=request)
        if request.url.path == "/api/v3/projects/1/work_packages/form":
            call_count["form"] += 1
            body = json.loads(request.content)
            if body.get("subject") == "Bad WP":
                return httpx.Response(
                    200,
                    json={
                        "_type": "Form",
                        "_embedded": {"payload": body, "validationErrors": {"subject": {"message": "too short"}}},
                    },
                    request=request,
                )
            return _make_wp_form_response(request, body)
        raise AssertionError(f"Unexpected: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))
    result = await client.bulk_create_work_packages(
        items=[
            {"project": "demo", "type": "Task", "subject": "Good WP"},
            {"project": "demo", "type": "Task", "subject": "Bad WP"},
        ],
        confirm=False,
    )

    assert result.total == 2
    assert result.succeeded == 1
    assert result.failed == 1
    assert result.items[0].success is True
    assert result.items[1].success is False
    assert result.items[1].error is not None
    await client.aclose()


@pytest.mark.asyncio
async def test_bulk_create_work_packages_reraises_cancelled_error_with_diagnostic_log(caplog) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in {"/api/v3/projects/demo", "/api/v3/projects/1"}:
            return _make_project_response(request)
        if request.url.path == "/api/v3/projects/1/types":
            return httpx.Response(200, json={"_embedded": {"elements": [{"id": 7, "name": "Task"}]}}, request=request)
        if request.url.path == "/api/v3/projects/1/versions":
            return httpx.Response(200, json={"total": 0, "_embedded": {"elements": []}}, request=request)
        if request.url.path == "/api/v3/projects/1/work_packages/form":
            body = json.loads(request.content)
            if body.get("subject") == "Cancel me":
                raise asyncio.CancelledError()
            return _make_wp_form_response(request, body)
        raise AssertionError(f"Unexpected: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))

    with caplog.at_level(logging.WARNING, logger="openproject_ce_mcp.client"):
        with pytest.raises(asyncio.CancelledError):
            await client.bulk_create_work_packages(
                items=[
                    {"project": "demo", "type": "Task", "subject": "Good WP"},
                    {"project": "demo", "type": "Task", "subject": "Cancel me"},
                    {"project": "demo", "type": "Task", "subject": "Never attempted"},
                ],
                confirm=False,
            )

    log_message = next(r.message for r in caplog.records if "bulk_create_work_packages cancelled" in r.message)
    assert "1/3 item(s) completed before cancellation (indices 0-0)" in log_message
    assert "item at index 1 has an unknown validation outcome" in log_message
    assert "confirm=false means no item in this call could have been written to OpenProject regardless" in log_message
    assert "1 item(s) were not yet attempted" in log_message

    await client.aclose()


@pytest.mark.asyncio
async def test_bulk_create_work_packages_cancelled_with_confirm_true_does_not_claim_preview_wording(
    caplog,
) -> None:
    # With confirm=true a write may genuinely have reached OpenProject before
    # cancellation, so the log must not use the confirm=false "nothing could
    # have been written" wording here.
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in {"/api/v3/projects/demo", "/api/v3/projects/1"}:
            return _make_project_response(request)
        if request.url.path == "/api/v3/projects/1/types":
            return httpx.Response(200, json={"_embedded": {"elements": [{"id": 7, "name": "Task"}]}}, request=request)
        if request.url.path == "/api/v3/projects/1/versions":
            return httpx.Response(200, json={"total": 0, "_embedded": {"elements": []}}, request=request)
        if request.url.path == "/api/v3/projects/1/work_packages/form":
            body = json.loads(request.content)
            if body.get("subject") == "Cancel me":
                raise asyncio.CancelledError()
            return _make_wp_form_response(request, body)
        raise AssertionError(f"Unexpected: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))

    with caplog.at_level(logging.WARNING, logger="openproject_ce_mcp.client"):
        with pytest.raises(asyncio.CancelledError):
            await client.bulk_create_work_packages(
                items=[
                    {"project": "demo", "type": "Task", "subject": "Cancel me"},
                    {"project": "demo", "type": "Task", "subject": "Never attempted"},
                ],
                confirm=True,
            )

    log_message = next(r.message for r in caplog.records if "bulk_create_work_packages cancelled" in r.message)
    assert "item at index 0 has an unknown outcome" in log_message
    assert "not necessarily written to OpenProject" in log_message
    assert "confirm=false" not in log_message

    await client.aclose()


@pytest.mark.asyncio
async def test_bulk_update_work_packages_preview_mode() -> None:
    captured: dict[str, dict] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/10" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 10,
                    "subject": "Old 10",
                    "lockVersion": 1,
                    "_links": {
                        "project": {"title": "Demo", "href": "/api/v3/projects/1"},
                        "status": {"title": "New"},
                        "type": {"title": "Task"},
                        "activities": {"href": "/api/v3/work_packages/10/activities"},
                        "relations": {"href": "/api/v3/work_packages/10/relations"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/20" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 20,
                    "subject": "Old 20",
                    "lockVersion": 2,
                    "_links": {
                        "project": {"title": "Demo", "href": "/api/v3/projects/1"},
                        "status": {"title": "New"},
                        "type": {"title": "Task"},
                        "activities": {"href": "/api/v3/work_packages/20/activities"},
                        "relations": {"href": "/api/v3/work_packages/20/relations"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/10/form":
            body = json.loads(request.content)
            captured["body"] = body
            return _make_wp_form_response(request, body)
        if request.url.path == "/api/v3/work_packages/20/form":
            body = json.loads(request.content)
            return _make_wp_form_response(request, body)
        if request.url.path == "/api/v3/statuses":
            return httpx.Response(
                200, json={"_embedded": {"elements": [{"id": 5, "name": "In progress"}]}}, request=request
            )
        if request.url.path == "/api/v3/statuses/5":
            return httpx.Response(200, json={"id": 5, "name": "In progress", "isClosed": False}, request=request)
        raise AssertionError(f"Unexpected: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))
    result = await client.bulk_update_work_packages(
        items=[
            {
                "work_package_id": 10,
                "subject": "New 10",
                "estimated_time": "PT8H",
                "remaining_time": "PT3H",
                "duration": "PT10H",
            },
            {"work_package_id": 20, "status": "In progress"},
        ],
        confirm=False,
    )

    assert result.action == "bulk_update"
    assert result.confirmed is False
    assert result.requires_confirmation is True
    assert result.total == 2
    assert result.succeeded == 2
    assert result.failed == 0
    assert captured["body"]["estimatedTime"] == "PT8H"
    assert captured["body"]["remainingTime"] == "PT3H"
    assert captured["body"]["duration"] == "PT10H"
    await client.aclose()


@pytest.mark.asyncio
async def test_bulk_update_work_packages_continues_after_partial_failure() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/10" and request.method == "GET":
            return httpx.Response(404, json={"_type": "Error", "message": "Not found"}, request=request)
        if request.url.path == "/api/v3/work_packages/20" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 20,
                    "subject": "Old 20",
                    "lockVersion": 1,
                    "_links": {
                        "project": {"title": "Demo", "href": "/api/v3/projects/1"},
                        "status": {"title": "New"},
                        "type": {"title": "Task"},
                        "activities": {"href": "/api/v3/work_packages/20/activities"},
                        "relations": {"href": "/api/v3/work_packages/20/relations"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/20/form":
            body = json.loads(request.content)
            return _make_wp_form_response(request, body)
        raise AssertionError(f"Unexpected: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))
    result = await client.bulk_update_work_packages(
        items=[
            {"work_package_id": 10, "subject": "Will fail"},
            {"work_package_id": 20, "subject": "Should succeed"},
        ],
        confirm=False,
    )

    assert result.total == 2
    assert result.succeeded == 1
    assert result.failed == 1
    assert result.items[0].success is False
    assert result.items[0].error is not None
    assert result.items[1].success is True
    await client.aclose()


@pytest.mark.asyncio
async def test_bulk_update_work_packages_reraises_cancelled_error_with_diagnostic_log(caplog) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/10" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 10,
                    "subject": "Old 10",
                    "lockVersion": 1,
                    "_links": {
                        "project": {"title": "Demo", "href": "/api/v3/projects/1"},
                        "status": {"title": "New"},
                        "type": {"title": "Task"},
                        "activities": {"href": "/api/v3/work_packages/10/activities"},
                        "relations": {"href": "/api/v3/work_packages/10/relations"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/10/form":
            body = json.loads(request.content)
            return _make_wp_form_response(request, body)
        if request.url.path == "/api/v3/work_packages/20" and request.method == "GET":
            raise asyncio.CancelledError()
        raise AssertionError(f"Unexpected: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))

    with caplog.at_level(logging.WARNING, logger="openproject_ce_mcp.client"):
        with pytest.raises(asyncio.CancelledError):
            await client.bulk_update_work_packages(
                items=[
                    {"work_package_id": 10, "subject": "Should succeed"},
                    {"work_package_id": 20, "subject": "Cancel me"},
                    {"work_package_id": 30, "subject": "Never attempted"},
                ],
                confirm=False,
            )

    log_message = next(r.message for r in caplog.records if "bulk_update_work_packages cancelled" in r.message)
    assert "1/3 item(s) completed before cancellation (indices 0-0)" in log_message
    assert "item at index 1 has an unknown validation outcome" in log_message
    assert "confirm=false means no item in this call could have been written to OpenProject regardless" in log_message
    assert "1 item(s) were not yet attempted" in log_message

    await client.aclose()


@pytest.mark.asyncio
async def test_toggle_activity_emoji_reaction_patches_and_normalizes() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/activities/1988" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 1988, "_links": {"workPackage": {"href": "/api/v3/work_packages/42"}}},
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
                request=request,
            )
        if request.url.path == "/api/v3/activities/1988/emoji_reactions" and request.method == "PATCH":
            assert json.loads(request.content) == {"reaction": "heart"}
            return httpx.Response(
                200,
                json={
                    "_type": "Collection",
                    "_embedded": {
                        "elements": [
                            {
                                "_type": "EmojiReaction",
                                "reaction": "heart",
                                "emoji": "❤️",
                                "reactionsCount": 2,
                                "_links": {"reactingUsers": [{"title": "Alice"}, {"title": "Bob"}]},
                            }
                        ]
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_write_enabled_settings(), transport=httpx.MockTransport(handler))

    result = await client.toggle_activity_emoji_reaction(1988, "heart", confirm=True)

    assert result.confirmed is True
    assert result.result is not None
    assert result.result.count == 1
    assert result.result.results[0].reaction == "heart"
    assert result.result.results[0].emoji == "❤️"
    assert result.result.results[0].count == 2
    assert result.result.results[0].users == ["Alice", "Bob"]

    await client.aclose()


@pytest.mark.asyncio
async def test_toggle_activity_emoji_reaction_previews_without_confirm() -> None:
    """Without confirm=true, the allowlist check still runs but no PATCH is sent."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/activities/1988" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 1988, "_links": {"workPackage": {"href": "/api/v3/work_packages/42"}}},
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
                request=request,
            )
        if request.method == "PATCH":
            raise AssertionError("PATCH must not be issued without confirm=true")
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_write_enabled_settings(), transport=httpx.MockTransport(handler))

    result = await client.toggle_activity_emoji_reaction(1988, "heart")

    assert result.confirmed is False
    assert result.requires_confirmation is True
    assert result.ready is True
    assert result.result is None

    await client.aclose()


@pytest.mark.asyncio
async def test_toggle_activity_emoji_reaction_rejects_invalid_reaction() -> None:
    client = OpenProjectClient(
        _write_enabled_settings(),
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}, request=r)),
    )

    with pytest.raises(InvalidInputError, match="reaction must be one of"):
        await client.toggle_activity_emoji_reaction(1988, "banana")

    await client.aclose()


@pytest.mark.asyncio
async def test_toggle_activity_emoji_reaction_fails_closed_without_work_package_link() -> None:
    """An activity with no workPackage link is refused; no PATCH is issued."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/activities/1988" and request.method == "GET":
            return httpx.Response(200, json={"id": 1988, "_links": {}}, request=request)
        if request.method == "PATCH":
            raise AssertionError("PATCH must not be issued when the activity has no work package link")
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_write_enabled_settings(), transport=httpx.MockTransport(handler))

    with pytest.raises(OpenProjectServerError, match="missing a work package link"):
        await client.toggle_activity_emoji_reaction(1988, "heart")

    await client.aclose()


async def test_update_work_package_sets_percentage_done_explicitly() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "lockVersion": 1,
                    "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}},
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42/form":
            body = json.loads(request.content)
            assert body["percentageDone"] == 40
            return _make_wp_form_response(request, body)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_base_settings(), transport=httpx.MockTransport(handler))
    result = await client.update_work_package(work_package_id=42, percentage_done=40, confirm=False)
    assert result.ready
    await client.aclose()


async def test_update_work_package_autofills_progress_on_close_without_estimate() -> None:
    """OpenProject's own validation requires remainingTime to be null/absent
    (not "PT0H") when the work package has no estimatedTime -- live-verified
    against real OpenProject: submitting "PT0H" here gets rejected with
    "must stay empty". The GET response below deliberately has no
    estimatedTime, matching that case."""
    form_calls = {"count": 0}
    status_list_calls = {"count": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "lockVersion": 1,
                    "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}},
                },
                request=request,
            )
        if request.url.path == "/api/v3/statuses":
            status_list_calls["count"] += 1
            return httpx.Response(200, json={"_embedded": {"elements": [{"id": 9, "name": "Closed"}]}}, request=request)
        if request.url.path == "/api/v3/statuses/9":
            return httpx.Response(200, json={"id": 9, "name": "Closed", "isClosed": True}, request=request)
        if request.url.path == "/api/v3/work_packages/42/form":
            form_calls["count"] += 1
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "_type": "Form",
                    "_embedded": {
                        "payload": body,
                        "validationErrors": {},
                        "schema": {
                            "percentageDone": {"writable": True},
                            "remainingTime": {"writable": True},
                        },
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_base_settings(), transport=httpx.MockTransport(handler))
    result = await client.update_work_package(work_package_id=42, status="Closed", confirm=False)
    assert result.ready
    assert result.payload["percentageDone"] == 100
    assert result.payload["remainingTime"] is None
    # First form POST (without the auto-filled fields) + second POST once the schema
    # confirmed writability — never more than that.
    assert form_calls["count"] == 2
    # Regression guard: the closed-status check reuses the status id _build_write_payload
    # already resolved for the status link, instead of resolving "Closed" -> id a second
    # time via a redundant GET /api/v3/statuses.
    assert status_list_calls["count"] == 1
    await client.aclose()


async def test_update_work_package_autofills_progress_on_close_with_existing_estimate() -> None:
    """Opposite of the no-estimate case above: when the work package already
    has an estimatedTime (from the pre-write GET, not this call's own
    params), remainingTime must autofill to "PT0H", not null -- live-verified:
    submitting null here gets rejected with "must be 0h"."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "lockVersion": 1,
                    "estimatedTime": "PT8H",
                    "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}},
                },
                request=request,
            )
        if request.url.path == "/api/v3/statuses":
            return httpx.Response(200, json={"_embedded": {"elements": [{"id": 9, "name": "Closed"}]}}, request=request)
        if request.url.path == "/api/v3/statuses/9":
            return httpx.Response(200, json={"id": 9, "name": "Closed", "isClosed": True}, request=request)
        if request.url.path == "/api/v3/work_packages/42/form":
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "_type": "Form",
                    "_embedded": {
                        "payload": body,
                        "validationErrors": {},
                        "schema": {
                            "percentageDone": {"writable": True},
                            "remainingTime": {"writable": True},
                        },
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_base_settings(), transport=httpx.MockTransport(handler))
    result = await client.update_work_package(work_package_id=42, status="Closed", confirm=False)
    assert result.ready
    assert result.payload["percentageDone"] == 100
    assert result.payload["remainingTime"] == "PT0H"
    await client.aclose()


async def test_update_work_package_autofills_progress_using_this_calls_own_new_estimate() -> None:
    """The "effective estimate" check must prefer THIS call's own estimated_time
    param over the pre-write GET's value -- a caller setting an estimate for
    the first time while also closing the status should autofill "PT0H", not
    null, even though the GET response has no estimatedTime yet."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "lockVersion": 1,
                    "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}},
                },
                request=request,
            )
        if request.url.path == "/api/v3/statuses":
            return httpx.Response(200, json={"_embedded": {"elements": [{"id": 9, "name": "Closed"}]}}, request=request)
        if request.url.path == "/api/v3/statuses/9":
            return httpx.Response(200, json={"id": 9, "name": "Closed", "isClosed": True}, request=request)
        if request.url.path == "/api/v3/work_packages/42/form":
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "_type": "Form",
                    "_embedded": {
                        "payload": body,
                        "validationErrors": {},
                        "schema": {
                            "percentageDone": {"writable": True},
                            "remainingTime": {"writable": True},
                        },
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_base_settings(), transport=httpx.MockTransport(handler))
    result = await client.update_work_package(work_package_id=42, status="Closed", estimated_time="PT4H", confirm=False)
    assert result.ready
    assert result.payload["percentageDone"] == 100
    assert result.payload["remainingTime"] == "PT0H"
    await client.aclose()


async def test_update_work_package_skips_autofill_when_schema_not_writable() -> None:
    """Status-based progress mode (OpenProject derives these itself) — must not error, must not add fields."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "lockVersion": 1,
                    "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}},
                },
                request=request,
            )
        if request.url.path == "/api/v3/statuses":
            return httpx.Response(200, json={"_embedded": {"elements": [{"id": 9, "name": "Closed"}]}}, request=request)
        if request.url.path == "/api/v3/statuses/9":
            return httpx.Response(200, json={"id": 9, "name": "Closed", "isClosed": True}, request=request)
        if request.url.path == "/api/v3/work_packages/42/form":
            body = json.loads(request.content)
            assert "percentageDone" not in body
            assert "remainingTime" not in body
            return httpx.Response(
                200,
                json={
                    "_type": "Form",
                    "_embedded": {
                        "payload": body,
                        "validationErrors": {},
                        "schema": {
                            "percentageDone": {"writable": False},
                            "remainingTime": {"writable": False},
                        },
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_base_settings(), transport=httpx.MockTransport(handler))
    result = await client.update_work_package(work_package_id=42, status="Closed", confirm=False)
    assert result.ready
    await client.aclose()


async def test_update_work_package_preserves_explicit_values_on_close() -> None:
    """Explicit percentage_done/remaining_time always win, even when closing."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "lockVersion": 1,
                    "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}},
                },
                request=request,
            )
        if request.url.path == "/api/v3/statuses":
            return httpx.Response(200, json={"_embedded": {"elements": [{"id": 9, "name": "Closed"}]}}, request=request)
        if request.url.path == "/api/v3/statuses/9":
            return httpx.Response(200, json={"id": 9, "name": "Closed", "isClosed": True}, request=request)
        if request.url.path == "/api/v3/work_packages/42/form":
            body = json.loads(request.content)
            assert body["percentageDone"] == 50
            assert body["remainingTime"] == "PT5H"
            return _make_wp_form_response(request, body)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_base_settings(), transport=httpx.MockTransport(handler))
    result = await client.update_work_package(
        work_package_id=42,
        status="Closed",
        percentage_done=50,
        remaining_time="PT5H",
        confirm=False,
    )
    assert result.ready
    # Only one form POST: nothing was auto-filled since both fields were explicit.
    await client.aclose()


async def test_update_work_package_clears_duration_fields_via_clear_sentinel() -> None:
    """CLEAR on estimated_time/remaining_time/duration must send an explicit null,
    not be dropped from the payload (which would leave the field unchanged) or
    forward the sentinel object itself."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "lockVersion": 1,
                    "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}},
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42/form":
            body = json.loads(request.content)
            assert body["estimatedTime"] is None
            assert body["remainingTime"] is None
            assert body["duration"] is None
            return _make_wp_form_response(request, body)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_base_settings(), transport=httpx.MockTransport(handler))
    result = await client.update_work_package(
        work_package_id=42,
        estimated_time=CLEAR,
        remaining_time=CLEAR,
        duration=CLEAR,
        confirm=False,
    )
    assert result.ready
    await client.aclose()


async def test_update_work_package_close_succeeds_with_work_package_read_disabled() -> None:
    """Closing must not route the internal status lookup through get_status()'s read gate."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "lockVersion": 1,
                    "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}},
                },
                request=request,
            )
        if request.url.path == "/api/v3/statuses":
            return httpx.Response(200, json={"_embedded": {"elements": [{"id": 9, "name": "Closed"}]}}, request=request)
        if request.url.path == "/api/v3/statuses/9":
            return httpx.Response(200, json={"id": 9, "name": "Closed", "isClosed": True}, request=request)
        if request.url.path == "/api/v3/work_packages/42/form":
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "_type": "Form",
                    "_embedded": {
                        "payload": body,
                        "validationErrors": {},
                        "schema": {
                            "percentageDone": {"writable": True},
                            "remainingTime": {"writable": True},
                        },
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(enable_work_package_read=False)
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))
    result = await client.update_work_package(work_package_id=42, status="Closed", confirm=False)
    assert result.ready
    assert result.payload["percentageDone"] == 100
    await client.aclose()

    await client.aclose()
