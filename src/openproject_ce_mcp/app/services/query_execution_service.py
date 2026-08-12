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

from ...config import Settings
from ...models import WorkPackageListResult, WorkPackageSummary
from ..pagination import effective_limit, fetch_bounded_and_paginate
from ..policies import access, hidden_fields
from ..policies.work_package_policy import work_package_payload_allowed
from ..ports.query_execution_api import QueryExecutionApi
from ..ports.work_package_api import WorkPackageApi


class QueryExecutionService:
    def __init__(
        self,
        *,
        api: QueryExecutionApi,
        work_package_api: WorkPackageApi,
        settings: Settings,
        project_id_to_identifier: dict[int, str],
    ) -> None:
        self._api = api
        self._work_package_api = work_package_api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier

    async def execute(self, query_id: int, *, offset: int = 1, limit: int | None = None) -> WorkPackageListResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        effective = effective_limit(limit, settings=self._settings)

        async def _fetch_page(server_offset: int, page_size: int) -> dict:
            page = await self._api.execute(query_id, offset=server_offset, page_size=page_size)
            return {"_embedded": {"elements": page.raw_elements}}

        async def _item_allowed(raw: dict) -> bool:
            return work_package_payload_allowed(
                raw, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
            )

        def _normalize(raw: dict) -> WorkPackageSummary:
            record = self._work_package_api.to_record(raw, text_limit=self._settings.text_limit)
            return hidden_fields.apply_hidden_fields("work_package", record.summary, settings=self._settings)

        results, total, next_offset, truncated = await fetch_bounded_and_paginate(
            fetch_page=_fetch_page,
            normalize=_normalize,
            item_allowed=_item_allowed,
            server_page_size=self._settings.max_page_size,
            offset=offset,
            limit=effective,
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
