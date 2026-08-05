"""Work Package Activities Domain API port.

Get-only, single-anchor domain (a work package's own activity feed), no list
endpoint of its own to diverge from and no separate Detail model: a get-only,
no-list domain has exactly one method and one result shape, no separate
summary/detail split at all.

`ActivityRecord.to_summary` is a LAZY callable (`Callable[[int | None],
ActivitySummary]`, parameterized by `text_limit`), not an eager field: the
Service (not the Adapter) slices to the most recent N elements BEFORE any
normalization happens (`elements[-effective_limit:]`, then `normalize_activity`
only on the survivors) -- an eager field would force `normalize_activity`
(real work: formattable-text extraction, details-array truncation) to run on
every element the Service is about to discard, silently inverting that
order. Services may not import from Adapters (architecture-boundary rule),
so the lazy callable -- not a raw dict the Service would have to normalize
itself -- is how the HAL->model translation stays entirely inside the
Adapter while still letting the Service control WHEN it runs; the same
shape `ReminderRecord.summary` uses.

`to_record`/`get_raw` support comment-posting: `add_work_package_comment`
normalizes a just-posted comment's raw activity payload and fetches a
fallback single activity by id (the `_fill_missing_activity_user`
best-effort pattern) -- both reuse this Port/Adapter instead of a duplicated
normalizer on `WorkPackageApi`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from ...models import ActivitySummary


@dataclass(frozen=True)
class ActivityRecord:
    to_summary: Callable[[int | None], ActivitySummary]


class ActivityApi(Protocol):
    """Narrow, Activities-only Domain API port. ActivityService and
    WorkPackageService both depend on this Protocol, never on
    HttpxActivityApi concretely (enforced by the architecture-boundary
    test).
    """

    async def list_for_work_package(self, work_package_id: int) -> list[ActivityRecord]: ...

    def to_record(self, payload: dict[str, Any]) -> ActivityRecord:
        """Pure, synchronous wrap of an already-fetched raw activity payload
        (e.g. the response of a comment-posting POST) into an `ActivityRecord`
        -- no HTTP call. Exists as a Protocol method (not a bare module-level
        function) so a Service depends only on the `ActivityApi` Protocol,
        never importing the concrete adapter's `normalize_activity` directly.
        """
        ...

    async def get_raw(self, activity_id: int) -> dict[str, Any]:
        """Raw, unnormalized GET `activities/{activity_id}` -- used by the
        `_fill_missing_activity_user` best-effort fallback fetch, which only
        reads `_links.user` off the result. Lets errors propagate; the one
        caller that needs a catch-and-log-and-continue behavior does so
        itself, rather than this method swallowing errors for every caller.
        """
        ...
