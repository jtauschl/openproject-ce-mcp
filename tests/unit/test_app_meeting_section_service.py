from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import PermissionDeniedError
from openproject_ce_mcp.app.ports.meeting_api import MeetingRecord
from openproject_ce_mcp.app.ports.meeting_section_api import MeetingSectionRecord
from openproject_ce_mcp.app.services.meeting_section_service import MeetingSectionService
from openproject_ce_mcp.models import MeetingSectionSummary, MeetingSummary


def _section_summary(section_id: int = 41, **extra) -> MeetingSectionSummary:
    defaults = {
        "id": section_id,
        "title": "Backlog",
        "position": 1,
        "backlog": False,
        "meeting_id": 12,
        "created_at": "2026-08-01T00:00:00Z",
        "updated_at": "2026-08-01T00:00:00Z",
    }
    defaults.update(extra)
    return MeetingSectionSummary(**defaults)


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


class _FakeMeetingSectionApi:
    def __init__(self, records: list[MeetingSectionRecord] | None = None) -> None:
        self._records = records or [MeetingSectionRecord(summary=_section_summary())]
        self.list_calls: list[int] = []
        self.get_calls: list[int] = []
        self.create_calls: list[dict] = []
        self.update_calls: list[tuple[int, dict]] = []
        self.delete_calls: list[int] = []

    async def list_for_meeting(self, meeting_id: int):
        self.list_calls.append(meeting_id)
        return list(self._records)

    async def get(self, section_id: int) -> MeetingSectionRecord:
        self.get_calls.append(section_id)
        return self._records[0]

    async def create(self, payload: dict) -> MeetingSectionRecord:
        self.create_calls.append(payload)
        return self._records[0]

    async def update(self, section_id: int, payload: dict) -> MeetingSectionRecord:
        self.update_calls.append((section_id, payload))
        return MeetingSectionRecord(summary=_section_summary(title="Updated"))

    async def delete(self, section_id: int) -> None:
        self.delete_calls.append(section_id)


def _service(
    *,
    api: _FakeMeetingSectionApi | None = None,
    meeting_api: _FakeMeetingApi | None = None,
    settings=None,
) -> MeetingSectionService:
    return MeetingSectionService(
        api=api or _FakeMeetingSectionApi(),
        meeting_api=meeting_api or _FakeMeetingApi(),
        settings=settings or make_settings(),
        project_id_to_identifier={6: "demo"},
        api_prefix="/api/v3/",
    )


@pytest.mark.asyncio
async def test_list_for_meeting_returns_stamped_results() -> None:
    service = _service()
    result = await service.list_for_meeting(12)
    assert result.count == 1
    assert result.results[0].title == "Backlog"


@pytest.mark.asyncio
async def test_list_for_meeting_denies_read_when_parent_meeting_project_disallowed() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other-project",))
    api = _FakeMeetingSectionApi()
    service = _service(api=api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.list_for_meeting(12)

    assert api.list_calls == []


@pytest.mark.asyncio
async def test_get_denies_read_when_fetched_parent_meeting_project_disallowed() -> None:
    """Security regression: get() must check the allowlist against the
    fetched section's own meeting_id (walked to its project)."""
    settings = dataclasses.replace(make_settings(), read_projects=("other-project",))
    api = _FakeMeetingSectionApi([MeetingSectionRecord(summary=_section_summary(meeting_id=12))])
    meeting_api = _FakeMeetingApi()
    service = _service(api=api, meeting_api=meeting_api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get(41)

    assert meeting_api.get_calls == [12]


@pytest.mark.asyncio
async def test_create_preview_without_confirm_does_not_call_api_create() -> None:
    api = _FakeMeetingSectionApi()
    service = _service(api=api)
    result = await service.create(meeting_id=12, title="Backlog", confirm=False)
    assert result.state == "preview"
    assert api.create_calls == []


@pytest.mark.asyncio
async def test_create_commit_with_confirm_calls_api_create() -> None:
    api = _FakeMeetingSectionApi()
    service = _service(api=api)
    result = await service.create(meeting_id=12, title="Backlog", backlog=True, confirm=True)
    assert result.state == "confirmed"
    assert api.create_calls[0]["backlog"] is True


@pytest.mark.asyncio
async def test_create_denies_write_when_parent_meeting_project_disallowed() -> None:
    settings = dataclasses.replace(make_settings(), write_projects=("other-project",))
    api = _FakeMeetingSectionApi()
    service = _service(api=api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.create(meeting_id=12, title="Backlog", confirm=True)

    assert api.create_calls == []


@pytest.mark.asyncio
async def test_create_denies_write_even_without_confirm() -> None:
    settings = dataclasses.replace(make_settings(), write_projects=("other-project",))
    api = _FakeMeetingSectionApi()
    service = _service(api=api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.create(meeting_id=12, title="Backlog", confirm=False)

    assert api.create_calls == []


def test_update_signature_has_no_backlog_param() -> None:
    """backlog is create-only -- update() must not accept it (docstring
    convention, not just an implementation detail)."""
    import inspect

    sig = inspect.signature(MeetingSectionService.update)
    assert "backlog" not in sig.parameters


@pytest.mark.asyncio
async def test_update_preview_without_confirm_does_not_call_api_update() -> None:
    api = _FakeMeetingSectionApi()
    service = _service(api=api)
    result = await service.update(section_id=41, title="Updated", confirm=False)
    assert result.state == "preview"
    assert api.update_calls == []


@pytest.mark.asyncio
async def test_update_denies_write_when_fetched_parent_meeting_project_disallowed() -> None:
    settings = dataclasses.replace(make_settings(), write_projects=("other-project",))
    api = _FakeMeetingSectionApi([MeetingSectionRecord(summary=_section_summary(meeting_id=12))])
    service = _service(api=api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.update(section_id=41, title="Updated", confirm=True)

    assert api.update_calls == []


@pytest.mark.asyncio
async def test_delete_preview_without_confirm_does_not_call_api_delete() -> None:
    api = _FakeMeetingSectionApi()
    service = _service(api=api)
    result = await service.delete(section_id=41, confirm=False)
    assert result.state == "preview"
    assert api.delete_calls == []


@pytest.mark.asyncio
async def test_delete_commit_with_confirm_calls_api_delete() -> None:
    api = _FakeMeetingSectionApi()
    service = _service(api=api)
    result = await service.delete(section_id=41, confirm=True)
    assert result.state == "confirmed"
    assert api.delete_calls == [41]


@pytest.mark.asyncio
async def test_delete_denies_write_when_fetched_parent_meeting_project_disallowed() -> None:
    settings = dataclasses.replace(make_settings(), write_projects=("other-project",))
    api = _FakeMeetingSectionApi([MeetingSectionRecord(summary=_section_summary(meeting_id=12))])
    service = _service(api=api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.delete(section_id=41, confirm=True)

    assert api.delete_calls == []


@pytest.mark.asyncio
async def test_delete_denies_write_even_without_confirm() -> None:
    settings = dataclasses.replace(make_settings(), write_projects=("other-project",))
    api = _FakeMeetingSectionApi([MeetingSectionRecord(summary=_section_summary(meeting_id=12))])
    service = _service(api=api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.delete(section_id=41, confirm=False)

    assert api.delete_calls == []
