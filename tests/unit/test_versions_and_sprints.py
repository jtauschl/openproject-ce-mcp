from __future__ import annotations

import json

import httpx
import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.client import (
    NotFoundError,
    OpenProjectClient,
    _paginate_client,
    _paginate_server,
)
from openproject_ce_mcp.config import Settings


def test_paginate_server_derives_truncated_from_next_offset() -> None:
    # OPM-210: truncated and next_offset used to be two independently written
    # (but logically identical) expressions per list method -- this locks in
    # that they're now one derivation, for every boundary case.
    next_offset, truncated = _paginate_server(offset=1, limit=10, total=25)
    assert (next_offset, truncated) == (2, True)

    next_offset, truncated = _paginate_server(offset=3, limit=10, total=25)
    assert (next_offset, truncated) == (None, False)

    # Exact boundary: offset*limit == total means nothing left, not truncated.
    next_offset, truncated = _paginate_server(offset=2, limit=10, total=20)
    assert (next_offset, truncated) == (None, False)


def test_paginate_client_slices_and_derives_envelope_from_local_results() -> None:
    results = list(range(25))

    page, total, next_offset, truncated = _paginate_client(offset=1, limit=10, results=results)
    assert page == list(range(0, 10))
    assert (total, next_offset, truncated) == (25, 2, True)

    page, total, next_offset, truncated = _paginate_client(offset=3, limit=10, results=results)
    assert page == list(range(20, 25))
    assert (total, next_offset, truncated) == (25, None, False)

    page, total, next_offset, truncated = _paginate_client(offset=1, limit=10, results=[])
    assert page == []
    assert (total, next_offset, truncated) == (0, None, False)


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
        read_projects=("*",),
        write_projects=("*",),
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
        read_projects=("*",),
        write_projects=("*",),
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
        read_projects=("*",),
        write_projects=("*",),
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
    # Filter key is version_id per OpenProject's source-defined filter key
    version_filter = next(f for f in filters if "version_id" in f)
    assert version_filter["version_id"]["operator"] == "c"
    assert version_filter["version_id"]["values"] == []

    await client.aclose()


@pytest.mark.asyncio
async def test_list_work_packages_version_filter_uses_correct_key() -> None:
    """Verify version filter uses version_id key per source definition.

    OpenProject CE 17.5 app/models/queries/work_packages/filter/version_filter.rb
    defines: def self.key → :version_id

    Both the equality filter (version="v1.0") and status filter (version_status="open")
    use version_id as the filter key.
    """
    captured_calls: list[dict[str, str]] = []

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
        if "/versions" in request.url.path:
            return httpx.Response(
                200,
                json={"total": 1, "_embedded": {"elements": [{"id": 5, "name": "v1.0", "_links": {}}]}},
                request=request,
            )
        if request.url.path == "/api/v3/work_packages":
            captured_calls.append({"filters": request.url.params.get("filters", "")})
            return httpx.Response(200, json={"_embedded": {"elements": []}, "total": 0}, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))

    # Test 1: version equality filter
    await client.list_work_packages(version="v1.0", project="demo")
    filters_eq = json.loads(captured_calls[0]["filters"])
    assert any("version_id" in f for f in filters_eq), "version_id filter key not found (equality)"
    assert not any("version" in f and "version_id" not in f for f in filters_eq), "Found deprecated 'version' key"

    # Test 2: version status filter
    captured_calls.clear()
    await client.list_work_packages(version_status="open")
    filters_status = json.loads(captured_calls[0]["filters"])
    assert any("version_id" in f for f in filters_status), "version_id filter key not found (status)"

    version_filter = next(f for f in filters_status if "version_id" in f)
    assert version_filter["version_id"]["operator"] == "o"  # open status

    await client.aclose()


@pytest.mark.asyncio
async def test_list_sprints_normalizes_backlogs_collection() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/sprints" and request.method == "GET":
            assert request.url.params["offset"] == "1"
            # Fetches up to settings.max_results (not the caller's limit) in one
            # request, then paginates the filtered survivors in memory.
            assert request.url.params["pageSize"] == "100"
            return httpx.Response(
                200,
                json={
                    "_type": "Collection",
                    "total": 1,
                    "count": 1,
                    "pageSize": 20,
                    "offset": 1,
                    "_embedded": {
                        "elements": [
                            {
                                "_type": "Sprint",
                                "id": 1,
                                "name": "0.3.0 Release Finalization",
                                "startDate": None,
                                "finishDate": "2026-07-10",
                                "createdAt": "2026-07-09T18:56:07Z",
                                "updatedAt": "2026-07-09T18:57:01Z",
                                "_links": {
                                    "self": {"href": "/api/v3/sprints/1", "title": "0.3.0 Release Finalization"},
                                    "status": {
                                        "href": "urn:openproject-org:api:v3:sprints:status:in_planning",
                                        "title": "In Planning",
                                    },
                                    "definingWorkspace": {"href": "/api/v3/projects/7", "title": "Demo"},
                                },
                            }
                        ]
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))
    result = await client.list_sprints()

    assert result.total == 1
    assert result.results[0].id == 1
    assert result.results[0].name == "0.3.0 Release Finalization"
    assert result.results[0].status == "In Planning"
    assert result.results[0].status_href == "urn:openproject-org:api:v3:sprints:status:in_planning"
    assert result.results[0].finish_date == "2026-07-10"
    assert result.results[0].defining_workspace_id == 7
    assert result.results[0].defining_workspace == "Demo"

    await client.aclose()


@pytest.mark.asyncio
async def test_list_project_sprints_resolves_project_and_allows_empty_collection() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo" and request.method == "GET":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 7, "identifier": "demo", "name": "Demo", "active": True},
                request=request,
            )
        if request.url.path == "/api/v3/projects/7/sprints" and request.method == "GET":
            return httpx.Response(
                200,
                json={"_type": "Collection", "total": 0, "count": 0, "pageSize": 20, "offset": 1, "_embedded": {}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))
    result = await client.list_project_sprints("demo")

    assert result.total == 0
    assert result.count == 0
    assert result.results == []

    await client.aclose()


@pytest.mark.asyncio
async def test_list_project_sprints_filters_sprints_outside_allowed_projects() -> None:
    # A sprint shared into an allowed project can still be *defined* by a
    # different, disallowed project. list_project_sprints must filter those out the
    # same way list_sprints already does via _sprint_payload_allowed.
    import dataclasses

    settings = dataclasses.replace(make_settings(), read_projects=("demo",))

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo" and request.method == "GET":
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
                    "total": 2,
                    "count": 2,
                    "pageSize": 20,
                    "offset": 1,
                    "_embedded": {
                        "elements": [
                            {
                                "_type": "Sprint",
                                "id": 1,
                                "name": "Owned by demo",
                                "_embedded": {
                                    "definingWorkspace": {
                                        "_type": "Project",
                                        "id": 7,
                                        "identifier": "demo",
                                        "name": "Demo",
                                        "_links": {"self": {"href": "/api/v3/projects/7", "title": "Demo"}},
                                    }
                                },
                                "_links": {},
                            },
                            {
                                "_type": "Sprint",
                                "id": 2,
                                "name": "Shared from secret-project",
                                "_embedded": {
                                    "definingWorkspace": {
                                        "_type": "Project",
                                        "id": 99,
                                        "identifier": "secret-project",
                                        "name": "Secret Project",
                                        "_links": {"self": {"href": "/api/v3/projects/99", "title": "Secret Project"}},
                                    }
                                },
                                "_links": {},
                            },
                        ]
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))
    result = await client.list_project_sprints("demo")

    assert result.total == 1
    assert result.count == 1
    assert [s.id for s in result.results] == [1]
    assert result.results[0].defining_workspace == "Demo"

    await client.aclose()


@pytest.mark.asyncio
async def test_list_versions_global_backfills_after_allowlist_filter() -> None:
    # The global endpoint has no project filter, so results are filtered
    # client-side against the allowlist. Fetching only one page sized to the caller's
    # limit could return a page that looks sparser than reality once filtered. This
    # returns 6 raw items (3 allowed, 3 disallowed, interleaved) with limit=2 —
    # a naive pageSize=limit request would only ever ask the server for 2 raw items
    # at a time and could easily return 0-2 allowed ones; instead all 6 must be fetched
    # in one request (pageSize=settings.max_results), paginating the 3 filtered survivors.
    import dataclasses

    settings = dataclasses.replace(make_settings(), read_projects=("demo",))

    def version_item(item_id: int, allowed: bool) -> dict:
        title = "Demo" if allowed else "Secret Project"
        return {
            "id": item_id,
            "name": f"v{item_id}",
            "_links": {"definingProject": {"href": f"/api/v3/projects/{item_id}", "title": title}},
        }

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/versions" and request.method == "GET":
            assert request.url.params["offset"] == "1"
            assert request.url.params["pageSize"] == "100"
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            version_item(1, allowed=False),
                            version_item(2, allowed=True),
                            version_item(3, allowed=False),
                            version_item(4, allowed=True),
                            version_item(5, allowed=False),
                            version_item(6, allowed=True),
                        ]
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))
    page = await client.list_versions(limit=2)

    assert [v.id for v in page.results] == [2, 4]
    assert page.count == 2
    assert page.total == 3
    assert page.truncated is True
    assert page.next_offset == 2

    await client.aclose()


@pytest.mark.asyncio
async def test_list_versions_project_scoped_uses_exact_server_pagination() -> None:
    # Unlike the global branch above, the project-scoped branch does no client-side
    # filtering at all (access to the project is already verified), so it keeps exact
    # server-side pagination with the caller's own limit as pageSize — this must not be
    # unified with the global branch's fetch-all-and-slice pattern, since no allowlist
    # filtering happens here that could produce a sparse page.
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo" and request.method == "GET":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 7, "identifier": "demo", "name": "Demo", "active": True},
                request=request,
            )
        if request.url.path == "/api/v3/projects/7/versions" and request.method == "GET":
            assert request.url.params["offset"] == "1"
            assert request.url.params["pageSize"] == "2"
            return httpx.Response(
                200,
                json={
                    "total": 5,
                    "_embedded": {
                        "elements": [
                            {"id": 1, "name": "v1", "_links": {}},
                            {"id": 2, "name": "v2", "_links": {}},
                        ]
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))
    page = await client.list_versions(project="demo", limit=2)

    assert [v.id for v in page.results] == [1, 2]
    # No client-side filtering happens on this branch, so total is the real
    # server-reported match count (5), not just this page's item count (2).
    assert page.total == 5
    assert page.count == 2
    assert page.truncated is True
    assert page.next_offset == 2

    await client.aclose()


@pytest.mark.asyncio
async def test_list_versions_global_search_filters_by_name_substring() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/versions" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            {"id": 1, "name": "0.2.3", "_links": {}},
                            {"id": 2, "name": "0.3.0", "_links": {}},
                            {"id": 3, "name": "Rejected", "_links": {}},
                        ]
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))
    page = await client.list_versions(search="0.3")

    assert [v.id for v in page.results] == [2]
    assert page.total == 1

    no_match = await client.list_versions(search="nonexistent")
    assert no_match.results == []
    assert no_match.total == 0

    await client.aclose()


@pytest.mark.asyncio
async def test_list_versions_project_scoped_search_overfetches_and_filters() -> None:
    # Unlike the no-search project-scoped path (exact server pagination, tested above),
    # a search filter has no server-side equivalent here either — so it must switch to
    # the same over-fetch + in-memory filter/paginate pattern as the global branch.
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo" and request.method == "GET":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 7, "identifier": "demo", "name": "Demo", "active": True},
                request=request,
            )
        if request.url.path == "/api/v3/projects/7/versions" and request.method == "GET":
            # Always requests the over-fetch page (pageSize=max_results), regardless
            # of the caller's own limit/offset — those apply only to the filtered
            # in-memory result, confirmed below via the limit=1/offset=2 case.
            assert request.url.params["offset"] == "1"
            assert request.url.params["pageSize"] == str(make_settings().max_results)
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            {"id": 1, "name": "Sprint 1", "_links": {}},
                            {"id": 2, "name": "Sprint 2", "_links": {}},
                            {"id": 3, "name": "Backlog", "_links": {}},
                            {"id": 4, "name": "Sprint 3", "_links": {}},
                        ]
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))
    page = await client.list_versions(project="demo", search="sprint")

    assert [v.id for v in page.results] == [1, 2, 4]
    assert page.total == 3

    # Filter-then-paginate ordering: with 3 "sprint" matches, limit=1/offset=2 must
    # return the 2nd filtered survivor (id=2), not slice the raw 4-item page first.
    second_page = await client.list_versions(project="demo", search="sprint", limit=1, offset=2)
    assert [v.id for v in second_page.results] == [2]
    assert second_page.total == 3
    assert second_page.truncated is True
    assert second_page.next_offset == 3

    await client.aclose()


@pytest.mark.asyncio
async def test_list_sprints_backfills_after_allowlist_filter() -> None:
    # Same allowlist-safe pagination as list_versions above, applied to the
    # always-filtered list_sprints (sprints can be shared cross-project via Backlogs sharing).
    import dataclasses

    settings = dataclasses.replace(make_settings(), read_projects=("demo",))

    def sprint_item(item_id: int, allowed: bool) -> dict:
        workspace_id = 7 if allowed else 99
        workspace_identifier = "demo" if allowed else "secret-project"
        workspace_name = "Demo" if allowed else "Secret Project"
        return {
            "_type": "Sprint",
            "id": item_id,
            "name": f"Sprint {item_id}",
            "_embedded": {
                "definingWorkspace": {
                    "_type": "Project",
                    "id": workspace_id,
                    "identifier": workspace_identifier,
                    "name": workspace_name,
                    "_links": {"self": {"href": f"/api/v3/projects/{workspace_id}", "title": workspace_name}},
                }
            },
            "_links": {},
        }

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/sprints" and request.method == "GET":
            assert request.url.params["offset"] == "1"
            assert request.url.params["pageSize"] == "100"
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            sprint_item(1, allowed=False),
                            sprint_item(2, allowed=True),
                            sprint_item(3, allowed=False),
                            sprint_item(4, allowed=True),
                            sprint_item(5, allowed=False),
                            sprint_item(6, allowed=True),
                        ]
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))
    page = await client.list_sprints(limit=2)

    assert [s.id for s in page.results] == [2, 4]
    assert page.count == 2
    assert page.total == 3
    assert page.truncated is True
    assert page.next_offset == 2

    await client.aclose()


@pytest.mark.asyncio
async def test_list_project_sprints_backfills_after_allowlist_filter() -> None:
    # Same allowlist-safe pagination as above, applied to list_project_sprints — still filtered
    # client-side despite being project-scoped, because a sprint shared into this
    # project can be *defined* by a different, possibly disallowed project.
    import dataclasses

    settings = dataclasses.replace(make_settings(), read_projects=("demo",))

    def sprint_item(item_id: int, allowed: bool) -> dict:
        workspace_id = 7 if allowed else 99
        workspace_identifier = "demo" if allowed else "secret-project"
        workspace_name = "Demo" if allowed else "Secret Project"
        return {
            "_type": "Sprint",
            "id": item_id,
            "name": f"Sprint {item_id}",
            "_embedded": {
                "definingWorkspace": {
                    "_type": "Project",
                    "id": workspace_id,
                    "identifier": workspace_identifier,
                    "name": workspace_name,
                    "_links": {"self": {"href": f"/api/v3/projects/{workspace_id}", "title": workspace_name}},
                }
            },
            "_links": {},
        }

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo" and request.method == "GET":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 7, "identifier": "demo", "name": "Demo", "active": True},
                request=request,
            )
        if request.url.path == "/api/v3/projects/7/sprints" and request.method == "GET":
            assert request.url.params["offset"] == "1"
            assert request.url.params["pageSize"] == "100"
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            sprint_item(1, allowed=False),
                            sprint_item(2, allowed=True),
                            sprint_item(3, allowed=False),
                            sprint_item(4, allowed=True),
                            sprint_item(5, allowed=False),
                            sprint_item(6, allowed=True),
                        ]
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))
    page = await client.list_project_sprints("demo", limit=2)

    assert [s.id for s in page.results] == [2, 4]
    assert page.count == 2
    assert page.total == 3
    assert page.truncated is True
    assert page.next_offset == 2

    await client.aclose()


@pytest.mark.asyncio
async def test_get_sprint_normalizes_detail() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/sprints/1" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "_type": "Sprint",
                    "id": 1,
                    "name": "0.3.0 Release Finalization",
                    "startDate": "2026-07-09",
                    "finishDate": "2026-07-10",
                    "createdAt": "2026-07-09T18:56:07Z",
                    "updatedAt": "2026-07-09T18:57:01Z",
                    "_embedded": {
                        "definingWorkspace": {
                            "_type": "Project",
                            "id": 7,
                            "identifier": "demo",
                            "name": "Demo",
                            "_links": {"self": {"href": "/api/v3/projects/7", "title": "Demo"}},
                        }
                    },
                    "_links": {
                        "status": {
                            "href": "urn:openproject-org:api:v3:sprints:status:in_planning",
                            "title": "In Planning",
                        },
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))
    sprint = await client.get_sprint(1)

    assert sprint.id == 1
    assert sprint.start_date == "2026-07-09"
    assert sprint.finish_date == "2026-07-10"
    assert sprint.defining_workspace_id == 7

    await client.aclose()


@pytest.mark.asyncio
async def test_list_sprints_translates_missing_backlogs_module() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/sprints" and request.method == "GET":
            return httpx.Response(404, json={"message": "Not found"}, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))

    with pytest.raises(NotFoundError, match="Backlogs module"):
        await client.list_sprints()

    await client.aclose()
