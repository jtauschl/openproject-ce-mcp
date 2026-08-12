from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import PermissionDeniedError
from openproject_ce_mcp.app.ports.cost_api import CostEntryRecord, CostTypeRecord
from openproject_ce_mcp.app.services.cost_service import CostService
from openproject_ce_mcp.models import (
    CostEntrySummary,
    CostTypeSummary,
    WorkPackageCostsByTypeElement,
    WorkPackageCostsByTypeResult,
)

PROJECT_ID_TO_IDENTIFIER = {1: "demo", 20: "other"}


def _cost_entry_summary(cost_entry_id: int = 9, *, project: str | None = "Demo") -> CostEntrySummary:
    return CostEntrySummary(
        id=cost_entry_id,
        project=project,
        cost_type="Labor costs",
        user="Admin",
        entity_id=42,
        entity_name="Do the thing",
        spent_units="3.5",
        spent_on="2026-03-20",
        created_at=None,
        updated_at=None,
    )


def _cost_type_summary(cost_type_id: int = 2) -> CostTypeSummary:
    return CostTypeSummary(
        id=cost_type_id,
        name="Labor costs",
        unit="hour",
        unit_plural="hours",
        is_default=True,
    )


class _FakeCostApi:
    def __init__(
        self,
        *,
        cost_entry_id: int = 9,
        project_link: dict | None = None,
        entries_for_work_package: list[CostEntrySummary] | None = None,
        costs_by_type_result: WorkPackageCostsByTypeResult | None = None,
        cost_type_id: int = 2,
    ) -> None:
        self._cost_entry_id = cost_entry_id
        self._project_link = project_link or {"href": "/api/v3/projects/1", "title": "Demo"}
        self._entries_for_work_package = (
            entries_for_work_package if entries_for_work_package is not None else [_cost_entry_summary()]
        )
        self._costs_by_type_result = costs_by_type_result
        self._cost_type_id = cost_type_id
        self.get_cost_entry_raw_calls: list[int] = []
        self.fetch_cost_entries_for_work_package_calls: list[int] = []
        self.fetch_costs_by_type_calls: list[int] = []
        self.get_cost_type_raw_calls: list[int] = []

    async def get_cost_entry_raw(self, cost_entry_id: int) -> dict:
        self.get_cost_entry_raw_calls.append(cost_entry_id)
        return {"__summary__": _cost_entry_summary(cost_entry_id), "_links": {"project": self._project_link}}

    def to_cost_entry_record(self, payload: dict) -> CostEntryRecord:
        return CostEntryRecord(summary=payload["__summary__"])

    async def fetch_cost_entries_for_work_package(self, work_package_id: int) -> list[dict]:
        self.fetch_cost_entries_for_work_package_calls.append(work_package_id)
        return [{"__summary__": s} for s in self._entries_for_work_package]

    async def fetch_costs_by_type(self, work_package_id: int) -> dict:
        self.fetch_costs_by_type_calls.append(work_package_id)
        return {"__work_package_id__": work_package_id}

    def to_costs_by_type_result(self, payload: dict, *, work_package_id: int) -> WorkPackageCostsByTypeResult:
        if self._costs_by_type_result is not None:
            return self._costs_by_type_result
        return WorkPackageCostsByTypeResult(
            work_package_id=work_package_id,
            count=1,
            results=[WorkPackageCostsByTypeElement(cost_type="Labor costs", cost_type_id=2, spent_units="3.5")],
        )

    async def get_cost_type_raw(self, cost_type_id: int) -> dict:
        self.get_cost_type_raw_calls.append(cost_type_id)
        return {"__summary__": _cost_type_summary(cost_type_id)}

    def to_cost_type_record(self, payload: dict) -> CostTypeRecord:
        return CostTypeRecord(summary=payload["__summary__"])


def _resolve_work_package_id_ok(resolved_id: int = 42):
    calls: list[tuple[int | str, bool]] = []

    async def resolve(work_package_ref, *, write: bool = False) -> int:
        calls.append((work_package_ref, write))
        return resolved_id

    resolve.calls = calls  # type: ignore[attr-defined]
    return resolve


def _service(
    *,
    api: _FakeCostApi | None = None,
    settings=None,
    resolve_work_package_id=None,
) -> CostService:
    return CostService(
        api=api or _FakeCostApi(),
        settings=settings or make_settings(),
        project_id_to_identifier=PROJECT_ID_TO_IDENTIFIER,
        resolve_work_package_id=resolve_work_package_id or _resolve_work_package_id_ok(),
    )


# --- get_cost_entry ----------------------------------------------------------


@pytest.mark.asyncio
async def test_get_cost_entry_returns_summary_under_allowed_project() -> None:
    api = _FakeCostApi(cost_entry_id=9)
    settings = dataclasses.replace(make_settings(), read_projects=("*",))
    service = _service(api=api, settings=settings)

    result = await service.get_cost_entry(9)

    assert result.id == 9
    assert api.get_cost_entry_raw_calls == [9]


@pytest.mark.asyncio
async def test_get_cost_entry_denies_outside_read_allowlist() -> None:
    api = _FakeCostApi(cost_entry_id=9, project_link={"href": "/api/v3/projects/2", "title": "Other"})
    settings = dataclasses.replace(make_settings(), read_projects=("demo",))
    service = _service(api=api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get_cost_entry(9)


@pytest.mark.asyncio
async def test_get_cost_entry_denies_when_work_package_read_disabled() -> None:
    api = _FakeCostApi()
    settings = dataclasses.replace(make_settings(), enable_work_package_read=False)
    service = _service(api=api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get_cost_entry(9)

    assert api.get_cost_entry_raw_calls == []


@pytest.mark.asyncio
async def test_get_cost_entry_masks_hidden_fields() -> None:
    api = _FakeCostApi()
    settings = dataclasses.replace(make_settings(), hidden_fields={"cost_entry": ("spent_units",)})
    service = _service(api=api, settings=settings)

    result = await service.get_cost_entry(9)

    assert result._hidden_keys == frozenset({"spent_units"})  # type: ignore[attr-defined]


# --- list_work_package_cost_entries ------------------------------------------


@pytest.mark.asyncio
async def test_list_work_package_cost_entries_resolves_work_package_and_returns_all_entries() -> None:
    entries = [_cost_entry_summary(9), _cost_entry_summary(10)]
    api = _FakeCostApi(entries_for_work_package=entries)
    resolve = _resolve_work_package_id_ok(42)
    service = _service(api=api, resolve_work_package_id=resolve)

    result = await service.list_work_package_cost_entries("PROJ-51")

    assert result.count == 2
    assert len(result.results) == 2
    assert not hasattr(result, "offset")
    assert not hasattr(result, "limit")
    assert not hasattr(result, "truncated")
    assert resolve.calls == [("PROJ-51", False)]
    assert api.fetch_cost_entries_for_work_package_calls == [42]


# --- get_work_package_costs_by_type ------------------------------------------


@pytest.mark.asyncio
async def test_get_work_package_costs_by_type_stamps_resolved_numeric_id() -> None:
    api = _FakeCostApi()
    resolve = _resolve_work_package_id_ok(42)
    service = _service(api=api, resolve_work_package_id=resolve)

    result = await service.get_work_package_costs_by_type("PROJ-51")

    assert result.work_package_id == 42
    assert resolve.calls == [("PROJ-51", False)]
    assert api.fetch_costs_by_type_calls == [42]


@pytest.mark.asyncio
async def test_get_work_package_costs_by_type_masks_hidden_element_fields() -> None:
    api = _FakeCostApi(
        costs_by_type_result=WorkPackageCostsByTypeResult(
            work_package_id=42,
            count=1,
            results=[WorkPackageCostsByTypeElement(cost_type="Labor costs", cost_type_id=2, spent_units="3.5")],
        )
    )
    settings = dataclasses.replace(
        make_settings(), hidden_fields={"work_package_costs_by_type_element": ("spent_units",)}
    )
    service = _service(api=api, settings=settings)

    result = await service.get_work_package_costs_by_type(42)

    assert result.results[0]._hidden_keys == frozenset({"spent_units"})  # type: ignore[attr-defined]


# --- get_cost_type ------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_cost_type_returns_summary() -> None:
    api = _FakeCostApi(cost_type_id=2)
    service = _service(api=api)

    result = await service.get_cost_type(2)

    assert result.id == 2
    assert api.get_cost_type_raw_calls == [2]


@pytest.mark.asyncio
async def test_get_cost_type_never_calls_work_package_resolver() -> None:
    """Cost types are project-agnostic catalog data -- no work package
    context is ever needed to look one up."""
    api = _FakeCostApi(cost_type_id=2)
    resolve = _resolve_work_package_id_ok(42)
    service = _service(api=api, resolve_work_package_id=resolve)

    await service.get_cost_type(2)

    assert resolve.calls == []


@pytest.mark.asyncio
async def test_get_cost_type_ignores_a_restrictive_read_allowlist() -> None:
    """No project-allowlist check runs for cost types at all -- proves the
    'project-agnostic catalog' design decision, not just documents it."""
    api = _FakeCostApi(cost_type_id=2)
    settings = dataclasses.replace(make_settings(), read_projects=())
    service = _service(api=api, settings=settings)

    result = await service.get_cost_type(2)

    assert result.id == 2


@pytest.mark.asyncio
async def test_get_cost_type_denies_when_work_package_read_disabled() -> None:
    api = _FakeCostApi()
    settings = dataclasses.replace(make_settings(), enable_work_package_read=False)
    service = _service(api=api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get_cost_type(2)

    assert api.get_cost_type_raw_calls == []
