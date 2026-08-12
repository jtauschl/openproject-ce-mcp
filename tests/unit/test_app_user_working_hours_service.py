from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import InvalidInputError, PermissionDeniedError
from openproject_ce_mcp.app.ports.user_working_hours_api import UserWorkingHoursRecord
from openproject_ce_mcp.app.services.user_working_hours_service import UserWorkingHoursService
from openproject_ce_mcp.models import UserWorkingHoursSummary
from openproject_ce_mcp.tools import _to_payload


def _summary(record_id: int = 5, *, user_id: int | None = 3, valid_from: str = "2026-08-01") -> UserWorkingHoursSummary:
    return UserWorkingHoursSummary(
        id=record_id,
        user_id=user_id,
        user_name="Alice",
        valid_from=valid_from,
        monday_hours=8.0,
        tuesday_hours=8.0,
        wednesday_hours=8.0,
        thursday_hours=8.0,
        friday_hours=4.0,
        saturday_hours=None,
        sunday_hours=None,
        availability_factor=1.0,
    )


def _schedule_settings(**overrides):
    return dataclasses.replace(
        make_settings(), enable_user_schedule_read=True, enable_user_schedule_write=True, **overrides
    )


class _FakeUserWorkingHoursApi:
    def __init__(self, *, records: list[UserWorkingHoursRecord] | None = None) -> None:
        self._records = records if records is not None else [UserWorkingHoursRecord(summary=_summary())]
        self.list_calls: list[tuple[str, int, int]] = []
        self.get_calls: list[tuple[str, int]] = []
        self.create_calls: list[tuple] = []
        self.update_calls: list[tuple[str, int, dict]] = []
        self.delete_calls: list[tuple[str, int]] = []

    async def list_for_user(self, user_ref, *, offset, page_size):
        self.list_calls.append((user_ref, offset, page_size))
        return list(self._records), len(self._records)

    async def get(self, user_ref, working_hours_id):
        self.get_calls.append((user_ref, working_hours_id))
        for record in self._records:
            if record.summary.id == working_hours_id:
                return record
        return UserWorkingHoursRecord(summary=_summary(record_id=working_hours_id))

    async def create(self, user_ref, *, valid_from, **kwargs):
        self.create_calls.append((user_ref, valid_from, kwargs))
        return UserWorkingHoursRecord(summary=_summary(record_id=9, user_id=3, valid_from=valid_from))

    async def update(self, user_ref, working_hours_id, *, payload):
        self.update_calls.append((user_ref, working_hours_id, payload))
        return UserWorkingHoursRecord(summary=_summary(record_id=working_hours_id))

    async def delete(self, user_ref, working_hours_id):
        self.delete_calls.append((user_ref, working_hours_id))


def _service(api: _FakeUserWorkingHoursApi | None = None, *, settings=None) -> UserWorkingHoursService:
    return UserWorkingHoursService(api=api or _FakeUserWorkingHoursApi(), settings=settings or _schedule_settings())


# ── list_for_user ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_for_user_returns_stamped_summaries() -> None:
    api = _FakeUserWorkingHoursApi()
    service = _service(api)

    result = await service.list_for_user("me")

    assert result.count == 1
    assert result.results[0].id == 5
    assert api.list_calls == [("me", 1, make_settings().max_results)]


@pytest.mark.asyncio
async def test_list_for_user_checks_read_enabled() -> None:
    settings = dataclasses.replace(_schedule_settings(), enable_user_schedule_read=False)
    api = _FakeUserWorkingHoursApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.list_for_user("me")

    assert api.list_calls == []


@pytest.mark.asyncio
async def test_list_for_user_paginates_client_side() -> None:
    records = [UserWorkingHoursRecord(summary=_summary(record_id=i)) for i in range(3)]
    api = _FakeUserWorkingHoursApi(records=records)
    service = _service(api)

    result = await service.list_for_user("me", offset=1, limit=1)

    assert result.count == 1
    assert result.total == 3
    assert result.truncated is True


@pytest.mark.asyncio
async def test_list_for_user_applies_hidden_field_masking() -> None:
    settings = dataclasses.replace(_schedule_settings(), hidden_fields={"user_working_hours": ("monday_hours",)})
    service = _service(settings=settings)

    result = await service.list_for_user("me")
    record = result.results[0]

    assert record._hidden_keys == frozenset({"monday_hours"})
    serialized = _to_payload(record)
    assert "monday_hours" not in serialized


# ── get ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_returns_stamped_summary() -> None:
    api = _FakeUserWorkingHoursApi()
    service = _service(api)

    result = await service.get("me", 5)

    assert result.id == 5
    assert api.get_calls == [("me", 5)]


@pytest.mark.asyncio
async def test_get_checks_read_enabled() -> None:
    settings = dataclasses.replace(_schedule_settings(), enable_user_schedule_read=False)
    api = _FakeUserWorkingHoursApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get("me", 5)

    assert api.get_calls == []


# ── create ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_preview_does_not_write() -> None:
    api = _FakeUserWorkingHoursApi()
    service = _service(api)

    result = await service.create("me", valid_from="2026-08-01", monday_hours=8.0, confirm=False)

    assert result.state == "preview"
    assert result.result is None
    assert api.create_calls == []
    assert result.payload == {"validFrom": "2026-08-01", "mondayHours": 8.0}


@pytest.mark.asyncio
async def test_create_confirmed_writes() -> None:
    api = _FakeUserWorkingHoursApi()
    service = _service(api)

    result = await service.create("me", valid_from="2026-08-01", monday_hours=8.0, confirm=True)

    assert result.state == "confirmed"
    assert result.working_hours_id == 9
    assert len(api.create_calls) == 1


@pytest.mark.asyncio
async def test_create_confirmed_checks_write_enabled() -> None:
    settings = dataclasses.replace(_schedule_settings(), enable_user_schedule_write=False)
    api = _FakeUserWorkingHoursApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.create("me", valid_from="2026-08-01", confirm=True)

    assert api.create_calls == []


@pytest.mark.asyncio
async def test_create_preview_does_not_require_write_enabled() -> None:
    settings = dataclasses.replace(_schedule_settings(), enable_user_schedule_write=False)
    api = _FakeUserWorkingHoursApi()
    service = _service(api, settings=settings)

    result = await service.create("me", valid_from="2026-08-01", confirm=False)

    assert result.state == "preview"
    assert api.create_calls == []


@pytest.mark.asyncio
async def test_create_denies_hidden_field() -> None:
    settings = dataclasses.replace(_schedule_settings(), hidden_fields={"user_working_hours": ("monday_hours",)})
    api = _FakeUserWorkingHoursApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError):
        await service.create("me", valid_from="2026-08-01", monday_hours=8.0, confirm=True)

    assert api.create_calls == []


# ── update ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_uses_real_single_get_not_a_list_scan() -> None:
    api = _FakeUserWorkingHoursApi()
    service = _service(api)

    result = await service.update("me", 5, monday_hours=6.0, confirm=False)

    assert result.state == "preview"
    assert api.get_calls == [("me", 5)]
    assert api.list_calls == []
    assert result.payload == {"mondayHours": 6.0}


@pytest.mark.asyncio
async def test_update_confirmed_writes() -> None:
    api = _FakeUserWorkingHoursApi()
    service = _service(api)

    result = await service.update("me", 5, monday_hours=6.0, confirm=True)

    assert result.state == "confirmed"
    assert api.update_calls == [("me", 5, {"mondayHours": 6.0})]


# ── delete ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_uses_real_single_get_not_a_list_scan() -> None:
    api = _FakeUserWorkingHoursApi()
    service = _service(api)

    result = await service.delete("me", 5, confirm=False)

    assert result.state == "preview"
    assert api.get_calls == [("me", 5)]
    assert api.list_calls == []
    assert api.delete_calls == []


@pytest.mark.asyncio
async def test_delete_confirmed_deletes() -> None:
    api = _FakeUserWorkingHoursApi()
    service = _service(api)

    result = await service.delete("me", 5, confirm=True)

    assert result.state == "confirmed"
    assert api.delete_calls == [("me", 5)]
