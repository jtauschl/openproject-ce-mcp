"""Project-reference resolution port (ADR 0001)."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any, Protocol

from .project_resolution import ProjectResolutionContext


class ProjectRefResolver(Protocol):
    """Narrow seam onto the still-unmigrated Project domain's existing resolution
    machinery (_get_project_payload/_resolve_project_ref -- explicitly out of scope
    for OPM-153, reused as-is). The concrete value OpenProjectClient hands in is
    literally the bound method self._get_project_payload (structural typing, no
    wrapper class needed). Replace with a real ProjectApi port once Projects migrates.
    """

    def __call__(
        self, project_ref: str, *, write: bool = False, context: ProjectResolutionContext | None = None
    ) -> Awaitable[dict[str, Any]]: ...
