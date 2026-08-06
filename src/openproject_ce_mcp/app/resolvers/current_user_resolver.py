"""Current-user lookup resolver -- the `CurrentUserLookup` seam's own implementation.

Depends directly on `CurrentUserApi`, never on `CurrentUserService` -- same
"depend on Ports, not sibling Services" shape as every other Resolver in this
package. Replaces the earlier design, where `PrincipalResolver`,
`AssigneeResolver`, `WorkPackageService`, and `TimeEntryService` all received
`client.py`'s own `get_current_user` bound method (itself a one-line
delegation to `CurrentUserService.get_current_user()`) as their
`CurrentUserLookup` implementation -- a hidden, indirect Service dependency
the AST-import-based architecture-boundary test cannot see, since it flows
through a runtime-bound callable rather than a literal `import`.

`__call__` deliberately duplicates `CurrentUserService.get_current_user()`'s
scope-gate (`access.ensure_read_enabled("principal", ...)`, matching
`SprintResolver`'s precedent for reproducing a gate directly in a Resolver)
and hidden-field masking
(`hidden_fields.apply_hidden_fields("current_user", ...)`) rather than
sharing a helper with the Service -- both are 3-line, stable domain-policy
calls, not worth a new shared abstraction. `CurrentUserService` itself is
unchanged and still backs the `get_current_user` MCP tool directly; this
Resolver is a second, independent implementation of the exact same
free-standing logic, not a replacement for the Service.
"""

from __future__ import annotations

from ...config import Settings
from ...models import CurrentUser
from ..policies import access, hidden_fields
from ..ports.current_user_api import CurrentUserApi


class CurrentUserResolver:
    def __init__(self, *, api: CurrentUserApi, settings: Settings) -> None:
        self._api = api
        self._settings = settings

    async def __call__(self) -> CurrentUser:
        access.ensure_read_enabled("principal", settings=self._settings)
        record = await self._api.get_current_user()
        return hidden_fields.apply_hidden_fields("current_user", record.summary, settings=self._settings)
