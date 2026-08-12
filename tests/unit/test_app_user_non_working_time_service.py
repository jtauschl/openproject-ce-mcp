from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import InvalidInputError, NotFoundError, PermissionDeniedError
from openproject_ce_mcp.app.ports.user_non_working_time_api import UserNonWorkingTimeRecord
from openproject_ce_mcp.app.services.user_non_working_time_service import UserNonWorkingTimeService
from openproject_ce_mcp.models import UserNonWorkingTimeSummary
from openproject_ce_mcp.tools import _to_payload


def _summary(record_id: int = 5, *, user_id: int | None = 3, start: str = "2026-08-01", end: str = "2026-08-10"):
    return UserNonWorkingTimeSummary(id=record_id, user_id=user_id, user_name="Alice", start_date=start, end_date=end)


def _schedule_settings(**overrides):
    return dataclasses.replace(
        make_settings(), enable_user_schedule_read=True, enable_user_schedule_write=True, **overrides
    )


class _FakeUserNonWorkingTimeApi:
    def __init__(self, *, records: list[UserNonWorkingTimeRecord] | None = None) -> None:
        self._records = records if records is not None else [UserNonWorkingTimeRecord(summary=_summary())]
        self.list_calls: list[tuple[str, int | None, int, int]] = []
        self.create_calls: list[tuple[str, str, str]] = []
        self.update_calls: list[tuple[str, int, dict]] = []
        self.delete_calls: list[tuple[str, int]] = []

    async def list_for_user(self, user_ref, *, year, offset, page_size):
        self.list_calls.append((user_ref, year, offset, page_size))
        return list(self._records), len(self._records)

    async def create(self, user_ref, *, start_date, end_date):
        self.create_calls.append((user_ref, start_date, end_date))
        return UserNonWorkingTimeRecord(summary=_summary(record_id=9, user_id=3, start=start_date, end=end_date))

    async def update(self, user_ref, non_working_time_id, *, payload):
        self.update_calls.append((user_ref, non_working_time_id, payload))
        return UserNonWorkingTimeRecord(
            summary=_summary(
                record_id=non_working_time_id,
                start=payload.get("startDate", "2026-08-01"),
                end=payload.get("endDate", "2026-08-10"),
            )
        )

    async def delete(self, user_ref, non_working_time_id):
        self.delete_calls.append((user_ref, non_working_time_id))


def _service(api: _FakeUserNonWorkingTimeApi | None = None, *, settings=None) -> UserNonWorkingTimeService:
    return UserNonWorkingTimeService(api=api or _FakeUserNonWorkingTimeApi(), settings=settings or _schedule_settings())


# ── list_for_user ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_for_user_returns_stamped_summaries() -> None:
    api = _FakeUserNonWorkingTimeApi()
    service = _service(api)

    result = await service.list_for_user("me")

    assert result.count == 1
    assert result.results[0].id == 5
    # Unpaginated collection: always fetched with max_results, not effective_limit.
    assert api.list_calls == [("me", None, 1, make_settings().max_results)]


@pytest.mark.asyncio
async def test_list_for_user_passes_year_through() -> None:
    api = _FakeUserNonWorkingTimeApi()
    service = _service(api)

    await service.list_for_user("me", year=2026)

    assert api.list_calls == [("me", 2026, 1, make_settings().max_results)]


@pytest.mark.asyncio
async def test_list_for_user_checks_read_enabled() -> None:
    settings = dataclasses.replace(_schedule_settings(), enable_user_schedule_read=False)
    api = _FakeUserNonWorkingTimeApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.list_for_user("me")

    assert api.list_calls == []


@pytest.mark.asyncio
async def test_list_for_user_paginates_client_side() -> None:
    records = [UserNonWorkingTimeRecord(summary=_summary(record_id=i)) for i in range(3)]
    api = _FakeUserNonWorkingTimeApi(records=records)
    service = _service(api)

    result = await service.list_for_user("me", offset=1, limit=1)

    assert result.count == 1
    assert result.total == 3
    assert result.truncated is True
    assert result.next_offset == 2


@pytest.mark.asyncio
async def test_list_for_user_applies_hidden_field_masking() -> None:
    settings = dataclasses.replace(_schedule_settings(), hidden_fields={"user_non_working_time": ("start_date",)})
    service = _service(settings=settings)

    result = await service.list_for_user("me")
    record = result.results[0]

    assert record._hidden_keys == frozenset({"start_date"})
    serialized = _to_payload(record)
    assert "start_date" not in serialized


# ── create ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_preview_does_not_write() -> None:
    api = _FakeUserNonWorkingTimeApi()
    service = _service(api)

    result = await service.create("me", start_date="2026-08-01", end_date="2026-08-10", confirm=False)

    assert result.state == "preview"
    assert result.result is None
    assert api.create_calls == []


@pytest.mark.asyncio
async def test_create_confirmed_writes() -> None:
    api = _FakeUserNonWorkingTimeApi()
    service = _service(api)

    result = await service.create("me", start_date="2026-08-01", end_date="2026-08-10", confirm=True)

    assert result.state == "confirmed"
    assert result.result is not None
    assert result.non_working_time_id == 9
    assert api.create_calls == [("me", "2026-08-01", "2026-08-10")]


@pytest.mark.asyncio
async def test_create_confirmed_checks_write_enabled() -> None:
    settings = dataclasses.replace(_schedule_settings(), enable_user_schedule_write=False)
    api = _FakeUserNonWorkingTimeApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.create("me", start_date="2026-08-01", end_date="2026-08-10", confirm=True)

    assert api.create_calls == []


@pytest.mark.asyncio
async def test_create_preview_does_not_require_write_enabled() -> None:
    """Preview stays available even when write is disabled -- matching
    WikiPageLinkService's precedent: ensure_write_enabled is checked only on
    the confirmed path, never for a preview."""
    settings = dataclasses.replace(_schedule_settings(), enable_user_schedule_write=False)
    api = _FakeUserNonWorkingTimeApi()
    service = _service(api, settings=settings)

    result = await service.create("me", start_date="2026-08-01", end_date="2026-08-10", confirm=False)

    assert result.state == "preview"
    assert api.create_calls == []


@pytest.mark.asyncio
async def test_create_denies_hidden_field() -> None:
    settings = dataclasses.replace(_schedule_settings(), hidden_fields={"user_non_working_time": ("start_date",)})
    api = _FakeUserNonWorkingTimeApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError):
        await service.create("me", start_date="2026-08-01", end_date="2026-08-10", confirm=True)

    assert api.create_calls == []


# ── update ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_raises_not_found_when_id_absent_from_list() -> None:
    api = _FakeUserNonWorkingTimeApi(records=[])
    service = _service(api)

    with pytest.raises(NotFoundError):
        await service.update("me", 999, end_date="2026-08-15", confirm=False)


@pytest.mark.asyncio
async def test_update_preview_does_not_write() -> None:
    api = _FakeUserNonWorkingTimeApi()
    service = _service(api)

    result = await service.update("me", 5, end_date="2026-08-15", confirm=False)

    assert result.state == "preview"
    assert result.payload == {"endDate": "2026-08-15"}
    assert api.update_calls == []


@pytest.mark.asyncio
async def test_update_confirmed_writes() -> None:
    api = _FakeUserNonWorkingTimeApi()
    service = _service(api)

    result = await service.update("me", 5, end_date="2026-08-15", confirm=True)

    assert result.state == "confirmed"
    assert api.update_calls == [("me", 5, {"endDate": "2026-08-15"})]


# ── delete ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_raises_not_found_when_id_absent_from_list() -> None:
    api = _FakeUserNonWorkingTimeApi(records=[])
    service = _service(api)

    with pytest.raises(NotFoundError):
        await service.delete("me", 999, confirm=False)

    assert api.delete_calls == []


@pytest.mark.asyncio
async def test_delete_preview_does_not_delete() -> None:
    api = _FakeUserNonWorkingTimeApi()
    service = _service(api)

    result = await service.delete("me", 5, confirm=False)

    assert result.state == "preview"
    assert api.delete_calls == []


@pytest.mark.asyncio
async def test_delete_confirmed_deletes() -> None:
    api = _FakeUserNonWorkingTimeApi()
    service = _service(api)

    result = await service.delete("me", 5, confirm=True)

    assert result.state == "confirmed"
    assert api.delete_calls == [("me", 5)]
