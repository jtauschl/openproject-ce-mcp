"""User Non-Working Times Domain API port.

Per-user date-range schedule exceptions (vacation etc.) -- OpenProject's
`/api/v3/users/{user_id}/non_working_times` resource. Requires 17.3+
(feature-flag-guarded 17.3-17.6 via `guard_feature_flag :user_working_times`,
generally available 17.7+ -- verified against op-sources: present in
17.3-17.6's `non_working_times_by_user_api.rb`, absent in 17.7's; the route
itself does not exist at all before 17.3, `lib/api/v3/user_non_working_times/`
is absent in 17.0-17.2). No client-side version check: server errors pass
through unmodified, per this project's established pattern; docstrings state
the version facts for operator awareness only.

Full CRUD minus a single-item GET: list, create, update, delete -- OpenProject
mounts no `GET .../non_working_times/{id}` route at all (verified against
`non_working_times_by_user_api.rb`, only `patch`/`delete` exist under
`route_param :non_working_time_id`). `update`/`delete` therefore need the
Service to already know the record belongs to the target user (from a prior
`list_for_user` scan), the same no-single-GET shape `WikiPageLinkApi.delete`
documents.

Collection is UNPAGINATED (`UserNonWorkingTimeCollectionRepresenter` subclasses
`::API::Decorators::UnpaginatedCollection`, verified against source) --
`offset`/`page_size` params exist here only for interface symmetry, matching
RoleApi's identical documented caveat; the server always returns the full
year's records regardless of what's sent. `year` filters server-side
(defaults to the current year when omitted, per
`non_working_times_by_user_api.rb`).

Auth is enforced entirely server-side, at the route level, per-request:
`@user == current_user || current_user.allowed_globally?(:manage_working_times)`,
else a 404 (NOT 403 -- OpenProject deliberately hides existence of another
user's records from an unauthorized caller). No project concept at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ...models import UserNonWorkingTimeSummary


@dataclass(frozen=True)
class UserNonWorkingTimeRecord:
    """One non-working-time record as read from the API: the normalized `summary`."""

    summary: UserNonWorkingTimeSummary


class UserNonWorkingTimeApi(Protocol):
    """Narrow, User-Non-Working-Times-only Domain API port.
    UserNonWorkingTimeService depends on this Protocol, never on
    HttpxUserNonWorkingTimeApi concretely (enforced by the
    architecture-boundary test).
    """

    async def list_for_user(
        self, user_ref: str, *, year: int | None, offset: int, page_size: int
    ) -> tuple[list[UserNonWorkingTimeRecord], int]: ...
    async def create(self, user_ref: str, *, start_date: str, end_date: str) -> UserNonWorkingTimeRecord: ...
    async def update(
        self, user_ref: str, non_working_time_id: int, *, payload: dict[str, object]
    ) -> UserNonWorkingTimeRecord: ...
    async def delete(self, user_ref: str, non_working_time_id: int) -> None: ...
