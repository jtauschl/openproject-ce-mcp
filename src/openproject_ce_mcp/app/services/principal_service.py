"""Application Service for the Principals domain.

Depends on the PrincipalApi Protocol, never HttpxPrincipalApi concretely
(enforced by the architecture-boundary test). No Resolver dependency, no
Policy module: instance-wide search, no project link and no allowlist
concept at all.

Only ONE public method: `list_principals`, gated on `"admin"`
(OPENPROJECT_ENABLE_ADMIN_READ) -- this is the tool-facing method that
surfaces the full PrincipalSummary list (name/login/email/status) to the
agent. There is deliberately no ungated twin method on this Service (an
earlier design draft had one, `list_unchecked`, rejected during review: no
other Service in this codebase exposes a public ungated method alongside a
gated one). The internal, ungated principal-name-to-id lookup instead lives
on `PrincipalResolver` (app/resolvers/principal_resolver.py), which depends
on this same `PrincipalApi` Port directly -- bypassing this Service
entirely, mirroring how `MembershipService._resolve_role_hrefs` reaches
`RoleApi` directly rather than going through `RoleService`, and how
`WorkPackageService` gets `StatusPriorityTypeApi` injected directly rather
than through `StatusPriorityTypeService`.
"""

from __future__ import annotations

from ...config import Settings
from ...models import PrincipalListResult
from ..pagination import effective_limit as _effective_limit
from ..pagination import paginate_server as _paginate_server
from ..policies import access, hidden_fields
from ..ports.principal_api import PrincipalApi


class PrincipalService:
    def __init__(self, *, api: PrincipalApi, settings: Settings) -> None:
        self._api = api
        self._settings = settings

    async def list_principals(
        self, *, search: str | None = None, offset: int = 1, limit: int | None = None
    ) -> PrincipalListResult:
        access.ensure_read_enabled("admin", settings=self._settings)
        limit = _effective_limit(limit, settings=self._settings)
        records, total = await self._api.list_principals(search=search, offset=offset, page_size=limit)
        results = [
            hidden_fields.apply_hidden_fields("principal", record.summary, settings=self._settings)
            for record in records
        ]
        next_offset, truncated = _paginate_server(offset=offset, limit=limit, total=total)
        return PrincipalListResult(
            offset=offset,
            limit=limit,
            total=total,
            count=len(results),
            next_offset=next_offset,
            truncated=truncated,
            results=results,
        )
