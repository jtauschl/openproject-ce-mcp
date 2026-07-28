"""Application Service for the File Links domain (ADR 0001, OPM-318 first
consumer of `WorkPackageIdResolver`).

Depends on the `FileLinkApi` Protocol (never `HttpxFileLinkApi` concretely --
enforced by the architecture-boundary test), on `WorkPackageLookupApi`
directly, and on `WorkPackageIdResolver`. Three Protocol dependencies, not
one: `list_for_work_package`'s anchor-resolution goes through
`WorkPackageIdResolver` (the actual OPM-318 seam this migration proves out),
while `delete()`'s raw work-package-payload fetch goes through
`WorkPackageLookupApi.get()` directly rather than the resolver -- `delete()`
already has a concrete numeric work-package id (derived from the file link's
own container link, not a caller-supplied reference to resolve) and must
itself control the fail-closed behavior when that id is missing, which
`WorkPackageIdResolver`'s reference-resolution semantics don't cleanly serve.

No dedicated FileLinkResolver, no file_link_policy.py: `list()`'s scoping is
entirely delegated to `WorkPackageIdResolver` (read-check on the anchor work
package happens THERE, before the file-links sub-fetch); `delete()`'s scoping
is a direct `scope_policy.ensure_project_write_link_allowed` call against the
container work package's own project link.

No create/update: OpenProject's v3 API has no such endpoint for file links.
`delete()` is a single flat preview/commit method (same shape as
`GridService.delete()`/`BoardService.delete()`) -- no shared
`_write_outcome.py` state machine, since this domain has exactly one write
action.

Read/write scope reuses `"work_package"` (not a dedicated `"file_link"`
scope) -- verbatim behavior of client.py's `_ensure_read_enabled("work_package")`
/ `write_scope="work_package"` in the original `_finalize_delete` call.
"""

from __future__ import annotations

from ...config import Settings
from ...models import FileLinkListResult, FileLinkSummary, FileLinkWriteResult
from ..policies import access, hidden_fields
from ..policies import scope as scope_policy
from ..policies.scope import id_from_href
from ..ports.file_link_api import FileLinkApi
from ..ports.work_package_lookup_api import WorkPackageLookupApi
from ..ports.work_package_ref import WorkPackageIdResolver


class FileLinkService:
    def __init__(
        self,
        *,
        api: FileLinkApi,
        work_package_lookup_api: WorkPackageLookupApi,
        settings: Settings,
        project_id_to_identifier: dict[int, str],
        resolve_work_package_id: WorkPackageIdResolver,
    ) -> None:
        self._api = api
        self._work_package_lookup_api = work_package_lookup_api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier
        self._resolve_work_package_id = resolve_work_package_id

    def _stamp(self, summary: FileLinkSummary) -> FileLinkSummary:
        return hidden_fields.apply_hidden_fields("file_link", summary, settings=self._settings)

    async def list_for_work_package(self, work_package_id: int | str) -> FileLinkListResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        # Resolving the id already confirms the anchor work package itself is
        # allowed against OPENPROJECT_READ_PROJECTS before its file links are
        # fetched (verbatim behavior of client.py's original comment/order).
        resolved_id = await self._resolve_work_package_id(work_package_id, write=False)
        records = await self._api.list_for_work_package(resolved_id)
        results = [self._stamp(record.summary) for record in records]
        return FileLinkListResult(count=len(results), results=results)

    async def delete(self, file_link_id: int, *, confirm: bool = False) -> FileLinkWriteResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        record = await self._api.get(file_link_id)
        file_link = self._stamp(record.summary)

        container_href = record.container_link.get("href") if isinstance(record.container_link, dict) else None
        work_package_id = id_from_href(container_href)

        # Fail closed when the container cannot be resolved:
        # ensure_project_write_link_allowed(None) rejects unless write scope
        # is unconfigured / "*" -- verbatim behavior of client.py's original.
        if work_package_id:
            work_package_payload = await self._work_package_lookup_api.get(str(work_package_id))
            project_link = work_package_payload.get("_links", {}).get("project")
        else:
            project_link = None
        scope_policy.ensure_project_write_link_allowed(
            project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )

        if not confirm:
            return FileLinkWriteResult(
                action="delete",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject found the file link. Ask for confirmation, then call again with confirm=true to delete it.",
                file_link_id=file_link.id,
                work_package_id=work_package_id,
                validation_errors={},
                result=file_link,
            )

        access.ensure_write_enabled("work_package", settings=self._settings)
        await self._api.delete(file_link_id)
        return FileLinkWriteResult(
            action="delete",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="File link deleted successfully.",
            file_link_id=file_link.id,
            work_package_id=work_package_id,
            validation_errors={},
            result=None,
        )
