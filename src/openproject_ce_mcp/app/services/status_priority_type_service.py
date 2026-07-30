"""Application Service for the Statuses/Priorities/Types domain (16th migrated
domain).

Depends on the StatusPriorityTypeApi Protocol, never HttpxStatusPriorityTypeApi
concretely (enforced by the architecture-boundary test). No dedicated
Resolver for any of the three: `status_id`/`priority_id`/`type_id` are always
numeric values already validated by tools.py.

All three share `access.ensure_read_enabled("work_package", ...)` as their
gate (verbatim port of client.py's `_ensure_read_enabled("work_package")` for
all six methods), so one Service bundling all three, rather than three
separate Services, avoids depending on the exact same seam three times for
no behavioral difference -- same rationale as Actions & Capabilities bundling
`list_actions`/`list_capabilities` under one Service.

`list_types(project=...)` takes a `ProjectRefResolver` dependency to resolve
the optional `project` ref to an id -- this shapes which endpoint the Adapter
calls (`projects/{id}/types` vs `types`), it is not a per-record allowlist
filter: read-scope enforcement for the given `project` ref already happens
inside `ProjectRefResolver` itself (`ensure_project_read_allowed`, called
from `ProjectResolver._resolve_record_uncached` for `write=False`), verified
by reading that resolver's own source before writing this Service -- no
additional Policy/allowlist check belongs here, matching client.py's original
`list_types` behavior exactly (it never filtered *returned* type rows by
project link; the `project` ref only picks the request URL).

**Priority hidden-field bugfix (found during this migration, not present in
client.py's original `normalize_priority`)**: `list_priorities`/`get_priority`
now call `hidden_fields.apply_hidden_fields("priority", ...)`, matching
Status/Type. client.py's `normalize_priority` never called
`_apply_hidden_fields` at all, and `config.py`'s `HIDE_FIELD_ENV_BY_ENTITY`
had no `"priority"` entry either -- both gaps are fixed together (the config
map entry lives in `config.py`, this Service supplies the missing call site).
`PriorityRecord`/`PrioritySummary` are structurally near-identical to
`TypeRecord`/`TypeSummary` (id/name/color/position/is_default), so there was
no principled reason for the asymmetry; it was simply missing from the start.
"""

from __future__ import annotations

from ...config import Settings
from ...models import (
    PriorityListResult,
    PrioritySummary,
    StatusListResult,
    StatusSummary,
    TypeListResult,
    TypeSummary,
)
from ..policies import access, hidden_fields
from ..ports.project_ref import ProjectRefResolver
from ..ports.status_priority_type_api import StatusPriorityTypeApi


class StatusPriorityTypeService:
    def __init__(
        self,
        *,
        api: StatusPriorityTypeApi,
        settings: Settings,
        resolve_project_ref: ProjectRefResolver,
    ) -> None:
        self._api = api
        self._settings = settings
        self._resolve_project_ref = resolve_project_ref

    async def list_statuses(self) -> StatusListResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        records = await self._api.list_statuses()
        results = [
            hidden_fields.apply_hidden_fields("status", record.summary, settings=self._settings) for record in records
        ]
        return StatusListResult(count=len(results), results=results)

    async def get_status(self, status_id: int) -> StatusSummary:
        access.ensure_read_enabled("work_package", settings=self._settings)
        record = await self._api.get_status(status_id)
        return hidden_fields.apply_hidden_fields("status", record.summary, settings=self._settings)

    async def list_priorities(self) -> PriorityListResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        records = await self._api.list_priorities()
        results = [
            hidden_fields.apply_hidden_fields("priority", record.summary, settings=self._settings) for record in records
        ]
        return PriorityListResult(count=len(results), results=results)

    async def get_priority(self, priority_id: int) -> PrioritySummary:
        access.ensure_read_enabled("work_package", settings=self._settings)
        record = await self._api.get_priority(priority_id)
        return hidden_fields.apply_hidden_fields("priority", record.summary, settings=self._settings)

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

    async def get_type(self, type_id: int) -> TypeSummary:
        access.ensure_read_enabled("work_package", settings=self._settings)
        record = await self._api.get_type(type_id)
        return hidden_fields.apply_hidden_fields("type", record.summary, settings=self._settings)
