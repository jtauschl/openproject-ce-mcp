"""Client-level regression tests for the Backlog Buckets domain, mirroring
the equivalent Sprints tests in test_versions_and_sprints.py: these exercise
end-to-end allowlist-safe pagination through the real
`scan_records_and_paginate` helper via HTTP mocks, which the Service-level
unit tests (test_app_backlog_bucket_service.py) do not cover -- those only
prove filtering *within* a single already-fetched page.
"""

from __future__ import annotations

import dataclasses

import httpx
import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.client import OpenProjectClient


def _bucket_item(item_id: int, allowed: bool) -> dict:
    workspace_id = 7 if allowed else 99
    workspace_identifier = "demo" if allowed else "secret-project"
    workspace_name = "Demo" if allowed else "Secret Project"
    return {
        "_type": "BacklogBucket",
        "id": item_id,
        "name": f"Backlog Bucket {item_id}",
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


@pytest.mark.asyncio
async def test_list_backlog_buckets_backfills_after_allowlist_filter() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("demo",))

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/backlog_buckets" and request.method == "GET":
            assert request.url.params["offset"] == "1"
            assert request.url.params["pageSize"] == "50"
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            _bucket_item(1, allowed=False),
                            _bucket_item(2, allowed=True),
                            _bucket_item(3, allowed=False),
                            _bucket_item(4, allowed=True),
                            _bucket_item(5, allowed=False),
                            _bucket_item(6, allowed=True),
                        ]
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))
    page = await client.backlog_bucket.list(limit=2)

    assert [b.id for b in page.results] == [2, 4]
    assert page.count == 2
    assert page.total == 2
    assert page.truncated is True
    assert page.next_offset == 2

    await client.aclose()


@pytest.mark.asyncio
async def test_list_project_backlog_buckets_backfills_after_allowlist_filter() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("demo",))

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo" and request.method == "GET":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 7, "identifier": "demo", "name": "Demo", "active": True},
                request=request,
            )
        if request.url.path == "/api/v3/projects/7/backlog_buckets" and request.method == "GET":
            assert request.url.params["offset"] == "1"
            assert request.url.params["pageSize"] == "50"
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            _bucket_item(1, allowed=False),
                            _bucket_item(2, allowed=True),
                            _bucket_item(3, allowed=False),
                            _bucket_item(4, allowed=True),
                            _bucket_item(5, allowed=False),
                            _bucket_item(6, allowed=True),
                        ]
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))
    page = await client.backlog_bucket.list_for_project("demo", limit=2)

    assert [b.id for b in page.results] == [2, 4]
    assert page.count == 2
    assert page.total == 2
    assert page.truncated is True
    assert page.next_offset == 2

    await client.aclose()


@pytest.mark.asyncio
async def test_list_backlog_buckets_not_truncated_when_exactly_limit_allowed_matches_exist() -> None:
    """Regression: a naive scan implementation can set truncated=True as soon
    as `limit` allowed items are collected, without checking whether a
    matching backlog bucket actually exists beyond that window (mirrors the
    equivalent Sprints regression test)."""
    requested_offsets: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/backlog_buckets" and request.method == "GET":
            offset = request.url.params["offset"]
            requested_offsets.append(offset)
            if offset == "1":
                return httpx.Response(
                    200,
                    json={
                        "_embedded": {
                            "elements": [
                                {
                                    "id": 1,
                                    "name": "Backlog Bucket 1",
                                    "_links": {"definingWorkspace": {"href": "/api/v3/projects/1", "title": "Demo"}},
                                }
                            ]
                        }
                    },
                    request=request,
                )
            raise AssertionError(f"Unexpected offset: {offset}")
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))
    page = await client.backlog_bucket.list(limit=1)

    assert requested_offsets == ["1"], f"expected only one (short) page, got {requested_offsets}"
    assert [b.id for b in page.results] == [1]
    assert page.truncated is False
    assert page.next_offset is None

    await client.aclose()


@pytest.mark.asyncio
async def test_list_project_backlog_buckets_not_truncated_when_exactly_limit_allowed_matches_exist() -> None:
    """Same exact-limit regression as list_backlog_buckets above, for the
    project-scoped variant."""
    requested_offsets: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo" and request.method == "GET":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 7, "identifier": "demo", "name": "Demo", "active": True},
                request=request,
            )
        if request.url.path == "/api/v3/projects/7/backlog_buckets" and request.method == "GET":
            offset = request.url.params["offset"]
            requested_offsets.append(offset)
            if offset == "1":
                return httpx.Response(
                    200,
                    json={
                        "_embedded": {
                            "elements": [
                                {
                                    "id": 1,
                                    "name": "Backlog Bucket 1",
                                    "_links": {"definingWorkspace": {"href": "/api/v3/projects/7", "title": "Demo"}},
                                }
                            ]
                        }
                    },
                    request=request,
                )
            raise AssertionError(f"Unexpected offset: {offset}")
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))
    page = await client.backlog_bucket.list_for_project("demo", limit=1)

    assert requested_offsets == ["1"], f"expected only one (short) page, got {requested_offsets}"
    assert [b.id for b in page.results] == [1]
    assert page.truncated is False
    assert page.next_offset is None

    await client.aclose()
