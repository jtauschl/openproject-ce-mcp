"""Application Service for the Backlog Buckets (Backlogs) domain.

Depends on the BacklogBucketApi Protocol, never HttpxBacklogBucketApi
concretely (enforced by the architecture-boundary test). No dedicated
BacklogBucketResolver: a `backlog_bucket_id` is always a numeric value
already validated by tools_sprints.py -- there is no semantic-reference resolution
for this domain to warrant a Resolver (mirrors Sprints/Views/Categories/Wiki
Pages).

Backlog Buckets shares the "project" read scope with Sprints/Projects/News/
Documents/Categories/Views/Grids -- no dedicated
OPENPROJECT_ENABLE_BACKLOG_BUCKET_* flag exists, so access.ensure_read_enabled
here uses scope="project" throughout.

Like Sprints, Backlog Buckets DOES need a dedicated Policy module
(backlog_bucket_policy.py): the allowlist check has two branches (embedded-
object vs. link), not one.

Two list methods, not one: `list()` hits the global `backlog_buckets`
endpoint (no project filter at all); `list_for_project()` hits the
project-scoped `projects/{id}/backlog_buckets` endpoint via a resolved
project id, but STILL filters client-side afterward -- a bucket shared into a
project via Backlogs sharing can be *defined* by a different, possibly
disallowed project.

NotFoundError rewrap ("Backlogs module" message) happens here, not in the
adapter -- mirrors the existing SprintService/ProjectService NotFoundError-
rewrap precedent.

Read-only domain: OpenProject's `backlog_buckets` API has no
Create/Update/Delete endpoint. Its `backlog_buckets_api.rb` and
`backlog_buckets_by_project_api.rb` route files
mount only Index/Show) -- unlike Sprints, this Service has no write-tool
integration to guard, so there is no confirm/preview-ordering concern here.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...models import BacklogBucketDetail, BacklogBucketListResult
from ..errors import NotFoundError
from ..pagination import clamp_limit, scan_records_and_paginate
from ..policies import access, hidden_fields
from ..policies.backlog_bucket_policy import backlog_bucket_payload_allowed, ensure_backlog_bucket_workspace_allowed
from ..ports.backlog_bucket_api import BacklogBucketApi, BacklogBucketRecord
from ..ports.project_ref import ProjectRefResolver
from ..ports.project_resolution import ProjectResolutionContext


class BacklogBucketService:
    def __init__(
        self,
        *,
        api: BacklogBucketApi,
        settings: Settings,
        project_id_to_identifier: dict[int, str],
        resolve_project_ref: ProjectRefResolver,
    ) -> None:
        self._api = api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier
        self._resolve_project_ref = resolve_project_ref

    def _stamp(self, value: Any) -> Any:
        return hidden_fields.apply_hidden_fields("backlog_bucket", value, settings=self._settings)

    def _allowed(self, record: BacklogBucketRecord) -> bool:
        return backlog_bucket_payload_allowed(
            defining_workspace_payload=record.defining_workspace_payload,
            defining_workspace_link=record.defining_workspace_link,
            settings=self._settings,
            project_id_to_identifier=self._project_id_to_identifier,
        )

    def _item_allowed(self, record: BacklogBucketRecord, *, search: str | None) -> bool:
        if not self._allowed(record):
            return False
        if search is None:
            return True
        return search.casefold() in (record.summary.name or "").casefold()

    def _to_result(
        self, raw_items: list[BacklogBucketRecord], *, truncated: bool, offset: int, limit: int
    ) -> BacklogBucketListResult:
        results = [self._stamp(record.summary) for record in raw_items]
        total = len(results)
        return BacklogBucketListResult(
            offset=offset,
            limit=limit,
            total=total,
            count=total,
            next_offset=offset + 1 if truncated else None,
            truncated=truncated,
            results=results,
        )

    async def list(
        self,
        *,
        search: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> BacklogBucketListResult:
        access.ensure_read_enabled("project", settings=self._settings)
        effective_limit = clamp_limit(
            limit,
            default_page_size=self._settings.default_page_size,
            max_page_size=self._settings.max_page_size,
            max_results=self._settings.max_results,
        )
        try:
            # Scan server pages rather than a single fetch capped at
            # settings.max_results, which would silently hide any backlog
            # bucket beyond that cap once the endpoint's real result count
            # exceeds it.
            raw_items, truncated = await scan_records_and_paginate(
                lambda o, ps: self._api.list_all(offset=o, page_size=ps),
                item_allowed=lambda record: self._item_allowed(record, search=search),
                server_page_size=self._settings.max_page_size,
                offset=offset,
                limit=effective_limit,
                key=lambda r: r.summary.id,
            )
        except NotFoundError as exc:
            raise NotFoundError(
                "OpenProject backlog buckets require the Backlogs module and OpenProject 17.6 or newer."
            ) from exc
        return self._to_result(raw_items, truncated=truncated, offset=offset, limit=effective_limit)

    async def list_for_project(
        self,
        project: str,
        *,
        search: str | None = None,
        offset: int = 1,
        limit: int | None = None,
        context: ProjectResolutionContext | None = None,
    ) -> BacklogBucketListResult:
        access.ensure_read_enabled("project", settings=self._settings)
        effective_limit = clamp_limit(
            limit,
            default_page_size=self._settings.default_page_size,
            max_page_size=self._settings.max_page_size,
            max_results=self._settings.max_results,
        )
        project_payload = await self._resolve_project_ref(project, write=False, context=context)
        project_id = int(project_payload["id"])
        try:
            # Even though this is project-scoped, results are still filtered
            # client-side (a bucket shared into this project can be *defined*
            # by a different, possibly disallowed project), so a full scan of
            # server pages is required -- a single bounded fetch would
            # silently hide any backlog bucket beyond that cap.
            raw_items, truncated = await scan_records_and_paginate(
                lambda o, ps: self._api.list_for_project(project_id, offset=o, page_size=ps),
                item_allowed=lambda record: self._item_allowed(record, search=search),
                server_page_size=self._settings.max_page_size,
                offset=offset,
                limit=effective_limit,
                key=lambda r: r.summary.id,
            )
        except NotFoundError as exc:
            raise NotFoundError(
                "OpenProject project backlog buckets require the Backlogs module and OpenProject 17.6 or newer."
            ) from exc
        return self._to_result(raw_items, truncated=truncated, offset=offset, limit=effective_limit)

    async def get(self, backlog_bucket_id: int) -> BacklogBucketDetail:
        access.ensure_read_enabled("project", settings=self._settings)
        try:
            record = await self._api.get(backlog_bucket_id)
        except NotFoundError as exc:
            raise NotFoundError(
                "OpenProject backlog bucket not found, or the Backlogs module / backlog bucket API is unavailable."
            ) from exc
        ensure_backlog_bucket_workspace_allowed(
            defining_workspace_payload=record.defining_workspace_payload,
            defining_workspace_link=record.defining_workspace_link,
            settings=self._settings,
            project_id_to_identifier=self._project_id_to_identifier,
        )
        return self._stamp(record.detail)
