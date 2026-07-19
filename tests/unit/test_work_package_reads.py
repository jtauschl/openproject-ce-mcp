from __future__ import annotations

import json

import httpx
import pytest
from _client_test_helpers import (
    _base_settings,
    _empty_scope_settings,
    _no_request_handler,
    _wp_detail_payload,
    _wp_detail_payload_with_description,
    make_settings,
)

from openproject_ce_mcp.client import (
    InvalidInputError,
    NotFoundError,
    OpenProjectClient,
)
from openproject_ce_mcp.config import Settings


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

    result = await client.search_work_packages(search="Feature")

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

    result = await client.search_work_packages(search="Feature", status="In progress")

    assert result.count == 0
    assert status_calls["count"] == 1

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
            # Filter keys use type_id/version_id per OpenProject's source-defined filter keys
            assert "type_id" in filter_keys
            assert "version_id" in filter_keys
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
    )

    assert result.count == 1
    assert result.results[0].type == "Feature"
    assert result.results[0].version == "v1"
    assert result.results[0].description == "<user-content>Sync steps and calories</user-content>"
    assert result.results[0].has_description is True

    await client.aclose()


@pytest.mark.asyncio
async def test_list_work_packages_returns_parent_display_id_when_present() -> None:
    # parent_display_id mirrors parent_id: both are derived from the same
    # _links.parent object already present in the list/search payload, not an
    # extra lookup. displayId is only present on 17.5+ (semantic mode).
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
                                "subject": "Child with semantic parent",
                                "_links": {
                                    "parent": {
                                        "href": "/api/v3/work_packages/7",
                                        "title": "Parent",
                                        "displayId": "EMTB-7",
                                    },
                                },
                            },
                            {
                                "id": 43,
                                "subject": "Child on classic instance",
                                "_links": {
                                    "parent": {"href": "/api/v3/work_packages/8", "title": "Parent"},
                                },
                            },
                        ]
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_base_settings(read_projects=("*",)), transport=httpx.MockTransport(handler))

    result = await client.list_work_packages()

    assert result.results[0].parent_id == 7
    assert result.results[0].parent_display_id == "EMTB-7"
    assert result.results[1].parent_id == 8
    assert result.results[1].parent_display_id is None

    await client.aclose()


@pytest.mark.asyncio
async def test_search_work_packages_returns_parent_display_id_when_present() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/work_packages"
        return httpx.Response(
            200,
            json={
                "total": 1,
                "_embedded": {
                    "elements": [
                        {
                            "id": 42,
                            "subject": "Block D task",
                            "_links": {
                                "parent": {
                                    "href": "/api/v3/work_packages/7",
                                    "title": "Parent",
                                    "displayId": "EMTB-7",
                                },
                            },
                        }
                    ]
                },
            },
            request=request,
        )

    client = OpenProjectClient(_base_settings(read_projects=("*",)), transport=httpx.MockTransport(handler))

    result = await client.search_work_packages(search="Block D")

    assert result.results[0].parent_id == 7
    assert result.results[0].parent_display_id == "EMTB-7"

    await client.aclose()


@pytest.mark.asyncio
async def test_list_work_packages_exposes_real_total_when_scope_unrestricted() -> None:
    # read_projects="*" -- the query is provably unrestricted, so the server's
    # real total is safe to expose regardless of what any single page contains.
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/work_packages"
        return httpx.Response(
            200,
            json={
                "total": 5,
                "_embedded": {
                    "elements": [
                        {"id": 1, "subject": "A", "_links": {"project": {"title": "demo"}}},
                        {"id": 2, "subject": "B", "_links": {"project": {"title": "demo"}}},
                    ]
                },
            },
            request=request,
        )

    client = OpenProjectClient(_base_settings(read_projects=("*",)), transport=httpx.MockTransport(handler))
    result = await client.list_work_packages(limit=2)

    assert result.total == 5
    assert result.count == 2
    assert result.next_offset == 2
    assert result.truncated is True

    await client.aclose()


@pytest.mark.asyncio
async def test_list_work_packages_falls_back_to_page_count_when_project_cache_empty() -> None:
    # Restricted scope, no explicit project, and the allowed-project-id cache
    # (populated by initialize(), which this test deliberately never calls --
    # e.g. because initialize() silently swallowed a failure) is empty. No
    # server-side project filter is sent at all, so even though nothing on
    # THIS page happens to be filtered, the server's total could still include
    # matches from a disallowed project on a later page -- total must fall
    # back to this page's item count regardless.
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/work_packages"
        params = dict(request.url.params)
        assert "project_id" not in params["filters"]
        return httpx.Response(
            200,
            json={
                "total": 50,
                "_embedded": {
                    "elements": [
                        {"id": 1, "subject": "A", "_links": {"project": {"title": "demo"}}},
                        {"id": 2, "subject": "B", "_links": {"project": {"title": "demo"}}},
                    ]
                },
            },
            request=request,
        )

    client = OpenProjectClient(_base_settings(read_projects=("demo",)), transport=httpx.MockTransport(handler))
    result = await client.list_work_packages(limit=2)

    assert [wp.id for wp in result.results] == [1, 2]
    assert result.total == 2
    assert result.count == 2

    await client.aclose()


@pytest.mark.asyncio
async def test_list_work_packages_exposes_real_total_when_restricted_scope_filter_sent() -> None:
    # Restricted scope, no explicit project, but the allowed-project-id cache IS
    # populated (as initialize() would do on success) -- a server-side project_id
    # filter covering exactly the allowed projects is sent, so the query is
    # provably restricted and the server's real total is safe to expose.
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/work_packages"
        params = dict(request.url.params)
        assert '"project_id"' in params["filters"]
        return httpx.Response(
            200,
            json={
                "total": 5,
                "_embedded": {
                    "elements": [
                        {"id": 1, "subject": "A", "_links": {"project": {"title": "demo"}}},
                        {"id": 2, "subject": "B", "_links": {"project": {"title": "demo"}}},
                    ]
                },
            },
            request=request,
        )

    client = OpenProjectClient(_base_settings(read_projects=("demo",)), transport=httpx.MockTransport(handler))
    client._project_id_to_identifier[1] = "demo"
    result = await client.list_work_packages(limit=2)

    assert result.total == 5
    assert result.count == 2

    await client.aclose()


@pytest.mark.asyncio
async def test_list_work_packages_pagination_hints_do_not_leak_untrusted_total() -> None:
    # Same untrusted-total scenario as the empty-cache test above, but this one
    # asserts on next_offset/truncated specifically: they must NOT be derived
    # from the server's secret total (50) -- that would reveal the existence of
    # further matches just as much as exposing the total itself. Since this raw
    # page came back short of the requested limit, there is nothing more to
    # page through.
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "total": 50,
                "_embedded": {
                    "elements": [
                        {"id": 1, "subject": "A", "_links": {"project": {"title": "demo"}}},
                    ]
                },
            },
            request=request,
        )

    client = OpenProjectClient(_base_settings(read_projects=("demo",)), transport=httpx.MockTransport(handler))
    result = await client.list_work_packages(limit=5)

    assert result.total == 1
    assert result.next_offset is None
    assert result.truncated is False

    await client.aclose()


@pytest.mark.asyncio
async def test_list_work_packages_pagination_continues_with_untrusted_total_when_page_full() -> None:
    # Same untrusted-total scope, but the raw page came back full (== limit) --
    # there may be more allowed matches on a later server page, so pagination
    # must still continue even though the total itself stays hidden.
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "total": 50,
                "_embedded": {
                    "elements": [
                        {"id": 1, "subject": "A", "_links": {"project": {"title": "demo"}}},
                        {"id": 2, "subject": "B", "_links": {"project": {"title": "demo"}}},
                    ]
                },
            },
            request=request,
        )

    client = OpenProjectClient(_base_settings(read_projects=("demo",)), transport=httpx.MockTransport(handler))
    result = await client.list_work_packages(offset=1, limit=2)

    assert result.total == 2
    assert result.next_offset == 2
    assert result.truncated is True

    await client.aclose()


@pytest.mark.asyncio
async def test_search_work_packages_falls_back_to_page_count_without_explicit_project() -> None:
    # search_work_packages has no restricted-scope project_id filter branch at
    # all (unlike list_work_packages), so without an explicit project it must
    # never trust the server total under a restricted scope, regardless of
    # whether this particular page happened to be filtered.
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "total": 50,
                "_embedded": {
                    "elements": [
                        {"id": 1, "subject": "A", "_links": {"project": {"title": "demo"}}},
                    ]
                },
            },
            request=request,
        )

    client = OpenProjectClient(_base_settings(read_projects=("demo",)), transport=httpx.MockTransport(handler))
    result = await client.search_work_packages(search="A", limit=5)

    assert result.total == 1
    assert result.count == 1
    assert result.next_offset is None

    await client.aclose()


@pytest.mark.asyncio
async def test_search_work_packages_exposes_real_total_with_explicit_project() -> None:
    # An explicit project is validated against the allowlist by
    # _get_project_payload before the filter is built, so the query is
    # provably restricted to that one allowed project and the server total is
    # safe to expose.
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo":
            return httpx.Response(200, json={"_type": "Project", "id": 1, "identifier": "demo", "name": "Demo"})
        return httpx.Response(
            200,
            json={
                "total": 5,
                "_embedded": {
                    "elements": [
                        {"id": 1, "subject": "A", "_links": {"project": {"title": "demo"}}},
                    ]
                },
            },
            request=request,
        )

    client = OpenProjectClient(_base_settings(read_projects=("demo",)), transport=httpx.MockTransport(handler))
    result = await client.search_work_packages(search="A", project="demo", limit=5)

    assert result.total == 5
    assert result.count == 1

    await client.aclose()


@pytest.mark.asyncio
async def test_list_my_open_work_packages_falls_back_to_page_count_under_restricted_scope() -> None:
    # list_my_open_work_packages never sends a project-scoping filter at all,
    # so under a restricted scope the total must always fall back to the
    # page's item count -- never the server's secret total.
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/users/me":
            return httpx.Response(200, json={"id": 9, "name": "Me", "login": "me"}, request=request)
        return httpx.Response(
            200,
            json={
                "total": 50,
                "_embedded": {
                    "elements": [
                        {"id": 1, "subject": "A", "_links": {"project": {"title": "demo"}}},
                    ]
                },
            },
            request=request,
        )

    client = OpenProjectClient(_base_settings(read_projects=("demo",)), transport=httpx.MockTransport(handler))
    result = await client.list_my_open_work_packages(limit=5)

    assert result.total == 1
    assert result.count == 1
    assert result.next_offset is None

    await client.aclose()


@pytest.mark.asyncio
async def test_list_work_packages_returns_empty_without_request_under_empty_read_projects() -> None:
    client = OpenProjectClient(_empty_scope_settings(), transport=httpx.MockTransport(_no_request_handler))

    result = await client.list_work_packages()

    assert result.count == 0
    assert result.results == []
    assert result.next_offset is None
    assert result.truncated is False

    await client.aclose()


@pytest.mark.asyncio
async def test_list_work_packages_returns_empty_without_request_even_with_project_and_type() -> None:
    # Proves the early return fires unconditionally — even with project=/type=
    # explicitly given, no lookup call (project resolution, type resolution) happens.
    client = OpenProjectClient(_empty_scope_settings(), transport=httpx.MockTransport(_no_request_handler))

    result = await client.list_work_packages(project="demo", type="Bug")

    assert result.results == []

    await client.aclose()


@pytest.mark.asyncio
async def test_search_work_packages_returns_empty_without_request_under_empty_read_projects() -> None:
    client = OpenProjectClient(_empty_scope_settings(), transport=httpx.MockTransport(_no_request_handler))

    result = await client.search_work_packages(search="demo")

    assert result.count == 0
    assert result.results == []

    await client.aclose()


@pytest.mark.asyncio
async def test_list_my_open_work_packages_returns_empty_without_request_even_with_assignee_me() -> None:
    # Proves the guard fires before get_current_user() is ever called.
    client = OpenProjectClient(_empty_scope_settings(), transport=httpx.MockTransport(_no_request_handler))

    result = await client.list_my_open_work_packages()

    assert result.count == 0
    assert result.results == []
    assert result.next_offset is None
    assert result.truncated is False

    await client.aclose()


@pytest.mark.asyncio
async def test_list_work_package_collection_defense_in_depth_guard() -> None:
    # Direct test of the shared helper's own guard, independent of its two
    # public callers, so a future new caller can't silently bypass it.
    client = OpenProjectClient(_empty_scope_settings(), transport=httpx.MockTransport(_no_request_handler))

    result = await client._list_work_package_collection(
        project_id=None, filters=[], offset=1, limit=10, total_is_scope_safe=False
    )

    assert result.count == 0
    assert result.results == []
    assert result.next_offset is None
    assert result.truncated is False

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
        read_projects=("6",),
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
        read_projects=("6",),
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
async def test_get_work_package_returns_full_description_by_default() -> None:
    long_desc = "word " * 400 + "END"  # well over 1200 chars

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_wp_detail_payload_with_description(42, "42", long_desc),
            request=request,
        )

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))

    detail = await client.get_work_package("42")

    assert detail.description is not None
    assert detail.description.endswith("END</user-content>")  # not cut, includes delimiter
    assert detail.description.startswith("<user-content>")
    assert "…" not in detail.description
    assert detail.description_truncated is False
    # description_length is the original length without delimiters
    assert detail.description_length + 29 == len(detail.description)  # +29 for <user-content> tags

    await client.aclose()


@pytest.mark.asyncio
async def test_get_work_package_text_limit_caps_and_flags() -> None:
    long_desc = "a" * 2000

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_wp_detail_payload_with_description(42, "42", long_desc),
            request=request,
        )

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))

    detail = await client.get_work_package("42", text_limit=200)

    assert detail.description is not None
    # Description includes <user-content> tags (29 chars), so limit is 200 + 29 = 229
    assert len(detail.description) <= 229
    assert detail.description.startswith("<user-content>")
    assert detail.description.endswith("…</user-content>")
    assert detail.description_truncated is True
    assert detail.description_length == 2000
    # Invariant.
    assert detail.description_truncated == (detail.description_length > 200)

    await client.aclose()


@pytest.mark.asyncio
async def test_get_work_package_preserves_paragraphs() -> None:
    structured = "First paragraph.\n\nSecond paragraph.\n\n- item one\n- item two"

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_wp_detail_payload_with_description(42, "42", structured),
            request=request,
        )

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))

    detail = await client.get_work_package("42")

    # newlines/list preserved, but wrapped in delimiters
    assert detail.description == f"<user-content>{structured}</user-content>"

    await client.aclose()


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
async def test_resolve_work_package_id_fetches_and_validates_both_reference_shapes() -> None:
    # Both a numeric id and a semantic ref fetch the WP to validate its
    # project against the allowlist — neither shape short-circuits.
    requests: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/api/v3/work_packages/99":
            return httpx.Response(200, json=_wp_detail_payload(99, "99"), request=request)
        if request.url.path == "/api/v3/work_packages/PROJ-7":
            return httpx.Response(200, json=_wp_detail_payload(55, "PROJ-7"), request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))

    assert await client._resolve_work_package_id(99) == 99
    assert requests == ["/api/v3/work_packages/99"]

    assert await client._resolve_work_package_id("PROJ-7") == 55
    assert requests == ["/api/v3/work_packages/99", "/api/v3/work_packages/PROJ-7"]

    await client.aclose()


@pytest.mark.asyncio
async def test_list_work_packages_created_on_validates_format() -> None:
    """Test that created_on rejects invalid date formats."""
    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(lambda r: None))

    with pytest.raises(InvalidInputError, match="YYYY-MM-DD format"):
        await client.list_work_packages(created_on="2024/01/15")

    with pytest.raises(InvalidInputError, match="YYYY-MM-DD format"):
        await client.list_work_packages(created_on="15-01-2024")

    with pytest.raises(InvalidInputError, match="YYYY-MM-DD format"):
        await client.list_work_packages(created_on="2024-13-01")

    await client.aclose()


@pytest.mark.asyncio
async def test_list_work_packages_created_between_validates_range() -> None:
    """Test that created_between validates start <= end."""
    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(lambda r: None))

    with pytest.raises(InvalidInputError, match="start date must be <= end date"):
        await client.list_work_packages(created_between=["2024-12-31", "2024-01-01"])

    with pytest.raises(InvalidInputError, match="exactly 2 dates"):
        await client.list_work_packages(created_between=["2024-01-01"])

    with pytest.raises(InvalidInputError, match="exactly 2 dates"):
        await client.list_work_packages(created_between=["2024-01-01", "2024-01-31", "2024-02-01"])

    await client.aclose()


@pytest.mark.asyncio
async def test_list_work_packages_rejects_both_on_and_between() -> None:
    """Test mutual exclusivity of _on and _between filters."""
    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(lambda r: None))

    with pytest.raises(InvalidInputError, match="Cannot specify both created_on and created_between"):
        await client.list_work_packages(created_on="2024-01-15", created_between=["2024-01-01", "2024-01-31"])

    with pytest.raises(InvalidInputError, match="Cannot specify both updated_on and updated_between"):
        await client.list_work_packages(updated_on="2024-01-15", updated_between=["2024-01-01", "2024-01-31"])

    with pytest.raises(InvalidInputError, match="Cannot specify both due_on and due_between"):
        await client.list_work_packages(due_on="2024-01-15", due_between=["2024-01-01", "2024-01-31"])

    await client.aclose()


@pytest.mark.asyncio
async def test_list_work_packages_created_on_builds_filter() -> None:
    """Test that created_on generates correct API filter."""
    captured: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages" and request.method == "GET":
            captured["filters"] = request.url.params.get("filters", "")
            return httpx.Response(200, json={"_embedded": {"elements": []}, "total": 0}, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))
    await client.list_work_packages(created_on="2024-01-15")

    filters = json.loads(captured["filters"])
    created_filter = next(f for f in filters if "created_at" in f)
    assert created_filter["created_at"]["operator"] == "=d"
    assert created_filter["created_at"]["values"] == ["2024-01-15"]

    await client.aclose()


@pytest.mark.asyncio
async def test_list_work_packages_created_between_builds_filter() -> None:
    """Test that created_between generates correct API filter."""
    captured: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages" and request.method == "GET":
            captured["filters"] = request.url.params.get("filters", "")
            return httpx.Response(200, json={"_embedded": {"elements": []}, "total": 0}, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))
    await client.list_work_packages(created_between=["2024-01-01", "2024-01-31"])

    filters = json.loads(captured["filters"])
    created_filter = next(f for f in filters if "created_at" in f)
    assert created_filter["created_at"]["operator"] == "<>d"
    assert created_filter["created_at"]["values"] == ["2024-01-01", "2024-01-31"]

    await client.aclose()


@pytest.mark.asyncio
async def test_list_work_packages_multiple_date_filters() -> None:
    """Test combining multiple date filters."""
    captured: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages" and request.method == "GET":
            captured["filters"] = request.url.params.get("filters", "")
            return httpx.Response(200, json={"_embedded": {"elements": []}, "total": 0}, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))
    await client.list_work_packages(
        created_between=["2024-01-01", "2024-01-31"], updated_on="2024-01-15", due_on="2024-02-01"
    )

    filters = json.loads(captured["filters"])
    assert len([f for f in filters if "created_at" in f]) == 1
    assert len([f for f in filters if "updated_at" in f]) == 1
    assert len([f for f in filters if "due_date" in f]) == 1

    created_filter = next(f for f in filters if "created_at" in f)
    assert created_filter["created_at"]["operator"] == "<>d"

    updated_filter = next(f for f in filters if "updated_at" in f)
    assert updated_filter["updated_at"]["operator"] == "=d"

    due_filter = next(f for f in filters if "due_date" in f)
    assert due_filter["due_date"]["operator"] == "=d"

    await client.aclose()


@pytest.mark.asyncio
async def test_search_work_packages_date_filters() -> None:
    """Test that search_work_packages also supports date filters."""
    captured: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages" and request.method == "GET":
            captured["filters"] = request.url.params.get("filters", "")
            return httpx.Response(200, json={"_embedded": {"elements": []}, "total": 0}, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))
    await client.search_work_packages(search="test", updated_on="2024-07-09")

    filters = json.loads(captured["filters"])
    # Should have both subject_or_id filter and updated_at filter
    assert any("subject_or_id" in f for f in filters)
    assert any("updated_at" in f for f in filters)

    updated_filter = next(f for f in filters if "updated_at" in f)
    assert updated_filter["updated_at"]["operator"] == "=d"
    assert updated_filter["updated_at"]["values"] == ["2024-07-09"]

    await client.aclose()


@pytest.mark.asyncio
async def test_list_work_packages_type_filter_uses_correct_key() -> None:
    """Verify type filter uses type_id key per source definition.

    OpenProject CE 17.5 app/models/queries/work_packages/filter/type_filter.rb
    defines: def self.key → :type_id

    This test ensures we use the official filter key as defined in the source.
    """
    captured: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo":
            return httpx.Response(
                200,
                json={
                    "_type": "Project",
                    "id": 1,
                    "name": "Demo",
                    "identifier": "demo",
                    "_links": {"types": {"href": "/api/v3/projects/1/types"}},
                },
                request=request,
            )
        if request.url.path == "/api/v3/projects/1/types":
            return httpx.Response(
                200,
                json={"_embedded": {"elements": [{"id": 1, "name": "Task"}]}},
                request=request,
            )
        if request.url.path == "/api/v3/work_packages":
            captured["filters"] = request.url.params.get("filters", "")
            return httpx.Response(200, json={"_embedded": {"elements": []}, "total": 0}, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))
    await client.list_work_packages(type="Task", project="demo")

    filters = json.loads(captured["filters"])
    # Must use "type_id" not "type"
    assert any("type_id" in f for f in filters), "type_id filter key not found"
    assert not any("type" in f and "type_id" not in f for f in filters), "Found deprecated 'type' key"

    type_filter = next(f for f in filters if "type_id" in f)
    assert type_filter["type_id"]["operator"] == "="
    assert len(type_filter["type_id"]["values"]) == 1

    await client.aclose()
