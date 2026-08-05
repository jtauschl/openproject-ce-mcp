"""Status-reference resolution port.

Narrow name->id resolution seam for status references. Not routed through
`StatusPriorityTypeService` -- that Service only exposes a numeric
`status_id` lookup (`get_status`), not name resolution, so there is no
Service-level equivalent to depend on instead. Mirrors
`app/ports/principal_ref.py`'s seam shape.
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Protocol


class StatusRefResolver(Protocol):
    def __call__(self, status_ref: str) -> Awaitable[str]: ...
