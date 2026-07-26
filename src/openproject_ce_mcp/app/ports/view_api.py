"""Views Domain API port (ADR 0001) -- narrow, no universal gateway."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ...models import ViewDetail, ViewSummary


@dataclass(frozen=True)
class ViewRecord:
    """One view as read from the API: `summary`, a precomputed `detail`, and
    the raw `project` HAL link (nullable -- a view need not belong to a
    project at all).

    `detail` is precomputed, not a lazy `to_detail` thunk: `summary_to_detail`
    reuses every field from the already-normalized `summary` verbatim and
    adds exactly one extra field (`links`) -- there is no second/different
    truncation limit applied to any field, unlike Documents' description. No
    expensive divergent re-extraction exists to defer, so eager computation
    here wastes nothing -- provided `detail` is built from `summary`, not by
    re-running `normalize_view` on the raw payload a second time (an earlier
    version of the adapter did that; fixed during the Sprints migration's
    step-6 efficiency audit, which found the same bug in this file too).

    `project_link` must be carried separately (mirrors DocumentRecord/
    MembershipRecord) because the allowlist Policy check needs the raw link
    (href/id), which neither normalized model carries. It may be None -- an
    individual view's project link is optional, unlike every other migrated
    domain's project-scoped record so far.
    """

    summary: ViewSummary
    detail: ViewDetail
    project_link: dict[str, Any] | None


class ViewApi(Protocol):
    """Narrow, Views-only Domain API port. ViewService depends on this
    Protocol, never on HttpxViewApi concretely (enforced by the
    architecture-boundary test).

    Read-only: no commit_create/update/delete methods exist on this
    Protocol -- client.py has no write path for views.
    """

    async def list_all(self, *, page_size: int) -> list[ViewRecord]: ...
    async def get(self, view_id: int) -> ViewRecord: ...
