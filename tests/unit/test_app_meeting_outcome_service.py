from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import NotFoundError, PermissionDeniedError
from openproject_ce_mcp.app.ports.meeting_agenda_item_api import MeetingAgendaItemRecord
from openproject_ce_mcp.app.ports.meeting_api import MeetingRecord
from openproject_ce_mcp.app.ports.meeting_outcome_api import MeetingOutcomeRecord
from openproject_ce_mcp.app.services.meeting_outcome_service import MeetingOutcomeService
from openproject_ce_mcp.models import MeetingAgendaItemSummary, MeetingOutcomeSummary, MeetingSummary


def _outcome_summary(outcome_id: int = 31, **extra) -> MeetingOutcomeSummary:
    defaults = {
        "id": outcome_id,
        "kind": "info",
        "notes": None,
        "notes_truncated": False,
        "notes_length": None,
        "author": "Alice",
        "meeting_agenda_item_id": 21,
        "work_package_id": None,
        "created_at": "2026-08-01T00:00:00Z",
        "updated_at": "2026-08-01T00:00:00Z",
    }
    defaults.update(extra)
    return MeetingOutcomeSummary(**defaults)


def _agenda_summary(item_id: int = 21, **extra) -> MeetingAgendaItemSummary:
    defaults = {
        "id": item_id,
        "title": "Discuss roadmap",
        "notes": None,
        "notes_truncated": False,
        "notes_length": None,
        "position": 1,
        "duration_in_minutes": 10,
        "item_type": "simple",
        "lock_version": 0,
        "meeting_id": 12,
        "author": "Alice",
        "presenter": None,
        "work_package_id": None,
        "meeting_section_id": None,
        "outcome_ids": [31],
        "created_at": "2026-08-01T00:00:00Z",
        "updated_at": "2026-08-01T00:00:00Z",
    }
    defaults.update(extra)
    return MeetingAgendaItemSummary(**defaults)


def _meeting_summary(meeting_id: int = 12, **extra) -> MeetingSummary:
    defaults = {
        "id": meeting_id,
        "title": "Sprint Planning",
        "location": None,
        "lock_version": 0,
        "start_time": None,
        "end_time": None,
        "duration": None,
        "state": "open",
        "sharing": "invited",
        "template": False,
        "notify": True,
        "author": "Alice",
        "participants": [],
        "project_id": 6,
        "project": "Demo",
        "recurring_meeting_id": None,
        "created_at": "2026-08-01T00:00:00Z",
        "updated_at": "2026-08-01T00:00:00Z",
    }
    defaults.update(extra)
    return MeetingSummary(**defaults)


class _FakeMeetingApi:
    def __init__(self, project_link=None) -> None:
        self._project_link = project_link or {"href": "/api/v3/projects/6", "title": "Demo"}
        self.get_calls: list[int] = []

    async def get(self, meeting_id: int) -> MeetingRecord:
        self.get_calls.append(meeting_id)
        return MeetingRecord(summary=_meeting_summary(meeting_id), project_link=self._project_link)


class _FakeMeetingAgendaItemApi:
    def __init__(self, meeting_id: int | None = 12) -> None:
        self._meeting_id = meeting_id
        self.get_calls: list[int] = []

    async def get(self, agenda_item_id: int) -> MeetingAgendaItemRecord:
        self.get_calls.append(agenda_item_id)
        return MeetingAgendaItemRecord(summary=_agenda_summary(agenda_item_id, meeting_id=self._meeting_id))


class _FakeMeetingOutcomeApi:
    def __init__(self, records: list[MeetingOutcomeRecord] | None = None) -> None:
        self._records = records or [MeetingOutcomeRecord(summary=_outcome_summary())]
        self.list_calls: list[tuple[int, int]] = []
        self.get_calls: list[int] = []
        self.create_calls: list[dict] = []
        self.update_calls: list[tuple[int, dict]] = []
        self.delete_calls: list[int] = []

    async def list_for_agenda_item(self, meeting_id: int, agenda_item_id: int):
        self.list_calls.append((meeting_id, agenda_item_id))
        return list(self._records)

    async def get(self, outcome_id: int) -> MeetingOutcomeRecord:
        self.get_calls.append(outcome_id)
        return self._records[0]

    async def create(self, payload: dict) -> MeetingOutcomeRecord:
        self.create_calls.append(payload)
        return self._records[0]

    async def update(self, outcome_id: int, payload: dict) -> MeetingOutcomeRecord:
        self.update_calls.append((outcome_id, payload))
        return MeetingOutcomeRecord(summary=_outcome_summary(kind="action"))

    async def delete(self, outcome_id: int) -> None:
        self.delete_calls.append(outcome_id)


def _service(
    *,
    api: _FakeMeetingOutcomeApi | None = None,
    meeting_agenda_item_api: _FakeMeetingAgendaItemApi | None = None,
    meeting_api: _FakeMeetingApi | None = None,
    settings=None,
) -> MeetingOutcomeService:
    return MeetingOutcomeService(
        api=api or _FakeMeetingOutcomeApi(),
        meeting_agenda_item_api=meeting_agenda_item_api or _FakeMeetingAgendaItemApi(),
        meeting_api=meeting_api or _FakeMeetingApi(),
        settings=settings or make_settings(),
        project_id_to_identifier={6: "demo"},
        api_prefix="/api/v3/",
    )


@pytest.mark.asyncio
async def test_list_for_agenda_item_walks_agenda_item_to_meeting_and_uses_both_ids() -> None:
    api = _FakeMeetingOutcomeApi()
    agenda_api = _FakeMeetingAgendaItemApi(meeting_id=12)
    service = _service(api=api, meeting_agenda_item_api=agenda_api)

    result = await service.list_for_agenda_item(21)

    assert result.count == 1
    assert agenda_api.get_calls == [21]
    assert api.list_calls == [(12, 21)]


@pytest.mark.asyncio
async def test_list_for_agenda_item_denies_read_when_grandparent_meeting_project_disallowed() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other-project",))
    api = _FakeMeetingOutcomeApi()
    service = _service(api=api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.list_for_agenda_item(21)

    assert api.list_calls == []


@pytest.mark.asyncio
async def test_list_for_agenda_item_fails_closed_when_agenda_item_has_no_meeting() -> None:
    agenda_api = _FakeMeetingAgendaItemApi(meeting_id=None)
    service = _service(meeting_agenda_item_api=agenda_api)

    with pytest.raises(NotFoundError):
        await service.list_for_agenda_item(21)


@pytest.mark.asyncio
async def test_get_returns_stamped_summary() -> None:
    service = _service()
    result = await service.get(31)
    assert result.id == 31


@pytest.mark.asyncio
async def test_get_denies_read_when_fetched_outcome_grandparent_meeting_project_disallowed() -> None:
    """Security regression -- the exact bypass-check requirement this
    domain's brief called out explicitly: get() must resolve the fetched
    outcome's own meeting_agenda_item_id -> meeting_id -> project chain, not
    trust any caller-supplied claim (there is none here -- outcome_id alone
    reveals nothing)."""
    settings = dataclasses.replace(make_settings(), read_projects=("other-project",))
    api = _FakeMeetingOutcomeApi([MeetingOutcomeRecord(summary=_outcome_summary(meeting_agenda_item_id=21))])
    agenda_api = _FakeMeetingAgendaItemApi(meeting_id=12)
    service = _service(api=api, meeting_agenda_item_api=agenda_api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get(31)

    assert agenda_api.get_calls == [21]


@pytest.mark.asyncio
async def test_create_preview_without_confirm_does_not_call_api_create() -> None:
    api = _FakeMeetingOutcomeApi()
    service = _service(api=api)
    result = await service.create(agenda_item_id=21, kind="info", confirm=False)
    assert result.state == "preview"
    assert api.create_calls == []


@pytest.mark.asyncio
async def test_create_commit_with_confirm_calls_api_create() -> None:
    api = _FakeMeetingOutcomeApi()
    service = _service(api=api)
    result = await service.create(agenda_item_id=21, kind="info", confirm=True)
    assert result.state == "confirmed"
    assert api.create_calls


@pytest.mark.asyncio
async def test_create_denies_write_when_grandparent_meeting_project_disallowed() -> None:
    settings = dataclasses.replace(make_settings(), write_projects=("other-project",))
    api = _FakeMeetingOutcomeApi()
    service = _service(api=api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.create(agenda_item_id=21, kind="info", confirm=True)

    assert api.create_calls == []


@pytest.mark.asyncio
async def test_create_denies_write_even_without_confirm() -> None:
    settings = dataclasses.replace(make_settings(), write_projects=("other-project",))
    api = _FakeMeetingOutcomeApi()
    service = _service(api=api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.create(agenda_item_id=21, kind="info", confirm=False)

    assert api.create_calls == []


@pytest.mark.asyncio
async def test_update_preview_without_confirm_does_not_call_api_update() -> None:
    api = _FakeMeetingOutcomeApi()
    service = _service(api=api)
    result = await service.update(outcome_id=31, kind="action", confirm=False)
    assert result.state == "preview"
    assert api.update_calls == []


@pytest.mark.asyncio
async def test_update_denies_write_when_fetched_outcome_chain_project_disallowed() -> None:
    settings = dataclasses.replace(make_settings(), write_projects=("other-project",))
    api = _FakeMeetingOutcomeApi([MeetingOutcomeRecord(summary=_outcome_summary(meeting_agenda_item_id=21))])
    service = _service(api=api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.update(outcome_id=31, kind="action", confirm=True)

    assert api.update_calls == []


@pytest.mark.asyncio
async def test_delete_preview_without_confirm_does_not_call_api_delete() -> None:
    api = _FakeMeetingOutcomeApi()
    service = _service(api=api)
    result = await service.delete(outcome_id=31, confirm=False)
    assert result.state == "preview"
    assert api.delete_calls == []


@pytest.mark.asyncio
async def test_delete_commit_with_confirm_calls_api_delete() -> None:
    api = _FakeMeetingOutcomeApi()
    service = _service(api=api)
    result = await service.delete(outcome_id=31, confirm=True)
    assert result.state == "confirmed"
    assert api.delete_calls == [31]


@pytest.mark.asyncio
async def test_delete_denies_write_when_fetched_outcome_chain_project_disallowed() -> None:
    settings = dataclasses.replace(make_settings(), write_projects=("other-project",))
    api = _FakeMeetingOutcomeApi([MeetingOutcomeRecord(summary=_outcome_summary(meeting_agenda_item_id=21))])
    service = _service(api=api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.delete(outcome_id=31, confirm=True)

    assert api.delete_calls == []


@pytest.mark.asyncio
async def test_delete_denies_write_even_without_confirm() -> None:
    settings = dataclasses.replace(make_settings(), write_projects=("other-project",))
    api = _FakeMeetingOutcomeApi([MeetingOutcomeRecord(summary=_outcome_summary(meeting_agenda_item_id=21))])
    service = _service(api=api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.delete(outcome_id=31, confirm=False)

    assert api.delete_calls == []
