"""Process-lifetime cache holders for read-only, process-global API responses.

`SingletonCache` deliberately holds no gating/masking logic of its own --
`client.py` constructs one instance per cached value and shares the same
reference across every consumer that needs it (same shape as
`_project_id_to_identifier`), so a Service and a Resolver with different
read-gate behavior (see `StatusPriorityTypeResolver`'s docstring) can safely
share one cache without either inheriting the other's gate check.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass
class SingletonCache(Generic[T]):
    value: T | None = None
