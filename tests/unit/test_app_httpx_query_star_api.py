from __future__ import annotations

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_query_star_api import HttpxQueryStarApi
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


@pytest.mark.asyncio
async def test_get_reads_the_query_without_running_it_and_maps_the_star_state() -> None:
    requests: list[tuple[str, dict[str, str]]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.url.path, dict(request.url.params)))
        return httpx.Response(
            200,
            json={
                "id": 3,
                "starred": True,
                "public": True,
                "_links": {
                    "project": {"href": "/api/v3/projects/6"},
                    "user": {"href": "/api/v3/users/12", "title": "Owner"},
                    "unstar": {"href": "/api/v3/queries/3/unstar"},
                },
            },
            request=request,
        )

    async with _client(handler) as http_client:
        record = await HttpxQueryStarApi(HttpxTransport(http_client, redact_server_text=False)).get(3)

    assert requests == [("/api/v3/queries/3", {"pageSize": "0"})]
    assert (record.query_id, record.starred, record.public) == (3, True, True)
    assert (record.can_star, record.can_unstar) == (False, True)
    assert record.owner_id == 12
    assert record.project_link == {"href": "/api/v3/projects/6"}


@pytest.mark.asyncio
async def test_get_of_a_global_private_query_has_no_project_link() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"id": 4, "starred": False, "public": False, "_links": {"star": {}}}, request=request
        )

    async with _client(handler) as http_client:
        record = await HttpxQueryStarApi(HttpxTransport(http_client, redact_server_text=False)).get(4)

    assert (record.project_link, record.owner_id) == (None, None)
    assert (record.starred, record.public, record.can_star) == (False, False, True)


@pytest.mark.asyncio
@pytest.mark.parametrize(("starred", "route"), [(True, "star"), (False, "unstar")])
async def test_set_starred_patches_the_matching_route_with_an_empty_json_body(starred: bool, route: str) -> None:
    requests: list[tuple[str, str, bytes]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path, request.content))
        return httpx.Response(200, json={"id": 3}, request=request)

    async with _client(handler) as http_client:
        await HttpxQueryStarApi(HttpxTransport(http_client, redact_server_text=False)).set_starred(3, starred=starred)

    assert requests == [("PATCH", f"/api/v3/queries/3/{route}", b"{}")]
