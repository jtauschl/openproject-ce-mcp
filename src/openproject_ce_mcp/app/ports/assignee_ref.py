"""Assignee-reference resolution port.

Deliberately NOT `PrincipalRefResolver` (the seam the READ-side
`WorkPackageService` uses for the `assignee`/`assignee_me` list filters).
This resolver is strictly narrower: it accepts only `"me"` or a bare numeric
user id, never a name search, and raises `InvalidInputError` otherwise -- a
deliberate behavioral asymmetry between filtering (accepts names) and
writing (numeric-or-me only). Reusing `PrincipalRefResolver` here would
silently broaden what `create`/`update` accept for `assignee`.
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Protocol


class AssigneeRefResolver(Protocol):
    def __call__(self, assignee_ref: str) -> Awaitable[str]: ...
