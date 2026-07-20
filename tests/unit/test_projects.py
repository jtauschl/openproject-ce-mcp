from __future__ import annotations

import json
import os

import httpx
import pytest
from _client_test_helpers import _base_settings, make_settings

from openproject_ce_mcp.client import (
    AuthenticationError,
    NotFoundError,
    OpenProjectClient,
    PermissionDeniedError,
)
from openproject_ce_mcp.config import Settings


@pytest.mark.asyncio
async def test_client_maps_401_to_authentication_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Unauthorized"}, request=request)

    transport = httpx.MockTransport(handler)
    client = OpenProjectClient(make_settings(), transport=transport)

    with pytest.raises(AuthenticationError):
        await client.get_project("demo")

    await client.aclose()


@pytest.mark.asyncio
async def test_get_project_work_package_context_returns_schema_and_metadata() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in {"/api/v3/projects/demo", "/api/v3/projects/1"}:
            return httpx.Response(
                200,
                json={
                    "_type": "Project",
                    "id": 1,
                    "name": "Demo",
                    "identifier": "demo",
                    "_links": {"versions": {"href": "/api/v3/projects/1/versions"}},
                },
                request=request,
            )
        if request.url.path == "/api/v3/projects/1/types":
            return httpx.Response(
                200,
                json={"_embedded": {"elements": [{"id": 7, "name": "Feature"}, {"id": 8, "name": "Task"}]}},
                request=request,
            )
        if request.url.path == "/api/v3/statuses":
            return httpx.Response(
                200,
                json={"_embedded": {"elements": [{"id": 1, "name": "New"}]}},
                request=request,
            )
        if request.url.path == "/api/v3/priorities":
            return httpx.Response(
                200,
                json={"_embedded": {"elements": [{"id": 9, "name": "High"}]}},
                request=request,
            )
        if request.url.path == "/api/v3/projects/1/categories":
            return httpx.Response(
                200,
                json={"_embedded": {"elements": [{"id": 3, "name": "Backend"}]}},
                request=request,
            )
        if request.url.path == "/api/v3/projects/1/versions":
            return httpx.Response(
                200,
                json={"total": 1, "_embedded": {"elements": [{"id": 11, "name": "Q2", "_links": {}}]}},
                request=request,
            )
        if request.url.path == "/api/v3/projects/1/work_packages/form":
            return httpx.Response(
                200,
                json={
                    "_type": "Form",
                    "_embedded": {
                        "schema": {
                            "status": {
                                "name": "Status",
                                "type": "Status",
                                "required": True,
                                "writable": True,
                                "hasDefault": True,
                                "location": "_links",
                                "_embedded": {
                                    "allowedValues": [
                                        {
                                            "id": 1,
                                            "name": "New",
                                            "_links": {"self": {"href": "/api/v3/statuses/1", "title": "New"}},
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
                        }
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
    result = await client.get_project_work_package_context(project="demo", type="Feature")

    assert result.project_id == 1
    assert result.selected_type_name == "Feature"
    assert result.available_priorities[0].title == "High"
    assert result.available_categories[0].title == "Backend"
    assert result.available_project_phases[0].title == "Executing"
    assert result.custom_fields[0].key == "customField10"
    assert result.custom_fields[0].name == "Story points"

    # OPM-1458: status/projectPhase's allowed_values are hoisted into
    # available_statuses/available_project_phases above — fields[] must not
    # also carry the same enumeration a second time.
    status_field = next(f for f in result.fields if f.key == "status")
    project_phase_field = next(f for f in result.fields if f.key == "projectPhase")
    assert status_field.allowed_values == []
    assert project_phase_field.allowed_values == []

    await client.aclose()


@pytest.mark.asyncio
async def test_get_project_admin_context_filters_parent_candidates_and_writable_fields() -> None:
    """OPM-1449/OPM-1458: available_parent_projects must not leak projects
    outside READ_PROJECTS, and fields[] should only carry writable entries."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 1, "name": "Demo", "identifier": "demo", "_links": {}},
                request=request,
            )
        if request.url.path == "/api/v3/projects/1/form":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "schema": {
                            "id": {"name": "Id", "type": "Integer", "required": False, "writable": False},
                            "name": {"name": "Name", "type": "String", "required": True, "writable": True},
                            "parent": {"name": "Parent", "type": "Project", "required": False, "writable": True},
                            "status": {
                                "name": "Status",
                                "type": "Status",
                                "required": False,
                                "writable": True,
                                "_embedded": {"allowedValues": [{"id": 1, "name": "On track"}]},
                            },
                        }
                    }
                },
                request=request,
            )
        if request.url.path == "/api/v3/projects/available_parent_projects" and request.url.params.get("of") == "1":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            {"_type": "Project", "id": 2, "name": "Allowed Parent", "identifier": "allowed-parent"},
                            {"_type": "Project", "id": 3, "name": "Secret Project", "identifier": "secret-project"},
                        ]
                    }
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings(
        read_projects=("demo", "allowed-parent"),
        write_projects=(),
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

    result = await client.get_project_admin_context("demo")

    assert [p.identifier for p in result.available_parent_projects] == ["allowed-parent"]
    # Lightweight ProjectRef, not a full ProjectSummary — no description/status_explanation (OPM-1458).
    assert result.available_parent_projects[0].name == "Allowed Parent"
    assert not hasattr(result.available_parent_projects[0], "description")
    assert {f.key for f in result.fields} == {"name", "parent", "status"}  # "id" (writable=False) is excluded
    assert result.available_statuses[0].title == "On track"
    assert not hasattr(result, "project_links")  # redundant with the inferred_* booleans (OPM-1458)

    await client.aclose()


@pytest.mark.asyncio
async def test_list_roles_and_project_memberships_and_my_access() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/roles":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            {
                                "id": 8,
                                "name": "Project admin",
                                "_links": {"self": {"href": "/api/v3/roles/8", "title": "Project admin"}},
                            },
                            {
                                "id": 6,
                                "name": "Member",
                                "_links": {"self": {"href": "/api/v3/roles/6", "title": "Member"}},
                            },
                        ]
                    }
                },
                request=request,
            )
        if request.url.path == "/api/v3/users/me":
            return httpx.Response(
                200,
                json={"id": 5, "name": "Jürgen Tauschl", "login": "juergen"},
                request=request,
            )
        if request.url.path == "/api/v3/projects/demo":
            return httpx.Response(
                200,
                json={
                    "_type": "Project",
                    "id": 1,
                    "name": "Demo",
                    "identifier": "demo",
                    "_links": {
                        "self": {"href": "/api/v3/projects/1", "title": "Demo"},
                        "memberships": {
                            "href": "/api/v3/memberships?filters=%5B%7B%22project%22%3A%7B%22operator%22%3A%22%3D%22%2C%22values%22%3A%5B%221%22%5D%7D%7D%5D"
                        },
                        "update": {"href": "/api/v3/projects/1/form", "method": "post"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/memberships":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            {
                                "id": 12,
                                "_links": {
                                    "self": {"href": "/api/v3/memberships/12", "title": "Jürgen Tauschl"},
                                    "update": {"href": "/api/v3/memberships/12/form", "method": "post"},
                                    "updateImmediately": {"href": "/api/v3/memberships/12", "method": "patch"},
                                    "project": {"href": "/api/v3/projects/1", "title": "Demo"},
                                    "principal": {"href": "/api/v3/users/5", "title": "Jürgen Tauschl"},
                                    "roles": [
                                        {"href": "/api/v3/roles/8", "title": "Project admin"},
                                        {"href": "/api/v3/roles/6", "title": "Member"},
                                    ],
                                },
                            }
                        ]
                    }
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))

    roles = await client.list_roles()
    assert roles.count == 2
    assert roles.results[0].name == "Project admin"

    memberships = await client.list_project_memberships("demo")
    assert memberships.count == 1
    assert memberships.results[0].role_names == ["Project admin", "Member"]

    access = await client.get_my_project_access("demo")
    assert access.membership is not None
    assert access.inferred_is_project_admin is True
    assert access.inferred_can_edit_project is True
    assert access.inferred_can_manage_memberships is True

    await client.aclose()


@pytest.mark.asyncio
async def test_list_project_memberships_paginates_and_preserves_project_filter() -> None:
    # OPM-1456: list_project_memberships previously fetched one unbounded page.
    # Now it must (a) send real offset/pageSize and (b) merge them into the
    # memberships href's own "filters" query rather than replacing it --
    # httpx's params= replaces a URL's existing query string outright, which
    # would have silently dropped the project scoping filter.
    def member(i: int) -> dict:
        return {
            "id": i,
            "_links": {
                "project": {"href": "/api/v3/projects/1", "title": "Demo"},
                "principal": {"href": f"/api/v3/users/{i}", "title": f"User {i}"},
                "roles": [{"href": "/api/v3/roles/6", "title": "Member"}],
            },
        }

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo":
            return httpx.Response(
                200,
                json={
                    "_type": "Project",
                    "id": 1,
                    "name": "Demo",
                    "identifier": "demo",
                    "_links": {
                        "memberships": {"href": "/api/v3/memberships?filters=%5B%7B%22project%22%3A1%7D%5D"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/memberships":
            assert request.url.params["filters"] == '[{"project":1}]'  # preserved, not dropped
            offset = request.url.params["offset"]
            assert request.url.params["pageSize"] == "1"
            if offset == "1":
                return httpx.Response(200, json={"total": 2, "_embedded": {"elements": [member(1)]}}, request=request)
            if offset == "2":
                return httpx.Response(200, json={"total": 2, "_embedded": {"elements": [member(2)]}}, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))

    page1 = await client.list_project_memberships("demo", offset=1, limit=1)
    assert [m.id for m in page1.results] == [1]
    assert page1.next_offset == 2
    assert page1.truncated is True

    page2 = await client.list_project_memberships("demo", offset=page1.next_offset, limit=1)
    assert [m.id for m in page2.results] == [2]
    assert page2.next_offset is None

    await client.aclose()


@pytest.mark.asyncio
async def test_instance_configuration_and_project_phase_definitions() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/configuration":
            return httpx.Response(
                200,
                json={
                    "_type": "Configuration",
                    "hostName": "op.example.com",
                    "maximumAttachmentFileSize": 12345,
                    "maximumAPIV3PageSize": 1000,
                    "perPageOptions": [20, 100],
                    "durationFormat": "hours_only",
                    "hoursPerDay": 8,
                    "daysPerMonth": 20,
                    "activeFeatureFlags": ["mcpServer", "portfolioModels"],
                    "availableFeatures": ["roadmaps"],
                    "triallingFeatures": [],
                },
                request=request,
            )
        if request.url.path == "/api/v3/project_phase_definitions":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            {
                                "_type": "ProjectPhaseDefinition",
                                "id": 1,
                                "name": "Initiating",
                                "startGateName": "Idea",
                                "finishGateName": "Approved",
                                "createdAt": "2026-03-01T10:00:00Z",
                                "updatedAt": "2026-03-02T10:00:00Z",
                            },
                            {
                                "_type": "ProjectPhaseDefinition",
                                "id": 2,
                                "name": "Executing",
                                "startGateName": "Kickoff",
                                "finishGateName": "Done",
                            },
                        ]
                    }
                },
                request=request,
            )
        if request.url.path == "/api/v3/project_phase_definitions/1":
            return httpx.Response(
                200,
                json={
                    "_type": "ProjectPhaseDefinition",
                    "id": 1,
                    "name": "Initiating",
                    "startGateName": "Idea",
                    "finishGateName": "Approved",
                    "createdAt": "2026-03-01T10:00:00Z",
                    "updatedAt": "2026-03-02T10:00:00Z",
                },
                request=request,
            )
        if request.url.path == "/api/v3/project_phases/5":
            return httpx.Response(
                200,
                json={
                    "_type": "ProjectPhase",
                    "id": 5,
                    "name": "Executing",
                    "startDate": "2026-03-10",
                    "finishDate": "2026-03-24",
                    "createdAt": "2026-03-10T10:00:00Z",
                    "updatedAt": "2026-03-12T10:00:00Z",
                    "_links": {
                        "project": {"href": "/api/v3/projects/1", "title": "Demo"},
                        "projectPhaseDefinition": {"href": "/api/v3/project_phase_definitions/2", "title": "Executing"},
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))

    configuration = await client.get_instance_configuration()
    phases = await client.list_project_phase_definitions()
    phase = await client.get_project_phase_definition(1)
    project_phase = await client.get_project_phase(5)

    assert configuration.host_name == "op.example.com"
    assert configuration.active_feature_flags == ["mcpServer", "portfolioModels"]
    assert phases.count == 2
    assert phases.results[0].name == "Initiating"
    assert phase.finish_gate == "Approved"
    assert project_phase.name == "Executing"
    assert project_phase.phase_definition_id == 2
    assert project_phase.project == "Demo"

    await client.aclose()


@pytest.mark.asyncio
async def test_get_project_configuration_and_copy_project() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 1, "name": "Demo", "identifier": "demo", "_links": {}},
                request=request,
            )
        if request.url.path == "/api/v3/projects/1/configuration":
            return httpx.Response(
                200,
                json={
                    "_type": "Configuration",
                    "maximumAttachmentFileSize": 12345,
                    "maximumAPIV3PageSize": 1000,
                    "perPageOptions": [20, 100],
                    "durationFormat": "hours_only",
                    "hoursPerDay": 8,
                    "daysPerMonth": 20,
                    "activeFeatureFlags": ["mcpServer"],
                    "availableFeatures": ["roadmaps"],
                    "triallingFeatures": [],
                    "enabledInternalComments": True,
                },
                request=request,
            )
        if request.url.path == "/api/v3/projects/form":
            return httpx.Response(
                200,
                json={"_type": "Form", "_embedded": {"schema": {}}},
                request=request,
            )
        if request.url.path == "/api/v3/projects/1/copy/form":
            body = json.loads(request.content)
            assert body["name"] == "Demo Copy"
            assert body["identifier"] == "demo-copy"
            return httpx.Response(
                200,
                json={"_type": "Form", "_embedded": {"payload": body, "validationErrors": {}}},
                request=request,
            )
        if request.url.path == "/api/v3/projects/1/copy":
            body = json.loads(request.content)
            assert body["name"] == "Demo Copy"
            assert body["identifier"] == "demo-copy"
            return httpx.Response(
                302,
                headers={"Location": "/api/v3/job_statuses/77"},
                request=request,
            )
        if request.url.path == "/api/v3/job_statuses/77":
            return httpx.Response(
                200,
                json={"_type": "JobStatus", "id": 77},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = make_settings()
    settings = Settings(
        read_projects=("*",),
        write_projects=("*",),
        base_url=settings.base_url,
        api_token=settings.api_token,
        enable_project_write=True,
        timeout=settings.timeout,
        verify_ssl=settings.verify_ssl,
        default_page_size=settings.default_page_size,
        max_page_size=settings.max_page_size,
        max_results=settings.max_results,
        log_level=settings.log_level,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    configuration = await client.get_project_configuration("demo")
    preview = await client.copy_project(
        source_project="demo",
        name="Demo Copy",
        identifier="demo-copy",
        confirm=False,
    )
    copied = await client.copy_project(
        source_project="demo",
        name="Demo Copy",
        identifier="demo-copy",
        confirm=True,
    )

    assert configuration.project_name == "Demo"
    assert configuration.enabled_internal_comments is True
    assert preview.ready is True
    assert preview.requires_confirmation is True
    assert preview.job_status_id is None
    assert preview.job_status_url is None
    assert copied.confirmed is True
    assert copied.job_status_id == 77
    assert copied.job_status_url == "https://op.example.com/api/v3/job_statuses/77"

    await client.aclose()


@pytest.mark.asyncio
async def test_job_status_documents_news_and_wiki() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 6, "name": "Demo", "identifier": "demo"},
                request=request,
            )
        if request.url.path == "/api/v3/job_statuses/77":
            return httpx.Response(
                200,
                json={
                    "_type": "JobStatus",
                    "id": 77,
                    "status": "in_progress",
                    "message": "Copy running",
                    "percentageDone": 40,
                    "createdAt": "2026-03-20T10:00:00Z",
                    "updatedAt": "2026-03-20T10:05:00Z",
                    "_links": {
                        "self": {"href": "/api/v3/job_statuses/77"},
                        "project": {"href": "/api/v3/projects/6", "title": "Demo"},
                        "createdProject": {"href": "/api/v3/projects/88", "title": "Demo Copy"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/documents" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            {
                                "_type": "Document",
                                "id": 5,
                                "title": "Architecture",
                                "description": {"raw": "System overview"},
                                "createdAt": "2026-03-20T09:00:00Z",
                                "_links": {
                                    "self": {"href": "/api/v3/documents/5"},
                                    "project": {"href": "/api/v3/projects/6", "title": "Demo"},
                                    "updateImmediately": {"href": "/api/v3/documents/5", "method": "patch"},
                                },
                                "_embedded": {
                                    "attachments": {"count": 2, "total": 2},
                                },
                            }
                        ]
                    }
                },
                request=request,
            )
        if request.url.path == "/api/v3/documents/5" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "_type": "Document",
                    "id": 5,
                    "title": "Architecture",
                    "description": {"raw": "System overview"},
                    "createdAt": "2026-03-20T09:00:00Z",
                    "_links": {
                        "self": {"href": "/api/v3/documents/5"},
                        "project": {"href": "/api/v3/projects/6", "title": "Demo"},
                        "attachments": {"href": "/api/v3/documents/5/attachments"},
                        "updateImmediately": {"href": "/api/v3/documents/5", "method": "patch"},
                    },
                    "_embedded": {
                        "attachments": {"count": 2, "total": 2},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/documents/5" and request.method == "PATCH":
            body = json.loads(request.content)
            assert body == {"title": "Architecture Updated"}
            return httpx.Response(
                200,
                json={
                    "_type": "Document",
                    "id": 5,
                    "title": "Architecture Updated",
                    "description": {"raw": "System overview"},
                    "createdAt": "2026-03-20T09:00:00Z",
                    "_links": {
                        "self": {"href": "/api/v3/documents/5"},
                        "project": {"href": "/api/v3/projects/6", "title": "Demo"},
                        "attachments": {"href": "/api/v3/documents/5/attachments"},
                        "updateImmediately": {"href": "/api/v3/documents/5", "method": "patch"},
                    },
                    "_embedded": {
                        "attachments": {"count": 2, "total": 2},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/news" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            {
                                "_type": "News",
                                "id": 7,
                                "title": "Release Notes",
                                "summary": "Sprint 8 is out",
                                "description": {"raw": "Shipped the sprint"},
                                "createdAt": "2026-03-20T08:00:00Z",
                                "_links": {
                                    "self": {"href": "/api/v3/news/7"},
                                    "project": {"href": "/api/v3/projects/6", "title": "Demo"},
                                    "author": {"href": "/api/v3/users/5", "title": "Jürgen Tauschl"},
                                    "updateImmediately": {"href": "/api/v3/news/7", "method": "patch"},
                                    "delete": {"href": "/api/v3/news/7", "method": "delete"},
                                },
                            }
                        ]
                    }
                },
                request=request,
            )
        if request.url.path == "/api/v3/news" and request.method == "POST":
            body = json.loads(request.content)
            assert body == {
                "title": "Fresh Update",
                "summary": "Ready",
                "description": {"format": "markdown", "raw": "Detailed body"},
                "_links": {"project": {"href": "/api/v3/projects/6"}},
            }
            return httpx.Response(
                201,
                json={
                    "_type": "News",
                    "id": 8,
                    "title": "Fresh Update",
                    "summary": "Ready",
                    "description": {"raw": "Detailed body"},
                    "createdAt": "2026-03-20T08:30:00Z",
                    "_links": {
                        "self": {"href": "/api/v3/news/8"},
                        "project": {"href": "/api/v3/projects/6", "title": "Demo"},
                        "author": {"href": "/api/v3/users/5", "title": "Jürgen Tauschl"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/news/7" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "_type": "News",
                    "id": 7,
                    "title": "Release Notes",
                    "summary": "Sprint 8 is out",
                    "description": {"raw": "Shipped the sprint"},
                    "createdAt": "2026-03-20T08:00:00Z",
                    "_links": {
                        "self": {"href": "/api/v3/news/7"},
                        "project": {"href": "/api/v3/projects/6", "title": "Demo"},
                        "author": {"href": "/api/v3/users/5", "title": "Jürgen Tauschl"},
                        "updateImmediately": {"href": "/api/v3/news/7", "method": "patch"},
                        "delete": {"href": "/api/v3/news/7", "method": "delete"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/news/7" and request.method == "PATCH":
            body = json.loads(request.content)
            assert body == {"summary": "Sprint 8.1 is out"}
            return httpx.Response(
                200,
                json={
                    "_type": "News",
                    "id": 7,
                    "title": "Release Notes",
                    "summary": "Sprint 8.1 is out",
                    "description": {"raw": "Shipped the sprint"},
                    "createdAt": "2026-03-20T08:00:00Z",
                    "_links": {
                        "self": {"href": "/api/v3/news/7"},
                        "project": {"href": "/api/v3/projects/6", "title": "Demo"},
                        "author": {"href": "/api/v3/users/5", "title": "Jürgen Tauschl"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/news/7" and request.method == "DELETE":
            return httpx.Response(202, request=request)
        if request.url.path == "/api/v3/wiki_pages/9":
            return httpx.Response(
                200,
                json={
                    "_type": "WikiPage",
                    "id": 9,
                    "title": "Runbook",
                    "_links": {
                        "self": {"href": "/api/v3/wiki_pages/9"},
                        "project": {"href": "/api/v3/projects/6", "title": "Demo"},
                        "attachments": {"href": "/api/v3/wiki_pages/9/attachments"},
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
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
        enable_project_write=True,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    job = await client.get_job_status(77)
    documents = await client.list_documents(project="demo")
    document = await client.get_document(5)
    document_preview = await client.update_document(document_id=5, title="Architecture Updated", confirm=False)
    document_updated = await client.update_document(document_id=5, title="Architecture Updated", confirm=True)
    news_list = await client.list_news(project="demo", search="release")
    news_detail = await client.get_news(7)
    news_preview = await client.create_news(
        project="demo", title="Fresh Update", summary="Ready", description="Detailed body", confirm=False
    )
    news_created = await client.create_news(
        project="demo", title="Fresh Update", summary="Ready", description="Detailed body", confirm=True
    )
    news_updated = await client.update_news(news_id=7, summary="Sprint 8.1 is out", confirm=True)
    news_deleted = await client.delete_news(news_id=7, confirm=True)
    wiki_page = await client.get_wiki_page(9)
    assert job.id == 77
    assert job.project == "Demo"
    assert job.created_resource_id == 88
    assert documents.count == 1
    assert document.attachment_count == 2
    assert document_preview.requires_confirmation is True
    assert document_updated.result is not None
    assert document_updated.result.title == "Architecture Updated"
    assert news_list.count == 1
    assert news_detail.author == "Jürgen Tauschl"
    assert news_preview.requires_confirmation is True
    assert news_created.result is not None
    assert news_created.result.id == 8
    assert news_updated.result is not None
    assert news_updated.result.summary == "Sprint 8.1 is out"
    assert news_deleted.confirmed is True
    assert wiki_page.title == "Runbook"

    await client.aclose()


@pytest.mark.asyncio
async def test_project_scoped_reads_accept_numeric_project_ids_when_allowed_by_name() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/6":
            return httpx.Response(
                200,
                json={
                    "_type": "Project",
                    "id": 6,
                    "name": "Demo",
                    "identifier": "demo",
                    "_links": {"versions": {"href": "/api/v3/projects/6/versions"}},
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages":
            return httpx.Response(
                200,
                json={
                    "total": 1,
                    "_embedded": {
                        "elements": [
                            {
                                "id": 42,
                                "subject": "Scoped task",
                                "_links": {
                                    "type": {"title": "Task"},
                                    "status": {"title": "Open"},
                                    "project": {"href": "/api/v3/projects/6", "title": "Demo"},
                                },
                            }
                        ]
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/projects/6/versions":
            return httpx.Response(
                200,
                json={
                    "total": 1,
                    "_embedded": {
                        "elements": [
                            {
                                "id": 9,
                                "name": "Q2",
                                "_links": {"definingProject": {"href": "/api/v3/projects/6", "title": "Demo"}},
                            }
                        ]
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/queries":
            return httpx.Response(
                200,
                json={
                    "total": 1,
                    "_embedded": {
                        "elements": [
                            {
                                "id": 12,
                                "name": "Demo Board",
                                "_links": {
                                    "self": {"href": "/api/v3/queries/12"},
                                    "project": {"href": "/api/v3/projects/6", "title": "Demo"},
                                },
                            }
                        ]
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/time_entries":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            {
                                "id": 10,
                                "hours": "PT1H",
                                "spentOn": "2026-03-20",
                                "_links": {
                                    "self": {"href": "/api/v3/time_entries/10"},
                                    "project": {"href": "/api/v3/projects/6", "title": "Demo"},
                                    "activity": {"href": "/api/v3/time_entries/activities/3", "title": "Development"},
                                },
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
        read_projects=("Demo",),
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    searched = await client.search_work_packages(search="Scoped", project="6")
    listed = await client.list_work_packages(project="6")
    versions = await client.list_versions(project="6")
    boards = await client.list_boards(project="6")
    entries = await client.list_time_entries(project="6")

    assert searched.count == 1
    assert listed.count == 1
    assert versions.count == 1
    assert boards.count == 1
    assert entries.count == 1

    await client.aclose()


@pytest.mark.asyncio
async def test_views_categories_and_attachments() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 6, "name": "Demo", "identifier": "demo"},
                request=request,
            )
        if request.url.path == "/api/v3/views":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            {
                                "_type": "Views::TeamPlanner",
                                "id": 12,
                                "name": "Team Planner",
                                "public": True,
                                "starred": False,
                                "createdAt": "2026-03-20T10:00:00Z",
                                "updatedAt": "2026-03-20T11:00:00Z",
                                "_links": {
                                    "self": {"href": "/api/v3/views/12"},
                                    "project": {"href": "/api/v3/projects/6", "title": "Demo"},
                                    "query": {"href": "/api/v3/queries/18", "title": "Planner Query"},
                                },
                            }
                        ]
                    }
                },
                request=request,
            )
        if request.url.path == "/api/v3/views/12":
            return httpx.Response(
                200,
                json={
                    "_type": "Views::TeamPlanner",
                    "id": 12,
                    "name": "Team Planner",
                    "public": True,
                    "starred": False,
                    "_links": {
                        "self": {"href": "/api/v3/views/12"},
                        "project": {"href": "/api/v3/projects/6", "title": "Demo"},
                        "query": {"href": "/api/v3/queries/18", "title": "Planner Query"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/projects/6/categories":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            {
                                "id": 3,
                                "name": "Backend",
                                "isDefault": True,
                                "_links": {"self": {"href": "/api/v3/categories/3"}},
                            }
                        ]
                    }
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/7" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 7,
                    "subject": "Upload spec",
                    "_links": {
                        "self": {"href": "/api/v3/work_packages/7"},
                        "project": {"href": "/api/v3/projects/6", "title": "Demo"},
                        "activities": {"href": "/api/v3/work_packages/7/activities"},
                        "relations": {"href": "/api/v3/work_packages/7/relations"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/7/attachments" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            {
                                "id": 5,
                                "title": "spec.md",
                                "fileName": "spec.md",
                                "fileSize": 12,
                                "status": "uploaded",
                                "_links": {
                                    "self": {"href": "/api/v3/attachments/5"},
                                    "container": {"href": "/api/v3/work_packages/7"},
                                    "author": {"href": "/api/v3/users/1", "title": "Bot"},
                                    "downloadLocation": {"href": "https://op.example.com/files/spec.md"},
                                },
                            }
                        ]
                    }
                },
                request=request,
            )
        if request.url.path == "/api/v3/attachments/5" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 5,
                    "title": "spec.md",
                    "fileName": "spec.md",
                    "fileSize": 12,
                    "status": "uploaded",
                    "_links": {
                        "self": {"href": "/api/v3/attachments/5"},
                        "container": {"href": "/api/v3/work_packages/7"},
                        "author": {"href": "/api/v3/users/1", "title": "Bot"},
                        "downloadLocation": {"href": "https://op.example.com/files/spec.md"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/configuration":
            return httpx.Response(
                200,
                json={"maximumAttachmentFileSize": 5000},
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/7/attachments" and request.method == "POST":
            assert request.headers["content-type"].startswith("multipart/form-data")
            body = request.content
            assert b'name="metadata"' in body
            # Regression: the metadata part must NOT carry a filename, or Rails treats
            # it as an uploaded file (Hash) instead of a JSON string and OpenProject
            # 500s ("no implicit conversion of HashWithIndifferentAccess into String").
            assert b'name="metadata"; filename=' not in body
            assert b'"fileName": "spec.md"' in body
            assert b'name="file"; filename="spec.md"' in body
            return httpx.Response(
                200,
                json={
                    "id": 6,
                    "title": "spec.md",
                    "fileName": "spec.md",
                    "fileSize": 12,
                    "status": "uploaded",
                    "_links": {
                        "self": {"href": "/api/v3/attachments/6"},
                        "container": {"href": "/api/v3/work_packages/7"},
                        "author": {"href": "/api/v3/users/1", "title": "Bot"},
                        "downloadLocation": {"href": "https://op.example.com/files/spec.md"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/attachments/5" and request.method == "DELETE":
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
        enable_work_package_write=True,
        attachment_root=os.getcwd(),  # uploads need a configured root
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    view_list = await client.list_views(project="demo", view_type="Views::TeamPlanner")
    view_detail = await client.get_view(12)
    categories = await client.list_categories("demo")
    category = await client.get_category(project_ref="demo", category_id=3)
    attachments = await client.list_work_package_attachments(7)
    attachment = await client.get_attachment(5)
    created_preview = await client.create_work_package_attachment(
        work_package_id=7,
        file_path="tests/fixtures/spec.md",
        description="Spec",
        confirm=False,
    )
    created = await client.create_work_package_attachment(
        work_package_id=7,
        file_path="tests/fixtures/spec.md",
        description="Spec",
        confirm=True,
    )
    deleted = await client.delete_attachment(attachment_id=5, confirm=True)

    assert view_list.count == 1
    assert view_list.results[0].type == "Views::TeamPlanner"
    assert view_detail.query == "Planner Query"
    assert categories.count == 1
    assert category.name == "Backend"
    assert attachments.count == 1
    assert attachment.file_name == "spec.md"
    assert created_preview.ready is True
    assert created.attachment_id == 6
    assert deleted.attachment_id == 5

    await client.aclose()


@pytest.mark.asyncio
async def test_list_views_search_filters_by_name_substring() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/views" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            {"id": 1, "_type": "Views::TeamPlanner", "name": "Planner View", "_links": {}},
                            {"id": 2, "_type": "Views::Work", "name": "My Work", "_links": {}},
                        ]
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))
    page = await client.list_views(search="planner")

    assert [v.id for v in page.results] == [1]
    assert page.total == 1

    no_match = await client.list_views(search="nonexistent")
    assert no_match.results == []
    assert no_match.total == 0

    await client.aclose()


@pytest.mark.asyncio
async def test_list_documents_search_filters_by_title_substring() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/documents" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            {"id": 1, "title": "Architecture Overview", "_links": {}},
                            {"id": 2, "title": "Onboarding Guide", "_links": {}},
                        ]
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))
    page = await client.list_documents(search="architecture")

    assert [d.id for d in page.results] == [1]
    assert page.total == 1

    no_match = await client.list_documents(search="nonexistent")
    assert no_match.results == []
    assert no_match.total == 0

    await client.aclose()


@pytest.mark.asyncio
async def test_render_text() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/render/markdown" and request.method == "POST":
            assert request.content.decode("utf-8") == "**Hello**"
            return httpx.Response(
                200,
                json={"html": "<p><strong>Hello</strong></p>"},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))

    result = await client.render_text(text="**Hello**", format="markdown")
    assert result.html == "<p><strong>Hello</strong></p>"
    assert result.raw == "**Hello**"

    await client.aclose()


@pytest.mark.asyncio
async def test_help_texts_and_working_days() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/help_texts" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "total": 1,
                    "_embedded": {
                        "elements": [
                            {
                                "id": 5,
                                "attribute": "description",
                                "attributeCaption": "Description",
                                "helpText": {"format": "markdown", "raw": "Describe the work."},
                            }
                        ]
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/help_texts/5" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 5,
                    "attributeName": "description",
                    "attributeCaption": "Description",
                    "helpText": {"format": "markdown", "raw": "Describe the work."},
                },
                request=request,
            )
        if request.url.path == "/api/v3/days/week" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "total": 7,
                    "_embedded": {
                        "elements": [
                            {"name": "Monday", "dayOfWeek": 1, "working": True},
                            {"name": "Saturday", "dayOfWeek": 6, "working": False},
                        ]
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/days/non_working" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "total": 1,
                    "_embedded": {
                        "elements": [
                            {"date": "2026-12-25", "name": "Christmas Day"},
                        ]
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))

    help_texts = await client.list_help_texts()
    assert help_texts.count == 1
    assert help_texts.results[0].attribute_name == "description"

    help_text = await client.get_help_text(5)
    assert help_text.help_text == "Describe the work."

    days = await client.list_working_days()
    assert days.count == 2
    assert days.results[0].name == "Monday"
    assert days.results[0].working is True
    assert days.results[1].working is False

    non_working = await client.list_non_working_days()
    assert non_working.count == 1
    assert non_working.results[0].name == "Christmas Day"

    await client.aclose()


@pytest.mark.asyncio
async def test_get_custom_option() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/custom_options/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 42, "value": "High Priority"},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))

    option = await client.get_custom_option(42)
    assert option.id == 42
    assert option.value == "High Priority"

    await client.aclose()


@pytest.mark.asyncio
async def test_create_project_returns_preview_when_not_confirmed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/form" and request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "schema": {},
                        "payload": {"name": "Alpha", "identifier": "alpha"},
                        "validationErrors": {},
                    }
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings(
        read_projects=("*",),
        write_projects=("*",),
        base_url="https://op.example.com",
        api_token="token",
        enable_project_write=True,
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.create_project(name="Alpha", identifier="alpha", confirm=False)

    assert result.confirmed is False
    assert result.requires_confirmation is True
    assert result.ready is True
    assert result.validation_errors == {}

    await client.aclose()


@pytest.mark.asyncio
async def test_create_project_rejects_validation_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/form" and request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "schema": {},
                        "payload": {},
                        "validationErrors": {"identifier": {"message": "Identifier has already been taken."}},
                    }
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings(
        read_projects=("*",),
        write_projects=("*",),
        base_url="https://op.example.com",
        api_token="token",
        enable_project_write=True,
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.create_project(name="Alpha", identifier="alpha", confirm=True)

    assert result.ready is False
    assert result.confirmed is False
    assert "identifier" in result.validation_errors

    await client.aclose()


@pytest.mark.asyncio
async def test_delete_project_returns_preview_and_executes_when_confirmed() -> None:
    project_json = {
        "_type": "Project",
        "id": 3,
        "name": "Old Project",
        "identifier": "old-project",
        "active": True,
        "public": False,
        "_links": {"status": {"title": "on track"}},
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/old-project" and request.method == "GET":
            return httpx.Response(200, json=project_json, request=request)
        if request.url.path == "/api/v3/projects/3" and request.method == "DELETE":
            return httpx.Response(204, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings(
        read_projects=("*",),
        write_projects=("*",),
        base_url="https://op.example.com",
        api_token="token",
        enable_project_write=True,
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    preview = await client.delete_project(project_ref="old-project", confirm=False)
    assert preview.confirmed is False
    assert preview.requires_confirmation is True
    assert preview.ready is True

    confirmed = await client.delete_project(project_ref="old-project", confirm=True)
    assert confirmed.confirmed is True
    assert confirmed.result is not None
    assert confirmed.result.name == "Old Project"

    await client.aclose()


@pytest.mark.asyncio
async def test_add_project_favorite_uses_workspaces_path_and_empty_body() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo" and request.method == "GET":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 6, "name": "Demo", "identifier": "demo", "_links": {}},
                request=request,
            )
        if request.url.path == "/api/v3/workspaces/6/favorite" and request.method == "POST":
            # 204 No Content with an empty body — must not be parsed as JSON.
            return httpx.Response(204, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    import dataclasses

    settings = dataclasses.replace(make_settings(), enable_project_write=True, write_projects=("demo",))
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.add_project_favorite(project="demo", confirm=True)

    assert result.confirmed is True
    assert result.action == "favorite"
    assert result.project_id == 6
    assert result.project == "Demo"

    await client.aclose()


@pytest.mark.asyncio
async def test_add_project_favorite_translates_404_to_version_hint() -> None:
    # Simulates an OpenProject older than 17.0, where the workspaces favorite
    # endpoint does not exist and returns 404.
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo" and request.method == "GET":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 6, "name": "Demo", "identifier": "demo", "_links": {}},
                request=request,
            )
        if request.url.path == "/api/v3/workspaces/6/favorite":
            return httpx.Response(404, json={"message": "Not found"}, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    import dataclasses

    settings = dataclasses.replace(make_settings(), enable_project_write=True, write_projects=("demo",))
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(NotFoundError, match="Project favorites requires OpenProject 17.0"):
        await client.add_project_favorite(project="demo", confirm=True)

    await client.aclose()


async def test_copy_project_checks_destination_allowlist() -> None:
    """copy_project refuses a destination outside the write allowlist."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/src":
            return httpx.Response(
                200,
                json={
                    "_type": "Project",
                    "id": 1,
                    "identifier": "src",
                    "name": "Source",
                    "_links": {"self": {"href": "/api/v3/projects/1"}},
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(
        enable_project_write=True,
        read_projects=("src", "dst-ok"),
        write_projects=("src", "dst-ok"),
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))
    # The source "src" is allowed, so a PermissionDeniedError here can only come
    # from the destination identifier "dst-bad" being outside the allowlist.
    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await client.copy_project(source_project="src", name="Bad", identifier="dst-bad", confirm=True)

    # Positive control: an allowed destination passes the allowlist stage (it then
    # proceeds to the copy/form request, which the handler serves).
    async def handler_ok(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/src":
            return httpx.Response(
                200,
                json={
                    "_type": "Project",
                    "id": 1,
                    "identifier": "src",
                    "name": "Source",
                    "_links": {"self": {"href": "/api/v3/projects/1"}},
                },
                request=request,
            )
        if request.url.path == "/api/v3/projects/form" and request.method == "POST":
            return httpx.Response(200, json={"_embedded": {"payload": {}, "validationErrors": {}}}, request=request)
        if request.url.path.endswith("/copy/form") and request.method == "POST":
            return httpx.Response(200, json={"_embedded": {"payload": {}, "validationErrors": {}}}, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client2 = OpenProjectClient(settings, transport=httpx.MockTransport(handler_ok))
    # Should NOT raise PermissionDeniedError for the allowed destination "dst-ok".
    result = await client2.copy_project(source_project="src", name="Good", identifier="dst-ok", confirm=False)
    assert result is not None  # reached preview without an allowlist denial
    await client2.aclose()
    await client.aclose()


@pytest.mark.asyncio
async def test_list_projects_reports_filtered_total_when_allowlist_drops_items() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects":
            return httpx.Response(
                200,
                json={
                    "total": 3,
                    "_embedded": {
                        "elements": [
                            {
                                "_type": "Project",
                                "id": 6,
                                "name": "Demo",
                                "identifier": "demo",
                                "_links": {"self": {"href": "/api/v3/projects/6", "title": "Demo"}},
                            },
                            {
                                "_type": "Project",
                                "id": 7,
                                "name": "Other",
                                "identifier": "other",
                                "_links": {"self": {"href": "/api/v3/projects/7", "title": "Other"}},
                            },
                            {
                                "_type": "Project",
                                "id": 8,
                                "name": "Another",
                                "identifier": "another",
                                "_links": {"self": {"href": "/api/v3/projects/8", "title": "Another"}},
                            },
                        ]
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
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.list_projects()

    assert result.count == 1
    assert result.total == 1
    assert result.results[0].identifier == "demo"
    assert result.next_offset is None
    assert result.truncated is False

    await client.aclose()


@pytest.mark.asyncio
async def test_list_projects_walks_multiple_server_pages_when_allowlist_thins_first_page() -> None:
    # Regression test: page 1 (server pageSize=2) has zero allowed projects,
    # page 2 has the one allowed project. Pagination must advance server_offset by
    # one page (not a full page SIZE) compared against the item total, so it keeps
    # scanning past page 1 until page 2's match is found. offset/pageSize below mirror
    # real OpenProject 1-based-page semantics.
    import dataclasses

    settings = dataclasses.replace(make_settings(), max_page_size=2, read_projects=("demo",))

    requested_offsets: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects":
            page = request.url.params["offset"]
            requested_offsets.append(page)
            assert request.url.params["pageSize"] == "2"
            if page == "1":
                return httpx.Response(
                    200,
                    json={
                        "total": 3,
                        "_embedded": {
                            "elements": [
                                {
                                    "_type": "Project",
                                    "id": 6,
                                    "name": "Other",
                                    "identifier": "other",
                                    "_links": {"self": {"href": "/api/v3/projects/6", "title": "Other"}},
                                },
                                {
                                    "_type": "Project",
                                    "id": 7,
                                    "name": "Another",
                                    "identifier": "another",
                                    "_links": {"self": {"href": "/api/v3/projects/7", "title": "Another"}},
                                },
                            ]
                        },
                    },
                    request=request,
                )
            if page == "2":
                return httpx.Response(
                    200,
                    json={
                        "total": 3,
                        "_embedded": {
                            "elements": [
                                {
                                    "_type": "Project",
                                    "id": 8,
                                    "name": "Demo",
                                    "identifier": "demo",
                                    "_links": {"self": {"href": "/api/v3/projects/8", "title": "Demo"}},
                                },
                            ]
                        },
                    },
                    request=request,
                )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.list_projects()

    assert requested_offsets == ["1", "2"], f"expected pages 1 then 2, got {requested_offsets}"
    assert result.count == 1
    assert result.results[0].identifier == "demo"
    assert result.truncated is False
    assert result.next_offset is None

    await client.aclose()


@pytest.mark.asyncio
async def test_list_projects_cross_call_pagination_does_not_skip_or_duplicate() -> None:
    # A single raw server page (max_page_size=50, well above the 3 allowed
    # projects below) yields more allowed matches (3) than effective_limit (2) needs.
    # offset=1 must stop mid-page and report truncated=True/next_offset=2 without
    # discarding the leftover match; offset=2 must resume exactly at that leftover
    # match via a fresh scan, not skip it or repeat what offset=1 already returned.
    all_projects = [
        {
            "_type": "Project",
            "id": i,
            "name": f"P{i}",
            "identifier": f"p{i}",
            "_links": {"self": {"href": f"/api/v3/projects/{i}", "title": f"P{i}"}},
        }
        for i in (1, 2, 3)
    ]

    def make_handler():
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v3/projects":
                assert request.url.params["offset"] == "1"  # single page covers all 3
                return httpx.Response(200, json={"total": 3, "_embedded": {"elements": all_projects}}, request=request)
            raise AssertionError(f"Unexpected request: {request.method} {request.url}")

        return handler

    client_page1 = OpenProjectClient(make_settings(), transport=httpx.MockTransport(make_handler()))
    first = await client_page1.list_projects(limit=2, offset=1)
    await client_page1.aclose()

    client_page2 = OpenProjectClient(make_settings(), transport=httpx.MockTransport(make_handler()))
    second = await client_page2.list_projects(limit=2, offset=2)
    await client_page2.aclose()

    first_ids = [p.identifier for p in first.results]
    second_ids = [p.identifier for p in second.results]
    assert first_ids == ["p1", "p2"]
    assert second_ids == ["p3"], f"offset=2 must resume at p3, not skip or repeat; got {second_ids}"
    assert set(first_ids) & set(second_ids) == set(), "no project should appear on both pages"
    assert first.truncated is True
    assert first.next_offset == 2
    assert second.truncated is False
    assert second.next_offset is None


@pytest.mark.asyncio
async def test_list_projects_cross_call_pagination_with_allowlist_thinning_across_pages() -> None:
    # OPM-117: the OPM-107 cross-call regression test (above) uses an unrestricted
    # allowlist, so it never exercises skip_count spanning a raw-page boundary while
    # an active allowlist is also thinning pages unevenly — the actual scenario the
    # original OPM-107 bug was about. Three raw server pages of 2 (pageSize=2), one
    # allowed project per page (p1, p3, p5); each of the three offset=1/2/3 calls
    # uses a *fresh* client (no shared state), mirroring the OPM-107 test's shape.
    import dataclasses

    pages = {
        1: [
            {"_type": "Project", "id": 1, "name": "P1", "identifier": "p1", "_links": {}},
            {"_type": "Project", "id": 2, "name": "P2", "identifier": "p2", "_links": {}},
        ],
        2: [
            {"_type": "Project", "id": 3, "name": "P3", "identifier": "p3", "_links": {}},
            {"_type": "Project", "id": 4, "name": "P4", "identifier": "p4", "_links": {}},
        ],
        3: [
            {"_type": "Project", "id": 5, "name": "P5", "identifier": "p5", "_links": {}},
            {"_type": "Project", "id": 6, "name": "P6", "identifier": "p6", "_links": {}},
        ],
    }
    settings = dataclasses.replace(make_settings(), max_page_size=2, read_projects=("p1", "p3", "p5"))

    def make_handler(seen_offsets: list[str]):
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v3/projects":
                assert request.url.params["pageSize"] == "2"
                offset = int(request.url.params["offset"])
                seen_offsets.append(request.url.params["offset"])
                return httpx.Response(200, json={"total": 6, "_embedded": {"elements": pages[offset]}}, request=request)
            raise AssertionError(f"Unexpected request: {request.method} {request.url}")

        return handler

    results_by_call: list[tuple[list[str], list[str]]] = []
    for call_offset in (1, 2, 3):
        seen: list[str] = []
        client = OpenProjectClient(settings, transport=httpx.MockTransport(make_handler(seen)))
        result = await client.list_projects(limit=1, offset=call_offset)
        await client.aclose()
        results_by_call.append((seen, [p.identifier for p in result.results]))

    assert results_by_call[0] == (["1"], ["p1"]), "offset=1 must stop after page 1 with p1"
    assert results_by_call[1] == (["1", "2"], ["p3"]), "offset=2 must skip p1 on page 1, collect p3 on page 2"
    assert results_by_call[2] == (
        ["1", "2", "3"],
        ["p5"],
    ), "offset=3 must skip p1+p3 across pages 1-2, collect p5 on page 3"
