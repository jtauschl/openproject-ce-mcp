"""Current User Domain API port (ADR 0001).

Single global GET, no project link, no list/create/update/delete -- returns
the token owner's own user record via `/api/v3/users/me`.

Named `current_user_api.py`, NOT `current_user.py` -- that filename is
already taken by the pre-existing `CurrentUserLookup` seam Protocol
(app/ports/current_user.py), a bare-callable seam other already-migrated
Services depend on (satisfied structurally by the bound method
`self.get_current_user`, unrelated to this migration and left untouched).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ...models import CurrentUser


@dataclass(frozen=True)
class CurrentUserRecord:
    summary: CurrentUser


class CurrentUserApi(Protocol):
    """Narrow, Current-User-only Domain API port. CurrentUserService depends
    on this Protocol, never on HttpxCurrentUserApi concretely (enforced by
    the architecture-boundary test).
    """

    async def get_current_user(self) -> CurrentUserRecord: ...
