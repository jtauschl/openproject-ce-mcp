"""Request-count regression tests for OPM-206's WorkPackageResolutionContext.

Verifies the redundancy the ticket targets: a bulk batch of work-package writes
in the same project used to re-resolve the project ref AND re-resolve
type/version/sprint name->id lookups once per item. These tests assert the
real HTTP call counts, not just that the calls succeed -- reverting the
WorkPackageResolutionContext wiring (e.g. always constructing a fresh one
per item inside a bulk loop) makes the "same project" tests below fail.
"""

from __future__ import annotations

import json
from collections import Counter

import httpx
import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.client import OpenProjectClient


def _project_payload(project_id: int, identifier: str) -> dict:
    return {
        "_type": "Project",
        "id": project_id,
        "name": f"Project {project_id}",
        "identifier": identifier,
        "active": True,
    }


def _types_payload(type_id: int, name: str) -> dict:
    return {"_embedded": {"elements": [{"id": type_id, "name": name}]}}


def _versions_payload(version_id: int, name: str) -> dict:
    return {"total": 1, "_embedded": {"elements": [{"id": version_id, "name": name, "_links": {}}]}}


def _sprints_payload(sprint_id: int, name: str) -> dict:
    return {
        "_type": "Collection",
        "total": 1,
        "count": 1,
        "pageSize": 100,
        "offset": 1,
        "_embedded": {"elements": [{"_type": "Sprint", "id": sprint_id, "name": name, "_links": {}}]},
    }


def _form_response(request: httpx.Request, body: dict) -> httpx.Response:
    return httpx.Response(
        200, json={"_type": "Form", "_embedded": {"payload": body, "validationErrors": {}}}, request=request
    )


@pytest.mark.asyncio
async def test_create_work_package_single_call_resolves_type_and_version_once() -> None:
    """Baseline (no bulk context involved): a single create still hits each
    endpoint exactly once -- unchanged behavior from before OPM-206."""
    counts: Counter[tuple[str, str]] = Counter()

    async def handler(request: httpx.Request) -> httpx.Response:
        counts[(request.method, request.url.path)] += 1
        if request.url.path == "/api/v3/projects/proj-a":
            return httpx.Response(200, json=_project_payload(1, "proj-a"), request=request)
        if request.url.path == "/api/v3/projects/1/types":
            return httpx.Response(200, json=_types_payload(7, "Bug"), request=request)
        if request.url.path == "/api/v3/projects/1/versions":
            return httpx.Response(200, json=_versions_payload(11, "Q2"), request=request)
        if request.url.path == "/api/v3/projects/1/work_packages/form":
            return _form_response(request, json.loads(request.content))
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))
    result = await client.create_work_package(project="proj-a", type="Bug", subject="WP 1", version="Q2")
    assert result.ready is True

    assert counts[("GET", "/api/v3/projects/proj-a")] == 1
    assert counts[("GET", "/api/v3/projects/1/types")] == 1
    assert counts[("GET", "/api/v3/projects/1/versions")] == 1
    assert counts[("POST", "/api/v3/projects/1/work_packages/form")] == 1

    await client.aclose()


@pytest.mark.asyncio
async def test_update_work_package_single_call_resolves_type_version_sprint_once() -> None:
    """Baseline: a single update resolving type+version+sprint hits the shared
    project payload exactly once across all three resolutions (pre-existing
    single-call dedup via the plain ProjectResolutionContext, unchanged by
    OPM-206) and each type/version/sprint endpoint exactly once."""
    counts: Counter[tuple[str, str]] = Counter()

    async def handler(request: httpx.Request) -> httpx.Response:
        counts[(request.method, request.url.path)] += 1
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "subject": "WP",
                    "lockVersion": 3,
                    "_links": {"project": {"title": "Demo", "href": "/api/v3/projects/1"}},
                },
                request=request,
            )
        if request.url.path == "/api/v3/projects/1" and request.method == "GET":
            return httpx.Response(200, json=_project_payload(1, "proj-a"), request=request)
        if request.url.path == "/api/v3/projects/1/types":
            return httpx.Response(200, json=_types_payload(7, "Bug"), request=request)
        if request.url.path == "/api/v3/projects/1/versions":
            return httpx.Response(200, json=_versions_payload(11, "Q2"), request=request)
        if request.url.path == "/api/v3/projects/1/sprints":
            return httpx.Response(200, json=_sprints_payload(21, "Sprint1"), request=request)
        if request.url.path == "/api/v3/work_packages/42/form" and request.method == "POST":
            return _form_response(request, json.loads(request.content))
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))
    result = await client.update_work_package(work_package_id=42, type="Bug", version="Q2", sprint="Sprint1")
    assert result.ready is True

    assert counts[("GET", "/api/v3/projects/1")] == 1
    assert counts[("GET", "/api/v3/projects/1/types")] == 1
    assert counts[("GET", "/api/v3/projects/1/versions")] == 1
    assert counts[("GET", "/api/v3/projects/1/sprints")] == 1

    await client.aclose()


@pytest.mark.asyncio
async def test_bulk_create_same_project_shares_project_and_type_version_resolution() -> None:
    """The actual OPM-206 target: two bulk_create items in the same project,
    both needing the same type/version name->id lookup, must only trigger the
    project fetch and the type/version lookups ONCE for the whole batch, not
    once per item."""
    counts: Counter[tuple[str, str]] = Counter()

    async def handler(request: httpx.Request) -> httpx.Response:
        counts[(request.method, request.url.path)] += 1
        if request.url.path == "/api/v3/projects/proj-a":
            return httpx.Response(200, json=_project_payload(1, "proj-a"), request=request)
        if request.url.path == "/api/v3/projects/1/types":
            return httpx.Response(200, json=_types_payload(7, "Bug"), request=request)
        if request.url.path == "/api/v3/projects/1/versions":
            return httpx.Response(200, json=_versions_payload(11, "Q2"), request=request)
        if request.url.path == "/api/v3/projects/1/work_packages/form":
            return _form_response(request, json.loads(request.content))
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))
    result = await client.bulk_create_work_packages(
        items=[
            {"project": "proj-a", "type": "Bug", "subject": "WP 1", "version": "Q2"},
            {"project": "proj-a", "type": "Bug", "subject": "WP 2", "version": "Q2"},
        ]
    )
    assert result.succeeded == 2
    assert result.failed == 0

    # The point of OPM-206: shared across both items, not one fetch per item.
    assert counts[("GET", "/api/v3/projects/proj-a")] == 1
    assert counts[("GET", "/api/v3/projects/1/types")] == 1
    assert counts[("GET", "/api/v3/projects/1/versions")] == 1
    # Not deduped: each item still gets its own create-preview call.
    assert counts[("POST", "/api/v3/projects/1/work_packages/form")] == 2

    await client.aclose()


@pytest.mark.asyncio
async def test_bulk_update_same_project_shares_type_version_sprint_resolution() -> None:
    """Two bulk_update items for different work packages in the SAME project, both
    needing the same type/version/sprint name->id lookup, must only trigger each
    lookup ONCE for the whole batch, not once per item. A different-project test
    alone (see below) cannot catch a reverted per-item context, since with only
    one item per project it would pass either way -- this is the one that would
    actually fail if bulk_update_work_packages stopped sharing its wp_context."""
    counts: Counter[tuple[str, str]] = Counter()

    async def handler(request: httpx.Request) -> httpx.Response:
        counts[(request.method, request.url.path)] += 1
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "subject": "WP A",
                    "lockVersion": 1,
                    "_links": {"project": {"title": "Demo", "href": "/api/v3/projects/1"}},
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/43" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 43,
                    "subject": "WP B",
                    "lockVersion": 1,
                    "_links": {"project": {"title": "Demo", "href": "/api/v3/projects/1"}},
                },
                request=request,
            )
        if request.url.path == "/api/v3/projects/1" and request.method == "GET":
            return httpx.Response(200, json=_project_payload(1, "proj-a"), request=request)
        if request.url.path == "/api/v3/projects/1/types":
            return httpx.Response(200, json=_types_payload(7, "Bug"), request=request)
        if request.url.path == "/api/v3/projects/1/versions":
            return httpx.Response(200, json=_versions_payload(11, "Q2"), request=request)
        if request.url.path == "/api/v3/projects/1/sprints":
            return httpx.Response(200, json=_sprints_payload(21, "Sprint1"), request=request)
        if request.url.path in {"/api/v3/work_packages/42/form", "/api/v3/work_packages/43/form"}:
            return _form_response(request, json.loads(request.content))
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))
    result = await client.bulk_update_work_packages(
        items=[
            {"work_package_id": 42, "type": "Bug", "version": "Q2", "sprint": "Sprint1"},
            {"work_package_id": 43, "type": "Bug", "version": "Q2", "sprint": "Sprint1"},
        ]
    )
    assert result.succeeded == 2
    assert result.failed == 0

    # The point of OPM-206: shared across both items, not one lookup per item.
    assert counts[("GET", "/api/v3/projects/1")] == 1
    assert counts[("GET", "/api/v3/projects/1/types")] == 1
    assert counts[("GET", "/api/v3/projects/1/versions")] == 1
    assert counts[("GET", "/api/v3/projects/1/sprints")] == 1
    # Not deduped: each item still gets its own read + write-preview call.
    assert counts[("GET", "/api/v3/work_packages/42")] == 1
    assert counts[("GET", "/api/v3/work_packages/43")] == 1

    await client.aclose()


@pytest.mark.asyncio
async def test_bulk_update_different_projects_never_share_resolved_ids() -> None:
    """Two bulk_update items in DIFFERENT projects, both resolving a type named
    "Bug" to a different numeric id per project: each project's resolution must
    happen independently (once per project) and never cross-contaminate --
    project 1's "Bug" must not leak into project 2's write."""
    counts: Counter[tuple[str, str]] = Counter()

    async def handler(request: httpx.Request) -> httpx.Response:
        counts[(request.method, request.url.path)] += 1
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "subject": "WP A",
                    "lockVersion": 1,
                    "_links": {"project": {"title": "Project 1", "href": "/api/v3/projects/1"}},
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/43" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 43,
                    "subject": "WP B",
                    "lockVersion": 1,
                    "_links": {"project": {"title": "Project 2", "href": "/api/v3/projects/2"}},
                },
                request=request,
            )
        if request.url.path == "/api/v3/projects/1" and request.method == "GET":
            return httpx.Response(200, json=_project_payload(1, "proj-a"), request=request)
        if request.url.path == "/api/v3/projects/2" and request.method == "GET":
            return httpx.Response(200, json=_project_payload(2, "proj-b"), request=request)
        if request.url.path == "/api/v3/projects/1/types":
            return httpx.Response(200, json=_types_payload(7, "Bug"), request=request)
        if request.url.path == "/api/v3/projects/2/types":
            return httpx.Response(200, json=_types_payload(8, "Bug"), request=request)
        if request.url.path == "/api/v3/work_packages/42/form" and request.method == "POST":
            body = json.loads(request.content)
            assert body["_links"]["type"]["href"] == "/api/v3/types/7"
            return _form_response(request, body)
        if request.url.path == "/api/v3/work_packages/43/form" and request.method == "POST":
            body = json.loads(request.content)
            assert body["_links"]["type"]["href"] == "/api/v3/types/8"
            return _form_response(request, body)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))
    result = await client.bulk_update_work_packages(
        items=[
            {"work_package_id": 42, "type": "Bug"},
            {"work_package_id": 43, "type": "Bug"},
        ]
    )
    assert result.succeeded == 2
    assert result.failed == 0

    # Each project resolved (and its type looked up) independently, exactly once.
    assert counts[("GET", "/api/v3/projects/1")] == 1
    assert counts[("GET", "/api/v3/projects/2")] == 1
    assert counts[("GET", "/api/v3/projects/1/types")] == 1
    assert counts[("GET", "/api/v3/projects/2/types")] == 1

    await client.aclose()
