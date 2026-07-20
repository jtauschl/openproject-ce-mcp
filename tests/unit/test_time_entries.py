from __future__ import annotations

import json

import httpx
import pytest
from _client_test_helpers import _base_settings, _write_enabled_settings, make_settings

from openproject_ce_mcp.client import (
    OpenProjectClient,
)
from openproject_ce_mcp.config import Settings


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
        if request.url.path == "/api/v3/work_packages/55" and request.method == "GET":
            # list_time_entries' work_package_id filter is allowlist-checked.
            return httpx.Response(
                200,
                json={"id": 55, "_links": {"project": {"href": "/api/v3/projects/6", "title": "Demo"}}},
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
        read_projects=("demo",),
        write_projects=("demo",),
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
async def test_update_time_entry_clears_comment_in_http_payload() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
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
                        "activity": {"href": "/api/v3/time_entries/activities/3", "title": "Development"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/time_entries/10" and request.method == "PATCH":
            body = json.loads(request.content)
            assert body == {"comment": {"format": "markdown", "raw": ""}}
            return httpx.Response(
                200,
                json={
                    "id": 10,
                    "hours": "PT1H30M",
                    "spentOn": "2026-03-20",
                    "ongoing": False,
                    "comment": {"raw": ""},
                    "_links": {
                        "self": {"href": "/api/v3/time_entries/10"},
                        "project": {"href": "/api/v3/projects/6", "title": "Demo"},
                        "activity": {"href": "/api/v3/time_entries/activities/3", "title": "Development"},
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(enable_work_package_write=True)
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.update_time_entry(time_entry_id=10, comment="", confirm=True)

    assert result.confirmed is True
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
                json={
                    "_type": "Form",
                    "_embedded": {"schema": {"activity": {"_embedded": {"allowedValues": allowed_values}}}},
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
                                                    "self": {
                                                        "href": "/api/v3/time_entries/activities/3",
                                                        "title": "Development",
                                                    },
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
                                                "self": {
                                                    "href": "/api/v3/time_entries/activities/3",
                                                    "title": "Development",
                                                },
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
                json={
                    "id": 9,
                    "spentOn": "2026-07-01",
                    "startTime": "2026-07-01T09:00:00Z",
                    "endTime": "2026-07-01T10:00:00Z",
                    "_links": {},
                },
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


@pytest.mark.asyncio
async def test_create_time_entry_entity_link_uses_numeric_id_for_semantic_ref() -> None:
    """A semantic work-package ref (PROJ-7) must produce a numeric entity href.

    HAL links only resolve by numeric id; passing the displayId form through
    would build an invalid ``entity`` link.
    """
    captured: dict[str, dict] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/PROJ-7" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 7, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
                request=request,
            )
        if request.url.path == "/api/v3/time_entries" and request.method == "POST":
            captured["body"] = json.loads(request.content)
            return httpx.Response(201, json={"id": 9, "spentOn": "2026-07-01", "_links": {}}, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_write_enabled_settings(), transport=httpx.MockTransport(handler))

    await client.create_time_entry(
        work_package_id="PROJ-7",
        activity=None,
        hours="PT1H",
        spent_on="2026-07-01",
        confirm=True,
    )

    assert captured["body"]["_links"]["entity"]["href"] == "/api/v3/work_packages/7"

    await client.aclose()


@pytest.mark.asyncio
async def test_time_entry_semantic_work_package_ref_uses_numeric_entity_href_shape() -> None:
    """Verify semantic WP refs become numeric HAL entity hrefs."""
    captured: dict[str, dict] = {}
    requests: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.url.path == "/api/v3/work_packages/PROJ-7" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 7, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
                request=request,
            )
        if request.url.path == "/api/v3/time_entries" and request.method == "POST":
            captured["body"] = json.loads(request.content)
            return httpx.Response(201, json={"id": 9, "spentOn": "2026-07-01", "_links": {}}, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_write_enabled_settings(), transport=httpx.MockTransport(handler))

    await client.create_time_entry(
        work_package_id="PROJ-7",
        activity=None,
        hours="PT1H",
        spent_on="2026-07-01",
        confirm=True,
    )

    assert captured["body"]["_links"]["entity"]["href"] == "/api/v3/work_packages/7"
    assert requests == [
        ("GET", "/api/v3/work_packages/PROJ-7"),
        ("POST", "/api/v3/time_entries"),
    ]

    await client.aclose()


@pytest.mark.asyncio
async def test_list_time_entries_comment_capped_at_text_limit() -> None:
    # OPM-1457: list rows cap comment at settings.text_limit (default 500),
    # like list_projects/list_work_packages, with truncation metadata.
    long_comment = "c" * 900

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/time_entries" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            {
                                "id": 1,
                                "comment": {"raw": long_comment},
                                "_links": {},
                            }
                        ]
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))
    page = await client.list_time_entries()

    assert page.results[0].comment is not None
    assert page.results[0].comment_truncated is True
    assert page.results[0].comment_length == 900

    await client.aclose()


@pytest.mark.asyncio
async def test_get_time_entry_returns_full_comment_by_default() -> None:
    # OPM-1457: single-time-entry reads are uncapped by default, like
    # get_work_package/get_project/get_version; text_limit is an opt-in override.
    long_comment = "c" * 1500

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/time_entries/1" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 1, "comment": {"raw": long_comment}, "_links": {}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))

    full = await client.get_time_entry(1)
    assert full.comment is not None
    assert len(full.comment) == 1500 + len("<user-content></user-content>")
    assert full.comment_truncated is False

    capped = await client.get_time_entry(1, text_limit=50)
    assert capped.comment_truncated is True
    assert capped.comment_length == 1500

    await client.aclose()
