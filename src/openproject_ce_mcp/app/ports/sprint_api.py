"""Sprints (Backlogs) Domain API port (ADR 0001) -- narrow, no universal gateway."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ...models import SprintDetail, SprintSummary


@dataclass(frozen=True)
class SprintRecord:
    """One sprint as read from the API: `summary`, a precomputed `detail`, and
    the raw `definingWorkspace` HAL link the Policy layer needs for allowlist
    checks.

    `detail` is precomputed, not a lazy `to_detail` thunk: SprintDetail is a bare
    subclass of SprintSummary with zero added fields and no second/different
    truncation limit -- mirrors ViewRecord's reasoning (an even stronger case
    for eager computation than Views' one-extra-field detail). It is built via
    `httpx_sprint_api.summary_to_detail(summary)` -- a field copy off the
    already-normalized `summary`, mirroring `version_api.summary_to_detail` --
    not by re-running `normalize_sprint` on the raw payload a second time (the
    adapter's first version did this and was fixed during this domain's own
    step-6 efficiency audit, which found the identical bug pre-existing in
    `httpx_view_api.py` too).

    `defining_workspace_link` carries the raw link (mirrors ViewRecord/DocumentRecord/
    MembershipRecord's `project_link`) because the allowlist Policy check needs the
    raw href/id, which neither normalized model carries. Unlike Views' `project_link`,
    this is synthesized by the adapter when only an `_embedded.definingWorkspace`
    object (no top-level `_links.definingWorkspace`) is present on the raw payload --
    verbatim port of client.py's `_sprint_workspace_link` fallback.

    `defining_workspace_payload` carries the raw `_embedded.definingWorkspace` object
    when present (None otherwise) -- the Policy layer's embedded-object allowlist
    branch needs this full payload (it can carry an `identifier` the synthesized
    link never has), not just the link. See `sprint_policy.ensure_sprint_workspace_allowed`.

    `lookup_name` carries the raw payload's `name` field, independent of
    `summary.name`. `normalize_sprint` falls back to a synthetic display name
    (`f"Sprint {id}"`) when the raw name is blank/missing -- correct DISPLAY
    behavior, but wrong for exact-name RESOLUTION (`SprintResolver` must not
    let a caller's literal search for "Sprint 7" accidentally match a sprint
    whose real name was blank). `lookup_name` is never synthesized, so
    `SprintResolver` compares against it instead of `summary.name`.
    """

    summary: SprintSummary
    detail: SprintDetail
    defining_workspace_link: dict[str, Any] | None
    defining_workspace_payload: dict[str, Any] | None
    lookup_name: str


class SprintApi(Protocol):
    """Narrow, Sprints-only Domain API port. SprintService depends on this
    Protocol, never on HttpxSprintApi concretely (enforced by the
    architecture-boundary test).

    Read-only: no commit_create/update/delete methods exist on this Protocol --
    client.py has no write path for sprints (sprint assignment happens via
    work-package writes, not here).

    Two list methods, not one, unlike every other read-only migrated domain so
    far: `list_all` hits the global `sprints` endpoint (client-side allowlist +
    search filtering only, no project scoping at the request level).
    `list_for_project` hits the project-scoped `projects/{id}/sprints` endpoint
    (server-scoped by project, but STILL requires client-side allowlist
    filtering afterward -- a sprint's defining workspace can differ from the
    project it was shared into via Backlogs sharing).
    """

    async def list_all(self, *, offset: int, page_size: int) -> tuple[list[SprintRecord], int]: ...
    async def list_for_project(
        self, project_id: int, *, offset: int, page_size: int
    ) -> tuple[list[SprintRecord], int]: ...

    async def get(self, sprint_id: int) -> SprintRecord: ...
