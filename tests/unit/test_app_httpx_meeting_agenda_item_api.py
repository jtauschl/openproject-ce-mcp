from __future__ import annotations

import json

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_meeting_agenda_item_api import (
    HttpxMeetingAgendaItemApi,
    normalize_meeting_agenda_item,
)
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _agenda_item_payload(*, item_id: int = 21, title: str = "Discuss roadmap") -> dict:
    return {
        "id": item_id,
        "title": title,
        "notes": {"raw": "Some notes", "html": "<p>Some notes</p>"},
        "position": 1,
        "durationInMinutes": 10,
        "itemType": "simple",
        "lockVersion": 3,
        "createdAt": "2026-08-01T00:00:00Z",
        "updatedAt": "2026-08-02T00:00:00Z",
        "_links": {
            "meeting": {"href": "/api/v3/meetings/12", "title": "Sprint Planning"},
            "author": {"href": "/api/v3/users/1", "title": "Alice"},
            "presenter": {"href": "/api/v3/users/2", "title": "Bob"},
            "workPackage": {"href": "/api/v3/work_packages/99", "title": "Fix bug"},
            "section": {"href": "/api/v3/meeting_sections/41", "title": "Backlog"},
        },
        "_embedded": {"outcomes": [{"id": 31}, {"id": 32}]},
    }


def test_normalize_meeting_agenda_item_extracts_all_fields() -> None:
    summary = normalize_meeting_agenda_item(_agenda_item_payload(), text_limit=None)
    assert summary.id == 21
    assert summary.title == "Discuss roadmap"
    assert summary.notes == "Some notes"
    assert summary.notes_truncated is False
    assert summary.position == 1
    assert summary.duration_in_minutes == 10
    assert summary.item_type == "simple"
    assert summary.lock_version == 3
    assert summary.meeting_id == 12
    assert summary.author == "Alice"
    assert summary.presenter == "Bob"
    assert summary.work_package_id == 99
    assert summary.meeting_section_id == 41
    assert summary.outcome_ids == [31, 32]
    assert summary.created_at == "2026-08-01T00:00:00Z"
    assert summary.updated_at == "2026-08-02T00:00:00Z"


def test_normalize_meeting_agenda_item_without_presenter_or_section() -> None:
    payload = _agenda_item_payload()
    del payload["_links"]["presenter"]
    del payload["_links"]["section"]
    summary = normalize_meeting_agenda_item(payload, text_limit=None)
    assert summary.presenter is None
    assert summary.meeting_section_id is None


def test_normalize_meeting_agenda_item_truncates_notes() -> None:
    payload = _agenda_item_payload()
    payload["notes"] = {"raw": "x" * 100}
    summary = normalize_meeting_agenda_item(payload, text_limit=10)
    assert summary.notes_truncated is True
    assert summary.notes_length == 100


@pytest.mark.asyncio
async def test_list_for_meeting_requests_the_meeting_scoped_endpoint() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/meetings/12/agenda_items"
        assert not request.url.params
        return httpx.Response(200, json={"_embedded": {"elements": [_agenda_item_payload()]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxMeetingAgendaItemApi(HttpxTransport(http_client))
        records = await api.list_for_meeting(12)

    assert [r.summary.id for r in records] == [21]


@pytest.mark.asyncio
async def test_list_for_work_package_requests_the_work_package_scoped_endpoint() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/work_packages/99/meeting_agenda_items"
        return httpx.Response(200, json={"_embedded": {"elements": [_agenda_item_payload()]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxMeetingAgendaItemApi(HttpxTransport(http_client))
        records = await api.list_for_work_package(99)

    assert [r.summary.id for r in records] == [21]


@pytest.mark.asyncio
async def test_get_requests_the_agenda_item_id() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/meeting_agenda_items/21"
        assert request.method == "GET"
        return httpx.Response(200, json=_agenda_item_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxMeetingAgendaItemApi(HttpxTransport(http_client))
        record = await api.get(21)

    assert record.summary.id == 21


@pytest.mark.asyncio
async def test_create_posts_to_global_meeting_agenda_items() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/meeting_agenda_items"
        assert request.method == "POST"
        body = json.loads(request.content)
        assert body["title"] == "Discuss roadmap"
        return httpx.Response(201, json=_agenda_item_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxMeetingAgendaItemApi(HttpxTransport(http_client))
        record = await api.create({"title": "Discuss roadmap"})

    assert record.summary.id == 21


@pytest.mark.asyncio
async def test_update_patches_the_agenda_item_id() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/meeting_agenda_items/21"
        assert request.method == "PATCH"
        return httpx.Response(200, json=_agenda_item_payload(title="Updated"), request=request)

    async with _client(handler) as http_client:
        api = HttpxMeetingAgendaItemApi(HttpxTransport(http_client))
        record = await api.update(21, {"title": "Updated"})

    assert record.summary.title == "Updated"


@pytest.mark.asyncio
async def test_delete_requests_the_agenda_item_id() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert request.url.path == "/api/v3/meeting_agenda_items/21"
        return httpx.Response(204, request=request)

    async with _client(handler) as http_client:
        api = HttpxMeetingAgendaItemApi(HttpxTransport(http_client))
        await api.delete(21)
