from __future__ import annotations

import httpx
import pytest
from _client_test_helpers import _base_settings

from openproject_ce_mcp.client import (
    OpenProjectClient,
    PermissionDeniedError,
    ProjectResolutionContext,
)
from openproject_ce_mcp.config import Settings


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
        read_projects=("*",),
        write_projects=("*",),
        enable_work_package_write=False,
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
        read_projects=("*",),
        write_projects=("demo",),
        enable_board_write=True,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
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
        read_projects=("*",),
        write_projects=("demo",),
        enable_work_package_write=True,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
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
            "OPENPROJECT_READ_PROJECTS": "*",
            "OPENPROJECT_WRITE_PROJECTS": "",
        }
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await client.create_board(name="Sprint Board", project="demo", confirm=False)

    await client.aclose()


@pytest.mark.asyncio
async def test_empty_read_projects_denies_project_scoped_read() -> None:
    # The true production default (no scope override at all) must deny,
    # not allow — constructed directly, not via make_settings()'s permissive default.
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

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"_type": "Project", "id": 1, "name": "Demo", "identifier": "demo", "_links": {}},
            request=request,
        )

    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await client.get_project("demo")

    await client.aclose()


@pytest.mark.asyncio
async def test_empty_write_projects_denies_project_scoped_write() -> None:
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
        enable_project_write=True,
        read_projects=("*",),
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await client.update_project(project_ref="demo", name="New Name", confirm=True)

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
            "OPENPROJECT_READ_PROJECTS": "demo",
            "OPENPROJECT_WRITE_PROJECTS": "*",
        }
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await client.create_board(name="Other Board", project="other", confirm=False)

    await client.aclose()


@pytest.mark.parametrize(
    "check",
    [
        lambda client: client._ensure_project_write_allowed("other"),
        lambda client: client._ensure_project_write_link_allowed({"href": "/api/v3/projects/other"}),
        lambda client: client._ensure_board_write_payload_allowed(
            {"_links": {"project": {"href": "/api/v3/projects/other"}}}
        ),
    ],
)
@pytest.mark.asyncio
async def test_write_is_always_a_subset_of_read_scope(check) -> None:
    # Architecture-level guarantee, not just a single-method test: an
    # unrestricted write_projects can never rescue a project excluded by
    # read_projects — read is always checked first, across every write path.
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
        enable_board_write=True,
        read_projects=("other-project",),
        write_projects=("*",),
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(lambda r: httpx.Response(200, request=r)))

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        check(client)

    await client.aclose()


@pytest.mark.asyncio
async def test_initialize_skips_project_fetch_when_both_scopes_allow_all() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(read_projects=("*",), write_projects=("*",))
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    await client.initialize()

    assert client._project_id_to_identifier == {}
    await client.aclose()


@pytest.mark.asyncio
async def test_initialize_populates_identifier_cache_for_restricted_write_scope_even_when_read_is_open() -> None:
    # Regression: initialize() used to bail out entirely whenever read_projects
    # allowed all, without considering that write_projects might still be
    # restricted and need the id->identifier cache for link-based matching
    # (_project_candidates only has the numeric id + display name from an
    # embedded HAL link, never the identifier itself, unless this cache fills
    # it in). READ="*" + WRITE="OPM" is exactly the config that exposed this.
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/projects"
        return httpx.Response(
            200,
            json={
                "_embedded": {
                    "elements": [
                        {"id": 7, "identifier": "OPM", "name": "OPM OpenProject CE MCP"},
                        {"id": 16, "identifier": "ENC", "name": "ENC Encore ST"},
                    ]
                }
            },
            request=request,
        )

    settings = _base_settings(read_projects=("*",), write_projects=("OPM",))
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    await client.initialize()

    assert client._project_id_to_identifier == {7: "OPM"}
    await client.aclose()


@pytest.mark.asyncio
async def test_write_link_allowlist_recognizes_identifier_after_initialize_with_open_read_scope() -> None:
    # End-to-end proof of the same regression: a work-package-style embedded
    # project link (numeric id + display name only, no identifier field) must
    # be recognized against an identifier-based WRITE_PROJECTS entry once
    # initialize() has run, even though READ_PROJECTS is wide open.
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/projects"
        return httpx.Response(
            200,
            json={"_embedded": {"elements": [{"id": 7, "identifier": "OPM", "name": "OPM OpenProject CE MCP"}]}},
            request=request,
        )

    settings = _base_settings(read_projects=("*",), write_projects=("OPM",))
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))
    await client.initialize()

    # Must not raise: the embedded link only carries id + title, exactly like a
    # real work package's "_links.project", and "OPM" (the identifier) is only
    # resolvable via the cache initialize() just populated.
    client._ensure_project_write_link_allowed({"href": "/api/v3/projects/7", "title": "OPM OpenProject CE MCP"})

    await client.aclose()


@pytest.mark.asyncio
async def test_project_resolution_context_caches_per_ref_and_write_flag() -> None:
    calls: list[tuple[str, bool]] = []

    async def resolve(project_ref: str, *, write: bool = False) -> dict:
        calls.append((project_ref, write))
        return {"id": int(project_ref), "identifier": f"P{project_ref}"}

    context = ProjectResolutionContext(resolve)

    first = await context.resolve("1", write=False)
    second = await context.resolve("1", write=False)
    assert first is second
    assert calls == [("1", False)]

    # A different write flag for the same ref is a distinct key -- read passing
    # must never be assumed to mean write also passes.
    await context.resolve("1", write=True)
    assert calls == [("1", False), ("1", True)]

    # A different project is never served from the first project's cache entry.
    await context.resolve("2", write=False)
    assert calls == [("1", False), ("1", True), ("2", False)]


@pytest.mark.asyncio
async def test_project_resolution_context_seed_prevents_a_redundant_resolve() -> None:
    calls: list[tuple[str, bool]] = []

    async def resolve(project_ref: str, *, write: bool = False) -> dict:
        calls.append((project_ref, write))
        return {"id": int(project_ref)}

    context = ProjectResolutionContext(resolve)
    context.seed("1", {"id": 1, "identifier": "demo"}, write=False)

    result = await context.resolve("1", write=False)

    assert result == {"id": 1, "identifier": "demo"}
    assert calls == []


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
        read_projects=("mcp-*",),
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
        read_projects=("demo-id",),
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
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
        read_projects=("demo-id",),
        write_projects=("demo-id",),
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
        read_projects=("demo-id",),
        write_projects=("demo-id",),
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
        read_projects=("demo-id",),
        write_projects=("demo-id",),
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
        read_projects=("demo-id",),
        write_projects=("demo-id",),
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
        read_projects=("demo-id",),
        write_projects=("demo-id",),
        enable_board_write=True,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    deleted = await client.delete_board(board_id=12, confirm=True)

    assert deleted.board_id == 12
    assert deleted.confirmed is True

    await client.aclose()


@pytest.mark.asyncio
async def test_chain_specific_read_flags_restrict_membership_reads_with_global_read() -> None:
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
        enable_membership_read=False,
    )
    client = OpenProjectClient(
        settings, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}, request=r))
    )

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_ENABLE_MEMBERSHIP_READ"):
        await client.list_roles()

    await client.aclose()


@pytest.mark.asyncio
async def test_toggle_activity_emoji_reaction_respects_allowed_write_projects() -> None:
    """The toggle enforces the project write allowlist via the activity's work package."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/activities/1988" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 1988, "_links": {"workPackage": {"href": "/api/v3/work_packages/9"}}},
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/9" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 9, "_links": {"project": {"href": "/api/v3/projects/2", "title": "Other"}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(enable_work_package_write=True, write_projects=("demo",))
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await client.toggle_activity_emoji_reaction(1988, "heart")

    await client.aclose()


@pytest.mark.asyncio
async def test_delete_file_link_respects_allowed_write_projects() -> None:
    """delete_file_link must enforce the project write allowlist via the container WP."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/file_links/5" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 5,
                    "_links": {
                        "self": {"href": "/api/v3/file_links/5"},
                        "container": {"href": "/api/v3/work_packages/9"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/9" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 9, "_links": {"project": {"href": "/api/v3/projects/2", "title": "Other"}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(enable_work_package_write=True, write_projects=("demo",))
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await client.delete_file_link(5, confirm=True)

    await client.aclose()
