from __future__ import annotations

import json

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_user_working_hours_api import (
    HttpxUserWorkingHoursApi,
    normalize_user_working_hours,
)
from openproject_ce_mcp.app.errors import InvalidInputError
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _record_payload(record_id: int = 5, *, user_href: str | None = "/api/v3/users/3") -> dict:
    payload: dict = {
        "id": record_id,
        "validFrom": "2026-08-01",
        "mondayHours": 8,
        "tuesdayHours": 8,
        "wednesdayHours": 8,
        "thursdayHours": 8,
        "fridayHours": 4,
        "saturdayHours": None,
        "sundayHours": None,
        "availabilityFactor": 1.0,
        "_links": {},
    }
    if user_href is not None:
        payload["_links"]["user"] = {"href": user_href, "title": "Alice"}
    return payload


def test_normalize_user_working_hours_full_payload() -> None:
    summary = normalize_user_working_hours(_record_payload())
    assert summary.id == 5
    assert summary.user_id == 3
    assert summary.user_name == "Alice"
    assert summary.valid_from == "2026-08-01"
    assert summary.monday_hours == 8
    assert summary.friday_hours == 4
    assert summary.saturday_hours is None
    assert summary.sunday_hours is None
    assert summary.availability_factor == 1.0


def test_normalize_user_working_hours_without_user_link() -> None:
    summary = normalize_user_working_hours(_record_payload(user_href=None))
    assert summary.user_id is None
    assert summary.user_name is None


@pytest.mark.asyncio
async def test_list_for_user_requests_offset_and_page_size() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/users/me/working_hours"
        assert request.url.params["offset"] == "1"
        assert request.url.params["pageSize"] == "100"
        return httpx.Response(200, json={"_embedded": {"elements": [_record_payload(1)]}, "total": 1}, request=request)

    async with _client(handler) as http_client:
        api = HttpxUserWorkingHoursApi(HttpxTransport(http_client))
        records, total = await api.list_for_user("me", offset=1, page_size=100)

    assert [r.summary.id for r in records] == [1]
    assert total == 1


@pytest.mark.asyncio
async def test_list_for_user_falls_back_to_page_length_when_total_is_missing() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"_embedded": {"elements": [_record_payload(1), _record_payload(2)]}}, request=request
        )

    async with _client(handler) as http_client:
        api = HttpxUserWorkingHoursApi(HttpxTransport(http_client))
        records, total = await api.list_for_user("me", offset=1, page_size=100)

    assert len(records) == 2
    assert total == 2


@pytest.mark.asyncio
async def test_get_requests_the_working_hours_id() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/v3/users/7/working_hours/5"
        return httpx.Response(200, json=_record_payload(5), request=request)

    async with _client(handler) as http_client:
        api = HttpxUserWorkingHoursApi(HttpxTransport(http_client))
        record = await api.get("7", 5)

    assert record.summary.id == 5


@pytest.mark.asyncio
async def test_create_posts_only_the_supplied_fields() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/users/me/working_hours"
        assert request.method == "POST"
        body = json.loads(request.read())
        assert body == {"validFrom": "2026-08-01", "mondayHours": 8.0, "availabilityFactor": 0.5}
        return httpx.Response(201, json=_record_payload(9), request=request)

    async with _client(handler) as http_client:
        api = HttpxUserWorkingHoursApi(HttpxTransport(http_client))
        record = await api.create(
            "me",
            valid_from="2026-08-01",
            monday_hours=8.0,
            tuesday_hours=None,
            wednesday_hours=None,
            thursday_hours=None,
            friday_hours=None,
            saturday_hours=None,
            sunday_hours=None,
            availability_factor=0.5,
        )

    assert record.summary.id == 9


@pytest.mark.asyncio
async def test_update_patches_with_the_given_payload() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/users/7/working_hours/5"
        assert request.method == "PATCH"
        body = json.loads(request.read())
        assert body == {"mondayHours": 6.0}
        return httpx.Response(200, json=_record_payload(5), request=request)

    async with _client(handler) as http_client:
        api = HttpxUserWorkingHoursApi(HttpxTransport(http_client))
        record = await api.update("7", 5, payload={"mondayHours": 6.0})

    assert record.summary.id == 5


@pytest.mark.asyncio
async def test_delete_requests_the_working_hours_id() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert request.url.path == "/api/v3/users/me/working_hours/5"
        return httpx.Response(204, request=request)

    async with _client(handler) as http_client:
        api = HttpxUserWorkingHoursApi(HttpxTransport(http_client))
        await api.delete("me", 5)


@pytest.mark.asyncio
async def test_user_ref_rejects_path_traversal_segment() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not send a request for a rejected user_ref")

    async with _client(handler) as http_client:
        api = HttpxUserWorkingHoursApi(HttpxTransport(http_client))
        with pytest.raises(InvalidInputError):
            await api.list_for_user("..", offset=1, page_size=100)
