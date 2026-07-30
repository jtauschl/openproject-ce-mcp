"""Application Service for the Roles domain (13th migrated domain).

Depends on the RoleApi Protocol, never HttpxRoleApi concretely (enforced by
the architecture-boundary test). No Resolver: `list_roles` has no semantic
reference to resolve, it is a plain list.

Second genuinely project-independent Service in `app/` after Actions &
Capabilities (`list_actions`) -- no `ProjectRefResolver` dependency at all,
following that domain's template exactly (see its module docstring).

`list_roles` paginates client-side via `paginate_client`, not server-side
(found via a live Docker integration run against real OpenProject
16.6.10/17.4.1/17.5.1): `/api/v3/roles`' `RoleCollectionRepresenter` subclasses
`UnpaginatedCollection`, not `OffsetPaginatedCollection` (verified against
`op-sources/17.6/lib/api/v3/roles/role_collection_representer.rb` and
`lib/api/v3/utilities/endpoints/index.rb`'s `paginated_representer?` check) --
the server ignores `offset`/`pageSize` entirely and always returns the full
collection, `total` included. Trusting that `total`-echo with `paginate_server`
would only truncate the caller-visible `count` implicitly through pass-through,
so `limit=1` would still return every role. `_api.list_roles` is always called
with `offset=1, page_size=settings.max_results` (fetch everything, same shape
as `board_service.py`'s client-filtering branch), and the resulting full list
is sliced locally via `paginate_client` -- same pattern as `GridService`/
`ViewService`/`DocumentService`/`NewsService`.

`MembershipService._resolve_role_hrefs` page-walks this Service's `RoleApi`
directly via `app.pagination.paginate_all`, not through `RoleService.list_roles`.
`paginate_all` itself still assumes a genuinely server-paginated fetcher;
against a real `UnpaginatedCollection` it would
re-fetch and duplicate the same full page if the role count ever exceeded
`max_page_size` (latent at today's 12 roles -- see membership_service.py).
"""

from __future__ import annotations

from ...config import Settings
from ...models import RoleListResult
from ..pagination import effective_limit as _effective_limit
from ..pagination import paginate_client
from ..policies import access, hidden_fields
from ..ports.role_api import RoleApi


class RoleService:
    def __init__(self, *, api: RoleApi, settings: Settings) -> None:
        self._api = api
        self._settings = settings

    async def list_roles(self, *, offset: int = 1, limit: int | None = None) -> RoleListResult:
        access.ensure_read_enabled("role", settings=self._settings)
        effective_limit = _effective_limit(limit, settings=self._settings)
        # NB: the server ignores offset/pageSize for /api/v3/roles and
        # always returns the full collection -- fetch everything once (bounded
        # by max_results, not effective_limit) and slice locally instead of
        # trusting a server-side page that never actually happens.
        records, _server_total = await self._api.list_roles(offset=1, page_size=self._settings.max_results)
        all_results = [
            hidden_fields.apply_hidden_fields("role", record.summary, settings=self._settings) for record in records
        ]
        page, total, next_offset, truncated = paginate_client(offset=offset, limit=effective_limit, results=all_results)
        return RoleListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(page),
            next_offset=next_offset,
            truncated=truncated,
            results=page,
        )
