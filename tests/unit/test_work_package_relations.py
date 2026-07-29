from __future__ import annotations

import re

import httpx
import pytest
from _client_test_helpers import _base_settings

from openproject_ce_mcp.client import (
    OpenProjectClient,
    PermissionDeniedError,
)


@pytest.mark.asyncio
async def test_get_work_package_filters_children_and_ancestors_by_read_allowlist() -> None:
    """get_work_package drops a child/ancestor entry outside OPENPROJECT_READ_PROJECTS.

    OpenProject's parent/child hierarchy is not project-constrained, so a
    linked work package's subject/display_id must not leak just because it's
    referenced from an anchor work package the caller IS allowed to read.
    """
    wp_project = {5: "allowed", 6: "secret", 7: "allowed", 8: "secret"}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/1" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 1,
                    "subject": "Anchor",
                    "_links": {
                        "project": {"href": "/api/v3/projects/1", "title": "allowed"},
                        "children": [
                            {"href": "/api/v3/work_packages/5", "title": "Kept child"},
                            {"href": "/api/v3/work_packages/6", "title": "Secret child"},
                        ],
                        "ancestors": [
                            {"href": "/api/v3/work_packages/7", "title": "Kept ancestor"},
                            {"href": "/api/v3/work_packages/8", "title": "Secret ancestor"},
                        ],
                    },
                },
                request=request,
            )
        m = re.match(r"^/api/v3/work_packages/(\d+)$", request.url.path)
        if m:
            wp = int(m.group(1))
            return httpx.Response(
                200,
                json={"id": wp, "_links": {"project": {"title": wp_project[wp]}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(read_projects=("allowed",))
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    detail = await client.get_work_package(1)

    child_titles = {c["title"] for c in detail.children or []}
    ancestor_titles = {a["title"] for a in detail.ancestors or []}
    assert child_titles == {"Kept child"}
    assert ancestor_titles == {"Kept ancestor"}

    await client.aclose()


@pytest.mark.asyncio
async def test_get_work_package_keeps_children_and_ancestors_under_wide_open_allowlist() -> None:
    """No extra per-item requests fire when read_projects is wide-open ('*')."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/1" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 1,
                    "subject": "Anchor",
                    "_links": {
                        "project": {"href": "/api/v3/projects/1", "title": "Demo"},
                        "children": [{"href": "/api/v3/work_packages/5", "title": "Child"}],
                        "ancestors": [{"href": "/api/v3/work_packages/7", "title": "Ancestor"}],
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(read_projects=("*",))
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    detail = await client.get_work_package(1)

    assert [c["title"] for c in detail.children or []] == ["Child"]
    assert [a["title"] for a in detail.ancestors or []] == ["Ancestor"]

    await client.aclose()


@pytest.mark.asyncio
async def test_list_work_package_watchers_denies_anchor_outside_read_allowlist() -> None:
    """list_work_package_watchers must check the anchor WP's own project.

    Previously it fetched work_packages/{id}/watchers directly with no
    allowlist check at all, leaking watcher names/emails for any WP id.
    """

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/9" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 9, "_links": {"project": {"href": "/api/v3/projects/2", "title": "secret"}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(read_projects=("allowed",))
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(PermissionDeniedError):
        await client.list_work_package_watchers(9)

    await client.aclose()


@pytest.mark.asyncio
async def test_list_work_package_watchers_allows_anchor_inside_read_allowlist() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/9" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 9, "_links": {"project": {"href": "/api/v3/projects/1", "title": "allowed"}}},
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/9/watchers" and request.method == "GET":
            return httpx.Response(
                200,
                json={"_embedded": {"elements": [{"id": 3, "name": "Alice"}]}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(read_projects=("allowed",))
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.list_work_package_watchers(9)

    assert result.count == 1

    await client.aclose()
