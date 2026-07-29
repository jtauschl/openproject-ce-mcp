"""Current-user lookup port (ADR 0001).

Narrow seam onto `self.get_current_user` (client.py), added for the Time
Entries migration -- `list_time_entries`'s `user="me"` filter resolves the
caller's own name via `get_current_user()`, which gates on the `"principal"`
read scope and returns the RAW `name` (no `SUBJECT_LIMIT` truncation, unlike
`UserApi.get_user`'s normalized result). `UserApi.get_user("me")` is NOT a
bit-for-bit substitute (different scope gate, different truncation), so this
dedicated seam exists rather than reusing `UserApi`. The concrete value
`OpenProjectClient` hands in is literally the bound method
`self.get_current_user` (structural typing, no wrapper class needed).
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Protocol

from ...models import CurrentUser


class CurrentUserLookup(Protocol):
    def __call__(self) -> Awaitable[CurrentUser]: ...
