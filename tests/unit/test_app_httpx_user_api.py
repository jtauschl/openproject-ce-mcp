from __future__ import annotations

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_user_api import HttpxUserApi, normalize_user, normalize_user_detail
from openproject_ce_mcp.app.errors import InvalidInputError
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _user_payload(user_id: int = 5, login: str = "ada", name: str = "Ada Lovelace") -> dict:
    return {
        "id": user_id,
        "name": name,
        "login": login,
        "email": f"{login}@example.com",
        "status": "active",
        "admin": False,
        "locked": False,
        "firstName": "Ada",
        "lastName": "Lovelace",
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-06-01T00:00:00Z",
        "_links": {},
    }


@pytest.mark.asyncio
async def test_list_users_requests_offset_and_page_size() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/users"
        assert request.url.params.get("offset") == "1"
        assert request.url.params.get("pageSize") == "20"
        return httpx.Response(200, json={"total": 1, "_embedded": {"elements": [_user_payload()]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxUserApi(HttpxTransport(http_client), base_url=BASE_URL)
        records, total = await api.list_users(offset=1, page_size=20)

    assert total == 1
    assert len(records) == 1
    summary = records[0].summary
    assert summary.id == 5
    assert summary.login == "ada"
    assert summary.url == f"{BASE_URL}/users/5"
    detail = records[0].to_detail()
    assert detail.firstname == "Ada"
    assert detail.lastname == "Lovelace"


@pytest.mark.asyncio
async def test_list_users_falls_back_to_record_count_when_total_missing() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"_embedded": {"elements": [_user_payload(), _user_payload(user_id=6, login="bob")]}},
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxUserApi(HttpxTransport(http_client), base_url=BASE_URL)
        records, total = await api.list_users(offset=1, page_size=20)

    assert total == 2
    assert len(records) == 2


@pytest.mark.asyncio
async def test_list_users_search_walks_a_single_short_page_to_completion() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/users"
        assert request.url.params.get("offset") == "1"
        assert request.url.params.get("pageSize") == "100"
        return httpx.Response(200, json={"total": 1, "_embedded": {"elements": [_user_payload()]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxUserApi(HttpxTransport(http_client), base_url=BASE_URL)
        records = await api.list_users_search(page_size=100)

    assert len(records) == 1
    assert records[0].summary.login == "ada"


@pytest.mark.asyncio
async def test_list_users_search_walks_every_server_page() -> None:
    """Regression: Users is genuinely OffsetPaginatedCollection server-side
    (verified against OpenProject's own API implementation) -- a single
    bounded fetch capped at page_size (this
    method's prior behavior) silently hid any match beyond that cap once the
    real user count exceeded it. Two full pages (page_size=2) followed by a
    short (empty) 3rd page prove the walk continues past the first page."""
    requested_offsets: list[str | None] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/users"
        offset = request.url.params.get("offset")
        requested_offsets.append(offset)
        page_users = {
            "1": [_user_payload(user_id=1, login="alice"), _user_payload(user_id=2, login="bob")],
            "2": [_user_payload(user_id=3, login="carol")],
        }.get(offset, [])
        return httpx.Response(200, json={"total": 3, "_embedded": {"elements": page_users}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxUserApi(HttpxTransport(http_client), base_url=BASE_URL)
        records = await api.list_users_search(page_size=2)

    assert requested_offsets == ["1", "2"]
    assert [r.summary.id for r in records] == [1, 2, 3]


@pytest.mark.asyncio
async def test_get_user_quotes_the_ref() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.raw_path == b"/api/v3/users/ada%40example.com"
        return httpx.Response(200, json=_user_payload(login="ada@example.com"), request=request)

    async with _client(handler) as http_client:
        api = HttpxUserApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.get_user("ada@example.com")

    assert record.summary.login == "ada@example.com"


@pytest.mark.asyncio
async def test_get_user_rejects_path_traversal_ref() -> None:
    """Regression: user_ref was interpolated into
    the URL path with no validation -- a value like "../projects/42" quotes
    to itself unchanged (quote() never escapes ".") and httpx then normalizes
    ".." away when building the request, redirecting to an unrelated endpoint.
    A real dotted login (see test_get_user_quotes_the_ref above) is unaffected
    since it never forms a bare "." path segment on its own."""

    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"No request should ever be issued: {request.method} {request.url}")

    async with _client(handler) as http_client:
        api = HttpxUserApi(HttpxTransport(http_client), base_url=BASE_URL)
        with pytest.raises(InvalidInputError, match="user_ref"):
            await api.get_user("../projects/42")


@pytest.mark.asyncio
async def test_create_form_returns_payload_and_validation_errors() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/users/form"
        return httpx.Response(
            200,
            json={
                "_embedded": {
                    "payload": {"login": "ada"},
                    "validationErrors": {"email": {"message": "is invalid"}},
                }
            },
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxUserApi(HttpxTransport(http_client), base_url=BASE_URL)
        form = await api.create_form({"login": "ada"})

    assert form.payload == {"login": "ada"}
    assert form.validation_errors == {"email": "is invalid"}


@pytest.mark.asyncio
async def test_commit_create_posts_to_users() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v3/users"
        return httpx.Response(200, json=_user_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxUserApi(HttpxTransport(http_client), base_url=BASE_URL)
        detail = await api.commit_create({"login": "ada"})

    assert detail.id == 5


@pytest.mark.asyncio
async def test_commit_update_patches_the_user() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        assert request.url.path == "/api/v3/users/5"
        return httpx.Response(200, json=_user_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxUserApi(HttpxTransport(http_client), base_url=BASE_URL)
        detail = await api.commit_update(5, {"login": "ada"})

    assert detail.id == 5


@pytest.mark.asyncio
async def test_commit_delete_sends_delete() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert request.url.path == "/api/v3/users/5"
        return httpx.Response(204, request=request)

    async with _client(handler) as http_client:
        api = HttpxUserApi(HttpxTransport(http_client), base_url=BASE_URL)
        await api.commit_delete(5)


@pytest.mark.asyncio
async def test_commit_lock_posts_to_the_lock_subresource() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v3/users/5/lock"
        # Regression: an omitted json_body (None) sends no Content-Type header
        # at all (httpx only sets one when `json` is non-None) -- OpenProject's
        # Grape endpoint rejects a bodyless POST here with 406 "Missing
        # content-type header" even though the request carries no real data.
        # Confirmed live against a real instance; json_body={} is required.
        assert request.content == b"{}"
        return httpx.Response(200, json=_user_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxUserApi(HttpxTransport(http_client), base_url=BASE_URL)
        detail = await api.commit_lock(5)

    assert detail.id == 5


@pytest.mark.asyncio
async def test_commit_unlock_sends_delete_and_parses_the_response_body() -> None:
    # DELETE .../lock returns the full updated user representation --
    # commit_unlock must NOT issue a follow-up GET.
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert request.url.path == "/api/v3/users/5/lock"
        return httpx.Response(200, json=_user_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxUserApi(HttpxTransport(http_client), base_url=BASE_URL)
        detail = await api.commit_unlock(5)

    assert detail.id == 5


def test_normalize_user_detail_reads_identity_url_from_the_real_property() -> None:
    payload = _user_payload()
    payload["identityUrl"] = "https://idp.example.com/subjects/abc123"
    payload["_links"] = {"showUser": {"href": "/users/5"}}

    detail = normalize_user_detail(payload, base_url=BASE_URL, origin=BASE_URL)

    assert detail.identity_url == "https://idp.example.com/subjects/abc123"


def test_normalize_user_no_hidden_field_masking_applied() -> None:
    # Pure HAL->model translation only -- masking is the Service's job.
    summary = normalize_user(_user_payload(), base_url=BASE_URL, origin=BASE_URL)

    assert not hasattr(summary, "_hidden_keys") or summary._hidden_keys == frozenset()
