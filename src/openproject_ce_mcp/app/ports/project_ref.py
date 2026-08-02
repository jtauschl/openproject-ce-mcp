"""Project-reference resolution port."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any, Protocol

from .project_resolution import ProjectResolutionContext


class ProjectRefResolver(Protocol):
    """Narrow seam onto Projects' resolution machinery (`self._get_project_payload`,
    itself a thin wrapper around `ProjectResolver.resolve`/`.resolve_record` --
    see `app/resolvers/project_resolver.py`). Originally written when Projects was
    still unmigrated and reused as-is once Projects migrated (the second domain,
    after the Versions pilot), rather than replaced with a direct `ProjectApi`
    dependency -- every other domain's Service/Resolver already depended on this
    seam, and swapping it for a concrete `ProjectApi` type everywhere would be a
    mechanical, behavior-preserving rename with no benefit, not a real fix. The
    concrete value `OpenProjectClient` hands in is literally the bound method
    `self._get_project_payload` (structural typing, no wrapper class needed).
    """

    def __call__(
        self, project_ref: str, *, write: bool = False, context: ProjectResolutionContext | None = None
    ) -> Awaitable[dict[str, Any]]: ...


class ProjectIdResolver(Protocol):
    """Narrow seam onto `self._resolve_project_id`, itself a thin pass-through to
    `ProjectResolver.resolve_id` (see `app/resolvers/project_resolver.py`) --
    analogous to `PrincipalRefResolver` (`app/ports/principal_ref.py`), added
    for the Time Entries migration (`_build_time_entry_write_payload`'s
    project-id resolution when writing a time entry directly against a
    project, not a work package). Distinct from `ProjectRefResolver` above:
    that seam returns the full project payload dict (for reading fields like
    `name`/`identifier`); this one returns only the resolved numeric id as a
    string, matching `_resolve_project_id`'s actual return type. The
    concrete value `OpenProjectClient` hands in is literally the bound method
    `self._resolve_project_id` (structural typing, no wrapper class needed).
    """

    def __call__(self, project_ref: str, *, write: bool = False) -> Awaitable[str]: ...
