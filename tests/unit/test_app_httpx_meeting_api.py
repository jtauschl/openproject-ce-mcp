from __future__ import annotations

import json

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_meeting_api import HttpxMeetingApi, normalize_meeting
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport
from openproject_ce_mcp.models import MeetingParticipantSummary

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _meeting_payload(*, meeting_id: int = 12, title: str = "Sprint Planning") -> dict:
    return {
        "id": meeting_id,
        "title": title,
        "location": "Room 1",
        "lockVersion": 2,
        "startTime": "2026-09-01T09:00:00Z",
        "endTime": "2026-09-01T10:00:00Z",
        "duration": "PT1H",
        "state": "open",
        "sharing": "invited",
        "template": False,
        "notify": True,
        "createdAt": "2026-08-01T00:00:00Z",
        "updatedAt": "2026-08-02T00:00:00Z",
        "_links": {
            "project": {"href": "/api/v3/projects/6", "title": "Demo"},
            "author": {"href": "/api/v3/users/1", "title": "Alice"},
            "recurringMeeting": {"href": "/api/v3/recurring_meetings/51"},
        },
        "_embedded": {"participants": [{"id": 5, "name": "Bob"}]},
    }


def test_normalize_meeting_extracts_all_fields() -> None:
    summary = normalize_meeting(_meeting_payload())
    assert summary.id == 12
    assert summary.title == "Sprint Planning"
    assert summary.location == "Room 1"
    assert summary.lock_version == 2
    assert summary.start_time == "2026-09-01T09:00:00Z"
    assert summary.end_time == "2026-09-01T10:00:00Z"
    assert summary.duration == "PT1H"
    assert summary.state == "open"
    assert summary.sharing == "invited"
    assert summary.template is False
    assert summary.notify is True
    assert summary.author == "Alice"
    assert summary.participants == [MeetingParticipantSummary(id=5, name="Bob")]
    assert summary.project_id == 6
    assert summary.project == "Demo"
    assert summary.recurring_meeting_id == 51
    assert summary.created_at == "2026-08-01T00:00:00Z"
    assert summary.updated_at == "2026-08-02T00:00:00Z"


def test_normalize_meeting_without_recurring_meeting_link() -> None:
    payload = _meeting_payload()
    del payload["_links"]["recurringMeeting"]
    summary = normalize_meeting(payload)
    assert summary.recurring_meeting_id is None


def test_normalize_meeting_without_participants() -> None:
    payload = _meeting_payload()
    payload["_embedded"]["participants"] = []
    summary = normalize_meeting(payload)
    assert summary.participants == []


@pytest.mark.asyncio
async def test_list_page_sends_offset_and_page_size() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/meetings"
        assert request.url.params["offset"] == "2"
        assert request.url.params["pageSize"] == "5"
        assert "filters" not in request.url.params
        return httpx.Response(
            200, json={"_embedded": {"elements": [_meeting_payload(meeting_id=3)]}, "total": 3}, request=request
        )

    async with _client(handler) as http_client:
        api = HttpxMeetingApi(HttpxTransport(http_client))
        records, total = await api.list_page(offset=2, limit=5, project_id=None)

    assert [r.summary.id for r in records] == [3]
    assert total == 3


@pytest.mark.asyncio
async def test_list_page_sends_project_id_filter_when_given() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        filters = request.url.params["filters"]
        assert json.loads(filters) == [{"project_id": {"operator": "=", "values": ["6"]}}]
        return httpx.Response(200, json={"_embedded": {"elements": []}, "total": 0}, request=request)

    async with _client(handler) as http_client:
        api = HttpxMeetingApi(HttpxTransport(http_client))
        await api.list_page(offset=1, limit=10, project_id=6)


@pytest.mark.asyncio
async def test_get_requests_the_meeting_id() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/meetings/12"
        assert request.method == "GET"
        return httpx.Response(200, json=_meeting_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxMeetingApi(HttpxTransport(http_client))
        record = await api.get(12)

    assert record.summary.id == 12
    assert record.project_link == {"href": "/api/v3/projects/6", "title": "Demo"}


@pytest.mark.asyncio
async def test_create_form_posts_to_meetings_form() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/meetings/form"
        assert request.method == "POST"
        body = json.loads(request.content)
        return httpx.Response(200, json={"_embedded": {"payload": body, "validationErrors": {}}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxMeetingApi(HttpxTransport(http_client))
        form = await api.create_form({"title": "Standup"})

    assert form.payload == {"title": "Standup"}
    assert form.validation_errors == {}


@pytest.mark.asyncio
async def test_create_form_extracts_message_first_validation_errors() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "_embedded": {
                    "payload": {},
                    "validationErrors": {"title": {"message": "can't be blank"}},
                }
            },
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxMeetingApi(HttpxTransport(http_client))
        form = await api.create_form({})

    assert form.validation_errors == {"title": "can't be blank"}


@pytest.mark.asyncio
async def test_update_form_posts_to_meeting_id_form() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/meetings/12/form"
        assert request.method == "POST"
        return httpx.Response(200, json={"_embedded": {"payload": {}, "validationErrors": {}}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxMeetingApi(HttpxTransport(http_client))
        await api.update_form(12, {})


@pytest.mark.asyncio
async def test_commit_create_posts_to_meetings() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/meetings"
        assert request.method == "POST"
        return httpx.Response(201, json=_meeting_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxMeetingApi(HttpxTransport(http_client))
        record = await api.commit_create({"title": "Standup"})

    assert record.summary.id == 12


@pytest.mark.asyncio
async def test_commit_update_patches_meeting_id() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/meetings/12"
        assert request.method == "PATCH"
        return httpx.Response(200, json=_meeting_payload(title="Standup Updated"), request=request)

    async with _client(handler) as http_client:
        api = HttpxMeetingApi(HttpxTransport(http_client))
        record = await api.commit_update(12, {"title": "Standup Updated"})

    assert record.summary.title == "Standup Updated"


@pytest.mark.asyncio
async def test_delete_requests_the_meeting_id() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert request.url.path == "/api/v3/meetings/12"
        return httpx.Response(204, request=request)

    async with _client(handler) as http_client:
        api = HttpxMeetingApi(HttpxTransport(http_client))
        await api.delete(12)
