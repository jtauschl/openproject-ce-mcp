"""Application Service for the Statuses/Priorities/Types domain.

Depends on the StatusPriorityTypeApi Protocol, never HttpxStatusPriorityTypeApi
concretely (enforced by the architecture-boundary test). No dedicated
Resolver for any of the three.

All three share `access.ensure_read_enabled("work_package", ...)` as their
gate, so one Service bundling all three, rather than three separate
Services, avoids depending on the exact same seam three times for no
behavioral difference -- same rationale as Actions & Capabilities bundling
`list_actions`/`list_capabilities` under one Service.

`list_types(project=...)` takes a `ProjectRefResolver` dependency to resolve
the optional `project` ref to an id -- this shapes which endpoint the Adapter
calls (`projects/{id}/types` vs `types`), it is not a per-record allowlist
filter: read-scope enforcement for the given `project` ref already happens
inside `ProjectRefResolver` itself (`ensure_project_read_allowed`, called
from `ProjectResolver._resolve_record_uncached` for `write=False`) -- no
additional Policy/allowlist check belongs here; `list_types` never filters
*returned* type rows by project link, the `project` ref only picks the
request URL.

`list_priorities` calls `hidden_fields.apply_hidden_fields("priority", ...)`,
matching Status/Type.
`PriorityRecord`/`PrioritySummary` are structurally near-identical to
`TypeRecord`/`TypeSummary` (id/name/color/position/is_default), so Priority
gets the identical masking treatment as its siblings.

`statuses_cache`/`priorities_cache` are the same `CachedValue` instances
`client.py` also gives `StatusPriorityTypeResolver` -- statuses/priorities
are instance-global in OpenProject (no `project_id` on the underlying API
call), safe to cache for the server process's lifetime (see
`app/caches.py`). `list_types` is NOT cached: unlike statuses/priorities,
types ARE enabled per-project, so a flat cache would leak one project's
enabled-type set into another's.
"""

from __future__ import annotations

from ...config import Settings
from ...models import PriorityListResult, StatusListResult, TypeListResult
from ..caches import CachedValue
from ..policies import access, hidden_fields
from ..ports.project_ref import ProjectRefResolver
from ..ports.status_priority_type_api import PriorityRecord, StatusPriorityTypeApi, StatusRecord


class StatusPriorityTypeService:
    def __init__(
        self,
        *,
        api: StatusPriorityTypeApi,
        settings: Settings,
        resolve_project_ref: ProjectRefResolver,
        statuses_cache: CachedValue[list[StatusRecord]],
        priorities_cache: CachedValue[list[PriorityRecord]],
    ) -> None:
        self._api = api
        self._settings = settings
        self._resolve_project_ref = resolve_project_ref
        self._statuses_cache = statuses_cache
        self._priorities_cache = priorities_cache

    async def list_statuses(self) -> StatusListResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        records = await self._statuses_cache.get(self._api.list_statuses)
        results = [
            hidden_fields.apply_hidden_fields("status", record.summary, settings=self._settings) for record in records
        ]
        return StatusListResult(count=len(results), results=results)

    async def list_priorities(self) -> PriorityListResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        records = await self._priorities_cache.get(self._api.list_priorities)
        results = [
            hidden_fields.apply_hidden_fields("priority", record.summary, settings=self._settings) for record in records
        ]
        return PriorityListResult(count=len(results), results=results)

    async def list_types(self, *, project: str | None = None) -> TypeListResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        project_id: int | None = None
        if project is not None:
            project_payload = await self._resolve_project_ref(project, write=False)
            project_id = int(project_payload["id"])
        records = await self._api.list_types(project_id=project_id)
        results = [
            hidden_fields.apply_hidden_fields("type", record.summary, settings=self._settings) for record in records
        ]
        return TypeListResult(count=len(results), results=results)
