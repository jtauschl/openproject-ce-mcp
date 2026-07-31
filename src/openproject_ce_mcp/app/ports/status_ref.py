"""Status-reference resolution port (ADR 0001).

Narrow seam onto the still-flat Statuses/Priorities/Types domain's existing
name->id resolution machinery (client.py's `_resolve_status_id`), reused as-is
rather than routed through `StatusPriorityTypeService` -- that Service only
exposes a numeric `status_id` lookup (`get_status`), not name resolution, so
there is no already-migrated equivalent to depend on instead. Mirrors
`app/ports/principal_ref.py`'s seam shape. The concrete value
`OpenProjectClient` hands in is the bound method `self._resolve_status_id`
(structural typing, no wrapper class needed).
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Protocol


class StatusRefResolver(Protocol):
    def __call__(self, status_ref: str) -> Awaitable[str]: ...
