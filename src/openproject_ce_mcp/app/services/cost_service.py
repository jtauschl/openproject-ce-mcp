"""Application Service for the Costs domain (cost_entries + cost_types).

Entirely read-only -- see `app/ports/cost_api.py`'s module docstring for the
verified route/representer citations. Depends on `CostApi` and
`WorkPackageIdResolver` only (no `ProjectApi`/`UserApi`/current-user
dependency needed -- unlike Time Entries, there is no create/update path
requiring project/user/activity resolution).

Read scope reuses `"work_package"` (not a dedicated `"cost_entry"`/
`"cost_type"` scope) -- matching Wiki Page Links' and Time Entries'
precedent for a work-package-scoped sub-resource.

Project-allowlist checks, one per work-package-touching method:
- `get_cost_entry`: reads `_links.project` off the RAW cost-entry payload
  (before normalizing) and runs `scope_policy.ensure_project_link_allowed`,
  exactly matching `TimeEntryService.get()`'s pattern -- the cost entry's own
  project link is the source of truth, not any caller-supplied project.
- `list_work_package_cost_entries` / `get_work_package_costs_by_type`: both
  resolve `work_package_id` via `WorkPackageIdResolver(ref, write=False)`,
  which already confirms the anchor work package is allowed against
  `OPENPROJECT_READ_PROJECTS` before any cost data is fetched -- matching
  `WikiPageLinkService.list_for_work_package()`'s identical precedent. No
  additional per-item allowlist check is needed for the entries returned:
  they are inherently scoped to the (already allowed) work package's own
  project -- there is no cross-project leakage vector the way a global list
  endpoint would have.

`get_cost_type` has NO project-allowlist check at all -- cost types are
project-agnostic catalog data (verified: `cost_types_api.rb`'s
`authorize_in_any_project` gate has no project param, matching the
project-agnostic, instance-wide nature of e.g. `list_statuses`/
`list_priorities`). It still requires `"work_package"` read to be enabled
(its home scope, since it's exposed alongside the other Costs tools), but no
project-link check runs -- `access.ensure_read_enabled("work_package", ...)`
is the only guard, deliberately not `scope_policy.ensure_project_link_allowed`.

No hidden_fields entity groups beyond a plain `apply_hidden_fields` call per
Summary/element type -- no field needs the "clear associated metadata
together" special handling `TimeEntryService._stamp`'s comment field
requires (Costs has no comment field at all -- see `app/ports/cost_api.py`'s
module docstring).
"""

from __future__ import annotations

from ...config import Settings
from ...models import (
    CostEntryListResult,
    CostEntrySummary,
    CostTypeSummary,
    WorkPackageCostsByTypeResult,
)
from ..policies import access, hidden_fields
from ..policies import scope as scope_policy
from ..ports.cost_api import CostApi
from ..ports.work_package_ref import WorkPackageIdResolver


class CostService:
    def __init__(
        self,
        *,
        api: CostApi,
        settings: Settings,
        project_id_to_identifier: dict[int, str],
        resolve_work_package_id: WorkPackageIdResolver,
    ) -> None:
        self._api = api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier
        self._resolve_work_package_id = resolve_work_package_id

    def _stamp_entry(self, summary: CostEntrySummary) -> CostEntrySummary:
        return hidden_fields.apply_hidden_fields("cost_entry", summary, settings=self._settings)

    def _stamp_type(self, summary: CostTypeSummary) -> CostTypeSummary:
        return hidden_fields.apply_hidden_fields("cost_type", summary, settings=self._settings)

    async def get_cost_entry(self, cost_entry_id: int) -> CostEntrySummary:
        access.ensure_read_enabled("work_package", settings=self._settings)
        raw = await self._api.get_cost_entry_raw(cost_entry_id)
        project_link = raw.get("_links", {}).get("project")
        scope_policy.ensure_project_link_allowed(
            project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        record = self._api.to_cost_entry_record(raw)
        return self._stamp_entry(record.summary)

    async def list_work_package_cost_entries(self, work_package_id: int | str) -> CostEntryListResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        resolved_id = await self._resolve_work_package_id(work_package_id, write=False)
        raw_elements = await self._api.fetch_cost_entries_for_work_package(resolved_id)
        results = [self._stamp_entry(self._api.to_cost_entry_record(item).summary) for item in raw_elements]
        return CostEntryListResult(count=len(results), results=results)

    async def get_work_package_costs_by_type(self, work_package_id: int | str) -> WorkPackageCostsByTypeResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        resolved_id = await self._resolve_work_package_id(work_package_id, write=False)
        raw = await self._api.fetch_costs_by_type(resolved_id)
        result = self._api.to_costs_by_type_result(raw, work_package_id=resolved_id)
        result.results = [
            hidden_fields.apply_hidden_fields("work_package_costs_by_type_element", element, settings=self._settings)
            for element in result.results
        ]
        return result

    async def get_cost_type(self, cost_type_id: int) -> CostTypeSummary:
        access.ensure_read_enabled("work_package", settings=self._settings)
        raw = await self._api.get_cost_type_raw(cost_type_id)
        record = self._api.to_cost_type_record(raw)
        return self._stamp_type(record.summary)
