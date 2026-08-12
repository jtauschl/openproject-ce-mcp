"""Application Service for the User Non-Working Times domain.

Depends on the `UserNonWorkingTimeApi` Protocol, never `HttpxUserNonWorkingTimeApi`
concretely (enforced by the architecture-boundary test). No Resolver -- this
domain has no project concept at all (route-level auth only, see the Port's
docstring). No dedicated `<domain>_policy.py`: the authorization decision is
"pass user_ref through and let OpenProject's own route gate answer" -- there
is no client-side allowlist to enforce beyond this MCP's own
`OPENPROJECT_ENABLE_USER_SCHEDULE_READ`/`_WRITE` surface-exposure flags.

Read/write scope is the dedicated `"user_schedule"` scope (own
`OPENPROJECT_ENABLE_USER_SCHEDULE_READ`/`_WRITE` flags) -- not `"personal"`
(current-user-only, no user_id param anywhere in that scope's tools) and not
`"admin"` (instance-wide user/group management; would incorrectly block a
non-admin caller from viewing/editing their OWN schedule, which OpenProject
itself always permits). See config.py's `_READ_SCOPE_SETTINGS`/
`_WRITE_SCOPE_SETTINGS` for the wiring.

`list_for_user` paginates CLIENT-side via `pagination.paginate_client`,
matching RoleService's exact precedent: the collection is
`UnpaginatedCollection` server-side (verified against source), so
`_api.list_for_user` is always called with `offset=1,
page_size=settings.max_results` (fetch the whole requested year) and the
result is sliced locally.

`update()`/`delete()` both require a prior `list_for_user` scan to find the
target record (there is no single-resource GET on OpenProject's side for
this domain at all -- see the Port's docstring) and, for `delete()`, to
confirm the id genuinely belongs to this `user_ref` before calling DELETE.
This mirrors `WikiPageLinkService.delete()`'s `_ensure_link_belongs_to_
work_package` shape, but for a materially different reason: OpenProject's own
DELETE/PATCH here already scope by `.for_user(@user).find(...)` server-side
(a mismatched id already 404s -- verified against
`non_working_times_by_user_api.rb`'s `after_validation` block), so this is
not an authorization-bypass fix the way WikiPageLink's was (that domain's
DELETE endpoint has no comparable per-parent scoping). It exists here purely
so a wrong id produces this MCP's own clear `NotFoundError` instead of an
`OpenProjectServerError` propagated from a raw 404, and so `update`/`delete`
can report the record's own `user_id` in their result even when the
caller-supplied `user_ref` was `"me"` or a login rather than a numeric id.
"""

from __future__ import annotations

from ...config import Settings
from ...models import UserNonWorkingTimeListResult, UserNonWorkingTimeSummary, UserNonWorkingTimeWriteResult
from ..errors import NotFoundError
from ..pagination import effective_limit as _effective_limit
from ..pagination import paginate_client
from ..policies import access, hidden_fields
from ..ports.user_non_working_time_api import UserNonWorkingTimeApi, UserNonWorkingTimeRecord


class UserNonWorkingTimeService:
    def __init__(self, *, api: UserNonWorkingTimeApi, settings: Settings) -> None:
        self._api = api
        self._settings = settings

    def _stamp(self, record: UserNonWorkingTimeRecord) -> UserNonWorkingTimeSummary:
        return hidden_fields.apply_hidden_fields("user_non_working_time", record.summary, settings=self._settings)

    async def list_for_user(
        self, user_ref: str, *, year: int | None = None, offset: int = 1, limit: int | None = None
    ) -> UserNonWorkingTimeListResult:
        access.ensure_read_enabled("user_schedule", settings=self._settings)
        effective_limit = _effective_limit(limit, settings=self._settings)
        # NB: the server ignores offset/pageSize here and always returns the
        # full (year-filtered) collection -- fetch everything once (bounded
        # by max_results, not effective_limit) and slice locally instead of
        # trusting a server-side page that never actually happens. See
        # RoleService.list_roles for the identical precedent.
        records, _server_total = await self._api.list_for_user(
            user_ref, year=year, offset=1, page_size=self._settings.max_results
        )
        all_results = [self._stamp(record) for record in records]
        page, total, next_offset, truncated = paginate_client(offset=offset, limit=effective_limit, results=all_results)
        return UserNonWorkingTimeListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(page),
            next_offset=next_offset,
            truncated=truncated,
            results=page,
        )

    async def _find_or_404(self, user_ref: str, non_working_time_id: int) -> UserNonWorkingTimeSummary:
        records, _total = await self._api.list_for_user(
            user_ref, year=None, offset=1, page_size=self._settings.max_results
        )
        for record in records:
            if record.summary.id == non_working_time_id:
                return record.summary
        raise NotFoundError(f"OpenProject non-working time {non_working_time_id} was not found for user {user_ref}.")

    async def create(
        self, user_ref: str, *, start_date: str, end_date: str, confirm: bool = False
    ) -> UserNonWorkingTimeWriteResult:
        access.ensure_read_enabled("user_schedule", settings=self._settings)
        hidden_fields.ensure_field_writable("user_non_working_time", "start_date", settings=self._settings)
        hidden_fields.ensure_field_writable("user_non_working_time", "end_date", settings=self._settings)
        payload = {"startDate": start_date, "endDate": end_date}
        if not confirm:
            return UserNonWorkingTimeWriteResult(
                action="create",
                state="preview",
                ready=True,
                message=(
                    "OpenProject is ready to create this non-working time. Ask for confirmation, "
                    "then call again with confirm=true."
                ),
                non_working_time_id=None,
                user_id=None,
                payload=payload,
                validation_errors={},
                result=None,
            )
        access.ensure_write_enabled("user_schedule", settings=self._settings)
        record = await self._api.create(user_ref, start_date=start_date, end_date=end_date)
        result = self._stamp(record)
        return UserNonWorkingTimeWriteResult(
            action="create",
            state="confirmed",
            ready=True,
            message="Non-working time created successfully.",
            non_working_time_id=result.id,
            user_id=result.user_id,
            payload=payload,
            validation_errors={},
            result=result,
        )

    async def update(
        self,
        user_ref: str,
        non_working_time_id: int,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        confirm: bool = False,
    ) -> UserNonWorkingTimeWriteResult:
        access.ensure_read_enabled("user_schedule", settings=self._settings)
        current = await self._find_or_404(user_ref, non_working_time_id)
        payload: dict[str, object] = {}
        if start_date is not None:
            hidden_fields.ensure_field_writable("user_non_working_time", "start_date", settings=self._settings)
            payload["startDate"] = start_date
        if end_date is not None:
            hidden_fields.ensure_field_writable("user_non_working_time", "end_date", settings=self._settings)
            payload["endDate"] = end_date
        if not confirm:
            return UserNonWorkingTimeWriteResult(
                action="update",
                state="preview",
                ready=True,
                message="Ask for confirmation, then call again with confirm=true to write it.",
                non_working_time_id=non_working_time_id,
                user_id=current.user_id,
                payload=payload,
                validation_errors={},
                result=None,
            )
        access.ensure_write_enabled("user_schedule", settings=self._settings)
        record = await self._api.update(user_ref, non_working_time_id, payload=payload)
        result = self._stamp(record)
        return UserNonWorkingTimeWriteResult(
            action="update",
            state="confirmed",
            ready=True,
            message="Non-working time updated successfully.",
            non_working_time_id=result.id,
            user_id=result.user_id,
            payload=payload,
            validation_errors={},
            result=result,
        )

    async def delete(
        self, user_ref: str, non_working_time_id: int, *, confirm: bool = False
    ) -> UserNonWorkingTimeWriteResult:
        access.ensure_read_enabled("user_schedule", settings=self._settings)
        current = await self._find_or_404(user_ref, non_working_time_id)
        payload = {"id": non_working_time_id}
        if not confirm:
            return UserNonWorkingTimeWriteResult(
                action="delete",
                state="preview",
                ready=True,
                message="Ask for confirmation, then call again with confirm=true to delete it.",
                non_working_time_id=non_working_time_id,
                user_id=current.user_id,
                payload=payload,
                validation_errors={},
                result=None,
            )
        access.ensure_write_enabled("user_schedule", settings=self._settings)
        await self._api.delete(user_ref, non_working_time_id)
        return UserNonWorkingTimeWriteResult(
            action="delete",
            state="confirmed",
            ready=True,
            message="Non-working time deleted successfully.",
            non_working_time_id=non_working_time_id,
            user_id=current.user_id,
            payload=payload,
            validation_errors={},
            result=None,
        )
