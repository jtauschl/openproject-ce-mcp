"""Work-package-type-reference resolution port.

Narrow seam onto client.py's still-flat `_resolve_type_id`, reused as-is --
type names are resolved per-project (`projects/{id}/types`), so no
already-migrated global Type service exists to depend on instead (see
`app/ports/status_ref.py`'s module docstring for the same reasoning applied
to statuses/priorities). The concrete value `OpenProjectClient` hands in is
the bound method `self._resolve_type_id` (structural typing, no wrapper
class needed).

`context` is `ProjectResolutionContext | None`, matching `_resolve_type_id`'s
own signature -- allows a caller resolving both a project and a type in the
same top-level call (e.g. `WorkPackageService.list`) to share one cache
instead of re-resolving/re-checking the same project twice.
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Protocol

from .project_resolution import ProjectResolutionContext


class TypeRefResolver(Protocol):
    def __call__(
        self, type_ref: str, *, project: str | None, context: ProjectResolutionContext | None = None
    ) -> Awaitable[str]: ...
