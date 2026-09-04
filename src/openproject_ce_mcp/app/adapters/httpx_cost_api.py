"""HTTP-backed CostApi adapter.

No `httpx` import (depends on the `Transport` Protocol only, matching every
other adapter).

Route verification (op-sources/17.7/modules/costs/lib/api/v3/):
- `GET cost_entries/{id}`                          -- cost_entries/cost_entries_api.rb
- `GET work_packages/{id}/cost_entries`             -- cost_entries/cost_entries_by_work_package_api.rb
- `GET work_packages/{id}/summarized_costs_by_type` -- cost_entries/cost_entries_by_work_package_api.rb
- `GET cost_types/{id}`                             -- cost_types/cost_types_api.rb

`fetch_cost_entries_for_work_package` reads `_embedded.elements` directly and
returns the raw list -- no offset/pageSize params are sent (the route accepts
none; `CostEntryCollectionRepresenter < API::Decorators::Collection`, no
override, no params block reads them), matching the unpaginated collection
shape (`TimeEntryActivityListResult`'s shape, not `TimeEntryListResult`'s).

`cost_entry_representer.rb` has NO `entityType` property (verified directly
-- unlike `time_entry_representer.rb`, which also has none despite
`httpx_time_entry_api.py` reading `payload.get("entityType")`; that read is
a latent no-op there too, not a pattern to copy here). `entity_id`/
`entity_name` are extracted from the `_links.entity` link only, which IS
always present (`associated_resource :entity` renders its link
unconditionally via `create_link_lambda`; only the EMBEDDED representer body
is gated on `embed_links`).

`normalize_costs_by_type_raw`'s `total`/`count` in the raw payload are the
NUMBER OF COST-TYPE GROUPS (`cost_helper.summarized_cost_entries.size`
upstream), not a monetary total -- do not rename/reinterpret as a sum. Each
element's `budgetId` field is a legacy Budgets-module naming artifact for the
cost type's id (verified: `AggregatedCostEntryRepresenter#budget_id`'s getter
returns `@cost_type.id`), unrelated to the Enterprise Budgets domain this MCP
does not implement -- extracted here as `cost_type_id`, not exposed as
`budget_id`, to avoid the misleading name leaking into the MCP's own surface.
`AggregatedCostEntryRepresenter` has no `id` property of its own
(`model_required? => false`, no `self` link).
"""

from __future__ import annotations

from typing import Any

from ...models import (
    CostEntrySummary,
    CostTypeSummary,
    WorkPackageCostsByTypeElement,
    WorkPackageCostsByTypeResult,
)
from ..ports.cost_api import CostEntryRecord, CostTypeRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import id_from_href as _id_from_href
from ._text import link_title as _link_title
from ._text import trim_text as _trim_text


def normalize_cost_entry_raw(payload: dict[str, Any]) -> CostEntrySummary:
    links = payload.get("_links", {})
    # `entity` doesn't exist before 16.6 (server representer only has
    # `workPackage` there) -- same fallback as httpx_time_entry_api.py's
    # normalize_time_entry_raw.
    entity_link = links.get("entity") or links.get("workPackage")
    return CostEntrySummary(
        id=int(payload["id"]),
        project=_link_title(links.get("project")),
        cost_type=_link_title(links.get("costType")),
        user=_link_title(links.get("user")),
        entity_id=_id_from_href(entity_link.get("href")) if isinstance(entity_link, dict) else None,
        entity_name=_link_title(entity_link),
        spent_units=_trim_text(payload.get("spentUnits"), limit=SUBJECT_LIMIT),
        spent_on=_trim_text(payload.get("spentOn"), limit=SUBJECT_LIMIT),
        created_at=payload.get("createdAt"),
        updated_at=payload.get("updatedAt"),
    )


def normalize_cost_type_raw(payload: dict[str, Any]) -> CostTypeSummary:
    return CostTypeSummary(
        id=int(payload["id"]),
        name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT),
        unit=_trim_text(payload.get("unit"), limit=SUBJECT_LIMIT),
        unit_plural=_trim_text(payload.get("unitPlural"), limit=SUBJECT_LIMIT),
        is_default=bool(payload.get("isDefault")),
    )


def normalize_costs_by_type_raw(payload: dict[str, Any], *, work_package_id: int) -> WorkPackageCostsByTypeResult:
    elements_raw = payload.get("_embedded", {}).get("elements", [])
    elements = []
    for item in elements_raw:
        if not isinstance(item, dict):
            continue
        cost_type_link = item.get("_links", {}).get("costType")
        elements.append(
            WorkPackageCostsByTypeElement(
                cost_type=_link_title(cost_type_link),
                cost_type_id=_id_from_href(cost_type_link.get("href")) if isinstance(cost_type_link, dict) else None,
                spent_units=_trim_text(item.get("spentUnits"), limit=SUBJECT_LIMIT),
            )
        )
    return WorkPackageCostsByTypeResult(
        work_package_id=work_package_id,
        count=int(payload.get("count", len(elements))),
        results=elements,
    )


class HttpxCostApi:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def to_cost_entry_record(self, payload: dict[str, Any]) -> CostEntryRecord:
        return CostEntryRecord(summary=normalize_cost_entry_raw(payload))

    def to_cost_type_record(self, payload: dict[str, Any]) -> CostTypeRecord:
        return CostTypeRecord(summary=normalize_cost_type_raw(payload))

    def to_costs_by_type_result(self, payload: dict[str, Any], *, work_package_id: int) -> WorkPackageCostsByTypeResult:
        return normalize_costs_by_type_raw(payload, work_package_id=work_package_id)

    async def get_cost_entry_raw(self, cost_entry_id: int) -> dict[str, Any]:
        return await self._transport.get_json(f"cost_entries/{cost_entry_id}")

    async def fetch_cost_entries_for_work_package(self, work_package_id: int) -> list[dict[str, Any]]:
        payload = await self._transport.get_json(f"work_packages/{work_package_id}/cost_entries")
        return [item for item in payload.get("_embedded", {}).get("elements", []) if isinstance(item, dict)]

    async def fetch_costs_by_type(self, work_package_id: int) -> dict[str, Any]:
        return await self._transport.get_json(f"work_packages/{work_package_id}/summarized_costs_by_type")

    async def get_cost_type_raw(self, cost_type_id: int) -> dict[str, Any]:
        return await self._transport.get_json(f"cost_types/{cost_type_id}")
