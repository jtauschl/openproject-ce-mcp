"""Application Service for the Current User domain.

Depends on the CurrentUserApi Protocol, never HttpxCurrentUserApi concretely
(enforced by the architecture-boundary test). No Resolver, no Policy module:
self-scoped to the token owner, no project link and no allowlist concept at
all.

Gates on the `"principal"` read scope, which `config.py` maps to
`enable_membership_read` -- NOT a dedicated current-user flag. Pre-existing
quirk of client.py's original get_current_user, preserved exactly rather
than "fixed" during migration.

`OpenProjectClient.get_current_user` (the one-line delegation this Service
backs) MUST remain a bindable, zero-argument, `CurrentUser`-returning async
method: it is already injected as the bound method `self.get_current_user`
into the pre-existing `CurrentUserLookup` seam Protocol
(app/ports/current_user.py), consumed by `WorkPackageService`/
`TimeEntryService`, and called directly by `_resolve_principal_id`'s "me"
fast path, `_resolve_assignee_id`, and `get_my_project_access`. None of
those call sites needed to change -- they still see the same bound method,
whose body now delegates here instead of doing I/O directly.
"""

from __future__ import annotations

from ...config import Settings
from ...models import CurrentUser
from ..policies import access, hidden_fields
from ..ports.current_user_api import CurrentUserApi


class CurrentUserService:
    def __init__(self, *, api: CurrentUserApi, settings: Settings) -> None:
        self._api = api
        self._settings = settings

    async def get_current_user(self) -> CurrentUser:
        access.ensure_read_enabled("principal", settings=self._settings)
        record = await self._api.get_current_user()
        return hidden_fields.apply_hidden_fields("current_user", record.summary, settings=self._settings)
