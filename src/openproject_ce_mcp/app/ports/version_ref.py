"""Version-reference resolution port.

Narrow seam exposing `VersionResolver.resolve_id` via a Protocol, the same
way `app/ports/project_ref.py`'s `ProjectRefResolver` seams onto
`self._get_project_payload`.
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Protocol

from .project_resolution import ProjectResolutionContext


class VersionIdResolver(Protocol):
    def __call__(
        self, version_ref: str, *, project: str | None = None, context: ProjectResolutionContext | None = None
    ) -> Awaitable[str]: ...
