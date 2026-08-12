"""Costs Domain API port (cost_entries + cost_types -- entirely read-only).

Costs module has NO create/update/delete anywhere in its API (verified against
op-sources/17.7/modules/costs/lib/api/v3/{cost_entries,cost_types}/ -- see
app/adapters/httpx_cost_api.py's module docstring for the full route/
representer citation). This Port therefore exposes only GETs, unlike
`TimeEntryApi`'s Protocol.

cost_entries has three distinct read shapes:
- `get_cost_entry_raw`: single cost entry by its own id (`GET cost_entries/{id}`).
- `fetch_cost_entries_for_work_package`: ALL cost entries for a work package in
  one call (`GET work_packages/{id}/cost_entries`) -- UNPAGINATED upstream
  (`CostEntryCollectionRepresenter` extends the plain `API::Decorators::Collection`
  base with no override; no offset/pageSize params are read anywhere in the route).
- `fetch_costs_by_type`/`to_costs_by_type_result`: aggregated per-cost-type
  totals for a work package (`GET work_packages/{id}/summarized_costs_by_type`)
  -- also unpaginated, and NOT a monetary total: `total`/`count` are the
  number of distinct cost types with spend, and each element carries
  `spent_units` (a quantity), not money.

cost_types has one read shape (`get_cost_type_raw`/`to_cost_type_record`,
`GET cost_types/{id}`) -- no collection endpoint exists upstream at all, so no
`fetch_page`/`list` method is declared here.

`get_cost_entry_raw`/`get_cost_type_raw` return the raw HAL payload (not a
record), matching `TimeEntryApi.get_raw`'s precedent: the Service needs
`_links.project` off the raw cost-entry payload BEFORE normalizing, to run
the allowlist check (`scope_policy.ensure_project_link_allowed`), exactly
like `TimeEntryService.get()`.

`to_costs_by_type_result` takes `work_package_id` as an explicit kwarg
alongside the raw payload -- the raw `WorkPackageCostsByTypeRepresenter`
payload carries no field identifying which work package it summarizes (only
a `self` link an adapter would have to re-parse), and the Service already
holds the resolved numeric id in scope from `WorkPackageIdResolver`. Mirrors
`TimeEntryApi.to_record(payload, *, text_limit)`'s shape of a normalize
method taking a second, Service-supplied argument beyond the raw payload.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ...models import CostEntrySummary, CostTypeSummary, WorkPackageCostsByTypeResult


@dataclass(frozen=True)
class CostEntryRecord:
    summary: CostEntrySummary


@dataclass(frozen=True)
class CostTypeRecord:
    summary: CostTypeSummary


class CostApi(Protocol):
    """Narrow, Costs-only Domain API port. CostService depends on this
    Protocol, never on HttpxCostApi concretely (enforced by the
    architecture-boundary test).
    """

    async def get_cost_entry_raw(self, cost_entry_id: int) -> dict[str, Any]: ...
    def to_cost_entry_record(self, payload: dict[str, Any]) -> CostEntryRecord: ...
    async def fetch_cost_entries_for_work_package(self, work_package_id: int) -> list[dict[str, Any]]: ...
    async def fetch_costs_by_type(self, work_package_id: int) -> dict[str, Any]: ...
    def to_costs_by_type_result(
        self, payload: dict[str, Any], *, work_package_id: int
    ) -> WorkPackageCostsByTypeResult: ...
    async def get_cost_type_raw(self, cost_type_id: int) -> dict[str, Any]: ...
    def to_cost_type_record(self, payload: dict[str, Any]) -> CostTypeRecord: ...
