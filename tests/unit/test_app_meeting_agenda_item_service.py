from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings
from _work_package_target_helpers import resolved_record

from openproject_ce_mcp.app.errors import NotFoundError, PermissionDeniedError
from openproject_ce_mcp.app.ports.meeting_agenda_item_api import MeetingAgendaItemRecord
from openproject_ce_mcp.app.ports.meeting_api import MeetingRecord
from openproject_ce_mcp.app.ports.work_package_ref import ResolvedRecord
from openproject_ce_mcp.app.services.meeting_agenda_item_service import MeetingAgendaItemService
from openproject_ce_mcp.models import MeetingAgendaItemSummary, MeetingSummary


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
        "outcome_ids": [],
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
    def __init__(self, records: list[MeetingAgendaItemRecord] | None = None) -> None:
        self._records = records or [
            MeetingAgendaItemRecord(summary=_agenda_summary(), meeting_project_link={"href": "/api/v3/projects/6"})
        ]
        self.list_for_meeting_calls: list[int] = []
        self.list_for_work_package_calls: list[int] = []
        self.list_text_limit_calls: list[int | None] = []
        self.get_calls: list[int] = []
        self.create_calls: list[dict] = []
        self.update_calls: list[tuple[int, dict]] = []
        self.delete_calls: list[int] = []

    async def list_for_meeting(self, meeting_id: int, *, text_limit: int | None = None):
        self.list_for_meeting_calls.append(meeting_id)
        self.list_text_limit_calls.append(text_limit)
        return list(self._records)

    async def list_for_work_package(self, work_package_id: int, *, text_limit: int | None = None):
        self.list_for_work_package_calls.append(work_package_id)
        self.list_text_limit_calls.append(text_limit)
        return list(self._records)

    async def get(self, agenda_item_id: int) -> MeetingAgendaItemRecord:
        self.get_calls.append(agenda_item_id)
        return self._records[0]

    async def create(self, payload: dict) -> MeetingAgendaItemRecord:
        self.create_calls.append(payload)
        return self._records[0]

    async def update(self, agenda_item_id: int, payload: dict) -> MeetingAgendaItemRecord:
        self.update_calls.append((agenda_item_id, payload))
        return MeetingAgendaItemRecord(summary=_agenda_summary(title="Updated"))

    async def delete(self, agenda_item_id: int) -> None:
        self.delete_calls.append(agenda_item_id)


async def _resolve_work_package_record_ok(ref, *, write: bool = False) -> ResolvedRecord:
    return resolved_record(99)


def _service(
    *,
    api: _FakeMeetingAgendaItemApi | None = None,
    meeting_api: _FakeMeetingApi | None = None,
    settings=None,
    resolve_work_package_record=None,
) -> MeetingAgendaItemService:
    return MeetingAgendaItemService(
        api=api or _FakeMeetingAgendaItemApi(),
        meeting_api=meeting_api or _FakeMeetingApi(),
        settings=settings or make_settings(),
        project_id_to_identifier={6: "demo"},
        resolve_work_package_record=resolve_work_package_record or _resolve_work_package_record_ok,
        api_prefix="/api/v3/",
    )


# --- list_for_meeting -----------------------------------------------------


@pytest.mark.asyncio
async def test_list_for_meeting_returns_stamped_results() -> None:
    api = _FakeMeetingAgendaItemApi()
    meeting_api = _FakeMeetingApi()
    service = _service(api=api, meeting_api=meeting_api)

    result = await service.list_for_meeting(12)

    assert result.count == 1
    assert result.results[0].title == "Discuss roadmap"
    assert meeting_api.get_calls == [12]


@pytest.mark.asyncio
async def test_list_for_meeting_denies_read_when_parent_meeting_project_disallowed() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other-project",))
    api = _FakeMeetingAgendaItemApi()
    meeting_api = _FakeMeetingApi()
    service = _service(api=api, meeting_api=meeting_api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.list_for_meeting(12)

    assert api.list_for_meeting_calls == []


@pytest.mark.asyncio
async def test_list_for_meeting_passes_text_limit_through_to_the_adapter() -> None:
    api = _FakeMeetingAgendaItemApi()
    service = _service(api=api)

    await service.list_for_meeting(12, text_limit=10)

    assert api.list_text_limit_calls == [10]


@pytest.mark.asyncio
async def test_list_for_meeting_omits_text_limit_by_default() -> None:
    api = _FakeMeetingAgendaItemApi()
    service = _service(api=api)

    await service.list_for_meeting(12)

    assert api.list_text_limit_calls == [None]


@pytest.mark.asyncio
async def test_list_for_meeting_applies_client_side_pagination() -> None:
    records = [MeetingAgendaItemRecord(summary=_agenda_summary(item_id=i)) for i in range(1, 6)]
    api = _FakeMeetingAgendaItemApi(records)
    service = _service(api=api)

    result = await service.list_for_meeting(12, offset=1, limit=2)

    assert [r.id for r in result.results] == [1, 2]
    assert result.truncated is True
    assert result.next_offset == 2


# --- list_for_work_package -------------------------------------------------


@pytest.mark.asyncio
async def test_list_for_work_package_resolves_work_package_id() -> None:
    api = _FakeMeetingAgendaItemApi()
    resolved: list[tuple] = []

    async def resolve(ref, *, write: bool = False):
        resolved.append((ref, write))
        return resolved_record(99)

    service = _service(api=api, resolve_work_package_record=resolve)

    result = await service.list_for_work_package("99")

    assert result.count == 1
    assert resolved == [("99", False)]
    assert api.list_for_work_package_calls == [99]


@pytest.mark.asyncio
async def test_list_for_work_package_passes_text_limit_through_to_the_adapter() -> None:
    api = _FakeMeetingAgendaItemApi()
    service = _service(api=api)

    await service.list_for_work_package("99", text_limit=10)

    assert api.list_text_limit_calls == [10]


def _items(*pairs: tuple[int, int | None]) -> list[MeetingAgendaItemRecord]:
    """One record per (item id, project id of its embedded meeting; None = nothing embedded)."""
    return [
        MeetingAgendaItemRecord(
            summary=_agenda_summary(item_id),
            meeting_project_link=None if project_id is None else {"href": f"/api/v3/projects/{project_id}"},
        )
        for item_id, project_id in pairs
    ]


def _restricted_service(records, *, read=("demo",)):
    return MeetingAgendaItemService(
        api=_FakeMeetingAgendaItemApi(records),
        meeting_api=_FakeMeetingApi(),
        settings=dataclasses.replace(make_settings(), read_projects=read),
        project_id_to_identifier={6: "demo", 7: "secret"},
        resolve_work_package_record=_resolve_work_package_record_ok,
        api_prefix="/api/v3/",
    )


@pytest.mark.asyncio
async def test_list_for_work_package_drops_items_of_meetings_outside_the_read_scope() -> None:
    service = _restricted_service(_items((1, 6), (2, 7), (3, 6)))

    result = await service.list_for_work_package(99)

    assert [item.id for item in result.results] == [1, 3]
    assert (result.total, result.count) == (2, 2)


@pytest.mark.asyncio
async def test_list_for_work_package_returns_nothing_when_every_meeting_is_outside_the_read_scope() -> None:
    result = await _restricted_service(_items((1, 7))).list_for_work_package(99)

    assert result.results == []
    assert result.total == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("read", [("demo",), ("*",)])
async def test_list_for_work_package_drops_an_item_whose_meeting_project_is_unknown(read) -> None:
    result = await _restricted_service(_items((1, None), (2, 6)), read=read).list_for_work_package(99)

    assert [item.id for item in result.results] == [2]


@pytest.mark.asyncio
async def test_list_for_work_package_under_every_project_admits_each_meeting_project() -> None:
    result = await _restricted_service(_items((1, 6), (2, 7)), read=("*",)).list_for_work_package(99)

    assert [item.id for item in result.results] == [1, 2]


@pytest.mark.asyncio
async def test_list_for_work_package_drops_items_of_a_meeting_with_an_undisclosed_project() -> None:
    records = [
        MeetingAgendaItemRecord(
            summary=_agenda_summary(1), meeting_project_link={"href": "urn:openproject-org:api:v3:undisclosed"}
        )
    ]

    assert (await _restricted_service(records).list_for_work_package(99)).results == []


@pytest.mark.asyncio
async def test_list_for_work_package_asks_for_no_meeting_beyond_the_embedded_one() -> None:
    meeting_api = _FakeMeetingApi()
    service = MeetingAgendaItemService(
        api=_FakeMeetingAgendaItemApi(_items((1, 6), (2, 7))),
        meeting_api=meeting_api,
        settings=dataclasses.replace(make_settings(), read_projects=("demo",)),
        project_id_to_identifier={6: "demo", 7: "secret"},
        resolve_work_package_record=_resolve_work_package_record_ok,
        api_prefix="/api/v3/",
    )

    await service.list_for_work_package(99)

    assert meeting_api.get_calls == []


# --- get -- fetch-then-check bypass regression ------------------------------


@pytest.mark.asyncio
async def test_get_returns_stamped_summary() -> None:
    api = _FakeMeetingAgendaItemApi()
    service = _service(api=api)

    result = await service.get(21)

    assert result.id == 21


@pytest.mark.asyncio
async def test_get_denies_read_when_fetched_agenda_item_meeting_project_is_disallowed() -> None:
    """Security regression: get() must check the ALLOWLIST against the
    fetched agenda item's OWN meeting_id (walked to its project), not trust
    a caller-supplied claim -- a bare agenda_item_id alone reveals nothing
    about its project until fetched and its parent meeting resolved."""
    settings = dataclasses.replace(make_settings(), read_projects=("other-project",))
    api = _FakeMeetingAgendaItemApi([MeetingAgendaItemRecord(summary=_agenda_summary(meeting_id=12))])
    meeting_api = _FakeMeetingApi(project_link={"href": "/api/v3/projects/6", "title": "Demo"})
    service = _service(api=api, meeting_api=meeting_api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get(21)

    assert meeting_api.get_calls == [12]


@pytest.mark.asyncio
async def test_get_fails_closed_when_agenda_item_has_no_meeting() -> None:
    """meeting_id is a mandatory belongs_to upstream, so a None here should be
    unreachable via the live API -- but must fail closed, not silently skip
    the allowlist check, if it ever occurs."""
    api = _FakeMeetingAgendaItemApi([MeetingAgendaItemRecord(summary=_agenda_summary(meeting_id=None))])
    meeting_api = _FakeMeetingApi()
    service = _service(api=api, meeting_api=meeting_api)

    with pytest.raises(NotFoundError):
        await service.get(21)

    assert meeting_api.get_calls == []


# --- create ------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_preview_without_confirm_does_not_call_api_create() -> None:
    api = _FakeMeetingAgendaItemApi()
    service = _service(api=api)

    result = await service.create(meeting_id=12, title="Discuss roadmap", confirm=False)

    assert result.state == "preview"
    assert api.create_calls == []


@pytest.mark.asyncio
async def test_create_commit_with_confirm_calls_api_create() -> None:
    api = _FakeMeetingAgendaItemApi()
    service = _service(api=api)

    result = await service.create(meeting_id=12, title="Discuss roadmap", confirm=True)

    assert result.state == "confirmed"
    assert api.create_calls


@pytest.mark.asyncio
async def test_create_resolves_linked_work_package_id_with_write_scope() -> None:
    """Regression: create() previously resolved a supplied work_package_id
    with write=False (a READ-scope check), even though linking a work
    package into an agenda item is a WRITE target reference -- a caller
    with write access to the meeting but only READ access to the work
    package's own project could link that work package into a meeting they
    can write to. Must use write=True, same as wiki_page_link_service.
    create's own work_package_id resolution."""
    api = _FakeMeetingAgendaItemApi()
    resolved: list[tuple] = []

    async def resolve(ref, *, write: bool = False):
        resolved.append((ref, write))
        return resolved_record(99)

    service = _service(api=api, resolve_work_package_record=resolve)

    await service.create(meeting_id=12, title="Discuss roadmap", work_package_id="99", confirm=True)

    assert resolved == [("99", True)]


@pytest.mark.asyncio
async def test_create_denies_write_when_parent_meeting_project_disallowed() -> None:
    settings = dataclasses.replace(make_settings(), write_projects=("other-project",))
    api = _FakeMeetingAgendaItemApi()
    service = _service(api=api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.create(meeting_id=12, title="Discuss roadmap", confirm=True)

    assert api.create_calls == []


@pytest.mark.asyncio
async def test_create_denies_write_even_without_confirm() -> None:
    settings = dataclasses.replace(make_settings(), write_projects=("other-project",))
    api = _FakeMeetingAgendaItemApi()
    service = _service(api=api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.create(meeting_id=12, title="Discuss roadmap", confirm=False)

    assert api.create_calls == []


# --- update ------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_preview_without_confirm_does_not_call_api_update() -> None:
    api = _FakeMeetingAgendaItemApi()
    service = _service(api=api)

    result = await service.update(agenda_item_id=21, title="Updated", confirm=False)

    assert result.state == "preview"
    assert api.update_calls == []


@pytest.mark.asyncio
async def test_update_resolves_linked_work_package_id_with_write_scope() -> None:
    """Regression: same as create()'s own version of this test above."""
    api = _FakeMeetingAgendaItemApi([MeetingAgendaItemRecord(summary=_agenda_summary(meeting_id=12))])
    resolved: list[tuple] = []

    async def resolve(ref, *, write: bool = False):
        resolved.append((ref, write))
        return resolved_record(99)

    service = _service(api=api, resolve_work_package_record=resolve)

    await service.update(agenda_item_id=21, work_package_id="99", confirm=True)

    assert resolved == [("99", True)]


@pytest.mark.asyncio
async def test_update_denies_write_when_fetched_parent_meeting_project_disallowed() -> None:
    settings = dataclasses.replace(make_settings(), write_projects=("other-project",))
    api = _FakeMeetingAgendaItemApi([MeetingAgendaItemRecord(summary=_agenda_summary(meeting_id=12))])
    service = _service(api=api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.update(agenda_item_id=21, title="Updated", confirm=True)

    assert api.update_calls == []


@pytest.mark.asyncio
async def test_update_fails_closed_when_agenda_item_has_no_meeting() -> None:
    api = _FakeMeetingAgendaItemApi([MeetingAgendaItemRecord(summary=_agenda_summary(meeting_id=None))])
    service = _service(api=api)

    with pytest.raises(NotFoundError):
        await service.update(agenda_item_id=21, title="Updated", confirm=True)

    assert api.update_calls == []


# --- delete ------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_preview_without_confirm_does_not_call_api_delete() -> None:
    api = _FakeMeetingAgendaItemApi()
    service = _service(api=api)

    result = await service.delete(agenda_item_id=21, confirm=False)

    assert result.state == "preview"
    assert api.delete_calls == []


@pytest.mark.asyncio
async def test_delete_commit_with_confirm_calls_api_delete() -> None:
    api = _FakeMeetingAgendaItemApi()
    service = _service(api=api)

    result = await service.delete(agenda_item_id=21, confirm=True)

    assert result.state == "confirmed"
    assert api.delete_calls == [21]


@pytest.mark.asyncio
async def test_delete_denies_write_when_fetched_parent_meeting_project_disallowed() -> None:
    settings = dataclasses.replace(make_settings(), write_projects=("other-project",))
    api = _FakeMeetingAgendaItemApi([MeetingAgendaItemRecord(summary=_agenda_summary(meeting_id=12))])
    service = _service(api=api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.delete(agenda_item_id=21, confirm=True)

    assert api.delete_calls == []


@pytest.mark.asyncio
async def test_delete_fails_closed_when_agenda_item_has_no_meeting() -> None:
    api = _FakeMeetingAgendaItemApi([MeetingAgendaItemRecord(summary=_agenda_summary(meeting_id=None))])
    service = _service(api=api)

    with pytest.raises(NotFoundError):
        await service.delete(agenda_item_id=21, confirm=True)

    assert api.delete_calls == []


@pytest.mark.asyncio
async def test_delete_denies_write_even_without_confirm() -> None:
    settings = dataclasses.replace(make_settings(), write_projects=("other-project",))
    api = _FakeMeetingAgendaItemApi([MeetingAgendaItemRecord(summary=_agenda_summary(meeting_id=12))])
    service = _service(api=api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.delete(agenda_item_id=21, confirm=False)

    assert api.delete_calls == []
