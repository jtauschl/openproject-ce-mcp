"""Assignee-reference resolution port.

Narrow seam onto client.py's `_resolve_assignee_id` -- deliberately NOT
`PrincipalRefResolver` (the seam the READ-side `WorkPackageService` already
uses for the `assignee`/`assignee_me` list filters). `_resolve_assignee_id` is
a strictly narrower resolver: it accepts only `"me"` or a bare numeric user
id, never a name search, and raises `InvalidInputError` otherwise -- a
deliberate, pre-existing behavioral asymmetry between filtering (accepts
names) and writing (numeric-or-me only). Reusing `PrincipalRefResolver` here
would silently broaden what `create`/`update` accept for `assignee`.

The concrete value `OpenProjectClient` hands in is the bound method
`self._resolve_assignee_id` (structural typing, no wrapper class needed).
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Protocol


class AssigneeRefResolver(Protocol):
    def __call__(self, assignee_ref: str) -> Awaitable[str]: ...
