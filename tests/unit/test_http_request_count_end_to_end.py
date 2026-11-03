from __future__ import annotations

import httpx
import pytest
from _client_test_helpers import _base_settings, serving_projects

from openproject_ce_mcp import http_request_counter
from openproject_ce_mcp.client import OpenProjectClient


@pytest.mark.asyncio
async def test_the_count_includes_the_lookup_of_a_project_the_directory_did_not_know() -> None:
    wire: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/9":
            return httpx.Response(
                200,
                json={"id": 9, "_links": {"project": {"href": "/api/v3/projects/3", "title": "New"}}},
                request=request,
            )
        if request.url.path == "/api/v3/projects/3":
            return httpx.Response(
                200,
                json={
                    "_type": "Project",
                    "id": 3,
                    "identifier": "allowed-new",
                    "name": "New",
                    "active": True,
                    "_links": {"self": {"href": "/api/v3/projects/3", "title": "New"}},
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/9/file_links":
            return httpx.Response(200, json={"_embedded": {"elements": []}}, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    served = serving_projects(handler, [(1, "allowed", "Allowed")])

    async def counted(request: httpx.Request) -> httpx.Response:
        wire.append(request.url.path)
        return await served(request)

    client = OpenProjectClient(_base_settings(read_projects=("allowed*",)), transport=httpx.MockTransport(counted))
    http_request_counter.reset()

    await client.file_link.list_for_work_package(9)

    assert sorted(wire) == [
        "/api/v3/projects/3",
        "/api/v3/work_packages/9",
        "/api/v3/work_packages/9/file_links",
    ]
    assert http_request_counter.current() == len(wire)
    await client.aclose()


@pytest.mark.asyncio
async def test_the_count_includes_every_page_of_the_directory_scan() -> None:
    wire: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    served = serving_projects(handler, [(1, "allowed", "Allowed"), (2, "allowed-b", "Allowed b")])

    async def counted(request: httpx.Request) -> httpx.Response:
        wire.append(request.url.path)
        return await served(request)

    client = OpenProjectClient(_base_settings(read_projects=("allowed*",)), transport=httpx.MockTransport(counted))
    http_request_counter.reset()

    assert await client._project_directory.current_readable_project_ids() == {1, 2}

    assert wire.count("/api/v3/projects") >= 2
    assert http_request_counter.current() == len(wire)
    await client.aclose()
