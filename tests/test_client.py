from __future__ import annotations

import json

import httpx
import pytest

from openproject_mcp.client import (
    AuthenticationError,
    InvalidInputError,
    NotFoundError,
    OpenProjectClient,
    PermissionDeniedError,
    _extract_formattable_text,
)
from openproject_mcp.config import Settings


def make_settings() -> Settings:
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
async def test_add_comment_requires_write_gate_not_delete_gate() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/1" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 1, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings(
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

    with pytest.raises(PermissionDeniedError, match="write support is disabled"):
        await client.add_work_package_comment(work_package_id=1, comment="Hello", confirm=True)

    await client.aclose()


@pytest.mark.asyncio
async def test_board_create_respects_allowed_write_projects() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/other":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 2, "name": "Other", "identifier": "other", "_links": {}},
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
        allowed_write_projects=("demo",),
        enable_board_write=True,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_ALLOWED_PROJECTS_WRITE"):
        await client.create_board(name="Sprint Board", project="other", confirm=False)

    await client.aclose()


@pytest.mark.asyncio
async def test_create_time_entry_with_work_package_respects_allowed_write_projects() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/9":
            return httpx.Response(
                200,
                json={
                    "id": 9,
                    "subject": "Other project ticket",
                    "_links": {
                        "project": {"href": "/api/v3/projects/2", "title": "Other"},
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
        allowed_write_projects=("demo",),
        enable_work_package_write=True,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_ALLOWED_PROJECTS_WRITE"):
        await client.create_time_entry(
            work_package_id=9,
            activity="Development",
            hours="PT1H",
            spent_on="2026-03-20",
            confirm=False,
        )

    await client.aclose()


@pytest.mark.asyncio
async def test_explicit_empty_write_scope_blocks_project_scoped_write() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 1, "name": "Demo", "identifier": "demo", "_links": {}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token",
            "OPENPROJECT_ENABLE_BOARD_WRITE": "true",
            "OPENPROJECT_ALLOWED_PROJECTS_WRITE": "",
        }
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_ALLOWED_PROJECTS_WRITE"):
        await client.create_board(name="Sprint Board", project="demo", confirm=False)

    await client.aclose()


@pytest.mark.asyncio
async def test_write_scope_is_intersection_of_read_scope() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/other":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 2, "name": "Other", "identifier": "other", "_links": {}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings.from_env(
        {
            "OPENPROJECT_BASE_URL": "https://op.example.com",
            "OPENPROJECT_API_TOKEN": "token",
            "OPENPROJECT_ENABLE_BOARD_WRITE": "true",
            "OPENPROJECT_ALLOWED_PROJECTS_READ": "demo",
            "OPENPROJECT_ALLOWED_PROJECTS_WRITE": "*",
        }
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_ALLOWED_PROJECTS_READ"):
        await client.create_board(name="Other Board", project="other", confirm=False)

    await client.aclose()


@pytest.mark.asyncio
async def test_project_wildcard_patterns_match_identifier_and_title() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/mcp-test":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 6, "name": "MCP-Test", "identifier": "mcp-test", "_links": {}},
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
        allowed_projects=("mcp-*",),
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    project = await client.get_project("mcp-test")

    assert project.id == 6
    assert project.name == "MCP-Test"

    await client.aclose()


@pytest.mark.asyncio
async def test_get_membership_respects_project_scope() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/memberships/3":
            return httpx.Response(
                200,
                json={
                    "id": 3,
                    "_links": {
                        "self": {"href": "/api/v3/memberships/3"},
                        "project": {"href": "/api/v3/projects/other-id", "title": "Other"},
                        "principal": {"href": "/api/v3/users/5", "title": "Alice"},
                        "roles": [{"href": "/api/v3/roles/2", "title": "Developer"}],
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
        allowed_projects=("demo-id",),
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_ALLOWED_PROJECTS_READ"):
        await client.get_membership(3)

    await client.aclose()


@pytest.mark.asyncio
async def test_delete_membership_allows_identifier_write_scope() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/memberships/3" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 3,
                    "_links": {
                        "self": {"href": "/api/v3/memberships/3"},
                        "project": {"href": "/api/v3/projects/demo-id", "title": "Demo"},
                        "principal": {"href": "/api/v3/users/5", "title": "Alice"},
                        "roles": [{"href": "/api/v3/roles/2", "title": "Developer"}],
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/memberships/3" and request.method == "DELETE":
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
        allowed_projects=("demo-id",),
        allowed_write_projects=("demo-id",),
        enable_membership_write=True,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    deleted = await client.delete_membership(membership_id=3, confirm=True)

    assert deleted.membership_id == 3
    assert deleted.confirmed is True

    await client.aclose()


@pytest.mark.asyncio
async def test_delete_news_allows_identifier_write_scope() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/news/7" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "_type": "News",
                    "id": 7,
                    "title": "Release",
                    "_links": {
                        "self": {"href": "/api/v3/news/7"},
                        "project": {"href": "/api/v3/projects/demo-id", "title": "Demo"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/news/7" and request.method == "DELETE":
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
        allowed_projects=("demo-id",),
        allowed_write_projects=("demo-id",),
        enable_project_write=True,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    deleted = await client.delete_news(news_id=7, confirm=True)

    assert deleted.news_id == 7
    assert deleted.confirmed is True

    await client.aclose()


@pytest.mark.asyncio
async def test_delete_time_entry_allows_identifier_write_scope() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/time_entries/10" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "_type": "TimeEntry",
                    "id": 10,
                    "hours": "PT1H",
                    "spentOn": "2026-03-20",
                    "_links": {
                        "self": {"href": "/api/v3/time_entries/10"},
                        "project": {"href": "/api/v3/projects/demo-id", "title": "Demo"},
                        "activity": {"href": "/api/v3/time_entries/activities/3", "title": "Development"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/time_entries/10" and request.method == "DELETE":
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
        allowed_projects=("demo-id",),
        allowed_write_projects=("demo-id",),
        enable_work_package_write=True,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    deleted = await client.delete_time_entry(time_entry_id=10, confirm=True)

    assert deleted.time_entry_id == 10
    assert deleted.confirmed is True

    await client.aclose()


@pytest.mark.asyncio
async def test_delete_version_allows_identifier_write_scope() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/versions/8" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "_type": "Version",
                    "id": 8,
                    "name": "Release 1",
                    "_links": {
                        "self": {"href": "/api/v3/versions/8"},
                        "definingProject": {"href": "/api/v3/projects/demo-id", "title": "Demo"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/versions/8" and request.method == "DELETE":
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
        allowed_projects=("demo-id",),
        allowed_write_projects=("demo-id",),
        enable_version_write=True,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    deleted = await client.delete_version(version_id=8, confirm=True)

    assert deleted.version_id == 8
    assert deleted.confirmed is True

    await client.aclose()


@pytest.mark.asyncio
async def test_delete_board_allows_identifier_write_scope() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/queries/12" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "_type": "Query",
                    "id": 12,
                    "name": "Sprint Board",
                    "_links": {
                        "self": {"href": "/api/v3/queries/12", "title": "Sprint Board"},
                        "project": {"href": "/api/v3/projects/demo-id", "title": "Demo"},
                        "delete": {"href": "/api/v3/queries/12", "method": "delete"},
                    },
                },
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
        allowed_projects=("demo-id",),
        allowed_write_projects=("demo-id",),
        enable_board_write=True,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    deleted = await client.delete_board(board_id=12, confirm=True)

    assert deleted.board_id == 12
    assert deleted.confirmed is True

    await client.aclose()


@pytest.mark.asyncio
async def test_search_work_packages_uses_supported_subject_or_id_operator() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/work_packages"
        assert json.loads(request.url.params["filters"]) == [
            {"subject_or_id": {"operator": "**", "values": ["Feature"]}}
        ]
        return httpx.Response(200, json={"total": 0, "_embedded": {"elements": []}}, request=request)

    transport = httpx.MockTransport(handler)
    client = OpenProjectClient(make_settings(), transport=transport)

    result = await client.search_work_packages(query="Feature")

    assert result.count == 0

    await client.aclose()


@pytest.mark.asyncio
async def test_search_work_packages_accepts_status_filter() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/statuses"
        if "filters" in request.url.params:
            raise AssertionError("Did not expect filters on statuses lookup")
        if request.method != "GET":
            raise AssertionError(f"Unexpected request method for statuses: {request.method}")
        return httpx.Response(
            200,
            json={
                "_embedded": {
                    "elements": [
                        {"id": 1, "name": "New"},
                        {"id": 7, "name": "In progress"},
                    ]
                }
            },
            request=request,
        )

    status_calls = {"count": 0}

    async def routed_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/statuses":
            status_calls["count"] += 1
            return await handler(request)
        if request.url.path == "/api/v3/work_packages":
            assert json.loads(request.url.params["filters"]) == [
                {"subject_or_id": {"operator": "**", "values": ["Feature"]}},
                {"status_id": {"operator": "=", "values": ["7"]}},
            ]
            return httpx.Response(200, json={"total": 0, "_embedded": {"elements": []}}, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(routed_handler))

    result = await client.search_work_packages(query="Feature", status="In progress")

    assert result.count == 0
    assert status_calls["count"] == 1

    await client.aclose()


@pytest.mark.asyncio
async def test_allowed_projects_and_hidden_fields_filter_read_outputs() -> None:
    settings = Settings(
        base_url="https://op.example.com",
        api_token="token",
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
        allowed_projects=("demo",),
        hide_project_fields=("description",),
        hide_work_package_fields=("description",),
        hide_activity_fields=("comment",),
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}, request=request)))

    visible_project = client.normalize_project(
        {
            "id": 1,
            "name": "Demo",
            "identifier": "demo",
            "description": {"raw": "secret"},
            "_links": {},
        }
    )
    hidden_description_wp = client.normalize_work_package_detail(
        {
            "id": 42,
            "subject": "Test",
            "description": {"raw": "hidden"},
            "_links": {
                "project": {"href": "/api/v3/projects/1", "title": "Demo"},
                "activities": {"href": "/api/v3/work_packages/42/activities"},
                "relations": {"href": "/api/v3/work_packages/42/relations"},
            },
        }
    )
    activity = client.normalize_activity(
        {
            "id": 7,
            "_type": "Activity",
            "comment": {"raw": "hidden"},
            "_links": {"user": {"title": "Bot"}},
        }
    )

    assert visible_project.description is None
    assert hidden_description_wp.description is None
    assert activity.comment is None
    assert client._project_name_allowed("Demo") is True
    assert client._project_name_allowed("Other") is False

    await client.aclose()


@pytest.mark.asyncio
async def test_chain_specific_read_flags_restrict_membership_reads_with_global_read() -> None:
    settings = Settings(
        base_url="https://op.example.com",
        api_token="token",
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
        enable_membership_read=False,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}, request=r)))

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_ENABLE_MEMBERSHIP_READ"):
        await client.list_roles()

    await client.aclose()


@pytest.mark.asyncio
async def test_hidden_fields_support_wildcards_for_principal_reads() -> None:
    client = OpenProjectClient(
        Settings(
            base_url="https://op.example.com",
            api_token="token",
            timeout=12,
            verify_ssl=True,
            default_page_size=20,
            max_page_size=50,
            max_results=100,
            log_level="WARNING",
            hidden_fields={"principal": ("n*", "*mail", "url")},
        ),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}, request=request)),
    )

    principal = client.normalize_principal(
        {"id": 5, "_type": "User", "name": "Alice", "login": "alice", "email": "alice@example.com"}
    )

    assert principal.name is None
    assert principal.email is None
    assert principal.url is None
    assert principal.login == "alice"

    await client.aclose()


@pytest.mark.asyncio
async def test_hidden_project_field_is_rejected_on_write() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/form":
            return httpx.Response(
                200,
                json={"_type": "Form", "_embedded": {"schema": {}}},
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
        hide_project_fields=("description",),
        enable_project_write=True,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(InvalidInputError, match="hidden by OPENPROJECT_HIDE_PROJECT_FIELDS"):
        await client.create_project(name="Demo", identifier="demo", description="secret", confirm=False)

    await client.aclose()


@pytest.mark.asyncio
async def test_hidden_document_field_is_rejected_on_write() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/documents/5" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 5, "title": "Architecture", "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
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
        hidden_fields={"document": ("title",)},
        enable_project_write=True,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(InvalidInputError, match="hidden by OPENPROJECT_HIDE_DOCUMENT_FIELDS"):
        await client.update_document(document_id=5, title="Blocked", confirm=False)

    await client.aclose()


@pytest.mark.asyncio
async def test_hidden_work_package_field_is_rejected_on_write() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 1, "name": "Demo", "identifier": "demo", "_links": {}},
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
        hide_work_package_fields=("description",),
        enable_work_package_write=True,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(InvalidInputError, match="hidden by OPENPROJECT_HIDE_WORK_PACKAGE_FIELDS"):
        await client.create_work_package(
            project="demo",
            type="Task",
            subject="Blocked",
            description="secret",
            confirm=False,
        )

    await client.aclose()


@pytest.mark.asyncio
async def test_hidden_activity_field_is_rejected_on_write() -> None:
    client = OpenProjectClient(
        Settings(
            base_url="https://op.example.com",
            api_token="token",
            timeout=12,
            verify_ssl=True,
            default_page_size=20,
            max_page_size=50,
            max_results=100,
            log_level="WARNING",
            hide_activity_fields=("comment",),
            enable_work_package_write=True,
        ),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}, request=request)),
    )

    with pytest.raises(InvalidInputError, match="hidden by OPENPROJECT_HIDE_ACTIVITY_FIELDS"):
        await client.create_time_entry(
            activity="Development",
            hours="PT1H",
            spent_on="2026-03-20",
            comment="secret",
            confirm=False,
        )

    await client.aclose()


@pytest.mark.asyncio
async def test_hidden_time_entry_field_is_rejected_on_write() -> None:
    client = OpenProjectClient(
        Settings(
            base_url="https://op.example.com",
            api_token="token",
            timeout=12,
            verify_ssl=True,
            default_page_size=20,
            max_page_size=50,
            max_results=100,
            log_level="WARNING",
            hidden_fields={"time_entry": ("hours",)},
            enable_work_package_write=True,
        ),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}, request=request)),
    )

    with pytest.raises(InvalidInputError, match="hidden by OPENPROJECT_HIDE_TIME_ENTRY_FIELDS"):
        await client.create_time_entry(
            activity="Development",
            hours="PT1H",
            spent_on="2026-03-20",
            confirm=False,
        )

    await client.aclose()


@pytest.mark.asyncio
async def test_hidden_custom_field_is_rejected_on_write() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 1, "name": "Demo", "identifier": "demo", "_links": {}},
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
        hide_custom_fields=("Story points",),
        enable_work_package_write=True,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(InvalidInputError, match="hidden by OPENPROJECT_HIDE_CUSTOM_FIELDS"):
        await client.create_work_package(
            project="demo",
            type="Task",
            subject="Blocked",
            custom_fields={"Story points": 8},
            confirm=False,
        )

    await client.aclose()


@pytest.mark.asyncio
async def test_list_work_packages_resolves_type_and_version_filters() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo":
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
                json={
                    "_embedded": {
                        "elements": [
                            {"id": 7, "name": "Feature"},
                            {"id": 8, "name": "Task"},
                        ]
                    }
                },
                request=request,
            )
        if request.url.path == "/api/v3/projects/1/versions":
            return httpx.Response(
                200,
                json={
                    "total": 1,
                    "_embedded": {"elements": [{"id": 11, "name": "v1", "_links": {}}]},
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages":
            filters = json.loads(request.url.params.get("filters", "[]"))
            filter_keys = [list(f.keys())[0] for f in filters]
            assert "project_id" in filter_keys
            assert "type" in filter_keys
            assert "version" in filter_keys
            assert "description" in filter_keys
            return httpx.Response(
                200,
                json={
                    "total": 1,
                    "_embedded": {
                        "elements": [
                            {
                                "id": 42,
                                "subject": "Apple HealthKit Anbindung",
                                "description": {"raw": "Sync steps and calories"},
                                "_links": {
                                    "type": {"title": "Feature"},
                                    "status": {"title": "New"},
                                    "project": {"title": "Demo"},
                                    "version": {"title": "v1"},
                                },
                            }
                        ]
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    transport = httpx.MockTransport(handler)
    client = OpenProjectClient(make_settings(), transport=transport)

    result = await client.list_work_packages(
        project="demo",
        type="Feature",
        version="v1",
        has_description=True,
    )

    assert result.count == 1
    assert result.results[0].type == "Feature"
    assert result.results[0].version == "v1"
    assert result.results[0].description == "Sync steps and calories"
    assert result.results[0].has_description is True

    await client.aclose()


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
async def test_delete_work_package_auto_confirms_with_write_auto_confirm() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "subject": "Delete me later",
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
        base_url="https://op.example.com",
        api_token="token",
        enable_work_package_write=True,
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
        auto_confirm_write=True,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.delete_work_package(work_package_id=42, confirm=False)

    assert result.confirmed is True
    assert result.requires_confirmation is False
    assert result.result is None

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
    assert result.result.comment == "Please verify on staging."

    await client.aclose()


@pytest.mark.asyncio
async def test_create_relation_and_delete_relation_work_when_enabled() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42/relations" and request.method == "POST":
            body = json.loads(request.content)
            assert body["type"] == "blocks"
            assert body["_links"]["to"]["href"] == "/api/v3/work_packages/55"
            return httpx.Response(
                201,
                json={
                    "id": 650,
                    "type": "blocks",
                    "description": "Blocked until API rollout finishes",
                    "_links": {
                        "from": {"href": "/api/v3/work_packages/42", "title": "Backend API"},
                        "to": {"href": "/api/v3/work_packages/55", "title": "App integration"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/relations/650" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 650,
                    "type": "blocks",
                    "description": "Blocked until API rollout finishes",
                    "_links": {
                        "from": {"href": "/api/v3/work_packages/42", "title": "Backend API"},
                        "to": {"href": "/api/v3/work_packages/55", "title": "App integration"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/relations/650" and request.method == "DELETE":
            return httpx.Response(204, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = make_settings()
    settings = Settings(
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

    created = await client.create_work_package_relation(
        work_package_id=42,
        related_to_work_package_id=55,
        relation_type="blocks",
        description="Blocked until API rollout finishes",
        confirm=True,
    )
    assert created.confirmed is True
    assert created.result is not None
    assert created.result.to_id == 55

    deleted = await client.delete_relation(relation_id=650, confirm=True)
    assert deleted.confirmed is True
    assert deleted.result is None

    await client.aclose()


@pytest.mark.asyncio
async def test_delete_relation_auto_confirms_with_write_auto_confirm() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/relations/650" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 650,
                    "type": "blocks",
                    "_links": {
                        "from": {"href": "/api/v3/work_packages/42", "title": "Backend API"},
                        "to": {"href": "/api/v3/work_packages/55", "title": "App integration"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
                request=request,
            )
        if request.url.path == "/api/v3/relations/650" and request.method == "DELETE":
            return httpx.Response(204, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings(
        base_url="https://op.example.com",
        api_token="token",
        enable_work_package_write=True,
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
        auto_confirm_write=True,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    deleted = await client.delete_relation(relation_id=650, confirm=False)

    assert deleted.confirmed is True
    assert deleted.result is None

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
                                        {"id": 1, "name": "New", "_links": {"self": {"href": "/api/v3/statuses/1", "title": "New"}}}
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
                                        {"id": 5, "name": "Executing", "_links": {"self": {"href": "/api/v3/project_phases/5", "title": "Executing"}}}
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
                            {"id": 8, "name": "Project admin", "_links": {"self": {"href": "/api/v3/roles/8", "title": "Project admin"}}},
                            {"id": 6, "name": "Member", "_links": {"self": {"href": "/api/v3/roles/6", "title": "Member"}}},
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
                        "memberships": {"href": "/api/v3/memberships?filters=%5B%7B%22project%22%3A%7B%22operator%22%3A%22%3D%22%2C%22values%22%3A%5B%221%22%5D%7D%7D%5D"},
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
    news_preview = await client.create_news(project="demo", title="Fresh Update", summary="Ready", description="Detailed body", confirm=False)
    news_created = await client.create_news(project="demo", title="Fresh Update", summary="Ready", description="Detailed body", confirm=True)
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
async def test_time_entry_crud_and_activity_listing() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/time_entries/activities":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            {
                                "id": 3,
                                "name": "Development",
                                "position": 1,
                                "default": True,
                                "_links": {
                                    "self": {"href": "/api/v3/time_entries/activities/3"},
                                    "projects": [{"href": "/api/v3/projects/6", "title": "Demo"}],
                                },
                            }
                        ]
                    }
                },
                request=request,
            )
        if request.url.path == "/api/v3/projects/demo":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 6, "name": "Demo", "identifier": "demo"},
                request=request,
            )
        if request.url.path == "/api/v3/time_entries/form" and request.method == "POST":
            body = json.loads(request.content)
            assert body == {"_links": {"project": {"href": "/api/v3/projects/6"}}}
            return httpx.Response(
                200,
                json={
                    "_type": "Form",
                    "_embedded": {
                        "schema": {
                            "activity": {
                                "_embedded": {
                                    "allowedValues": [
                                        {
                                            "id": 3,
                                            "name": "Development",
                                            "position": 1,
                                            "default": True,
                                            "_links": {
                                                "self": {"href": "/api/v3/time_entries/activities/3"},
                                                "projects": [{"href": "/api/v3/projects/6", "title": "Demo"}],
                                            },
                                        }
                                    ]
                                }
                            }
                        }
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/time_entries" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            {
                                "id": 10,
                                "hours": "PT1H30M",
                                "spentOn": "2026-03-20",
                                "ongoing": False,
                                "comment": {"raw": "Initial implementation"},
                                "_links": {
                                    "self": {"href": "/api/v3/time_entries/10"},
                                    "project": {"href": "/api/v3/projects/6", "title": "Demo"},
                                    "entity": {"href": "/api/v3/work_packages/55", "title": "Feature A"},
                                    "user": {"href": "/api/v3/users/5", "title": "Jürgen Tauschl"},
                                    "activity": {"href": "/api/v3/time_entries/activities/3", "title": "Development"},
                                },
                                "entityType": "WorkPackage",
                            }
                        ]
                    }
                },
                request=request,
            )
        if request.url.path == "/api/v3/time_entries/10" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 10,
                    "hours": "PT1H30M",
                    "spentOn": "2026-03-20",
                    "ongoing": False,
                    "comment": {"raw": "Initial implementation"},
                    "_links": {
                        "self": {"href": "/api/v3/time_entries/10"},
                        "project": {"href": "/api/v3/projects/6", "title": "Demo"},
                        "entity": {"href": "/api/v3/work_packages/55", "title": "Feature A"},
                        "user": {"href": "/api/v3/users/5", "title": "Jürgen Tauschl"},
                        "activity": {"href": "/api/v3/time_entries/activities/3", "title": "Development"},
                    },
                    "entityType": "WorkPackage",
                },
                request=request,
            )
        if request.url.path == "/api/v3/time_entries" and request.method == "POST":
            body = json.loads(request.content)
            assert body == {
                "hours": "PT1H30M",
                "spentOn": "2026-03-20",
                "comment": {"format": "markdown", "raw": "Initial implementation"},
                "_links": {
                    "project": {"href": "/api/v3/projects/6"},
                    "activity": {"href": "/api/v3/time_entries/activities/3"},
                },
            }
            return httpx.Response(
                201,
                json={
                    "id": 11,
                    "hours": "PT1H30M",
                    "spentOn": "2026-03-20",
                    "ongoing": False,
                    "comment": {"raw": "Initial implementation"},
                    "_links": {
                        "self": {"href": "/api/v3/time_entries/11"},
                        "project": {"href": "/api/v3/projects/6", "title": "Demo"},
                        "user": {"href": "/api/v3/users/5", "title": "Jürgen Tauschl"},
                        "activity": {"href": "/api/v3/time_entries/activities/3", "title": "Development"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/time_entries/10" and request.method == "PATCH":
            body = json.loads(request.content)
            assert body == {"hours": "PT2H"}
            return httpx.Response(
                200,
                json={
                    "id": 10,
                    "hours": "PT2H",
                    "spentOn": "2026-03-20",
                    "ongoing": False,
                    "_links": {
                        "self": {"href": "/api/v3/time_entries/10"},
                        "project": {"href": "/api/v3/projects/6", "title": "Demo"},
                        "activity": {"href": "/api/v3/time_entries/activities/3", "title": "Development"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/time_entries/10" and request.method == "DELETE":
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
        allowed_projects=("demo",),
        enable_work_package_write=True,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    activities = await client.list_time_entry_activities()
    listed = await client.list_time_entries(project="demo", work_package_id=55)
    detail = await client.get_time_entry(10)
    created_preview = await client.create_time_entry(
        project="demo",
        activity="Development",
        hours="PT1H30M",
        spent_on="2026-03-20",
        comment="Initial implementation",
        confirm=False,
    )
    created = await client.create_time_entry(
        project="demo",
        activity="Development",
        hours="PT1H30M",
        spent_on="2026-03-20",
        comment="Initial implementation",
        confirm=True,
    )
    updated = await client.update_time_entry(time_entry_id=10, hours="PT2H", confirm=True)
    deleted = await client.delete_time_entry(time_entry_id=10, confirm=True)

    assert activities.count == 1
    assert activities.results[0].name == "Development"
    assert listed.count == 1
    assert listed.results[0].entity_id == 55
    assert detail.activity == "Development"
    assert created_preview.ready is True
    assert created.time_entry_id == 11
    assert updated.result is not None and updated.result.hours == "PT2H"
    assert deleted.time_entry_id == 10

    await client.aclose()


@pytest.mark.asyncio
async def test_list_time_entry_activities_paginates_project_fallback() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/time_entries/activities":
            return httpx.Response(404, request=request)
        if request.url.path == "/api/v3/projects":
            offset = request.url.params["offset"]
            if offset == "1":
                return httpx.Response(
                    200,
                    json={
                        "total": 2,
                        "_embedded": {
                            "elements": [
                                {"_type": "Project", "id": 1, "name": "Empty", "identifier": "empty", "_links": {}},
                            ]
                        },
                    },
                    request=request,
                )
            if offset == "2":
                return httpx.Response(
                    200,
                    json={
                        "total": 2,
                        "_embedded": {
                            "elements": [
                                {"_type": "Project", "id": 6, "name": "Demo", "identifier": "demo", "_links": {}},
                            ]
                        },
                    },
                    request=request,
                )
        if request.url.path == "/api/v3/time_entries/form":
            body = json.loads(request.content)
            project_href = body["_links"]["project"]["href"]
            allowed_values = []
            if project_href == "/api/v3/projects/6":
                allowed_values = [
                    {
                        "id": 3,
                        "name": "Development",
                        "_links": {
                            "self": {"href": "/api/v3/time_entries/activities/3", "title": "Development"},
                            "projects": [{"href": "/api/v3/projects/6", "title": "Demo"}],
                        },
                    }
                ]
            return httpx.Response(
                200,
                json={"_type": "Form", "_embedded": {"schema": {"activity": {"_embedded": {"allowedValues": allowed_values}}}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings(
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

    activities = await client.list_time_entry_activities()

    assert activities.count == 1
    assert activities.results[0].name == "Development"

    await client.aclose()


@pytest.mark.asyncio
async def test_list_time_entry_activities_falls_back_across_visible_projects() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/time_entries/activities":
            return httpx.Response(404, request=request)
        if request.url.path == "/api/v3/projects":
            return httpx.Response(
                200,
                json={
                    "total": 2,
                    "_embedded": {
                        "elements": [
                            {"_type": "Project", "id": 1, "name": "Empty", "identifier": "empty", "_links": {}},
                            {"_type": "Project", "id": 6, "name": "Demo", "identifier": "demo", "_links": {}},
                        ]
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/time_entries/form":
            body = json.loads(request.content)
            project_href = body["_links"]["project"]["href"]
            if project_href == "/api/v3/projects/1":
                allowed_values = []
            elif project_href == "/api/v3/projects/6":
                allowed_values = [
                    {
                        "id": 3,
                        "name": "Development",
                        "_links": {
                            "self": {"href": "/api/v3/time_entries/activities/3", "title": "Development"},
                            "projects": [{"href": "/api/v3/projects/6", "title": "Demo"}],
                        },
                    }
                ]
            else:
                raise AssertionError(f"Unexpected project href: {project_href}")
            return httpx.Response(
                200,
                json={
                    "_type": "Form",
                    "_embedded": {
                        "schema": {
                            "activity": {
                                "_embedded": {"allowedValues": allowed_values},
                            }
                        }
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))

    activities = await client.list_time_entry_activities()

    assert activities.count == 1
    assert activities.results[0].name == "Development"

    await client.aclose()


@pytest.mark.asyncio
async def test_list_time_entry_activities_skips_projects_without_form_access() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/time_entries/activities":
            return httpx.Response(404, request=request)
        if request.url.path == "/api/v3/projects":
            return httpx.Response(
                200,
                json={
                    "total": 2,
                    "_embedded": {
                        "elements": [
                            {"_type": "Project", "id": 7, "name": "Blocked", "identifier": "blocked", "_links": {}},
                            {"_type": "Project", "id": 6, "name": "Demo", "identifier": "demo-id", "_links": {}},
                        ]
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/time_entries/form":
            body = json.loads(request.content)
            project_href = body["_links"]["project"]["href"]
            if project_href == "/api/v3/projects/7":
                return httpx.Response(403, json={"message": "Forbidden"}, request=request)
            if project_href == "/api/v3/projects/6":
                return httpx.Response(
                    200,
                    json={
                        "_type": "Form",
                        "_embedded": {
                            "schema": {
                                "activity": {
                                    "_embedded": {
                                        "allowedValues": [
                                            {
                                                "id": 3,
                                                "name": "Development",
                                                "_links": {
                                                    "self": {"href": "/api/v3/time_entries/activities/3", "title": "Development"},
                                                    "projects": [{"href": "/api/v3/projects/6", "title": "Demo"}],
                                                },
                                            }
                                        ]
                                    }
                                }
                            }
                        },
                    },
                    request=request,
                )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))

    activities = await client.list_time_entry_activities()

    assert activities.count == 1
    assert activities.results[0].name == "Development"

    await client.aclose()


@pytest.mark.asyncio
async def test_global_list_work_packages_and_versions_respect_allowlist_ids() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages":
            return httpx.Response(
                200,
                json={
                    "total": 2,
                    "_embedded": {
                        "elements": [
                            {
                                "id": 42,
                                "subject": "Visible task",
                                "_links": {
                                    "type": {"title": "Task"},
                                    "status": {"title": "Open"},
                                    "project": {"href": "/api/v3/projects/6", "title": "Demo"},
                                },
                            },
                            {
                                "id": 99,
                                "subject": "Hidden task",
                                "_links": {
                                    "type": {"title": "Task"},
                                    "status": {"title": "Open"},
                                    "project": {"href": "/api/v3/projects/7", "title": "Other"},
                                },
                            },
                        ]
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/versions":
            return httpx.Response(
                200,
                json={
                    "total": 2,
                    "_embedded": {
                        "elements": [
                            {
                                "id": 1,
                                "name": "Visible version",
                                "_links": {"definingProject": {"href": "/api/v3/projects/6", "title": "Demo"}},
                            },
                            {
                                "id": 2,
                                "name": "Hidden version",
                                "_links": {"definingProject": {"href": "/api/v3/projects/7", "title": "Other"}},
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
        allowed_projects=("6",),
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    work_packages = await client.list_work_packages()
    versions = await client.list_versions()

    assert work_packages.count == 1
    assert work_packages.total == 1
    assert work_packages.results[0].id == 42
    assert versions.count == 1
    assert versions.total == 1
    assert versions.results[0].id == 1

    await client.aclose()


@pytest.mark.asyncio
async def test_list_my_open_work_packages_filters_total_when_all_items_blocked_by_allowlist() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/users/me":
            return httpx.Response(
                200,
                json={"id": 5, "name": "Demo User", "login": "demo"},
                request=request,
            )
        if request.url.path == "/api/v3/work_packages":
            return httpx.Response(
                200,
                json={
                    "total": 3,
                    "_embedded": {
                        "elements": [
                            {
                                "id": 101,
                                "subject": "Hidden A",
                                "_links": {
                                    "type": {"title": "Task"},
                                    "status": {"title": "Open"},
                                    "project": {"href": "/api/v3/projects/7", "title": "Other"},
                                },
                            },
                            {
                                "id": 102,
                                "subject": "Hidden B",
                                "_links": {
                                    "type": {"title": "Task"},
                                    "status": {"title": "Open"},
                                    "project": {"href": "/api/v3/projects/7", "title": "Other"},
                                },
                            },
                            {
                                "id": 103,
                                "subject": "Hidden C",
                                "_links": {
                                    "type": {"title": "Task"},
                                    "status": {"title": "Open"},
                                    "project": {"href": "/api/v3/projects/8", "title": "Another"},
                                },
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
        allowed_projects=("6",),
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.list_my_open_work_packages(limit=20, offset=1)

    assert result.results == []
    assert result.count == 0
    assert result.total == 0
    assert result.next_offset is None
    assert result.truncated is False

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
        allowed_projects=("demo",),
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
async def test_create_time_entry_resolves_activity_from_project_form_context() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 6, "name": "Demo", "identifier": "demo"},
                request=request,
            )
        if request.url.path == "/api/v3/time_entries/form":
            body = json.loads(request.content)
            assert body == {"_links": {"project": {"href": "/api/v3/projects/6"}}}
            return httpx.Response(
                200,
                json={
                    "_type": "Form",
                    "_embedded": {
                        "schema": {
                            "activity": {
                                "_embedded": {
                                    "allowedValues": [
                                        {
                                            "id": 3,
                                            "name": "Development",
                                            "_links": {
                                                "self": {"href": "/api/v3/time_entries/activities/3", "title": "Development"},
                                                "projects": [{"href": "/api/v3/projects/6", "title": "Demo"}],
                                            },
                                        }
                                    ]
                                }
                            }
                        }
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/time_entries" and request.method == "POST":
            body = json.loads(request.content)
            assert body == {
                "hours": "PT15M",
                "spentOn": "2026-03-20",
                "_links": {
                    "project": {"href": "/api/v3/projects/6"},
                    "activity": {"href": "/api/v3/time_entries/activities/3"},
                },
            }
            return httpx.Response(
                201,
                json={
                    "id": 11,
                    "hours": "PT15M",
                    "spentOn": "2026-03-20",
                    "_links": {
                        "self": {"href": "/api/v3/time_entries/11"},
                        "project": {"href": "/api/v3/projects/6", "title": "Demo"},
                        "activity": {"href": "/api/v3/time_entries/activities/3", "title": "Development"},
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
        enable_work_package_write=True,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    created = await client.create_time_entry(
        project="demo",
        activity="Development",
        hours="PT15M",
        spent_on="2026-03-20",
        confirm=True,
    )

    assert created.confirmed is True
    assert created.result is not None
    assert created.result.activity == "Development"

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
        allowed_projects=("Demo",),
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    searched = await client.search_work_packages(query="Scoped", project="6")
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
        allowed_projects=("demo",),
        enable_work_package_write=True,
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
async def test_version_crud_uses_form_endpoints_and_commit_paths() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 6, "name": "Demo", "identifier": "demo"},
                request=request,
            )
        if request.url.path == "/api/v3/versions/form":
            body = json.loads(request.content)
            assert body == {
                "name": "Release 1",
                "description": {"format": "plain", "raw": "Initial rollout"},
                "startDate": "2026-04-01",
                "endDate": "2026-04-30",
                "status": "open",
                "sharing": "none",
                "_links": {"definingProject": {"href": "/api/v3/projects/6"}},
            }
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "payload": body,
                        "validationErrors": {},
                    }
                },
                request=request,
            )
        if request.url.path == "/api/v3/versions" and request.method == "POST":
            body = json.loads(request.content)
            assert body["name"] == "Release 1"
            return httpx.Response(
                201,
                json={
                    "id": 8,
                    "name": "Release 1",
                    "status": "open",
                    "sharing": "none",
                    "startDate": "2026-04-01",
                    "endDate": "2026-04-30",
                    "description": {"raw": "Initial rollout"},
                    "_links": {"definingProject": {"title": "Demo"}},
                },
                request=request,
            )
        if request.url.path == "/api/v3/versions/8" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 8,
                    "name": "Release 1",
                    "status": "open",
                    "sharing": "none",
                    "startDate": "2026-04-01",
                    "endDate": "2026-04-30",
                    "description": {"raw": "Initial rollout"},
                    "_links": {"definingProject": {"title": "Demo"}},
                },
                request=request,
            )
        if request.url.path == "/api/v3/versions/8/form":
            body = json.loads(request.content)
            assert body == {"name": "Release 1.1", "status": "locked"}
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "payload": body,
                        "validationErrors": {},
                    }
                },
                request=request,
            )
        if request.url.path == "/api/v3/versions/8" and request.method == "PATCH":
            body = json.loads(request.content)
            assert body == {"name": "Release 1.1", "status": "locked"}
            return httpx.Response(
                200,
                json={
                    "id": 8,
                    "name": "Release 1.1",
                    "status": "locked",
                    "sharing": "none",
                    "startDate": "2026-04-01",
                    "endDate": "2026-04-30",
                    "description": {"raw": "Initial rollout"},
                    "_links": {"definingProject": {"title": "Demo"}},
                },
                request=request,
            )
        if request.url.path == "/api/v3/versions/8" and request.method == "DELETE":
            return httpx.Response(204, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings(
        base_url="https://op.example.com",
        api_token="token",
        enable_version_write=True,
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    created_preview = await client.create_version(
        project="demo",
        name="Release 1",
        description="Initial rollout",
        start_date="2026-04-01",
        end_date="2026-04-30",
        status="open",
        sharing="none",
        confirm=False,
    )
    assert created_preview.ready is True
    assert created_preview.requires_confirmation is True

    created = await client.create_version(
        project="demo",
        name="Release 1",
        description="Initial rollout",
        start_date="2026-04-01",
        end_date="2026-04-30",
        status="open",
        sharing="none",
        confirm=True,
    )
    assert created.version_id == 8
    assert created.result is not None
    assert created.result.name == "Release 1"

    updated = await client.update_version(version_id=8, name="Release 1.1", status="locked", confirm=True)
    assert updated.result is not None
    assert updated.result.status == "locked"

    deleted_preview = await client.delete_version(version_id=8, confirm=False)
    assert deleted_preview.ready is True
    assert deleted_preview.requires_confirmation is True

    deleted = await client.delete_version(version_id=8, confirm=True)
    assert deleted.confirmed is True
    assert deleted.version_id == 8

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
                            query_payload(query_id=13, name="Other Board", project_title="Other", project_href="/api/v3/projects/9"),
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
        allowed_projects=("demo",),
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
        allowed_projects=("demo",),
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
                                            {"id": 9, "name": "High", "_links": {"self": {"href": "/api/v3/priorities/9", "title": "High"}}}
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
                                            {"id": 5, "name": "Executing", "_links": {"self": {"href": "/api/v3/project_phases/5", "title": "Executing"}}}
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
                                            {"id": 20, "name": "iOS", "_links": {"self": {"href": "/api/v3/custom_options/20", "title": "iOS"}}}
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
async def test_user_and_group_endpoints_normalize_results() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/users":
            return httpx.Response(
                200,
                json={
                    "total": 1,
                    "_embedded": {
                        "elements": [
                            {
                                "id": 5,
                                "name": "Alice Example",
                                "login": "alice",
                                "email": "alice@example.com",
                                "status": "active",
                                "admin": True,
                                "locked": False,
                                "createdAt": "2026-01-01T00:00:00Z",
                                "updatedAt": "2026-01-02T00:00:00Z",
                                "_links": {"avatar": {"href": "/avatars/5.png"}},
                            }
                        ]
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/users/5":
            return httpx.Response(
                200,
                json={
                    "id": 5,
                    "name": "Alice Example",
                    "login": "alice",
                    "email": "alice@example.com",
                    "status": "active",
                    "admin": True,
                    "locked": False,
                    "language": "en",
                    "createdAt": "2026-01-01T00:00:00Z",
                    "updatedAt": "2026-01-02T00:00:00Z",
                    "_links": {
                        "avatar": {"href": "/avatars/5.png"},
                        "showUser": {"href": "/users/5"},
                        "authSource": {"title": "LDAP"},
                        "groups": [{"title": "Admins"}],
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/groups":
            return httpx.Response(
                200,
                json={
                    "total": 1,
                    "_embedded": {
                        "elements": [
                            {
                                "id": 7,
                                "name": "Platform Team",
                                "createdAt": "2026-01-01T00:00:00Z",
                                "updatedAt": "2026-01-02T00:00:00Z",
                                "_embedded": {"members": {"count": 2}},
                                "_links": {"update": {"href": "/api/v3/groups/7"}, "delete": {"href": "/api/v3/groups/7"}},
                            }
                        ]
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/groups/7":
            return httpx.Response(
                200,
                json={
                    "id": 7,
                    "name": "Platform Team",
                    "createdAt": "2026-01-01T00:00:00Z",
                    "updatedAt": "2026-01-02T00:00:00Z",
                    "_embedded": {"members": {"count": 2, "elements": [{"name": "Alice"}, {"name": "Bob"}]}},
                    "_links": {
                        "memberships": {"href": "/api/v3/groups/7/memberships"},
                        "update": {"href": "/api/v3/groups/7"},
                        "delete": {"href": "/api/v3/groups/7"},
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))

    users = await client.list_users(search="alice")
    user = await client.get_user("5")
    groups = await client.list_groups(search="platform")
    group = await client.get_group(7)

    assert users.count == 1
    assert users.results[0].email == "alice@example.com"
    assert user.language == "en"
    assert user.groups == ["Admins"]
    assert groups.count == 1
    assert groups.results[0].member_count == 2
    assert group.members == ["Alice", "Bob"]

    await client.aclose()


@pytest.mark.asyncio
async def test_actions_capabilities_and_query_metadata_endpoints_normalize_results() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 1, "name": "Demo", "identifier": "demo", "_links": {}},
                request=request,
            )
        if request.url.path == "/api/v3/actions":
            return httpx.Response(
                200,
                json={"total": 1, "_embedded": {"elements": [{"name": "update", "description": "Update resource", "_links": {"self": {"href": "/api/v3/actions/update"}}}]}},
                request=request,
            )
        if request.url.path == "/api/v3/capabilities":
            assert request.url.params.get("filters") == '[{"context":{"operator":"=","values":["p1"]}}]'
            return httpx.Response(
                200,
                json={
                    "total": 1,
                    "_embedded": {
                        "elements": [
                            {
                                "name": "canUpdate",
                                "_links": {
                                    "self": {"href": "/api/v3/capabilities/update-project"},
                                    "action": {"href": "/api/v3/actions/update", "title": "update"},
                                    "principal": {"href": "/api/v3/users/5", "title": "Alice"},
                                    "context": {"title": "Demo"},
                                },
                            }
                        ]
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/queries/filters/assignee":
            return httpx.Response(
                200,
                json={"name": "Assignee", "_links": {"self": {"href": "/api/v3/queries/filters/assignee"}}},
                request=request,
            )
        if request.url.path == "/api/v3/queries/columns/subject":
            return httpx.Response(
                200,
                json={"name": "Subject", "_links": {"self": {"href": "/api/v3/queries/columns/subject"}}},
                request=request,
            )
        if request.url.path in {"/api/v3/queries/operators/%3D", "/api/v3/queries/operators/="}:
            return httpx.Response(
                200,
                json={"name": "Equals", "_links": {"self": {"href": "/api/v3/queries/operators/%3D"}}},
                request=request,
            )
        if request.url.path in {"/api/v3/queries/sort_bys/subject%3Aasc", "/api/v3/queries/sort_bys/subject:asc"}:
            return httpx.Response(
                200,
                json={"name": "Subject asc", "direction": "asc", "_links": {"self": {"href": "/api/v3/queries/sort_bys/subject:asc"}, "column": {"title": "Subject"}}},
                request=request,
            )
        if request.url.path == "/api/v3/queries/filter_instance_schemas":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            {
                                "_links": {"self": {"href": "/api/v3/queries/filter_instance_schemas/assignee"}, "filter": {"title": "Assignee"}},
                                "_dependencies": [{"dependencies": {"=": {}, "!": {}}}],
                            }
                        ]
                    }
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))

    actions = await client.list_actions()
    capabilities = await client.list_capabilities(project="demo")
    filter_ = await client.get_query_filter("assignee")
    column = await client.get_query_column("subject")
    operator = await client.get_query_operator("=")
    sort_by = await client.get_query_sort_by("subject:asc")
    schemas = await client.list_query_filter_instance_schemas()

    assert actions.count == 1
    assert actions.results[0].id == "update"
    assert capabilities.count == 1
    assert capabilities.results[0].principal_name == "Alice"
    assert filter_.id == "assignee"
    assert column.id == "subject"
    assert operator.id == "="
    assert sort_by.direction == "asc"
    assert schemas.count == 1
    assert schemas.results[0].operator_count == 2

    await client.aclose()


@pytest.mark.asyncio
async def test_user_preferences_get_and_update() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/my_preferences" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 1,
                    "lang": "en",
                    "timeZone": "Europe/Berlin",
                    "commentSortDescending": False,
                    "warnOnLeavingUnsaved": True,
                    "autoHidePopups": False,
                    "updatedAt": "2026-03-20T10:00:00Z",
                },
                request=request,
            )
        if request.url.path == "/api/v3/my_preferences" and request.method == "PATCH":
            body = json.loads(request.content)
            assert body["lang"] == "de"
            assert body["timeZone"] == "America/New_York"
            return httpx.Response(
                200,
                json={
                    "id": 1,
                    "lang": "de",
                    "timeZone": "America/New_York",
                    "commentSortDescending": False,
                    "warnOnLeavingUnsaved": True,
                    "autoHidePopups": False,
                    "updatedAt": "2026-03-20T11:00:00Z",
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = make_settings()
    settings = Settings(
        base_url=settings.base_url,
        api_token=settings.api_token,
        timeout=settings.timeout,
        verify_ssl=settings.verify_ssl,
        default_page_size=settings.default_page_size,
        max_page_size=settings.max_page_size,
        max_results=settings.max_results,
        log_level=settings.log_level,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    prefs = await client.get_my_preferences()
    assert prefs.lang == "en"
    assert prefs.time_zone == "Europe/Berlin"
    assert prefs.comment_sort_descending is False

    preview = await client.update_my_preferences(lang="de", time_zone="America/New_York", confirm=False)
    assert preview.requires_confirmation is True

    updated = await client.update_my_preferences(lang="de", time_zone="America/New_York", confirm=True)
    assert updated.result is not None
    assert updated.result.lang == "de"
    assert updated.result.time_zone == "America/New_York"

    await client.aclose()


@pytest.mark.asyncio
async def test_update_my_preferences_needs_no_write_gate() -> None:
    """update_my_preferences has no write gate — it works without any write flags."""
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/my_preferences" and request.method == "PATCH":
            return httpx.Response(200, json={"_type": "UserPreferences"}, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))
    result = await client.update_my_preferences(lang="de", confirm=True)
    assert result.confirmed
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
async def test_list_relations_and_update_relation() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/relations" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "total": 1,
                    "_embedded": {
                        "elements": [
                            {
                                "id": 7,
                                "type": "blocks",
                                "description": None,
                                "_links": {
                                    "from": {"href": "/api/v3/work_packages/1", "title": "Task A"},
                                    "to": {"href": "/api/v3/work_packages/2", "title": "Task B"},
                                },
                            }
                        ]
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/relations/7" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 7,
                    "type": "blocks",
                    "description": None,
                    "_links": {
                        "from": {"href": "/api/v3/work_packages/1", "title": "Task A"},
                        "to": {"href": "/api/v3/work_packages/2", "title": "Task B"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/relations/7" and request.method == "PATCH":
            body = json.loads(request.content)
            assert body["description"] == "updated"
            return httpx.Response(
                200,
                json={
                    "id": 7,
                    "type": "blocks",
                    "description": "updated",
                    "_links": {
                        "from": {"href": "/api/v3/work_packages/1", "title": "Task A"},
                        "to": {"href": "/api/v3/work_packages/2", "title": "Task B"},
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
        enable_work_package_write=True,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    relations = await client.list_relations()
    assert relations.count == 1
    assert relations.results[0].type == "blocks"

    preview = await client.update_relation(relation_id=7, description="updated", confirm=False)
    assert preview.requires_confirmation is True

    updated = await client.update_relation(relation_id=7, description="updated", confirm=True)
    assert updated.result is not None
    assert updated.result.type == "blocks"

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
                        "validationErrors": {
                            "identifier": {"message": "Identifier has already been taken."}
                        },
                    }
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings(
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
async def test_create_version_returns_preview_when_not_confirmed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/myproject":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 5, "name": "My Project", "identifier": "myproject"},
                request=request,
            )
        if request.url.path == "/api/v3/versions/form" and request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "payload": {"name": "v2.0", "_links": {"definingProject": {"href": "/api/v3/projects/5"}}},
                        "validationErrors": {},
                    }
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings(
        base_url="https://op.example.com",
        api_token="token",
        enable_version_write=True,
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.create_version(project="myproject", name="v2.0", confirm=False)

    assert result.confirmed is False
    assert result.requires_confirmation is True
    assert result.ready is True
    assert result.validation_errors == {}

    await client.aclose()


@pytest.mark.asyncio
async def test_create_version_rejects_validation_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/myproject":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 5, "name": "My Project", "identifier": "myproject"},
                request=request,
            )
        if request.url.path == "/api/v3/versions/form" and request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "payload": {},
                        "validationErrors": {"name": {"message": "Name is too long."}},
                    }
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings(
        base_url="https://op.example.com",
        api_token="token",
        enable_version_write=True,
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.create_version(project="myproject", name="v2.0", confirm=True)

    assert result.ready is False
    assert result.confirmed is False
    assert "name" in result.validation_errors

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
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.create_board(name="", confirm=True)

    assert result.ready is False
    assert result.confirmed is False
    assert "name" in result.validation_errors

    await client.aclose()


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
        "allowed_projects": ("demo",),
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


@pytest.mark.asyncio
async def test_update_grid_preview_mode() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/grids/55" and request.method == "GET":
            return httpx.Response(200, json=_make_grid_payload(), request=request)
        if request.url.path == "/api/v3/projects/demo":
            return httpx.Response(200, json={"_type": "Project", "id": 1, "name": "Demo", "identifier": "demo", "_links": {}}, request=request)
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
            return httpx.Response(200, json={"_type": "Project", "id": 1, "name": "Demo", "identifier": "demo", "_links": {}}, request=request)
        if request.url.path == "/api/v3/grids/55/form":
            body = json.loads(request.content)
            return httpx.Response(200, json={"_embedded": {"payload": {**body, "_links": {"scope": {"href": "/projects/demo"}}}, "validationErrors": {}}}, request=request)
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
            return httpx.Response(200, json={"_type": "Project", "id": 1, "name": "Demo", "identifier": "demo", "_links": {}}, request=request)
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
            return httpx.Response(200, json={"_type": "Project", "id": 1, "name": "Demo", "identifier": "demo", "_links": {}}, request=request)
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
                    json={"_type": "Form", "_embedded": {"payload": body, "validationErrors": {"subject": {"message": "too short"}}}},
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
async def test_bulk_update_work_packages_preview_mode() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/10" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 10, "subject": "Old 10", "lockVersion": 1,
                    "_links": {
                        "project": {"title": "Demo", "href": "/api/v3/projects/1"},
                        "status": {"title": "New"}, "type": {"title": "Task"},
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
                    "id": 20, "subject": "Old 20", "lockVersion": 2,
                    "_links": {
                        "project": {"title": "Demo", "href": "/api/v3/projects/1"},
                        "status": {"title": "New"}, "type": {"title": "Task"},
                        "activities": {"href": "/api/v3/work_packages/20/activities"},
                        "relations": {"href": "/api/v3/work_packages/20/relations"},
                    },
                },
                request=request,
            )
        if request.url.path in {"/api/v3/work_packages/10/form", "/api/v3/work_packages/20/form"}:
            body = json.loads(request.content)
            return _make_wp_form_response(request, body)
        if request.url.path == "/api/v3/statuses":
            return httpx.Response(200, json={"_embedded": {"elements": [{"id": 5, "name": "In progress"}]}}, request=request)
        raise AssertionError(f"Unexpected: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))
    result = await client.bulk_update_work_packages(
        items=[
            {"work_package_id": 10, "subject": "New 10"},
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
                    "id": 20, "subject": "Old 20", "lockVersion": 1,
                    "_links": {
                        "project": {"title": "Demo", "href": "/api/v3/projects/1"},
                        "status": {"title": "New"}, "type": {"title": "Task"},
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


def test_extract_formattable_text_trims_large_payloads() -> None:
    value = {
        "raw": "word " * 400,
        "html": "<p>ignored</p>",
    }

    trimmed = _extract_formattable_text(value)

    assert trimmed is not None
    assert len(trimmed) <= 1200
    assert trimmed.endswith("…")


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


@pytest.mark.asyncio
async def test_get_work_package_numeric_reference_hits_canonical_path() -> None:
    paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/v3/work_packages/42":
            paths.append(request.url.path)
            return httpx.Response(200, json=_wp_detail_payload(42, "42"), request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))

    detail = await client.get_work_package("42")

    assert detail.id == 42
    # Exactly one request, straight to the canonical numeric path. No lookup roundtrip.
    assert paths == ["/api/v3/work_packages/42"]

    await client.aclose()


@pytest.mark.asyncio
async def test_get_work_package_semantic_reference_passes_through_to_path() -> None:
    # OpenProject 17.5+ resolves a project-prefixed identifier server-side on the
    # work_packages/{id} endpoint, so the reference is sent through the path verbatim.
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/v3/work_packages/PROJ-123":
            return httpx.Response(200, json=_wp_detail_payload(412, "PROJ-123"), request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))

    detail = await client.get_work_package("PROJ-123")

    assert detail.id == 412
    assert detail.display_id == "PROJ-123"

    await client.aclose()


@pytest.mark.asyncio
async def test_get_work_package_unknown_reference_maps_404_to_not_found() -> None:
    # On instances without semantic identifiers a project-prefixed reference simply
    # yields a 404, which must surface as NotFoundError (backwards compatible).
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/PROJ-999":
            return httpx.Response(404, json={"message": "Not found"}, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))

    with pytest.raises(NotFoundError):
        await client.get_work_package("PROJ-999")

    await client.aclose()


@pytest.mark.asyncio
async def test_resolve_work_package_id_returns_numeric_id_for_semantic_reference() -> None:
    # The numeric-id resolver (used where the canonical id itself is needed, e.g. the
    # relations "involved" filter) fetches the WP for a semantic ref and reads back id;
    # a numeric ref short-circuits without any request.
    requests: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/api/v3/work_packages/PROJ-7":
            return httpx.Response(200, json=_wp_detail_payload(55, "PROJ-7"), request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))

    assert await client._resolve_work_package_id(99) == 99
    assert requests == []  # numeric short-circuit, no API call

    assert await client._resolve_work_package_id("PROJ-7") == 55
    assert requests == ["/api/v3/work_packages/PROJ-7"]

    await client.aclose()


def _write_enabled_settings() -> Settings:
    s = make_settings()
    return Settings(
        base_url=s.base_url,
        api_token=s.api_token,
        enable_work_package_write=True,
        timeout=s.timeout,
        verify_ssl=s.verify_ssl,
        default_page_size=s.default_page_size,
        max_page_size=s.max_page_size,
        max_results=s.max_results,
        log_level=s.log_level,
    )


@pytest.mark.asyncio
async def test_toggle_activity_emoji_reaction_patches_and_normalizes() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
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

    result = await client.toggle_activity_emoji_reaction(1988, "heart")

    assert result.count == 1
    assert result.results[0].reaction == "heart"
    assert result.results[0].emoji == "❤️"
    assert result.results[0].count == 2
    assert result.results[0].users == ["Alice", "Bob"]

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
async def test_create_work_package_reminder_posts_and_normalizes() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 42, "_links": {"project": {"href": "/api/v3/projects/1"}}},
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42/reminders" and request.method == "POST":
            assert json.loads(request.content) == {"remindAt": "2026-12-01T09:00:00Z", "note": "n"}
            return httpx.Response(
                201,
                json={
                    "_type": "Reminder",
                    "id": 7,
                    "remindAt": "2026-12-01T09:00:00.000Z",
                    "note": "n",
                    "_embedded": {"creator": {"name": "Alice"}},
                    "_links": {
                        "self": {"href": "/api/v3/reminders/7"},
                        "remindable": {"href": "/api/v3/work_packages/42"},
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_write_enabled_settings(), transport=httpx.MockTransport(handler))

    result = await client.create_work_package_reminder(
        work_package_id=42, remind_at="2026-12-01T09:00:00Z", note="n", confirm=True
    )

    assert result.confirmed is True
    assert result.reminder_id == 7
    assert result.result is not None
    assert result.result.work_package_id == 42
    assert result.result.creator == "Alice"

    await client.aclose()


@pytest.mark.asyncio
async def test_update_reminder_requires_a_field() -> None:
    client = OpenProjectClient(
        _write_enabled_settings(),
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}, request=r)),
    )

    with pytest.raises(InvalidInputError, match="At least one field"):
        await client.update_reminder(reminder_id=7, confirm=True)

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

    settings = make_settings()
    settings = Settings(
        base_url=settings.base_url,
        api_token=settings.api_token,
        enable_project_write=True,
        allowed_write_projects=("demo",),
        timeout=settings.timeout,
        verify_ssl=settings.verify_ssl,
        default_page_size=settings.default_page_size,
        max_page_size=settings.max_page_size,
        max_results=settings.max_results,
        log_level=settings.log_level,
    )
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

    settings = make_settings()
    settings = Settings(
        base_url=settings.base_url,
        api_token=settings.api_token,
        enable_project_write=True,
        allowed_write_projects=("demo",),
        timeout=settings.timeout,
        verify_ssl=settings.verify_ssl,
        default_page_size=settings.default_page_size,
        max_page_size=settings.max_page_size,
        max_results=settings.max_results,
        log_level=settings.log_level,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(NotFoundError, match="Project favorites requires OpenProject 17.0"):
        await client.add_project_favorite(project="demo", confirm=True)

    await client.aclose()


@pytest.mark.asyncio
async def test_list_work_packages_version_status_builds_filter() -> None:
    captured: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages" and request.method == "GET":
            captured["filters"] = request.url.params.get("filters", "")
            return httpx.Response(200, json={"_embedded": {"elements": []}, "total": 0}, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))

    await client.list_work_packages(version_status="closed")

    filters = json.loads(captured["filters"])
    version_filter = next(f for f in filters if "version" in f)
    assert version_filter["version"]["operator"] == "c"
    assert version_filter["version"]["values"] == []

    await client.aclose()


@pytest.mark.asyncio
async def test_create_time_entry_includes_start_and_end_time() -> None:
    captured: dict[str, dict] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
                request=request,
            )
        if request.url.path == "/api/v3/time_entries" and request.method == "POST":
            captured["body"] = json.loads(request.content)
            return httpx.Response(
                201,
                json={"id": 9, "spentOn": "2026-07-01", "startTime": "2026-07-01T09:00:00Z",
                      "endTime": "2026-07-01T10:00:00Z", "_links": {}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_write_enabled_settings(), transport=httpx.MockTransport(handler))

    result = await client.create_time_entry(
        work_package_id=42,
        activity=None,
        hours="PT1H",
        spent_on="2026-07-01",
        start_time="2026-07-01T09:00:00Z",
        end_time="2026-07-01T10:00:00Z",
        confirm=True,
    )

    assert captured["body"]["startTime"] == "2026-07-01T09:00:00Z"
    assert captured["body"]["endTime"] == "2026-07-01T10:00:00Z"
    assert result.result is not None
    assert result.result.start_time == "2026-07-01T09:00:00Z"
    assert result.result.end_time == "2026-07-01T10:00:00Z"

    await client.aclose()
