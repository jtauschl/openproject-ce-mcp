"""Application Service for the Revisions domain.

Depends on the `RevisionApi` Protocol (never `HttpxRevisionApi` concretely --
enforced by the architecture-boundary test) and on `WorkPackageIdResolver`.

`list_for_work_package()` resolves the anchor work package through the usual
read check first, then still filters each revision by its own project link:
a revision is linked to work packages by a commit message, so nothing
guarantees it lives in the work package's project. `get()` checks the one
revision's project link directly.

Read scope reuses `"work_package"`: revisions are only reachable through the
work packages they reference.
"""

from __future__ import annotations

from ...config import Settings
from ...models import RevisionListResult, RevisionSummary
from ..policies import access, hidden_fields
from ..policies import scope as scope_policy
from ..ports.revision_api import RevisionApi, RevisionRecord
from ..ports.work_package_ref import WorkPackageIdResolver


class RevisionService:
    def __init__(
        self,
        *,
        api: RevisionApi,
        settings: Settings,
        project_id_to_identifier: dict[int, str],
        resolve_work_package_id: WorkPackageIdResolver,
    ) -> None:
        self._api = api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier
        self._resolve_work_package_id = resolve_work_package_id

    def _stamp(self, summary: RevisionSummary) -> RevisionSummary:
        return hidden_fields.apply_hidden_fields("revision", summary, settings=self._settings)

    def _project_readable(self, record: RevisionRecord) -> bool:
        def ensure() -> None:
            scope_policy.ensure_project_link_allowed(
                record.project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
            )

        return scope_policy.payload_allowed(ensure)

    async def list_for_work_package(self, work_package_id: int | str) -> RevisionListResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        resolved_id = await self._resolve_work_package_id(work_package_id, write=False)
        records = await self._api.list_for_work_package(resolved_id)
        results = [self._stamp(record.summary) for record in records if self._project_readable(record)]
        return RevisionListResult(count=len(results), results=results)

    async def get(self, revision_id: int) -> RevisionSummary:
        access.ensure_read_enabled("work_package", settings=self._settings)
        record = await self._api.get(revision_id)
        scope_policy.ensure_project_link_allowed(
            record.project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        return self._stamp(record.summary)
