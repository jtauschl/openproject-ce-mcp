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
    adds exactly one extra field (`links`, a cheap `sorted(dict.keys())` over
    the already-fetched payload) -- there is no second/different truncation
    limit applied to any field, unlike Documents' description, and next to
    nothing is computed that `list()`'s own callers never read. Provided
    `detail` is built from `summary`, not by re-running `normalize_view` on
    the raw payload a second time (an earlier version of the adapter did
    that; fixed during the Sprints migration's step-6 efficiency audit,
    which found the same bug in this file too), the marginal per-row cost of
    eager computation here really is close to free -- unlike BoardRecord's
    otherwise-identical-looking eager `detail` (group_by/columns/sort_by/
    highlighted_attributes/filters each parse their own HAL link), where an
    independent Codex review correctly distinguished "safe" from "free."

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

    async def list_all(self, *, offset: int, page_size: int) -> tuple[list[ViewRecord], int]: ...
    async def get(self, view_id: int) -> ViewRecord: ...
