from __future__ import annotations

import json

import httpx
import pytest
from _client_test_helpers import _base_settings, _project_index_response, started_client

from openproject_ce_mcp.app.policies import board_policy, project_policy, scope
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
        await client.work_package.add_comment(work_package_id=1, comment="Hello", confirm=True)

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
        await client.board.create(name="Sprint Board", project="other", confirm=False)

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
    client = await started_client(settings, handler, [(1, "demo", "Demo"), (2, "other", "Other")])

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await client.time_entry.create(
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
        await client.board.create(name="Sprint Board", project="demo", confirm=False)

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
        await client.project.get("demo")

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
        await client.board.create(name="Other Board", project="other", confirm=False)

    await client.aclose()


@pytest.mark.parametrize(
    "check",
    [
        lambda client: project_policy.ensure_project_write_allowed(
            {"id": "other", "identifier": "other"},
            project_ref="other",
            settings=client.settings,
            project_id_to_identifier=client._project_id_to_identifier,
        ),
        lambda client: scope.ensure_project_write_link_allowed(
            {"href": "/api/v3/projects/other"},
            settings=client.settings,
            project_id_to_identifier=client._project_id_to_identifier,
        ),
        lambda client: board_policy.ensure_board_write_allowed(
            {"href": "/api/v3/projects/other"},
            settings=client.settings,
            project_id_to_identifier=client._project_id_to_identifier,
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
    # initialize() must populate the id->identifier cache whenever
    # write_projects is restricted, regardless of whether read_projects
    # allows all -- link-based matching needs the cache
    # (_project_candidates only has the numeric id + display name from an
    # embedded HAL link, never the identifier itself, unless this cache fills
    # it in). READ="*" + WRITE="DEMO" exercises this case.
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/projects"
        return _project_index_response(request, [(7, "DEMO", "Demo Project"), (16, "ENC", "ENC Encore ST")])

    settings = _base_settings(read_projects=("*",), write_projects=("DEMO",))
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    await client.initialize()

    assert client._project_id_to_identifier == {7: "DEMO"}
    await client.aclose()


@pytest.mark.asyncio
async def test_initialize_walks_every_server_page_of_projects() -> None:
    """Regression: Projects is genuinely OffsetPaginatedCollection server-side
    (verified against OpenProject's own API implementation) -- a single
    bounded fetch capped at 500
    (this method's prior behavior) silently skipped caching the identifier of
    any project beyond that cap, breaking link-based allowlist matching for
    that project. Two full pages (page_size=max_page_size) followed by a
    short 3rd page prove the walk continues past the first page and still
    finds a matching project on the 2nd page."""
    requested_offsets: list[str | None] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/projects"
        offset = request.url.params.get("offset")
        page_size = int(request.url.params["pageSize"])
        requested_offsets.append(offset)
        projects = [(i, f"proj-{i}", f"Project {i}") for i in range(1, page_size + 1)]
        return _project_index_response(request, [*projects, (999, "DEMO", "Demo Project")])

    settings = _base_settings(read_projects=("*",), write_projects=("DEMO",))
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    await client.initialize()

    assert requested_offsets == ["1", "2"]
    assert client._project_id_to_identifier == {999: "DEMO"}
    await client.aclose()


@pytest.mark.asyncio
async def test_initialize_logs_and_survives_an_expected_transport_failure(caplog) -> None:
    # An OpenProjectError-family failure (transport/API) during
    # initialize()'s identifier-cache fetch must be logged with its concrete
    # cause, not just a generic "something failed" message, and initialize()
    # must still return normally rather than crash server startup.
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    settings = _base_settings(read_projects=("*",), write_projects=("DEMO",))
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    try:
        with caplog.at_level("WARNING"):
            await client.initialize()
        assert client._project_id_to_identifier == {}
        [record] = [r for r in caplog.records if "allowlist scan failed" in r.message]
        assert "Could not reach OpenProject" in record.message
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_initialize_propagates_an_unexpected_programming_error() -> None:
    # The narrowed `except OpenProjectError` must NOT catch a real
    # programming error -- a broad `except Exception` would hide bugs here
    # just as readily as legitimate transport failures.
    async def handler(request: httpx.Request) -> httpx.Response:
        raise RuntimeError("boom")

    settings = _base_settings(read_projects=("*",), write_projects=("DEMO",))
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    try:
        with pytest.raises(RuntimeError, match="boom"):
            await client.initialize()
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_write_link_allowlist_recognizes_identifier_after_initialize_with_open_read_scope() -> None:
    # End-to-end proof of the same regression: a work-package-style embedded
    # project link (numeric id + display name only, no identifier field) must
    # be recognized against an identifier-based WRITE_PROJECTS entry once
    # initialize() has run, even though READ_PROJECTS is wide open.
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/projects"
        return _project_index_response(request, [(7, "DEMO", "Demo Project")])

    settings = _base_settings(read_projects=("*",), write_projects=("DEMO",))
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))
    await client.initialize()

    # Must not raise: the embedded link only carries id + title, exactly like a
    # real work package's "_links.project", and "DEMO" (the identifier) is only
    # resolvable via the cache initialize() just populated.
    scope.ensure_project_write_link_allowed(
        {"href": "/api/v3/projects/7", "title": "Demo Project"},
        settings=client.settings,
        project_id_to_identifier=client._project_id_to_identifier,
    )

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

    project = await client.project.get("mcp-test")

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
        await client.membership.get(3)

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

    deleted = await client.membership.delete(membership_id=3, confirm=True)

    assert deleted.membership_id == 3
    assert deleted.state == "confirmed"

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

    deleted = await client.news.delete(news_id=7, confirm=True)

    assert deleted.news_id == 7
    assert deleted.state == "confirmed"

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

    deleted = await client.time_entry.delete(time_entry_id=10, confirm=True)

    assert deleted.time_entry_id == 10
    assert deleted.state == "confirmed"

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

    deleted = await client.version.delete(version_id=8, confirm=True)

    assert deleted.version_id == 8
    assert deleted.state == "confirmed"

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

    deleted = await client.board.delete(board_id=12, confirm=True)

    assert deleted.board_id == 12
    assert deleted.state == "confirmed"

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
        await client.role.list_roles()

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
    client = await started_client(settings, handler, [(1, "demo", "Demo"), (2, "other", "Other")])

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await client.emoji_reaction.toggle(1988, "heart")

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
    client = await started_client(settings, handler, [(1, "demo", "Demo"), (2, "other", "Other")])

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await client.file_link.delete(5, confirm=True)

    await client.aclose()


def _project_json(project_id: int, identifier: str, name: str) -> dict:
    return {
        "_type": "Project",
        "id": project_id,
        "identifier": identifier,
        "name": name,
        "active": True,
        "_links": {"self": {"href": f"/api/v3/projects/{project_id}", "title": name}},
    }


def _work_package_json(work_package_id: int, project_id: int) -> dict:
    return {
        "_type": "WorkPackage",
        "id": work_package_id,
        "subject": "Task",
        "_links": {
            "self": {"href": f"/api/v3/work_packages/{work_package_id}"},
            "project": {"href": f"/api/v3/projects/{project_id}", "title": "Some project"},
        },
    }


@pytest.mark.asyncio
async def test_a_project_created_through_the_client_is_in_scope_without_a_restart() -> None:
    requests: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.method == "POST" and request.url.path == "/api/v3/projects/form":
            payload = json.loads(request.content)
            return httpx.Response(
                200,
                json={"_type": "Form", "_embedded": {"payload": payload, "schema": {}, "validationErrors": {}}},
                request=request,
            )
        if request.method == "POST" and request.url.path == "/api/v3/projects":
            return httpx.Response(201, json=_project_json(50, "demo-new", "Demo new"), request=request)
        if request.method == "GET" and request.url.path == "/api/v3/work_packages/9":
            return httpx.Response(200, json=_work_package_json(9, 50), request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(read_projects=("demo*",), write_projects=("demo*",), enable_project_write=True)
    client = await started_client(settings, handler, [(1, "demo", "Demo")])

    await client.project.create(name="Demo new", identifier="demo-new", confirm=True)
    work_package = await client.work_package.get(9)

    assert work_package.id == 9
    assert ("GET", "/api/v3/projects/50") not in requests
    await client.aclose()


@pytest.mark.parametrize(("read_projects", "allowed"), [(("demo*",), True), (("demo",), False)])
@pytest.mark.asyncio
async def test_a_copied_project_is_learned_from_its_job_status(read_projects: tuple, allowed: bool) -> None:
    # A finished copy job links the new project as payload._links.project;
    # OpenProject sends no createdProject link.
    requests: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/api/v3/job_statuses/77":
            return httpx.Response(
                200,
                json={
                    "_type": "JobStatus",
                    "jobId": "77",
                    "status": "success",
                    "payload": {"_links": {"project": {"href": "/api/v3/projects/114", "title": "Demo copy"}}},
                    "_links": {"self": {"href": "/api/v3/job_statuses/77"}},
                },
                request=request,
            )
        if request.url.path == "/api/v3/projects/114":
            return httpx.Response(200, json=_project_json(114, "demo-copy", "Demo copy"), request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = await started_client(_base_settings(read_projects=read_projects), handler, [(6, "demo", "Demo")])

    if allowed:
        job = await client.job_status.get("77")
        assert job.project_id == 114
        assert client._project_id_to_identifier[114] == "demo-copy"
    else:
        with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
            await client.job_status.get("77")
        assert 114 not in client._project_id_to_identifier
    assert requests == ["/api/v3/job_statuses/77", "/api/v3/projects/114"]
    await client.aclose()


@pytest.mark.parametrize(("identifier", "listed"), [("demo-ui", True), ("other-ui", False)])
@pytest.mark.asyncio
async def test_a_project_created_elsewhere_joins_the_global_work_package_filter(identifier: str, listed: bool) -> None:
    project_filters: list[list[str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/9":
            return httpx.Response(200, json=_work_package_json(9, 60), request=request)
        if request.url.path == "/api/v3/projects/60":
            return httpx.Response(200, json=_project_json(60, identifier, "Created in the web UI"), request=request)
        if request.url.path == "/api/v3/work_packages":
            filters = json.loads(request.url.params["filters"])
            project_filters.extend(f["project_id"]["values"] for f in filters if "project_id" in f)
            return httpx.Response(200, json={"total": 0, "_embedded": {"elements": []}}, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = await started_client(_base_settings(read_projects=("demo*",)), handler, [(1, "demo", "Demo")])

    if listed:
        await client.work_package.get(9)
    else:
        with pytest.raises(PermissionDeniedError):
            await client.work_package.get(9)
    await client.work_package.list(limit=5)

    assert project_filters == [["1", "60"] if listed else ["1"]]
    await client.aclose()


@pytest.mark.asyncio
async def test_the_global_work_package_filter_leaves_out_archived_projects() -> None:
    # OpenProject answers a project filter naming an archived project with
    # "Project filter has invalid values" and lists nothing.
    project_filters: list[list[str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/work_packages"
        filters = json.loads(request.url.params["filters"])
        project_filters.extend(f["project_id"]["values"] for f in filters if "project_id" in f)
        return httpx.Response(200, json={"total": 0, "_embedded": {"elements": []}}, request=request)

    client = await started_client(
        _base_settings(read_projects=("demo*",)), handler, [(1, "demo", "Demo"), (2, "demo-old", "Demo old", False)]
    )

    await client.work_package.list(limit=5)

    assert project_filters == [["1"]]
    await client.aclose()
