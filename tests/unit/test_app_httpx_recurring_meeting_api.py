from __future__ import annotations

import json

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_recurring_meeting_api import (
    HttpxRecurringMeetingApi,
    normalize_occurrence,
    normalize_recurring_meeting,
)
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _recurring_meeting_payload(*, recurring_meeting_id: int = 51, title: str = "Weekly Standup") -> dict:
    return {
        "id": recurring_meeting_id,
        "title": title,
        "frequency": "weekly",
        "monthlyDay": None,
        "monthlyOrdinal": None,
        "monthlyWeekday": None,
        "interval": 1,
        "endAfter": "never",
        "endDate": None,
        "iterations": None,
        "timeZone": "UTC",
        "startTime": "2026-09-01T09:00:00Z",
        "location": "Room 2",
        "duration": 0.5,
        "notify": True,
        "createdAt": "2026-08-01T00:00:00Z",
        "updatedAt": "2026-08-02T00:00:00Z",
        "_links": {
            "project": {"href": "/api/v3/projects/6", "title": "Demo"},
            "author": {"href": "/api/v3/users/1", "title": "Alice"},
            "template": {"href": "/api/v3/meetings/50", "title": "Weekly Standup Template"},
        },
    }


def test_normalize_recurring_meeting_duration_is_a_raw_float_not_a_formatted_string() -> None:
    """Critical distinction from Meeting.duration: RecurringMeeting's duration
    is read straight off template&.duration (a raw float), NOT
    format_duration_from_hours' formatted string."""
    summary = normalize_recurring_meeting(_recurring_meeting_payload())
    assert summary.duration == 0.5
    assert isinstance(summary.duration, float)


def test_normalize_recurring_meeting_extracts_all_fields() -> None:
    summary = normalize_recurring_meeting(_recurring_meeting_payload())
    assert summary.id == 51
    assert summary.title == "Weekly Standup"
    assert summary.frequency == "weekly"
    assert summary.interval == 1
    assert summary.end_after == "never"
    assert summary.time_zone == "UTC"
    assert summary.start_time == "2026-09-01T09:00:00Z"
    assert summary.location == "Room 2"
    assert summary.notify is True
    assert summary.author == "Alice"
    assert summary.project_id == 6
    assert summary.project == "Demo"
    assert summary.template_meeting_id == 50


def test_normalize_recurring_meeting_without_duration() -> None:
    payload = _recurring_meeting_payload()
    payload["duration"] = None
    summary = normalize_recurring_meeting(payload)
    assert summary.duration is None


def test_normalize_occurrence_defaults_state_to_planned() -> None:
    summary = normalize_occurrence({"startTime": "2026-09-08T09:00:00Z", "_links": {}})
    assert summary.state == "planned"
    assert summary.meeting_id is None


def test_normalize_occurrence_with_meeting_link() -> None:
    summary = normalize_occurrence(
        {"startTime": "2026-09-08T09:00:00Z", "state": "open", "_links": {"meeting": {"href": "/api/v3/meetings/13"}}}
    )
    assert summary.state == "open"
    assert summary.meeting_id == 13


@pytest.mark.asyncio
async def test_list_page_sends_project_id_filter_when_given() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        filters = request.url.params["filters"]
        assert json.loads(filters) == [{"project_id": {"operator": "=", "values": ["6"]}}]
        return httpx.Response(200, json={"_embedded": {"elements": []}, "total": 0}, request=request)

    async with _client(handler) as http_client:
        api = HttpxRecurringMeetingApi(HttpxTransport(http_client))
        await api.list_page(offset=1, limit=10, project_id=6)


@pytest.mark.asyncio
async def test_get_requests_the_recurring_meeting_id() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/recurring_meetings/51"
        return httpx.Response(200, json=_recurring_meeting_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxRecurringMeetingApi(HttpxTransport(http_client))
        record = await api.get(51)

    assert record.summary.id == 51
    assert record.project_link == {"href": "/api/v3/projects/6", "title": "Demo"}


@pytest.mark.asyncio
async def test_create_posts_to_recurring_meetings() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/recurring_meetings"
        assert request.method == "POST"
        return httpx.Response(201, json=_recurring_meeting_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxRecurringMeetingApi(HttpxTransport(http_client))
        record = await api.create({"title": "Weekly Standup"})

    assert record.summary.id == 51


@pytest.mark.asyncio
async def test_update_patches_the_recurring_meeting_id() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/recurring_meetings/51"
        assert request.method == "PATCH"
        return httpx.Response(200, json=_recurring_meeting_payload(title="Updated"), request=request)

    async with _client(handler) as http_client:
        api = HttpxRecurringMeetingApi(HttpxTransport(http_client))
        record = await api.update(51, {"title": "Updated"})

    assert record.summary.title == "Updated"


@pytest.mark.asyncio
async def test_delete_requests_the_recurring_meeting_id() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert request.url.path == "/api/v3/recurring_meetings/51"
        return httpx.Response(204, request=request)

    async with _client(handler) as http_client:
        api = HttpxRecurringMeetingApi(HttpxTransport(http_client))
        await api.delete(51)


@pytest.mark.asyncio
async def test_list_occurrences_sends_limit_only_for_upcoming_filter() -> None:
    seen_params = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/recurring_meetings/51/occurrences/upcoming"
        seen_params.update(dict(request.url.params))
        return httpx.Response(200, json={"_embedded": {"elements": []}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxRecurringMeetingApi(HttpxTransport(http_client))
        await api.list_occurrences(51, filter="upcoming", limit=5)

    assert seen_params == {"limit": "5"}


@pytest.mark.asyncio
async def test_list_occurrences_never_sends_limit_for_non_upcoming_filters() -> None:
    seen_params = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/recurring_meetings/51/occurrences/past"
        seen_params.update(dict(request.url.params))
        return httpx.Response(200, json={"_embedded": {"elements": []}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxRecurringMeetingApi(HttpxTransport(http_client))
        await api.list_occurrences(51, filter="past", limit=5)

    assert "limit" not in seen_params


@pytest.mark.asyncio
async def test_init_occurrence_returns_full_meeting_summary_normalized_via_normalize_meeting() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/v3/recurring_meetings/51":
            return httpx.Response(200, json=_recurring_meeting_payload(), request=request)
        if request.url.path == "/api/v3/meetings/50":
            return httpx.Response(200, json={"id": 50, "lockVersion": 0, "state": "open"}, request=request)
        assert request.url.path == "/api/v3/recurring_meetings/51/occurrences/2026-09-08T09:00:00Z/init"
        assert request.method == "POST"
        return httpx.Response(
            201,
            json={
                "id": 13,
                "title": "Weekly Standup",
                "location": None,
                "lockVersion": 0,
                "startTime": "2026-09-08T09:00:00Z",
                "endTime": None,
                "duration": "PT30M",
                "state": "open",
                "sharing": "invited",
                "template": False,
                "notify": True,
                "_links": {"project": {"href": "/api/v3/projects/6", "title": "Demo"}},
                "_embedded": {"participants": []},
            },
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxRecurringMeetingApi(HttpxTransport(http_client))
        summary = await api.init_occurrence(51, start_time="2026-09-08T09:00:00Z")

    assert summary.id == 13
    assert summary.title == "Weekly Standup"
    # Template already open -> no PATCH issued, only the two GET lookups plus init.
    assert [r.method for r in requests] == ["GET", "GET", "POST"]


@pytest.mark.asyncio
async def test_init_occurrence_clears_draft_template_state_before_init() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/v3/recurring_meetings/51" and request.method == "GET":
            return httpx.Response(200, json=_recurring_meeting_payload(), request=request)
        if request.url.path == "/api/v3/meetings/50" and request.method == "GET":
            return httpx.Response(200, json={"id": 50, "lockVersion": 2, "state": "draft"}, request=request)
        if request.url.path == "/api/v3/meetings/50" and request.method == "PATCH":
            body = json.loads(request.content)
            assert body == {"state": "open", "lockVersion": 2}
            return httpx.Response(200, json={"id": 50, "lockVersion": 3, "state": "open"}, request=request)
        assert request.url.path == "/api/v3/recurring_meetings/51/occurrences/2026-09-08T09:00:00Z/init"
        assert request.method == "POST"
        return httpx.Response(
            201,
            json={
                "id": 13,
                "title": "Weekly Standup",
                "location": None,
                "lockVersion": 0,
                "startTime": "2026-09-08T09:00:00Z",
                "endTime": None,
                "duration": "PT30M",
                "state": "open",
                "sharing": "invited",
                "template": False,
                "notify": True,
                "_links": {"project": {"href": "/api/v3/projects/6", "title": "Demo"}},
                "_embedded": {"participants": []},
            },
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxRecurringMeetingApi(HttpxTransport(http_client))
        summary = await api.init_occurrence(51, start_time="2026-09-08T09:00:00Z")

    assert summary.id == 13
    assert [r.method for r in requests] == ["GET", "GET", "PATCH", "POST"]


@pytest.mark.asyncio
async def test_cancel_occurrence_deletes_by_start_time() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/recurring_meetings/51/occurrences/2026-09-08T09:00:00Z"
        assert request.method == "DELETE"
        return httpx.Response(204, request=request)

    async with _client(handler) as http_client:
        api = HttpxRecurringMeetingApi(HttpxTransport(http_client))
        await api.cancel_occurrence(51, start_time="2026-09-08T09:00:00Z")
