"""Priority-reference resolution port.

Narrow seam onto the still-flat Statuses/Priorities/Types domain's existing
name->id resolution machinery (client.py's `_resolve_priority_id`), reused
as-is -- see `app/ports/status_ref.py`'s module docstring for why this isn't
routed through `StatusPriorityTypeService` instead. The concrete value
`OpenProjectClient` hands in is the bound method `self._resolve_priority_id`
(structural typing, no wrapper class needed).
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Protocol


class PriorityRefResolver(Protocol):
    def __call__(self, priority_ref: str) -> Awaitable[str]: ...
