from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import PermissionDeniedError
from openproject_ce_mcp.app.ports.status_priority_type_api import PriorityRecord, StatusRecord, TypeRecord
from openproject_ce_mcp.app.services.status_priority_type_service import StatusPriorityTypeService
from openproject_ce_mcp.models import PrioritySummary, StatusSummary, TypeSummary
from openproject_ce_mcp.tools import _to_payload


def _status_summary(status_id: int = 1, *, default_done_ratio: int | None = 30) -> StatusSummary:
    return StatusSummary(
        id=status_id,
        name="In progress",
        is_default=False,
        is_closed=False,
        color="#1A67A3",
        position=2,
        url=f"/api/v3/statuses/{status_id}",
        is_readonly=False,
        default_done_ratio=default_done_ratio,
        excluded_from_totals=False,
    )


def _priority_summary(priority_id: int = 1) -> PrioritySummary:
    return PrioritySummary(
        id=priority_id,
        name="High",
        is_default=False,
        is_active=True,
        color="#FF0000",
        position=3,
    )


def _type_summary(type_id: int = 1) -> TypeSummary:
    return TypeSummary(
        id=type_id,
        name="Task",
        color="#1A67A3",
        position=1,
        is_default=True,
        is_milestone=False,
        url=f"https://op.example.com/types/{type_id}",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-02T00:00:00Z",
    )


class _FakeStatusPriorityTypeApi:
    def __init__(
        self,
        *,
        statuses: list[StatusRecord] | None = None,
        priorities: list[PriorityRecord] | None = None,
        types: list[TypeRecord] | None = None,
    ) -> None:
        self._statuses = {r.summary.id: r for r in (statuses or [StatusRecord(summary=_status_summary())])}
        self._priorities = {r.summary.id: r for r in (priorities or [PriorityRecord(summary=_priority_summary())])}
        self._types = {r.summary.id: r for r in (types or [TypeRecord(summary=_type_summary())])}
        self.list_types_calls: list[int | None] = []

    async def list_statuses(self) -> list[StatusRecord]:
        return list(self._statuses.values())

    async def get_status(self, status_id: int) -> StatusRecord:
        return self._statuses[status_id]

    async def list_priorities(self) -> list[PriorityRecord]:
        return list(self._priorities.values())

    async def get_priority(self, priority_id: int) -> PriorityRecord:
        return self._priorities[priority_id]

    async def list_types(self, *, project_id: int | None) -> list[TypeRecord]:
        self.list_types_calls.append(project_id)
        return list(self._types.values())

    async def get_type(self, type_id: int) -> TypeRecord:
        return self._types[type_id]


async def _resolve_project_ref(project_ref: str, *, write: bool = False, context=None) -> dict:
    return {"id": 9, "identifier": project_ref, "name": "Demo Project", "_links": {}}


def _denying_resolve_project_ref(message: str):
    async def _resolve(project_ref: str, *, write: bool = False, context=None) -> dict:
        raise PermissionDeniedError(message)

    return _resolve


def _service(
    api: _FakeStatusPriorityTypeApi | None = None,
    *,
    settings=None,
    resolve_project_ref=_resolve_project_ref,
) -> StatusPriorityTypeService:
    api = api or _FakeStatusPriorityTypeApi()
    return StatusPriorityTypeService(
        api=api,
        settings=settings or make_settings(),
        resolve_project_ref=resolve_project_ref,
    )


# ── Statuses ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_statuses_returns_summaries() -> None:
    service = _service()

    result = await service.list_statuses()

    assert result.count == 1
    assert result.results[0].id == 1


@pytest.mark.asyncio
async def test_get_status_returns_summary() -> None:
    api = _FakeStatusPriorityTypeApi(statuses=[StatusRecord(summary=_status_summary(7))])
    service = _service(api)

    status = await service.get_status(7)

    assert status.id == 7


@pytest.mark.asyncio
async def test_list_statuses_applies_hidden_field_masking() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"status": ("default_done_ratio",)})
    service = _service(settings=settings)

    result = await service.list_statuses()
    status = result.results[0]

    assert status._hidden_keys == frozenset({"default_done_ratio"})
    assert status.default_done_ratio == 30  # preserved on the dataclass
    serialized = _to_payload(status)
    assert "default_done_ratio" not in serialized


@pytest.mark.asyncio
async def test_list_statuses_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_work_package_read=False)
    service = _service(settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.list_statuses()


# ── Priorities ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_priorities_returns_summaries() -> None:
    service = _service()

    result = await service.list_priorities()

    assert result.count == 1
    assert result.results[0].name == "High"


@pytest.mark.asyncio
async def test_get_priority_returns_summary() -> None:
    api = _FakeStatusPriorityTypeApi(priorities=[PriorityRecord(summary=_priority_summary(3))])
    service = _service(api)

    priority = await service.get_priority(3)

    assert priority.id == 3


@pytest.mark.asyncio
async def test_list_priorities_applies_hidden_field_masking() -> None:
    # OPENPROJECT_HIDE_PRIORITY_FIELDS must actually take effect on priority
    # reads, not be a no-op.
    settings = dataclasses.replace(make_settings(), hidden_fields={"priority": ("color",)})
    service = _service(settings=settings)

    result = await service.list_priorities()
    priority = result.results[0]

    assert priority._hidden_keys == frozenset({"color"})
    assert priority.color == "#FF0000"  # preserved on the dataclass
    serialized = _to_payload(priority)
    assert "color" not in serialized


@pytest.mark.asyncio
async def test_get_priority_applies_hidden_field_masking() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"priority": ("position",)})
    service = _service(settings=settings)

    priority = await service.get_priority(1)

    assert priority._hidden_keys == frozenset({"position"})
    serialized = _to_payload(priority)
    assert "position" not in serialized


@pytest.mark.asyncio
async def test_priority_hidden_by_priority_scope_not_status_scope() -> None:
    """Regression test for the entity="priority" vs a same-named-neighbor
    hide-field bug class (same class as the News hotfix): masking
    must be keyed to "priority", not silently reuse "status"'s or "type"'s
    configured patterns."""
    settings = dataclasses.replace(make_settings(), hidden_fields={"status": ("color",)})
    service = _service(settings=settings)

    result = await service.list_priorities()

    # apply_hidden_fields only stamps _hidden_keys when something is actually
    # hidden (see app/policies/hidden_fields.py) -- with only "status"
    # configured, "priority" masking must be a no-op, leaving the attribute unset.
    assert not hasattr(result.results[0], "_hidden_keys")


@pytest.mark.asyncio
async def test_list_priorities_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_work_package_read=False)
    service = _service(settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.list_priorities()


# ── Types ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_types_without_project_does_not_resolve_a_project_ref() -> None:
    api = _FakeStatusPriorityTypeApi()
    service = _service(api)

    result = await service.list_types()

    assert result.count == 1
    assert api.list_types_calls == [None]


@pytest.mark.asyncio
async def test_list_types_with_project_resolves_project_ref_for_read() -> None:
    calls: list[tuple[str, bool]] = []

    async def resolve_project_ref_tracking(project_ref: str, *, write: bool = False, context=None) -> dict:
        calls.append((project_ref, write))
        return await _resolve_project_ref(project_ref, write=write, context=context)

    api = _FakeStatusPriorityTypeApi()
    service = _service(api, resolve_project_ref=resolve_project_ref_tracking)

    result = await service.list_types(project="demo")

    assert result.count == 1
    assert calls == [("demo", False)]
    assert api.list_types_calls == [9]


@pytest.mark.asyncio
async def test_list_types_denies_when_project_ref_resolution_denies() -> None:
    service = _service(resolve_project_ref=_denying_resolve_project_ref("OPENPROJECT_READ_PROJECTS"))

    with pytest.raises(PermissionDeniedError):
        await service.list_types(project="demo")


@pytest.mark.asyncio
async def test_get_type_returns_summary() -> None:
    api = _FakeStatusPriorityTypeApi(types=[TypeRecord(summary=_type_summary(4))])
    service = _service(api)

    work_package_type = await service.get_type(4)

    assert work_package_type.id == 4


@pytest.mark.asyncio
async def test_list_types_applies_hidden_field_masking() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"type": ("updated_at",)})
    service = _service(settings=settings)

    result = await service.list_types()
    work_package_type = result.results[0]

    assert work_package_type._hidden_keys == frozenset({"updated_at"})
    assert work_package_type.updated_at == "2026-01-02T00:00:00Z"  # preserved on the dataclass
    serialized = _to_payload(work_package_type)
    assert "updated_at" not in serialized


@pytest.mark.asyncio
async def test_list_types_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_work_package_read=False)
    service = _service(settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.list_types()
