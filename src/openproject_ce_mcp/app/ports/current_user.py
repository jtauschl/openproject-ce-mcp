"""Current-user lookup port.

`list_time_entries`'s `user="me"` filter resolves the caller's own name via
`get_current_user()`, which gates on the `"principal"` read scope and
returns the RAW `name` (no `SUBJECT_LIMIT` truncation, unlike
`UserApi.get_user`'s normalized result). `UserApi.get_user("me")` is NOT a
bit-for-bit substitute (different scope gate, different truncation), so this
dedicated seam exists rather than reusing `UserApi`.

Implemented by `app/resolvers/current_user_resolver.py`'s
`CurrentUserResolver`, which depends directly on `CurrentUserApi` -- not by
a bound method on a Service or on `client.py`, so no consumer of this seam
carries a hidden Service dependency.
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Protocol

from ...models import CurrentUser


class CurrentUserLookup(Protocol):
    def __call__(self) -> Awaitable[CurrentUser]: ...
