"""Application Service for the Actions & Capabilities domain (ADR 0001, OPM-276).

Depends on the ActionCapabilityApi Protocol, never HttpxActionCapabilityApi
concretely (enforced by the architecture-boundary test). No dedicated
Resolver for either method: `capability_id` is an opaque string filter value,
not a semantic reference needing lookup.

`list_actions` is a purely project-independent Service method: Actions has no
project concept at all in the OpenProject API, so it takes no
`ProjectRefResolver` dependency, unlike most other migrated domains.

`list_capabilities`, by contrast, IS project-scoped when a `project` ref is
given (its `context` filter targets a specific project) -- so it depends on
`ProjectRefResolver`, same seam as Categories/Memberships/Documents. Both
methods share `access.ensure_read_enabled("membership", ...)` as their gate
(verbatim port of client.py's `_ensure_read_enabled("membership")` for both),
so a single Service bundling both, rather than two separate Services, avoids
depending on the exact same seam twice for no behavioral difference.

`list_capabilities` also allowlist-checks each RETURNED record's own
`context` link (via `scope.ensure_project_link_allowed`, same "nullable link,
no dedicated policy file" shape as `ViewService._allowed` -- Capabilities has
no dedicated policy file for the same reason Views doesn't), independent of
whether a `project` filter was supplied server-side. The pre-migration
client.py only ever allowlist-checked the caller-supplied `project`
parameter itself (by resolving it through `ProjectRefResolver` before
building the server-side `context` filter) -- a `capability_id`-only call
skipped that check entirely, since `project` was never given to resolve.
Found during this domain's own step-6.5 Codex review: capability records
carry a genuine `context.href` (a real `/api/v3/projects/{id}` link per the
OpenProject API docs), not just a display title, so a restrictive
`OPENPROJECT_READ_PROJECTS` scope was leaking capability records (including
project names/principals) for `capability_id`-only calls. The server-side
`context` filter remains a narrowing optimization when `project` is given,
not the security boundary -- the per-record check runs regardless.

`capability_id` is filtered via the server-side single-item `GET
/capabilities/{id}` endpoint, not a collection `id` filter -- OpenProject's
capabilities collection endpoint accepts only `action`/`principal`/`context`
filters (also found during the step-6.5 review; the pre-migration client.py
sent an undocumented `{"id": ...}` collection filter that this migration
initially ported verbatim without re-verifying against current API docs).
The `context` filter's project-scoping value uses the current `w{id}`
(workspace) syntax, not the deprecated `p{id}` form the pre-migration code
used.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...models import ActionListResult, CapabilityListResult
from ..errors import InvalidInputError
from ..pagination import effective_limit as _effective_limit
from ..pagination import paginate_server
from ..policies import access, hidden_fields
from ..policies import scope as scope_policy
from ..ports.action_capability_api import ActionCapabilityApi
from ..ports.project_ref import ProjectRefResolver


def _context_matches_project(context_link: dict[str, Any] | None, project_id: int) -> bool:
    if not isinstance(context_link, dict):
        return False
    href = context_link.get("href")
    if not href:
        return False
    try:
        return int(href.rstrip("/").split("/")[-1]) == project_id
    except (ValueError, IndexError):
        return False


class ActionCapabilityService:
    def __init__(
        self,
        *,
        api: ActionCapabilityApi,
        settings: Settings,
        project_id_to_identifier: dict[int, str],
        resolve_project_ref: ProjectRefResolver,
    ) -> None:
        self._api = api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier
        self._resolve_project_ref = resolve_project_ref

    def _context_allowed(self, context_link: dict[str, Any] | None) -> bool:
        return scope_policy.payload_allowed(
            lambda: scope_policy.ensure_project_link_allowed(
                context_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
            )
        )

    async def list_actions(self, *, offset: int = 1, limit: int | None = None) -> ActionListResult:
        access.ensure_read_enabled("membership", settings=self._settings)
        effective_limit = _effective_limit(limit, settings=self._settings)
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
        effective_limit = _effective_limit(limit, settings=self._settings)

        project_id: int | None = None
        if project is not None:
            project_payload = await self._resolve_project_ref(project, write=False)
            project_id = int(project_payload["id"])

        if capability_id is not None:
            record = await self._api.get_capability(capability_id)
            records = [record] if self._context_allowed(record.context_link) else []
            if project_id is not None:
                records = [r for r in records if _context_matches_project(r.context_link, project_id)]
            total = len(records)
        else:
            filters: list[dict[str, object]] = [{"context": {"operator": "=", "values": [f"w{project_id}"]}}]
            fetched, total = await self._api.list_capabilities(
                filters=filters, offset=offset, page_size=effective_limit
            )
            records = [r for r in fetched if self._context_allowed(r.context_link)]

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
