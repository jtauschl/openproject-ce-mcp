"""Backlog Buckets (Backlogs) Domain API port -- narrow, no universal gateway."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ...models import BacklogBucketDetail, BacklogBucketSummary


@dataclass(frozen=True)
class BacklogBucketRecord:
    """One backlog bucket as read from the API: `summary`, a precomputed
    `detail`, and the raw `definingWorkspace` HAL link the Policy layer needs
    for allowlist checks.

    `detail` is precomputed, not a lazy `to_detail` thunk: BacklogBucketDetail
    is a bare subclass of BacklogBucketSummary with zero added fields and no
    second/different truncation limit -- mirrors SprintRecord's reasoning. It
    is built via `httpx_backlog_bucket_api.summary_to_detail(summary)` -- a
    field copy off the already-normalized `summary`, mirroring
    `httpx_sprint_api.summary_to_detail` -- not by re-running
    `normalize_backlog_bucket` on the raw payload a second time.

    `defining_workspace_link` carries the raw link (mirrors SprintRecord's
    field of the same name) because the allowlist Policy check needs the raw
    href/id, which neither normalized model carries. Like Sprints, this is
    synthesized by the adapter when only an `_embedded.definingWorkspace`
    object (no top-level `_links.definingWorkspace`) is present on the raw
    payload -- the `BacklogBucketRepresenter` uses the same
    `API::V3::Workspaces::LinkedResource#associated_project` helper Sprints'
    representer uses in OpenProject's source.

    `defining_workspace_payload` carries the raw `_embedded.definingWorkspace`
    object when present (None otherwise) -- the Policy layer's embedded-object
    allowlist branch needs this full payload (it can carry an `identifier` the
    synthesized link never has), not just the link. See
    `backlog_bucket_policy.ensure_backlog_bucket_workspace_allowed`.

    `lookup_name` carries the raw payload's `name` field, independent of
    `summary.name`. `normalize_backlog_bucket` falls back to a synthetic
    display name (`f"Backlog Bucket {id}"`) when the raw name is
    blank/missing -- correct DISPLAY behavior, but this domain has no
    name-based resolver today, so `lookup_name` exists only for parity with
    SprintRecord's shape (kept in case a resolver is added later).
    """

    summary: BacklogBucketSummary
    detail: BacklogBucketDetail
    defining_workspace_link: dict[str, Any] | None
    defining_workspace_payload: dict[str, Any] | None
    lookup_name: str


class BacklogBucketApi(Protocol):
    """Narrow, Backlog-Buckets-only Domain API port. BacklogBucketService
    depends on this Protocol, never on HttpxBacklogBucketApi concretely
    (enforced by the architecture-boundary test).

    Read-only: no commit_create/update/delete methods exist on this
    Protocol -- OpenProject's `backlog_buckets` API mounts only Index (global
    and project-scoped) and Show (global-only); OpenProject's
    `backlog_buckets_api.rb` and `backlog_buckets_by_project_api.rb`
    neither file defines a Create/Update/Delete endpoint.

    Two list methods, not one, mirroring Sprints: `list_all` hits the global
    `backlog_buckets` endpoint (client-side allowlist + search filtering
    only, no project scoping at the request level). `list_for_project` hits
    the project-scoped `projects/{id}/backlog_buckets` endpoint (server-scoped
    by project, but STILL requires client-side allowlist filtering afterward
    -- a bucket's defining workspace can differ from the project it was
    shared into, same as Sprints).
    """

    async def list_all(self, *, offset: int, page_size: int) -> tuple[list[BacklogBucketRecord], int]: ...
    async def list_for_project(
        self, project_id: int, *, offset: int, page_size: int
    ) -> tuple[list[BacklogBucketRecord], int]: ...

    async def get(self, backlog_bucket_id: int) -> BacklogBucketRecord: ...
