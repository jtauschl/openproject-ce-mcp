from __future__ import annotations

import json

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_wiki_page_link_api import HttpxWikiPageLinkApi, normalize_wiki_page_link
from openproject_ce_mcp.app.errors import OpenProjectServerError
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _link_payload(
    link_id: int = 9, *, link_type: str = "Relation", work_package_href: str | None = "/api/v3/work_packages/42"
) -> dict:
    payload: dict = {
        "id": link_id,
        "identifier": "Home",
        "wikiPageLinkType": f"urn:openproject-org:api:v3:wikiPageLinks:{link_type}",
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-02T00:00:00Z",
        "_links": {
            "provider": {"href": "/api/v3/wiki_providers/internal", "title": "Internal Wiki"},
            "author": {"href": "/api/v3/users/1", "title": "Alice"},
        },
    }
    if work_package_href is not None:
        payload["_links"]["linkable"] = {"href": work_package_href, "title": "Demo WP"}
    return payload


def test_normalize_wiki_page_link_relation_type() -> None:
    summary = normalize_wiki_page_link(_link_payload())
    assert summary.id == 9
    assert summary.identifier == "Home"
    assert summary.link_type == "relation"
    assert summary.provider == "Internal Wiki"
    assert summary.work_package_id == 42
    assert summary.author == "Alice"
    assert summary.created_at == "2026-01-01T00:00:00Z"
    assert summary.updated_at == "2026-01-02T00:00:00Z"


def test_normalize_wiki_page_link_inline_type() -> None:
    summary = normalize_wiki_page_link(_link_payload(link_type="Inline"))
    assert summary.link_type == "inline"


def test_normalize_wiki_page_link_without_linkable_link() -> None:
    summary = normalize_wiki_page_link(_link_payload(work_package_href=None))
    assert summary.work_package_id is None


@pytest.mark.asyncio
async def test_list_for_work_package_requests_one_page_with_offset_and_page_size() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/work_packages/42/wiki_page_links"
        assert request.url.params["offset"] == "2"
        assert request.url.params["pageSize"] == "2"
        return httpx.Response(
            200,
            json={"_embedded": {"elements": [_link_payload(3)]}, "total": 3},
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxWikiPageLinkApi(HttpxTransport(http_client))
        records, total = await api.list_for_work_package(42, offset=2, page_size=2)

    assert [r.summary.id for r in records] == [3]
    assert total == 3


@pytest.mark.asyncio
async def test_list_for_work_package_falls_back_to_page_length_when_total_is_missing() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"_embedded": {"elements": [_link_payload(1), _link_payload(2)]}}, request=request
        )

    async with _client(handler) as http_client:
        api = HttpxWikiPageLinkApi(HttpxTransport(http_client))
        records, total = await api.list_for_work_package(42, offset=1, page_size=50)

    assert len(records) == 2
    assert total == 2


@pytest.mark.asyncio
async def test_create_posts_bulk_elements_shape_with_one_element() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/work_packages/42/wiki_page_links"
        assert request.method == "POST"
        body = request.read()
        parsed = json.loads(body)
        elements = parsed["_embedded"]["elements"]
        assert len(elements) == 1
        assert elements[0]["identifier"] == "Home"
        assert elements[0]["_links"]["provider"]["href"] == "/api/v3/wiki_providers/internal"
        assert elements[0]["_links"]["author"]["href"] == "/api/v3/users/7"
        return httpx.Response(201, json={"_embedded": {"elements": [_link_payload(9)]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxWikiPageLinkApi(HttpxTransport(http_client))
        record = await api.create(42, identifier="Home", provider="internal", author_id=7)

    assert record.summary.id == 9


@pytest.mark.asyncio
async def test_create_raises_server_error_on_empty_response_elements() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"_embedded": {"elements": []}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxWikiPageLinkApi(HttpxTransport(http_client))
        with pytest.raises(OpenProjectServerError):
            await api.create(42, identifier="Home", provider="internal", author_id=7)


@pytest.mark.asyncio
async def test_delete_requests_the_link_id() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert request.url.path == "/api/v3/wiki_page_links/9"
        return httpx.Response(204, request=request)

    async with _client(handler) as http_client:
        api = HttpxWikiPageLinkApi(HttpxTransport(http_client))
        await api.delete(9)
