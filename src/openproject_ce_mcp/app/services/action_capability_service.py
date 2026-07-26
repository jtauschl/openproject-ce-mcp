"""Application Service for the Actions & Capabilities domain (ADR 0001, OPM-276).

Depends on the ActionCapabilityApi Protocol, never HttpxActionCapabilityApi
concretely (enforced by the architecture-boundary test). No dedicated
Resolver for either method: `capability_id` is an opaque string filter value,
not a semantic reference needing lookup.

`list_actions` is the first genuinely project-independent Service in `app/`:
every other migrated domain (Versions, Projects, Memberships, News,
Documents, Wiki Pages, Categories, Views, Grids, Sprints, Boards) depends on
`ProjectRefResolver`, since Projects is the only domain with no domain above
it to scope against. Actions has no project concept at all in the OpenProject
API (verified: client.py's original list_actions never resolves or filters by
a project), so `list_actions` takes no `ProjectRefResolver` dependency --
future migrations of similarly global/admin-scoped domains (Users, Groups,
Roles, Principals, query-metadata, help-texts, working-days, custom-options --
see docs/architecture-migration-runbook.md's "Pick the next domain" section)
can use this Service as their shape template instead of Categories/Memberships.

`list_capabilities`, by contrast, IS project-scoped when a `project` ref is
given (its `context` filter targets a specific project) -- so it depends on
`ProjectRefResolver`, same seam as Categories/Memberships/Documents. Both
methods share `access.ensure_read_enabled("membership", ...)` as their gate
(verbatim port of client.py's `_ensure_read_enabled("membership")` for both),
so a single Service bundling both, rather than two separate Services, avoids
depending on the exact same seam twice for no behavioral difference.
"""

from __future__ import annotations

from ...config import Settings
from ...models import ActionListResult, CapabilityListResult
from ..errors import InvalidInputError
from ..pagination import clamp_limit, paginate_server
from ..policies import access, hidden_fields
from ..ports.action_capability_api import ActionCapabilityApi
from ..ports.project_ref import ProjectRefResolver


class ActionCapabilityService:
    def __init__(
        self,
        *,
        api: ActionCapabilityApi,
        settings: Settings,
        resolve_project_ref: ProjectRefResolver,
    ) -> None:
        self._api = api
        self._settings = settings
        self._resolve_project_ref = resolve_project_ref

    def _effective_limit(self, limit: int | None) -> int:
        return clamp_limit(
            limit,
            default_page_size=self._settings.default_page_size,
            max_page_size=self._settings.max_page_size,
            max_results=self._settings.max_results,
        )

    async def list_actions(self, *, offset: int = 1, limit: int | None = None) -> ActionListResult:
        access.ensure_read_enabled("membership", settings=self._settings)
        effective_limit = self._effective_limit(limit)
        records, total = await self._api.list_actions(offset=offset, page_size=effective_limit)
        results = [
            hidden_fields.apply_hidden_fields("action", record.summary, settings=self._settings) for record in records
        ]
        next_offset, truncated = paginate_server(offset=offset, limit=effective_limit, total=total)
        return ActionListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(results),
            next_offset=next_offset,
            truncated=truncated,
            results=results,
        )

    async def list_capabilities(
        self,
        *,
        project: str | None = None,
        capability_id: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> CapabilityListResult:
        access.ensure_read_enabled("membership", settings=self._settings)
        if project is None and capability_id is None:
            raise InvalidInputError("At least one of project or capability_id is required for capabilities.")
        effective_limit = self._effective_limit(limit)
        filters: list[dict[str, object]] = []
        if capability_id is not None:
            filters.append({"id": {"operator": "=", "values": [capability_id]}})
        if project is not None:
            project_payload = await self._resolve_project_ref(project, write=False)
            filters.append({"context": {"operator": "=", "values": [f"p{project_payload['id']}"]}})
        records, total = await self._api.list_capabilities(filters=filters, offset=offset, page_size=effective_limit)
        results = [
            hidden_fields.apply_hidden_fields("capability", record.summary, settings=self._settings)
            for record in records
        ]
        next_offset, truncated = paginate_server(offset=offset, limit=effective_limit, total=total)
        return CapabilityListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(results),
            next_offset=next_offset,
            truncated=truncated,
            results=results,
        )
