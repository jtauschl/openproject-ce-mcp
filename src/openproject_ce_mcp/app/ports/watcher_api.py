"""Watchers Domain API port.

Narrow: list (scoped to one work package) + add + remove. No get-one-watcher
endpoint -- a watcher's identity is simply the OpenProject user id, so
`add`'s preview needs a plain user lookup (`get_user`), not a "get one
watcher" call.

No `to_detail`: `WatcherSummary` IS the only normalized shape this domain
has (no separate Detail model exists in models.py), matching File Links'
precedent.
"""

from __future__ import annotations

from typing import Protocol

from ...models import WatcherSummary


class WatcherApi(Protocol):
    """Narrow, Watchers-only Domain API port. WatcherService depends on this
    Protocol, never on HttpxWatcherApi concretely (enforced by the
    architecture-boundary test).
    """

    async def list_for_work_package(self, work_package_id: int) -> list[WatcherSummary]: ...
    async def get_user(self, user_id: int) -> WatcherSummary: ...
    async def add(self, work_package_id: int, user_id: int) -> WatcherSummary: ...
    async def remove(self, work_package_id: int, user_id: int) -> None: ...
