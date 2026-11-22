"""Application Service for executing a saved OpenProject Query and returning
its resolved work packages.

Depends on the `QueryExecutionApi` Protocol (never `HttpxQueryExecutionApi`
concretely -- enforced by the architecture-boundary test) AND on the
`WorkPackageApi` Protocol from the Work Packages domain, injected the same
way -- normalizing each raw element via `WorkPackageApi.to_record()` rather
than importing `normalize_work_package_summary` from
`httpx_work_package_api.py` directly, which would be a forbidden
Service->Adapter dependency. Matches `WorkPackageService`'s own precedent of
depending on a sibling domain's Port directly (`activity_api`, for
`add_comment()`'s reuse of the Activities normalizer) rather than
duplicating that domain's normalization logic -- `to_record()` exists as a
Protocol method (not a module-level function) specifically to make this kind
of cross-domain reuse safe (see its docstring in `app/ports/work_package_api.py`).

Security-critical: OpenProject executes the query with the API token's full
server-side permissions, NOT scoped to this MCP's own
OPENPROJECT_READ_PROJECTS allowlist -- a query can return work packages from
projects the caller cannot otherwise see through this MCP. This Service
therefore:
  1. Never trusts the raw server-reported total (would leak match-existence
     in disallowed projects).
  2. Scans server pages (via `app/pagination.fetch_bounded_and_paginate`,
     the same early-stopping "collect limit+1 allowed items" shape every
     other allowlist-filtered list domain uses) rather than filtering only
     the single requested page -- a single-page filter would silently
     under-report results whenever allowed matches land beyond that page
     (the exact bug class documented for WorkPackageService's own
     _list_collection_scanned).
  3. Applies `work_package_policy.work_package_payload_allowed` to each raw
     element BEFORE normalization, mirroring Work Packages' own list() order.
"""

from __future__ import annotations

from collections.abc import Mapping

from ...config import Settings
from ...models import WorkPackageListResult
from ..pagination import effective_limit, fetch_bounded_and_paginate
from ..policies import access
from ..policies.work_package_policy import work_package_payload_allowed
from ..ports.query_execution_api import QueryExecutionApi
from ..ports.scoped_reference import ScopedReferencesAllowedBulkCheck
from ..ports.work_package_api import WorkPackageApi, WorkPackageRecord
from ..ports.work_package_ref import WorkPackageProjectAllowedBulkCheck
from ._error_masking import redacted_server_errors
from ._work_package_presentation import present_summaries


@redacted_server_errors("work_package")
class QueryExecutionService:
    def __init__(
        self,
        *,
        api: QueryExecutionApi,
        work_package_api: WorkPackageApi,
        settings: Settings,
        project_id_to_identifier: Mapping[int, str],
        work_package_project_allowed_bulk: WorkPackageProjectAllowedBulkCheck,
        references_allowed: ScopedReferencesAllowedBulkCheck,
        api_prefix: str,
    ) -> None:
        self._api = api
        self._work_package_api = work_package_api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier
        self._work_package_project_allowed_bulk = work_package_project_allowed_bulk
        self._references_allowed = references_allowed
        self._api_prefix = api_prefix

    async def execute(self, query_id: int, *, offset: int = 1, limit: int | None = None) -> WorkPackageListResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        effective = effective_limit(limit, settings=self._settings)
        if not self._settings.read_projects:
            # Nothing can ever be allowed with an empty allowlist -- skip the
            # round trip entirely, matching WorkPackageService.list()'s own
            # fast path for the same condition.
            return WorkPackageListResult(
                offset=offset, limit=effective, total=0, count=0, next_offset=None, truncated=False, results=[]
            )

        async def _fetch_page(server_offset: int, page_size: int) -> dict:
            page = await self._api.execute(query_id, offset=server_offset, page_size=page_size)
            return {"total": page.server_total, "_embedded": {"elements": page.raw_elements}}

        async def _item_allowed(raw: dict) -> bool:
            return work_package_payload_allowed(
                raw, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
            )

        def _normalize(raw: dict) -> WorkPackageRecord:
            return self._work_package_api.to_record(raw, text_limit=self._settings.text_limit)

        records, total, next_offset, truncated = await fetch_bounded_and_paginate(
            fetch_page=_fetch_page,
            normalize=_normalize,
            item_allowed=_item_allowed,
            server_page_size=self._settings.max_page_size,
            offset=offset,
            limit=effective,
        )
        results = await present_summaries(
            records,
            settings=self._settings,
            api_prefix=self._api_prefix,
            project_allowed_bulk=self._work_package_project_allowed_bulk,
            references_allowed=self._references_allowed,
        )
        return WorkPackageListResult(
            offset=offset,
            limit=effective,
            total=total,
            count=total,
            next_offset=next_offset,
            truncated=truncated,
            results=results,
        )
