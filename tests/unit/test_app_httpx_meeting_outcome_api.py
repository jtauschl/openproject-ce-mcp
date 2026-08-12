from __future__ import annotations

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_meeting_outcome_api import HttpxMeetingOutcomeApi, normalize_meeting_outcome
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _outcome_payload(*, outcome_id: int = 31, kind: str = "info") -> dict:
    return {
        "id": outcome_id,
        "kind": kind,
        "notes": {"raw": "Follow up next week"},
        "createdAt": "2026-08-01T00:00:00Z",
        "updatedAt": "2026-08-02T00:00:00Z",
        "_links": {
            "agendaItem": {"href": "/api/v3/meeting_agenda_items/21", "title": "Discuss roadmap"},
            "author": {"href": "/api/v3/users/1", "title": "Alice"},
            "workPackage": {"href": "/api/v3/work_packages/99", "title": "Fix bug"},
        },
    }


def test_normalize_meeting_outcome_reads_the_agendaItem_hal_key() -> None:
    """Critical: the meeting_agenda_item link renders under HAL key
    "agendaItem" (as: :agendaItem in source), NOT "meetingAgendaItem" -- a
    naive guess following the model field name would silently break the
    entire fetch-then-check authorization chain for this domain."""
    summary = normalize_meeting_outcome(_outcome_payload(), text_limit=None)
    assert summary.meeting_agenda_item_id == 21


def test_normalize_meeting_outcome_extracts_all_fields() -> None:
    summary = normalize_meeting_outcome(_outcome_payload(), text_limit=None)
    assert summary.id == 31
    assert summary.kind == "info"
    assert summary.notes == "Follow up next week"
    assert summary.notes_truncated is False
    assert summary.author == "Alice"
    assert summary.work_package_id == 99
    assert summary.created_at == "2026-08-01T00:00:00Z"
    assert summary.updated_at == "2026-08-02T00:00:00Z"


def test_normalize_meeting_outcome_without_author() -> None:
    payload = _outcome_payload()
    del payload["_links"]["author"]
    summary = normalize_meeting_outcome(payload, text_limit=None)
    assert summary.author is None


@pytest.mark.asyncio
async def test_list_for_agenda_item_requires_meeting_id_and_agenda_item_id_in_path() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/meetings/12/agenda_items/21/outcomes"
        return httpx.Response(200, json={"_embedded": {"elements": [_outcome_payload()]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxMeetingOutcomeApi(HttpxTransport(http_client))
        records = await api.list_for_agenda_item(12, 21)

    assert [r.summary.id for r in records] == [31]


@pytest.mark.asyncio
async def test_get_requests_the_outcome_id() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/meeting_outcomes/31"
        return httpx.Response(200, json=_outcome_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxMeetingOutcomeApi(HttpxTransport(http_client))
        record = await api.get(31)

    assert record.summary.id == 31


@pytest.mark.asyncio
async def test_create_posts_to_global_meeting_outcomes() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/meeting_outcomes"
        assert request.method == "POST"
        return httpx.Response(201, json=_outcome_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxMeetingOutcomeApi(HttpxTransport(http_client))
        record = await api.create({"kind": "info"})

    assert record.summary.id == 31


@pytest.mark.asyncio
async def test_update_patches_the_outcome_id() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/meeting_outcomes/31"
        assert request.method == "PATCH"
        return httpx.Response(200, json=_outcome_payload(kind="action"), request=request)

    async with _client(handler) as http_client:
        api = HttpxMeetingOutcomeApi(HttpxTransport(http_client))
        record = await api.update(31, {"kind": "action"})

    assert record.summary.kind == "action"


@pytest.mark.asyncio
async def test_delete_requests_the_outcome_id() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert request.url.path == "/api/v3/meeting_outcomes/31"
        return httpx.Response(204, request=request)

    async with _client(handler) as http_client:
        api = HttpxMeetingOutcomeApi(HttpxTransport(http_client))
        await api.delete(31)
