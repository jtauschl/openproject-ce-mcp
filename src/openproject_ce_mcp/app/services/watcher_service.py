"""Application Service for the Watchers domain (ADR 0001).

Depends on the `WatcherApi` Protocol (never `HttpxWatcherApi` concretely --
enforced by the architecture-boundary test) and on `WorkPackageIdResolver`.
Unlike File Links (which needed a second Port for `delete()`'s raw-payload
fetch, because the id there was already a concrete int derived from a
container link, not a caller-supplied reference), Watchers' `add`/`remove`
both take a genuine caller-supplied work-package reference that needs
resolving -- a cleaner fit for `WorkPackageIdResolver(ref, write=True)` than
File Links had: `resolve_id` already fetches the work package and enforces
the WRITE allowlist against its project link, replacing client.py's
hand-rolled `_work_package_ref` + manual `_get` + `_ensure_project_write_link_allowed`
chain with a single seam call.

No `to_detail`, no Policy module: `list()`'s scoping is entirely delegated to
`WorkPackageIdResolver` (read-scoped); `add()`/`remove()`'s scoping is
entirely delegated to the same seam (write-scoped). Neither method filters a
list of records against a per-record project-link predicate.

`add()` and `remove()` each stay a single flat method (not the shared
`_write_outcome.py` state machine), modeled on `ProjectService.set_favorite`'s
no-form toggle shape: their preview payloads are NOT symmetric (`add`'s
preview needs a real `WatcherSummary`, fetched via a user lookup; `remove`'s
preview has `result=None`), which the generic `_finalize_write` (always
`detail=None` in preview) doesn't fit.

Read/write scope reuses `"work_package"` (not a dedicated `"watcher"` scope)
-- verbatim behavior of client.py's `_ensure_read_enabled("work_package")` /
`_ensure_write_enabled("work_package")` calls.
"""

from __future__ import annotations

from ...config import Settings
from ...models import WatcherListResult, WatcherSummary, WatcherWriteResult
from ..policies import access, hidden_fields
from ..ports.watcher_api import WatcherApi
from ..ports.work_package_ref import WorkPackageIdResolver


class WatcherService:
    def __init__(
        self,
        *,
        api: WatcherApi,
        settings: Settings,
        resolve_work_package_id: WorkPackageIdResolver,
    ) -> None:
        self._api = api
        self._settings = settings
        self._resolve_work_package_id = resolve_work_package_id

    def _stamp(self, summary: WatcherSummary) -> WatcherSummary:
        return hidden_fields.apply_hidden_fields("watcher", summary, settings=self._settings)

    async def list_for_work_package(self, work_package_id: int | str) -> WatcherListResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        # Resolving the id already confirms the anchor work package itself is
        # allowed against OPENPROJECT_READ_PROJECTS before its watchers are
        # fetched (verbatim behavior of client.py's original comment/order).
        resolved_id = await self._resolve_work_package_id(work_package_id, write=False)
        summaries = await self._api.list_for_work_package(resolved_id)
        results = [self._stamp(summary) for summary in summaries]
        return WatcherListResult(count=len(results), results=results)

    async def add(self, work_package_id: int | str, user_id: int, *, confirm: bool = False) -> WatcherWriteResult:
        # write=True enforces OPENPROJECT_WRITE_PROJECTS against the resolved
        # work package's own project, before any preview or mutation --
        # verbatim behavior of client.py's original (which fetched the work
        # package and checked its project link unconditionally, even on a
        # confirm=False preview call).
        resolved_id = await self._resolve_work_package_id(work_package_id, write=True)
        if not confirm:
            watcher = self._stamp(await self._api.get_user(user_id))
            return WatcherWriteResult(
                action="add",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject is ready to add the watcher. Ask for confirmation, then call again with confirm=true.",
                work_package_id=resolved_id,
                watcher_user_id=user_id,
                validation_errors={},
                result=watcher,
            )
        access.ensure_write_enabled("work_package", settings=self._settings)
        watcher = self._stamp(await self._api.add(resolved_id, user_id))
        return WatcherWriteResult(
            action="add",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Watcher added successfully.",
            work_package_id=resolved_id,
            watcher_user_id=user_id,
            validation_errors={},
            result=watcher,
        )

    async def remove(self, work_package_id: int | str, user_id: int, *, confirm: bool = False) -> WatcherWriteResult:
        resolved_id = await self._resolve_work_package_id(work_package_id, write=True)
        if not confirm:
            return WatcherWriteResult(
                action="remove",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject is ready to remove the watcher. Ask for confirmation, then call again with confirm=true.",
                work_package_id=resolved_id,
                watcher_user_id=user_id,
                validation_errors={},
                result=None,
            )
        access.ensure_write_enabled("work_package", settings=self._settings)
        await self._api.remove(resolved_id, user_id)
        return WatcherWriteResult(
            action="remove",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Watcher removed successfully.",
            work_package_id=resolved_id,
            watcher_user_id=user_id,
            validation_errors={},
            result=None,
        )
