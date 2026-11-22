"""Application Service for the Work Package Activities domain.

Depends on the `ActivityApi` Protocol (never `HttpxActivityApi` concretely --
enforced by the architecture-boundary test) and `WorkPackageIdResolver` only
-- no `WorkPackageLookupApi` dependency, unlike File Links/Emoji Reactions/
Reminders/Attachments: nothing here derives a work-package id from another
resource's own link, the caller-supplied `work_package_id` reference is the
only input. Simplest Service among the work-package-reference-dependent
domains.

`WorkPackageIdResolver(ref, write=False)` confirms read access without
building and discarding a complete `WorkPackageDetail` (including its
hierarchy-filtering subroutine) just to check existence. A
non-existent/non-numeric reference surfaces the resolver's own enriched
`NotFoundError` hint message.

The resolver's anchor-resolution gates access to the work package (same
shape as File Links'/Emoji Reactions' `list_for_work_package`);
`activity_policy.details_allowed` decides whether the change details are
returned at all. No write path at all, so no `_write_outcome.py` question.

Slicing happens HERE, before normalization -- not in the Adapter: raw
elements are sliced to the most recent N BEFORE calling `to_summary`,
normalizing only the survivors. `ActivityApi.list_for_work_package` returns
`ActivityRecord`s carrying a LAZY `to_summary` callable rather than raw
dicts or pre-normalized summaries -- Services may not import from Adapters
(architecture-boundary rule), so normalization cannot happen here directly;
the lazy callable lets the Adapter own the HAL translation while the Service
still controls WHEN it runs. Normalizing every element first, then slicing,
would invert this slice-then-normalize order and do wasted/unsafe work on
elements about to be discarded.
"""

from __future__ import annotations

from collections.abc import Sequence

from ...config import Settings
from ...models import ActivityListResult, ActivitySummary
from ..pagination import effective_limit
from ..policies import access, activity_policy, hidden_fields
from ..ports.activity_api import ActivityApi, ActivityRecord
from ..ports.user_names import UserNames
from ..ports.work_package_ref import WorkPackageIdResolver
from ._error_masking import redacted_server_errors


@redacted_server_errors("activity")
class ActivityService:
    def __init__(
        self,
        *,
        api: ActivityApi,
        settings: Settings,
        resolve_work_package_id: WorkPackageIdResolver,
        user_names: UserNames,
    ) -> None:
        self._api = api
        self._settings = settings
        self._resolve_work_package_id = resolve_work_package_id
        self._user_names = user_names

    def _stamp(self, summary: ActivitySummary) -> ActivitySummary:
        return hidden_fields.apply_hidden_fields("activity", summary, settings=self._settings)

    async def _names_of(self, records: Sequence[ActivityRecord]) -> dict[int, str | None]:
        """The names of the users of `records`; none when `user` is a hidden activity field."""
        if hidden_fields.field_hidden("activity", "user", settings=self._settings):
            return {}
        return await self._user_names(
            list(dict.fromkeys(record.user_id for record in records if record.user_id is not None))
        )

    async def list_for_work_package(
        self, work_package_id: int | str, *, limit: int | None = None, text_limit: int | None = None
    ) -> ActivityListResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        resolved_id = await self._resolve_work_package_id(work_package_id, write=False)
        resolved_limit = effective_limit(limit, settings=self._settings)
        records = await self._api.list_for_work_package(resolved_id)
        # Return most recent first, bounded: slice to the last N elements,
        # then reverse. `to_summary` (the actual normalization) is called
        # only on the survivors, preserving slice-before-normalize order.
        sliced = records[-resolved_limit:]
        details = activity_policy.details_allowed(self._settings)
        names = await self._names_of(sliced)
        results = [
            self._stamp(
                record.to_summary(
                    text_limit, details=details, user=None if record.user_id is None else names.get(record.user_id)
                )
            )
            for record in reversed(sliced)
        ]
        return ActivityListResult(count=len(results), results=results)
