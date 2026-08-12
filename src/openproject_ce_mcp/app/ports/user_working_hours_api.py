"""User Working Hours Domain API port.

Per-user recurring weekly hours-per-weekday schedule, versioned by
`valid_from` -- OpenProject's `/api/v3/users/{user_id}/working_hours`
resource. Requires 17.3+ (feature-flag-guarded 17.3-17.6, generally available
17.7+ -- same version facts as UserNonWorkingTimeApi, independently verified
against `working_hours_by_user_api.rb` across op-sources/17.0-17.7). No
client-side version check, matching UserNonWorkingTimeApi.

Full CRUD INCLUDING a single-item GET (`GET .../working_hours/{id}` exists,
verified against `working_hours_by_user_api.rb`'s `route_param
:working_hours_id` block -- unlike UserNonWorkingTimeApi's sibling, which has
no such route). `get` therefore mirrors BoardApi's `get()` precedent (a real
single-resource GET, not a client-side scan-and-match).

Collection is UNPAGINATED (`UserWorkingHoursCollectionRepresenter` subclasses
`::API::Decorators::UnpaginatedCollection`, verified against source),
ordered `valid_from desc` server-side. Same interface-symmetry caveat on
`offset`/`page_size` as UserNonWorkingTimeApi/RoleApi.

Auth: identical self-service-or-`manage_working_times` route-level gate as
UserNonWorkingTimeApi, same 404-not-403 behavior for an unauthorized
cross-user request.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ...models import UserWorkingHoursSummary


@dataclass(frozen=True)
class UserWorkingHoursRecord:
    """One working-hours record as read from the API: the normalized `summary`."""

    summary: UserWorkingHoursSummary


class UserWorkingHoursApi(Protocol):
    """Narrow, User-Working-Hours-only Domain API port. UserWorkingHoursService
    depends on this Protocol, never on HttpxUserWorkingHoursApi concretely
    (enforced by the architecture-boundary test).
    """

    async def list_for_user(
        self, user_ref: str, *, offset: int, page_size: int
    ) -> tuple[list[UserWorkingHoursRecord], int]: ...
    async def get(self, user_ref: str, working_hours_id: int) -> UserWorkingHoursRecord: ...
    async def create(
        self,
        user_ref: str,
        *,
        valid_from: str,
        monday_hours: float | None,
        tuesday_hours: float | None,
        wednesday_hours: float | None,
        thursday_hours: float | None,
        friday_hours: float | None,
        saturday_hours: float | None,
        sunday_hours: float | None,
        availability_factor: float | None,
    ) -> UserWorkingHoursRecord: ...
    async def update(
        self, user_ref: str, working_hours_id: int, *, payload: dict[str, object]
    ) -> UserWorkingHoursRecord: ...
    async def delete(self, user_ref: str, working_hours_id: int) -> None: ...
