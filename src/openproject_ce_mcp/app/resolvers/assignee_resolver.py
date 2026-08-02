"""Assignee-reference resolver.

Verbatim behavioral port of the pre-existing `_resolve_assignee_id`.
Deliberately narrower than `PrincipalResolver`: accepts only `"me"` or a bare
numeric user id, never a name search -- the pre-existing, deliberate
behavioral asymmetry between filtering (accepts names, via `PrincipalRefResolver`)
and writing (numeric-or-me only, via this resolver and `AssigneeRefResolver`).
Depends only on the `CurrentUserLookup` seam, no domain-API Port -- unlike
every other Resolver in this package, so no architecture-boundary "api param
typed as the Port" pin test applies here (there is no `api` param to mistype).
"""

from __future__ import annotations

from ..errors import InvalidInputError
from ..ports.current_user import CurrentUserLookup


class AssigneeResolver:
    def __init__(self, *, current_user: CurrentUserLookup) -> None:
        self._current_user = current_user

    async def resolve_id(self, assignee_ref: str) -> str:
        if assignee_ref.casefold() == "me":
            current_user = await self._current_user()
            return str(current_user.id)
        if assignee_ref.isdigit():
            return assignee_ref
        raise InvalidInputError("assignee must be a positive integer user id or 'me'.")
