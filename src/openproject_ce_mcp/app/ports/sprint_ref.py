"""Sprint-reference resolution port.

Unlike `VersionIdResolver` (whose `project` parameter is optional, defaulting
to None for a project-agnostic lookup), Sprint resolution genuinely requires
a project: resolution does a paginated project-sprint walk scoped to one
project's Backlogs sprints, with no project-agnostic fallback. Do not copy
`VersionIdResolver`'s optional-`project` signature here -- `project` is
REQUIRED.
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Protocol

from .project_resolution import ProjectResolutionContext


class SprintIdResolver(Protocol):
    def __call__(
        self, sprint_ref: str, *, project: str, context: ProjectResolutionContext | None = None
    ) -> Awaitable[str]: ...
