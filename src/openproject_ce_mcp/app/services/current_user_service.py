"""Application Service for the Current User domain.

Depends on the CurrentUserApi Protocol, never HttpxCurrentUserApi concretely
(enforced by the architecture-boundary test). No Resolver, no Policy module:
self-scoped to the token owner, no project link and no allowlist concept at
all.

Gates on the `"principal"` read scope, which `config.py` maps to
`enable_membership_read` -- NOT a dedicated current-user flag. A deliberate
quirk, kept as-is rather than "fixed".

`OpenProjectClient.get_current_user` (the one-line delegation this Service
backs) directly backs only the `get_current_user` MCP tool and `client.py`'s
own `get_my_project_access` orchestrator. The `CurrentUserLookup` seam
Protocol (`app/ports/current_user.py`) that `PrincipalResolver`/
`AssigneeResolver`/`WorkPackageService`/`TimeEntryService` depend on is
implemented separately by `app/resolvers/current_user_resolver.py`'s
`CurrentUserResolver` -- a second, independent implementation of this same
gate+mask logic, depending directly on `CurrentUserApi` rather than on this
Service, so those four don't carry a hidden Service->Service dependency
through a runtime-bound `client.py` method.
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
