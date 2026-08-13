"""Application Service for the Project Storages domain.

Depends on the ProjectStorageApi Protocol, never HttpxProjectStorageApi
concretely (enforced by the architecture-boundary test). Genuinely
read-only: OpenProject's v3 API mounts only get/Index and get/Show for
project_storages (project_storages_api.rb) -- no create/update/delete
method exists on this Service, matching the Protocol.

Read/write scope is "project" (NOT "admin"): OpenProject's own API gates
project_storages purely per-project (`current_user.allowed_in_project?(
:view_file_links, project)`, both for the Index filter and the Show 404
disguise) -- there is no admin-only gate on this resource at all, unlike
storages itself (whose writes ARE hard admin-gated). Hiding a genuinely
per-project-permissioned, read-only resource behind this MCP's own
"admin"/OPENPROJECT_ENABLE_ADMIN_READ flag would misrepresent it as an
instance-wide-PII-shaped resource the way Users/Groups genuinely are;
"project" (OPENPROJECT_ENABLE_PROJECT_READ, the same scope Documents/News
use) is the correct fit, matched by adding this domain's two tools to
tools.py's `_PROJECT_SCOPED_READ_TOOLS`.

Each row is ADDITIONALLY gated per its own project link via
scope_policy.ensure_project_link_allowed (REQUIRED-project-link contract:
project_storages' representer's associated_project is never optional --
`t.references :project, null: false` at the DB level, `belongs_to :project`
with Rails 5+ default `optional: false` at the model level, verified
directly against source) -- the same two-layer gating shape every other
project-scoped domain in this codebase uses (an env-var check to enable the
tool family at all, PLUS a per-row OPENPROJECT_READ_PROJECTS allowlist
check).

`list_project_storages` paginates client-side via `paginate_client`, not
`scan_records_and_paginate`'s early-stopping server-page-scan (unlike
Documents/News, whose list endpoints ARE genuinely server-paginated):
`/api/v3/project_storages`' ProjectStorageCollectionRepresenter subclasses
UnpaginatedCollection, not OffsetPaginatedCollection -- verified directly
against source, same shape as RoleService/StorageService. `_api.list_all` is
always called with `offset=1, page_size=settings.max_results` (fetch
everything), filtered client-side (allowlist + optional project match), and
the resulting filtered list is sliced locally via `paginate_client`.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...models import ProjectStorageDetail, ProjectStorageListResult
from ..pagination import effective_limit as _effective_limit
from ..pagination import paginate_client
from ..policies import access, hidden_fields
from ..policies import scope as scope_policy
from ..policies.project_storage_policy import project_storage_payload_allowed
from ..ports.project_ref import ProjectRefResolver
from ..ports.project_storage_api import ProjectStorageApi
from .project_scoped_list import resolve_project_filter_candidates, summary_matches_project_candidates


class ProjectStorageService:
    def __init__(
        self,
        *,
        api: ProjectStorageApi,
        settings: Settings,
        project_id_to_identifier: dict[int, str],
        resolve_project_ref: ProjectRefResolver,
    ) -> None:
        self._api = api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier
        self._resolve_project_ref = resolve_project_ref

    def _stamp(self, value: Any) -> Any:
        return hidden_fields.apply_hidden_fields("project_storage", value, settings=self._settings)

    async def list_project_storages(
        self, *, project: str | None = None, offset: int = 1, limit: int | None = None
    ) -> ProjectStorageListResult:
        access.ensure_read_enabled("project", settings=self._settings)
        effective_limit = _effective_limit(limit, settings=self._settings)
        project_candidates = await resolve_project_filter_candidates(
            project, resolve_project_ref=self._resolve_project_ref
        )

        # NB: the server ignores offset/pageSize for /api/v3/project_storages
        # and always returns the full collection -- fetch everything once
        # (bounded by max_results, not effective_limit), filter, then slice
        # locally instead of trusting a server-side page that never actually
        # happens.
        records, _server_total = await self._api.list_all(offset=1, page_size=self._settings.max_results)

        def _record_allowed(record: Any) -> bool:
            if not project_storage_payload_allowed(
                {"_links": {"project": record.project_link}},
                settings=self._settings,
                project_id_to_identifier=self._project_id_to_identifier,
            ):
                return False
            return project_candidates is None or summary_matches_project_candidates(record.summary, project_candidates)

        all_results = [self._stamp(record.summary) for record in records if _record_allowed(record)]
        page, total, next_offset, truncated = paginate_client(offset=offset, limit=effective_limit, results=all_results)
        return ProjectStorageListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(page),
            next_offset=next_offset,
            truncated=truncated,
            results=page,
        )

    async def get_project_storage(self, project_storage_id: int) -> ProjectStorageDetail:
        access.ensure_read_enabled("project", settings=self._settings)
        record = await self._api.get(project_storage_id)
        scope_policy.ensure_project_link_allowed(
            record.project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        return self._stamp(record.to_detail())
