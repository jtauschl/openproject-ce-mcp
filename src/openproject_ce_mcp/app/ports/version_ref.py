"""Version-reference resolution port.

Narrow seam onto `VersionResolver.resolve_id` -- Versions is already fully
migrated, and client.py's own `_resolve_version_id` already delegates
verbatim to `self._version_resolver.resolve_id`, so this seam just exposes
that existing resolver's `resolve_id` method via a Protocol, the same way
`app/ports/project_ref.py`'s `ProjectRefResolver` seams onto
`self._get_project_payload`. The concrete value `OpenProjectClient` hands in
is the bound method `self._version_resolver.resolve_id` (structural typing,
no wrapper class needed).
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Protocol

from .project_resolution import ProjectResolutionContext


class VersionIdResolver(Protocol):
    def __call__(
        self, version_ref: str, *, project: str | None = None, context: ProjectResolutionContext | None = None
    ) -> Awaitable[str]: ...
