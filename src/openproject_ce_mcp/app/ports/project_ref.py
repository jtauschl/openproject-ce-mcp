"""Project-reference resolution port."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any, Protocol

from .project_resolution import ProjectResolutionContext


class ProjectRefResolver(Protocol):
    """Narrow seam onto Projects' resolution machinery (`self._get_project_payload`,
    itself a thin wrapper around `ProjectResolver.resolve`/`.resolve_record` --
    see `app/resolvers/project_resolver.py`). Every domain's Service/Resolver
    depends on this seam rather than a concrete `ProjectApi` type directly,
    keeping project-reference resolution behind one stable interface.
    """

    def __call__(
        self, project_ref: str, *, write: bool = False, context: ProjectResolutionContext | None = None
    ) -> Awaitable[dict[str, Any]]: ...


class ProjectIdResolver(Protocol):
    """Narrow seam onto `self._resolve_project_id`, itself a thin pass-through to
    `ProjectResolver.resolve_id` (see `app/resolvers/project_resolver.py`) --
    analogous to `PrincipalRefResolver` (`app/ports/principal_ref.py`). Used
    for project-id resolution when writing a time entry directly against a
    project, not a work package (`_build_time_entry_write_payload`).
    Distinct from `ProjectRefResolver` above: that seam returns the full
    project payload dict (for reading fields like `name`/`identifier`); this
    one returns only the resolved numeric id as a string.
    """

    def __call__(self, project_ref: str, *, write: bool = False) -> Awaitable[str]: ...
