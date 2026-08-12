from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import InvalidInputError, PermissionDeniedError
from openproject_ce_mcp.app.ports.recurring_meeting_api import RecurringMeetingOccurrenceRecord, RecurringMeetingRecord
from openproject_ce_mcp.app.services.recurring_meeting_service import RecurringMeetingService
from openproject_ce_mcp.models import MeetingSummary, RecurringMeetingOccurrenceSummary, RecurringMeetingSummary


def _recurring_summary(recurring_meeting_id: int = 51, **extra) -> RecurringMeetingSummary:
    defaults = {
        "id": recurring_meeting_id,
        "title": "Weekly Standup",
        "frequency": "weekly",
        "monthly_day": None,
        "monthly_ordinal": None,
        "monthly_weekday": None,
        "interval": 1,
        "end_after": "never",
        "end_date": None,
        "iterations": None,
        "time_zone": "UTC",
        "start_time": "2026-09-01T09:00:00Z",
        "location": None,
        "duration": 0.5,
        "notify": True,
        "author": "Alice",
        "project_id": 6,
        "project": "Demo",
        "template_meeting_id": 50,
        "created_at": "2026-08-01T00:00:00Z",
        "updated_at": "2026-08-01T00:00:00Z",
    }
    defaults.update(extra)
    return RecurringMeetingSummary(**defaults)


def _meeting_summary(meeting_id: int = 13, **extra) -> MeetingSummary:
    defaults = {
        "id": meeting_id,
        "title": "Weekly Standup",
        "location": None,
        "lock_version": 0,
        "start_time": "2026-09-08T09:00:00Z",
        "end_time": None,
        "duration": "PT30M",
        "state": "open",
        "sharing": "invited",
        "template": False,
        "notify": True,
        "author": "Alice",
        "participants": [],
        "project_id": 6,
        "project": "Demo",
        "recurring_meeting_id": 51,
        "created_at": "2026-08-01T00:00:00Z",
        "updated_at": "2026-08-01T00:00:00Z",
    }
    defaults.update(extra)
    return MeetingSummary(**defaults)


class _FakeRecurringMeetingApi:
    def __init__(self, records: list[RecurringMeetingRecord] | None = None, *, project_link=None) -> None:
        self._records = records or [
            RecurringMeetingRecord(
                summary=_recurring_summary(),
                project_link=project_link or {"href": "/api/v3/projects/6", "title": "Demo"},
            )
        ]
        self.list_calls: list[tuple[int, int, int | None]] = []
        self.get_calls: list[int] = []
        self.create_calls: list[dict] = []
        self.update_calls: list[tuple[int, dict]] = []
        self.delete_calls: list[int] = []
        self.list_occurrences_calls: list[tuple[int, str, int | None]] = []
        self.init_occurrence_calls: list[tuple[int, str]] = []
        self.cancel_occurrence_calls: list[tuple[int, str]] = []
        self.cancel_raises: Exception | None = None

    async def list_page(self, *, offset: int, limit: int, project_id: int | None):
        self.list_calls.append((offset, limit, project_id))
        return list(self._records), len(self._records)

    async def get(self, recurring_meeting_id: int) -> RecurringMeetingRecord:
        self.get_calls.append(recurring_meeting_id)
        return self._records[0]

    async def create(self, payload: dict) -> RecurringMeetingRecord:
        self.create_calls.append(payload)
        return self._records[0]

    async def update(self, recurring_meeting_id: int, payload: dict) -> RecurringMeetingRecord:
        self.update_calls.append((recurring_meeting_id, payload))
        return RecurringMeetingRecord(
            summary=_recurring_summary(title="Updated"), project_link={"href": "/api/v3/projects/6", "title": "Demo"}
        )

    async def delete(self, recurring_meeting_id: int) -> None:
        self.delete_calls.append(recurring_meeting_id)

    async def list_occurrences(self, recurring_meeting_id: int, *, filter: str, limit: int | None):
        self.list_occurrences_calls.append((recurring_meeting_id, filter, limit))
        return [
            RecurringMeetingOccurrenceRecord(
                summary=RecurringMeetingOccurrenceSummary(
                    start_time="2026-09-08T09:00:00Z", state="planned", meeting_id=None
                )
            )
        ]

    async def init_occurrence(self, recurring_meeting_id: int, *, start_time: str) -> MeetingSummary:
        self.init_occurrence_calls.append((recurring_meeting_id, start_time))
        return _meeting_summary()

    async def cancel_occurrence(self, recurring_meeting_id: int, *, start_time: str) -> None:
        self.cancel_occurrence_calls.append((recurring_meeting_id, start_time))
        if self.cancel_raises is not None:
            raise self.cancel_raises


async def _resolve_project_ref_ok(project_ref, *, write: bool = False, context=None):
    return {"id": 6, "name": "Demo", "identifier": "demo"}


async def _resolve_project_ref_denied(project_ref, *, write: bool = False, context=None):
    raise PermissionDeniedError("OpenProject writes to this project are disabled.")


def _service(
    *,
    api: _FakeRecurringMeetingApi | None = None,
    settings=None,
    resolve_project_ref=None,
) -> RecurringMeetingService:
    return RecurringMeetingService(
        api=api or _FakeRecurringMeetingApi(),
        settings=settings or make_settings(),
        project_id_to_identifier={6: "demo"},
        resolve_project_ref=resolve_project_ref or _resolve_project_ref_ok,
        api_prefix="/api/v3/",
    )


# --- list_all ------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_all_returns_stamped_results() -> None:
    api = _FakeRecurringMeetingApi()
    result = await _service(api=api).list_all()
    assert result.count == 1
    assert result.results[0].title == "Weekly Standup"


@pytest.mark.asyncio
async def test_list_all_filters_disallowed_project_under_client_side_scan() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other-project",))
    api = _FakeRecurringMeetingApi()
    result = await _service(api=api, settings=settings).list_all()
    assert result.count == 0


# --- get -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_returns_stamped_summary() -> None:
    api = _FakeRecurringMeetingApi()
    result = await _service(api=api).get(51)
    assert result.id == 51


@pytest.mark.asyncio
async def test_get_denies_read_outside_read_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other-project",))
    api = _FakeRecurringMeetingApi()
    with pytest.raises(PermissionDeniedError):
        await _service(api=api, settings=settings).get(51)


# --- create ------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_preview_without_confirm_does_not_call_api_create() -> None:
    api = _FakeRecurringMeetingApi()
    result = await _service(api=api).create(
        project="demo", title="Weekly Standup", frequency="weekly", start_time="2026-09-01T09:00:00Z", confirm=False
    )
    assert result.state == "preview"
    assert api.create_calls == []


@pytest.mark.asyncio
async def test_create_commit_with_confirm_calls_api_create() -> None:
    api = _FakeRecurringMeetingApi()
    result = await _service(api=api).create(
        project="demo", title="Weekly Standup", frequency="weekly", start_time="2026-09-01T09:00:00Z", confirm=True
    )
    assert result.state == "confirmed"
    assert api.create_calls


@pytest.mark.asyncio
async def test_create_denies_write_outside_write_allowlist() -> None:
    api = _FakeRecurringMeetingApi()
    service = _service(api=api, resolve_project_ref=_resolve_project_ref_denied)
    with pytest.raises(PermissionDeniedError):
        await service.create(
            project="demo", title="Weekly Standup", frequency="weekly", start_time="2026-09-01T09:00:00Z", confirm=True
        )
    assert api.create_calls == []


@pytest.mark.asyncio
async def test_create_denies_write_even_without_confirm() -> None:
    api = _FakeRecurringMeetingApi()
    service = _service(api=api, resolve_project_ref=_resolve_project_ref_denied)
    with pytest.raises(PermissionDeniedError):
        await service.create(
            project="demo", title="Weekly Standup", frequency="weekly", start_time="2026-09-01T09:00:00Z", confirm=False
        )
    assert api.create_calls == []


# --- update / delete -----------------------------------------------------


@pytest.mark.asyncio
async def test_update_denies_write_outside_write_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), write_projects=("other-project",))
    api = _FakeRecurringMeetingApi()
    with pytest.raises(PermissionDeniedError):
        await _service(api=api, settings=settings).update(recurring_meeting_id=51, title="Updated", confirm=True)
    assert api.update_calls == []


@pytest.mark.asyncio
async def test_delete_preview_without_confirm_does_not_call_api_delete() -> None:
    api = _FakeRecurringMeetingApi()
    result = await _service(api=api).delete(recurring_meeting_id=51, confirm=False)
    assert result.state == "preview"
    assert api.delete_calls == []


@pytest.mark.asyncio
async def test_delete_commit_with_confirm_calls_api_delete() -> None:
    api = _FakeRecurringMeetingApi()
    result = await _service(api=api).delete(recurring_meeting_id=51, confirm=True)
    assert result.state == "confirmed"
    assert api.delete_calls == [51]


# --- list_occurrences -------------------------------------------------------


@pytest.mark.asyncio
async def test_list_occurrences_checks_parent_recurring_meeting_allowlist() -> None:
    api = _FakeRecurringMeetingApi()
    result = await _service(api=api).list_occurrences(51, filter="upcoming", limit=5)
    assert result.count == 1
    assert api.get_calls == [51]
    assert api.list_occurrences_calls == [(51, "upcoming", 5)]


@pytest.mark.asyncio
async def test_list_occurrences_denies_read_when_parent_project_disallowed() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other-project",))
    api = _FakeRecurringMeetingApi()
    with pytest.raises(PermissionDeniedError):
        await _service(api=api, settings=settings).list_occurrences(51)
    assert api.list_occurrences_calls == []


# --- init_occurrence -------------------------------------------------------


@pytest.mark.asyncio
async def test_init_occurrence_preview_without_confirm_does_not_call_api() -> None:
    api = _FakeRecurringMeetingApi()
    result = await _service(api=api).init_occurrence(
        recurring_meeting_id=51, start_time="2026-09-08T09:00:00Z", confirm=False
    )
    assert result.state == "preview"
    assert api.init_occurrence_calls == []


@pytest.mark.asyncio
async def test_init_occurrence_commit_returns_full_meeting_summary() -> None:
    api = _FakeRecurringMeetingApi()
    result = await _service(api=api).init_occurrence(
        recurring_meeting_id=51, start_time="2026-09-08T09:00:00Z", confirm=True
    )
    assert result.state == "confirmed"
    assert result.result is not None
    assert result.result.id == 13
    assert api.init_occurrence_calls == [(51, "2026-09-08T09:00:00Z")]


@pytest.mark.asyncio
async def test_init_occurrence_denies_write_when_parent_project_disallowed() -> None:
    settings = dataclasses.replace(make_settings(), write_projects=("other-project",))
    api = _FakeRecurringMeetingApi()
    with pytest.raises(PermissionDeniedError):
        await _service(api=api, settings=settings).init_occurrence(
            recurring_meeting_id=51, start_time="2026-09-08T09:00:00Z", confirm=True
        )
    assert api.init_occurrence_calls == []


@pytest.mark.asyncio
async def test_init_occurrence_denies_write_even_without_confirm() -> None:
    settings = dataclasses.replace(make_settings(), write_projects=("other-project",))
    api = _FakeRecurringMeetingApi()
    with pytest.raises(PermissionDeniedError):
        await _service(api=api, settings=settings).init_occurrence(
            recurring_meeting_id=51, start_time="2026-09-08T09:00:00Z", confirm=False
        )
    assert api.init_occurrence_calls == []


# --- cancel_occurrence -------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_occurrence_preview_without_confirm_does_not_call_api() -> None:
    api = _FakeRecurringMeetingApi()
    result = await _service(api=api).cancel_occurrence(
        recurring_meeting_id=51, start_time="2026-09-08T09:00:00Z", confirm=False
    )
    assert result.state == "preview"
    assert api.cancel_occurrence_calls == []


@pytest.mark.asyncio
async def test_cancel_occurrence_commit_with_confirm_calls_api() -> None:
    api = _FakeRecurringMeetingApi()
    result = await _service(api=api).cancel_occurrence(
        recurring_meeting_id=51, start_time="2026-09-08T09:00:00Z", confirm=True
    )
    assert result.state == "confirmed"
    assert result.result is None
    assert api.cancel_occurrence_calls == [(51, "2026-09-08T09:00:00Z")]


@pytest.mark.asyncio
async def test_cancel_occurrence_surfaces_409_as_invalid_input_error_with_no_special_casing() -> None:
    """When the occurrence is already materialized and not cancelled,
    OpenProject 409s -- this surfaces as a normal InvalidInputError through
    the transport's existing error mapping, no special-casing needed in the
    Service."""
    api = _FakeRecurringMeetingApi()
    api.cancel_raises = InvalidInputError("Cannot cancel an already instantiated occurrence.")
    service = _service(api=api)

    with pytest.raises(InvalidInputError):
        await service.cancel_occurrence(recurring_meeting_id=51, start_time="2026-09-08T09:00:00Z", confirm=True)


@pytest.mark.asyncio
async def test_cancel_occurrence_denies_write_when_parent_project_disallowed() -> None:
    settings = dataclasses.replace(make_settings(), write_projects=("other-project",))
    api = _FakeRecurringMeetingApi()
    with pytest.raises(PermissionDeniedError):
        await _service(api=api, settings=settings).cancel_occurrence(
            recurring_meeting_id=51, start_time="2026-09-08T09:00:00Z", confirm=True
        )
    assert api.cancel_occurrence_calls == []


@pytest.mark.asyncio
async def test_cancel_occurrence_denies_write_even_without_confirm() -> None:
    settings = dataclasses.replace(make_settings(), write_projects=("other-project",))
    api = _FakeRecurringMeetingApi()
    with pytest.raises(PermissionDeniedError):
        await _service(api=api, settings=settings).cancel_occurrence(
            recurring_meeting_id=51, start_time="2026-09-08T09:00:00Z", confirm=False
        )
    assert api.cancel_occurrence_calls == []
