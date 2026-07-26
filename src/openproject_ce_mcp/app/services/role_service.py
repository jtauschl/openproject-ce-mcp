"""Application Service for the Roles domain (13th migrated domain).

Depends on the RoleApi Protocol, never HttpxRoleApi concretely (enforced by
the architecture-boundary test). No Resolver: `list_roles` has no semantic
reference to resolve, it is a plain paginated list.

Second genuinely project-independent Service in `app/` after Actions &
Capabilities (`list_actions`) -- no `ProjectRefResolver` dependency at all,
following that domain's template exactly (see its module docstring).

`list_roles` moves from an unpaginated `CollectionResult` (single-shot fetch
of the entire roles collection) to the `PageResult`/offset-limit pattern,
a deliberate behavior change requested alongside this migration, not a
mechanical consequence of it. This broke the previously-documented shortcut
in `MembershipService` (see docs/architecture.md's former note on `list_roles`
being "injected as a bare callable, without a dedicated port, since it
currently has only one consumer"): `MembershipService._resolve_role_hrefs`
needs the COMPLETE role set to resolve a role name by value, which a single
paginated page (default_page_size=10) can no longer guarantee. Fixed by
having `MembershipService` page-walk this Service's `RoleApi` via the new
`app.pagination.paginate_all` helper instead of calling a parameterless
`list_roles` callable -- the same shape `VersionResolver`/`ProjectResolver`
already use for the identical "resolve a name against a paginated list"
problem, but generalized into a shared helper since Roles has no
project-scoped fetch signature to entangle it with.
"""

from __future__ import annotations

from ...config import Settings
from ...models import RoleListResult
from ..pagination import clamp_limit, paginate_server
from ..policies import access, hidden_fields
from ..ports.role_api import RoleApi


class RoleService:
    def __init__(self, *, api: RoleApi, settings: Settings) -> None:
        self._api = api
        self._settings = settings

    def _effective_limit(self, limit: int | None) -> int:
        return clamp_limit(
            limit,
            default_page_size=self._settings.default_page_size,
            max_page_size=self._settings.max_page_size,
            max_results=self._settings.max_results,
        )

    async def list_roles(self, *, offset: int = 1, limit: int | None = None) -> RoleListResult:
        access.ensure_read_enabled("role", settings=self._settings)
        effective_limit = self._effective_limit(limit)
        records, total = await self._api.list_roles(offset=offset, page_size=effective_limit)
        results = [
            hidden_fields.apply_hidden_fields("role", record.summary, settings=self._settings) for record in records
        ]
        next_offset, truncated = paginate_server(offset=offset, limit=effective_limit, total=total)
        return RoleListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(results),
            next_offset=next_offset,
            truncated=truncated,
            results=results,
        )
