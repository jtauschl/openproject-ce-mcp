"""Priority-reference resolution port.

Narrow name->id resolution seam for priority references -- see
`app/ports/status_ref.py`'s module docstring for why this isn't routed
through `StatusPriorityTypeService` instead.
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Protocol


class PriorityRefResolver(Protocol):
    def __call__(self, priority_ref: str) -> Awaitable[str]: ...
