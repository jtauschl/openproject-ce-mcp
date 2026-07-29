from __future__ import annotations

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_group_api import HttpxGroupApi, normalize_group, normalize_group_detail
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _group_payload(group_id: int = 3, name: str = "Backend", members: list | dict | None = None) -> dict:
    if members is None:
        members = [{"name": "Ada Lovelace", "_links": {"self": {"href": "/api/v3/users/5"}}}]
    return {
        "id": group_id,
        "name": name,
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-06-01T00:00:00Z",
        "_links": {"memberships": {"href": "/api/v3/memberships?filters=..."}},
        "_embedded": {"members": members},
    }


@pytest.mark.asyncio
async def test_list_groups_requests_offset_and_page_size() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/groups"
        assert request.url.params.get("offset") == "1"
        assert request.url.params.get("pageSize") == "20"
        return httpx.Response(200, json={"total": 1, "_embedded": {"elements": [_group_payload()]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxGroupApi(HttpxTransport(http_client), base_url=BASE_URL)
        records, total = await api.list_groups(offset=1, page_size=20)

    assert total == 1
    assert len(records) == 1
    summary = records[0].summary
    assert summary.id == 3
    assert summary.name == "Backend"
    assert summary.member_count == 1
    assert summary.url == f"{BASE_URL}/groups/3"
    detail = records[0].to_detail()
    assert detail.members == ["Ada Lovelace"]
    assert detail.memberships_url == f"{BASE_URL}/api/v3/memberships?filters=..."


@pytest.mark.asyncio
async def test_list_groups_falls_back_to_record_count_when_total_missing() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"_embedded": {"elements": [_group_payload(), _group_payload(group_id=4, name="Frontend")]}},
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxGroupApi(HttpxTransport(http_client), base_url=BASE_URL)
        records, total = await api.list_groups(offset=1, page_size=20)

    assert total == 2
    assert len(records) == 2


@pytest.mark.asyncio
async def test_list_groups_search_walks_a_single_short_page_to_completion() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/groups"
        assert request.url.params.get("offset") == "1"
        assert request.url.params.get("pageSize") == "100"
        return httpx.Response(200, json={"total": 1, "_embedded": {"elements": [_group_payload()]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxGroupApi(HttpxTransport(http_client), base_url=BASE_URL)
        records = await api.list_groups_search(page_size=100)

    assert len(records) == 1
    assert records[0].summary.name == "Backend"


@pytest.mark.asyncio
async def test_list_groups_search_walks_every_server_page() -> None:
    """Regression (found via a full-diff Codex review on release/0.3.4, ported
    here): Groups is genuinely OffsetPaginatedCollection server-side (verified
    against op-sources) -- a single bounded fetch capped at page_size (this
    method's prior behavior) silently hid any match beyond that cap once the
    real group count exceeded it. Two full pages (page_size=2) followed by a
    short (empty) 3rd page prove the walk continues past the first page."""
    requested_offsets: list[str | None] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/groups"
        offset = request.url.params.get("offset")
        requested_offsets.append(offset)
        page_groups = {
            "1": [_group_payload(group_id=1, name="Alpha"), _group_payload(group_id=2, name="Beta")],
            "2": [_group_payload(group_id=3, name="Gamma")],
        }.get(offset, [])
        return httpx.Response(200, json={"total": 3, "_embedded": {"elements": page_groups}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxGroupApi(HttpxTransport(http_client), base_url=BASE_URL)
        records = await api.list_groups_search(page_size=2)

    assert requested_offsets == ["1", "2"]
    assert [r.summary.id for r in records] == [1, 2, 3]


@pytest.mark.asyncio
async def test_get_group_uses_plain_numeric_id() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/groups/3"
        return httpx.Response(200, json=_group_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxGroupApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.get_group(3)

    assert record.summary.id == 3


@pytest.mark.asyncio
async def test_get_member_ids_extracts_ids_from_links_members() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/groups/3"
        payload = _group_payload()
        payload["_links"]["members"] = [{"href": "/api/v3/users/5"}, {"href": "/api/v3/users/6"}]
        return httpx.Response(200, json=payload, request=request)

    async with _client(handler) as http_client:
        api = HttpxGroupApi(HttpxTransport(http_client), base_url=BASE_URL)
        ids = await api.get_member_ids(3)

    assert ids == {5, 6}


@pytest.mark.asyncio
async def test_get_member_ids_tolerates_missing_or_malformed_links() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = _group_payload()
        payload["_links"] = {}
        return httpx.Response(200, json=payload, request=request)

    async with _client(handler) as http_client:
        api = HttpxGroupApi(HttpxTransport(http_client), base_url=BASE_URL)
        ids = await api.get_member_ids(3)

    assert ids == set()


@pytest.mark.asyncio
async def test_commit_create_posts_to_groups_and_returns_summary_not_detail() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v3/groups"
        return httpx.Response(200, json=_group_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxGroupApi(HttpxTransport(http_client), base_url=BASE_URL)
        result = await api.commit_create({"name": "Backend"})

    assert result.id == 3
    assert not hasattr(result, "members")


@pytest.mark.asyncio
async def test_commit_update_patches_the_group() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        assert request.url.path == "/api/v3/groups/3"
        return httpx.Response(200, json=_group_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxGroupApi(HttpxTransport(http_client), base_url=BASE_URL)
        result = await api.commit_update(3, {"name": "Backend"})

    assert result.id == 3


@pytest.mark.asyncio
async def test_commit_delete_sends_delete() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert request.url.path == "/api/v3/groups/3"
        return httpx.Response(204, request=request)

    async with _client(handler) as http_client:
        api = HttpxGroupApi(HttpxTransport(http_client), base_url=BASE_URL)
        await api.commit_delete(3)


def test_normalize_group_tolerates_dict_shaped_members_collection() -> None:
    payload = _group_payload(members={"count": 4})

    summary = normalize_group(payload, base_url=BASE_URL)

    assert summary.member_count == 4


def test_normalize_group_tolerates_list_shaped_members_collection() -> None:
    payload = _group_payload(members=[{"name": "A"}, {"name": "B"}])

    summary = normalize_group(payload, base_url=BASE_URL)

    assert summary.member_count == 2


def test_normalize_group_counts_link_members_on_the_real_list_endpoint() -> None:
    """Regression, found via a live integration test against OpenProject
    17.4.1: list_all's real response has NO _embedded.members at all for
    each element -- membership is only ever exposed via _links.members (a
    bare array of HAL links). The _embedded.members shape the sibling tests
    above exercise is get's (single-item) response shape, not list_all's --
    member_count silently stayed 0 for every group returned by list_all
    specifically, unlike get."""
    payload = {
        "id": 3,
        "name": "Backend",
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-06-01T00:00:00Z",
        "_links": {
            "memberships": {"href": "/api/v3/memberships?filters=..."},
            "members": [
                {"href": "/api/v3/users/1", "title": "Alice"},
                {"href": "/api/v3/users/2", "title": "Bob"},
            ],
        },
    }

    summary = normalize_group(payload, base_url=BASE_URL)

    assert summary.member_count == 2


def test_normalize_group_detail_falls_back_to_link_title_when_name_missing() -> None:
    payload = _group_payload(members=[{"_links": {"self": {"href": "/api/v3/users/7", "title": "Bob"}}}])

    detail = normalize_group_detail(payload, base_url=BASE_URL, origin=BASE_URL)

    assert detail.members == ["Bob"]


def test_normalize_group_no_hidden_field_masking_applied() -> None:
    # Pure HAL->model translation only -- masking is the Service's job.
    summary = normalize_group(_group_payload(), base_url=BASE_URL)

    assert not hasattr(summary, "_hidden_keys") or summary._hidden_keys == frozenset()
