"""Work Package Pickers Domain API port.

Read-only lookups for assignees (per work package, or per project before
creation) and available relation candidates. Each endpoint returns a single
collection. Relation candidates carry their raw payload alongside the summary
so the service can filter by the candidate's project before returning it.

"""

from __future__ import annotations

from typing import Any, Protocol

from ...models import PrincipalSummary, RelationCandidateSummary


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

    async def relation_candidates(
        self, work_package_id: int, *, query: str | None, relation_type: str | None, page_size: int
    ) -> list[tuple[RelationCandidateSummary, dict[str, Any]]]: ...
