"""Sprint-reference resolution port (ADR 0001).

Narrow seam onto client.py's `_resolve_sprint_id` -- unlike `VersionIdResolver`
(whose `project` parameter is optional, defaulting to None for a
project-agnostic lookup), Sprint resolution genuinely requires a project:
`_resolve_sprint_id` does a paginated project-sprint walk scoped to one
project's Backlogs sprints, with no project-agnostic fallback. Do not copy
`VersionIdResolver`'s optional-`project` signature here -- `project` is
REQUIRED.

The concrete value `OpenProjectClient` hands in is the bound method
`self._resolve_sprint_id` (structural typing, no wrapper class needed).
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Protocol

from .project_resolution import ProjectResolutionContext


class SprintIdResolver(Protocol):
    def __call__(
        self, sprint_ref: str, *, project: str, context: ProjectResolutionContext | None = None
    ) -> Awaitable[str]: ...
