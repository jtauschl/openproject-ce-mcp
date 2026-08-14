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
`non_working_times_by_user_api.rb`), but `update`/`delete` do NOT need a
prior `list_for_user` scan to compensate: `route_param :non_working_time_id`
scopes both `patch`/`delete` server-side by `.visible(current_user).
for_user(@user).find(non_working_time_id)` with no year filter, so a bad id
already 404s on its own. (An earlier version of the Service pre-fetched via
`list_for_user` for this purpose -- unlike WikiPageLinkApi.delete's genuinely
unscoped DELETE, this domain's routes were already self-scoping, and the
scan's default `year` silently missed non-current-year records, found live
against a real 17.7.1 instance.)

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
