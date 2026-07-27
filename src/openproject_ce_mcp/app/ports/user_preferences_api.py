"""User Preferences Domain API port (18th migrated domain).

Self-scoped, not project-scoped: the `my_preferences` endpoint is a singleton
keyed to the token owner, with no `_links` block and no project concept at
all -- verified against client.py's normalize_user_preferences, which reads
only flat scalar fields off the payload. UserPreferencesRecord therefore
carries no summary/detail split (no list endpoint means no list-row
truncation to defer, same reasoning as WikiPageRecord) and no `<parent>_link`
field (no HAL link exists to carry for an allowlist check -- there is no
allowlist for a self-scoped resource).

`get()` takes no id parameter: the resource is implicit in the caller's own
auth token, unlike every other get-only Domain API port so far.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ...models import UserPreferences


@dataclass(frozen=True)
class UserPreferencesRecord:
    detail: UserPreferences


class UserPreferencesApi(Protocol):
    """Narrow, User-Preferences-only Domain API port. UserPreferencesService
    depends on this Protocol, never on HttpxUserPreferencesApi concretely
    (enforced by the architecture-boundary test).

    Singleton get + single write action: no list_all, no delete -- the
    OpenProject v3 API exposes only GET/PATCH on `my_preferences`.
    """

    async def get(self) -> UserPreferencesRecord: ...

    async def commit_update(self, payload: dict[str, Any]) -> UserPreferences: ...
