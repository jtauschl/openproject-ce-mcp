"""Application Service for the Work Package Activities domain.

Depends on the `ActivityApi` Protocol (never `HttpxActivityApi` concretely --
enforced by the architecture-boundary test) and `WorkPackageIdResolver` only
-- no `WorkPackageLookupApi` dependency, unlike File Links/Emoji Reactions/
Reminders/Attachments: nothing here derives a work-package id from another
resource's own link, the caller-supplied `work_package_id` reference is the
only input. Simplest Service among the work-package-reference-dependent
domains.

`WorkPackageIdResolver(ref, write=False)` replaces client.py's original
discard-the-result existence check (a full `get_work_package(...)` call,
building and throwing away a complete `WorkPackageDetail` including its
hierarchy-filtering subroutine, just to confirm read access) -- the same
unplanned efficiency win the Emoji Reactions migration found for
`list_work_package_reactions`. A non-existent/non-numeric reference now
surfaces the resolver's own enriched `NotFoundError` hint message instead of
`get_work_package`'s original 404 mapping -- already precedented twice
(File Links, Watchers) without being separately flagged as a risk.

No Policy module, no project-scoping infra of its own: the resolver's
anchor-resolution IS the entire enforcement surface (same shape as File
Links'/Emoji Reactions' `list_for_work_package`). No write path at all, so
no `_write_outcome.py` question.

Slicing happens HERE, before normalization -- not in the Adapter. client.py's
original slices raw elements to the most recent N BEFORE calling
`normalize_activity`, normalizing only the survivors. `ActivityApi.
list_for_work_package` returns `ActivityRecord`s carrying a LAZY `to_summary`
callable rather than raw dicts or pre-normalized summaries -- Services may
not import from Adapters (architecture-boundary rule), so normalization
cannot happen here directly; the lazy callable lets the Adapter own the HAL
translation while the Service still controls WHEN it runs, avoiding the
same eager-vs-lazy mistake class the Reminders migration hit at its own
list() level (normalizing every element first, then slicing, would invert
the original's slice-then-normalize order and do wasted/unsafe work on
elements about to be discarded).
"""

from __future__ import annotations

from ...config import Settings
from ...models import ActivityListResult, ActivitySummary
from ..pagination import effective_limit
from ..policies import access, hidden_fields
from ..ports.activity_api import ActivityApi
from ..ports.work_package_ref import WorkPackageIdResolver


class ActivityService:
    def __init__(
        self,
        *,
        api: ActivityApi,
        settings: Settings,
        resolve_work_package_id: WorkPackageIdResolver,
    ) -> None:
        self._api = api
        self._settings = settings
        self._resolve_work_package_id = resolve_work_package_id

    def _stamp(self, summary: ActivitySummary) -> ActivitySummary:
        return hidden_fields.apply_hidden_fields("activity", summary, settings=self._settings)

    async def list_for_work_package(
        self, work_package_id: int | str, *, limit: int | None = None, text_limit: int | None = None
    ) -> ActivityListResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        resolved_id = await self._resolve_work_package_id(work_package_id, write=False)
        resolved_limit = effective_limit(limit, settings=self._settings)
        records = await self._api.list_for_work_package(resolved_id)
        # Return most recent first, bounded -- verbatim of client.py's
        # original `elements[-effective_limit:]` then `reversed(...)`.
        # `to_summary` (the actual normalization) is called only on the
        # survivors, matching the original's slice-before-normalize order.
        sliced = records[-resolved_limit:]
        results = [self._stamp(record.to_summary(text_limit)) for record in reversed(sliced)]
        return ActivityListResult(count=len(results), results=results)
