"""Work Package Activities Domain API port (ADR 0001).

Get-only, single-anchor domain (a work package's own activity feed), no list
endpoint of its own to diverge from and no separate Detail model -- the
runbook's own explicit carve-out for "a get-only, no-list domain has exactly
one method and one result shape, no separate summary/detail split at all."

`ActivityRecord.to_summary` is a LAZY callable (`Callable[[int | None],
ActivitySummary]`, parameterized by `text_limit`), not an eager field: the
Service (not the Adapter) slices to the most recent N elements BEFORE any
normalization happens, matching client.py's original order
(`elements[-effective_limit:]`, then `normalize_activity` only on the
survivors) -- an eager field would force `normalize_activity` (real work:
formattable-text extraction, details-array truncation) to run on every
element the Service is about to discard, silently inverting that order (the
same eager-vs-lazy mistake class the Reminders migration hit at its own
`list()` level). Services may not import from Adapters (architecture-boundary
rule), so the lazy callable -- not a raw dict the Service would have to
normalize itself -- is how the HAL->model translation stays entirely inside
the Adapter while still letting the Service control WHEN it runs; the same
shape `ReminderRecord.summary` already established.

NOTE: `client.py`'s own `normalize_activity`/`ACTIVITY_DETAILS_LIMIT` are NOT
deleted by this migration -- `add_work_package_comment` (a still-flat,
separate write path, out of this migration's scope) also calls
`self.normalize_activity` directly to build its write-echo result. The
Adapter's copy here is verified byte-identical to that still-live original
at migration time; both copies coexist until Work Packages' own eventual
migration removes the last caller of the client.py version.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from ...models import ActivitySummary


@dataclass(frozen=True)
class ActivityRecord:
    to_summary: Callable[[int | None], ActivitySummary]


class ActivityApi(Protocol):
    """Narrow, Activities-only Domain API port. ActivityService depends on
    this Protocol, never on HttpxActivityApi concretely (enforced by the
    architecture-boundary test).
    """

    async def list_for_work_package(self, work_package_id: int) -> list[ActivityRecord]: ...
