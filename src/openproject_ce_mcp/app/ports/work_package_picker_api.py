"""Work Package Pickers Domain API port.

Read-only lookups OpenProject offers for filling one slot of a work package:
who can be assigned (per work package, or per project for a work package not
created yet), who can watch it, which projects it can be moved to, and which
work packages can be the other end of a new relation. Each is a single
unpaginated collection endpoint, so each Port method returns a plain list.

Projects and relation candidates come back as `(summary, raw payload)` pairs:
the Service filters them against OPENPROJECT_READ_PROJECTS by the raw payload
(a project's own id/identifier, a work package's `_links.project`) before
returning the summaries, which is why the raw payload crosses the boundary.
Principals are not project-scoped records, so they come back normalized.
"""

from __future__ import annotations

from typing import Any, Protocol

from ...models import PrincipalSummary, ProjectSummary, RelationCandidateSummary


class WorkPackagePickerApi(Protocol):
    """Narrow, pickers-only Domain API port. WorkPackagePickerService depends
    on this Protocol, never on HttpxWorkPackagePickerApi concretely (enforced
    by the architecture-boundary test).
    """

    async def available_assignees(
        self, *, work_package_id: int | None, project_id: int | None
    ) -> list[PrincipalSummary]:
        """GET work_packages/{id}/available_assignees, or
        projects/{id}/available_assignees when work_package_id is None."""
        ...

    async def available_watchers(self, work_package_id: int) -> list[PrincipalSummary]: ...

    async def available_projects(self, work_package_id: int) -> list[tuple[ProjectSummary, dict[str, Any]]]: ...

    async def relation_candidates(
        self, work_package_id: int, *, query: str | None, relation_type: str | None, page_size: int
    ) -> list[tuple[RelationCandidateSummary, dict[str, Any]]]: ...
