"""Application Service for the User Working Hours domain.

Depends on the `UserWorkingHoursApi` Protocol, never `HttpxUserWorkingHoursApi`
concretely (enforced by the architecture-boundary test). Same scope
(`"user_schedule"`), same no-Resolver/no-Policy shape as
`UserNonWorkingTimeService` -- see that Service's docstring for the shared
rationale.

Unlike `UserNonWorkingTimeService`, `get()`/`update()`/`delete()` use a REAL
single-resource GET (`GET users/{user_ref}/working_hours/{id}` exists here,
verified against source) rather than a list-scan -- this is `BoardService`'s
"delete fetches its own record via a real single-resource GET" pattern (per
this ticket's own instructions), not `WikiPageLinkService`'s workaround
(which only exists because `wiki_page_links` has NO single-resource GET at
all).

`list_for_user` paginates client-side via `pagination.paginate_client`, same
`UnpaginatedCollection` precedent as `UserNonWorkingTimeService`/`RoleService`.
"""

from __future__ import annotations

from ...config import Settings
from ...models import UserWorkingHoursListResult, UserWorkingHoursSummary, UserWorkingHoursWriteResult
from ..pagination import effective_limit as _effective_limit
from ..pagination import paginate_client
from ..policies import access, hidden_fields
from ..ports.user_working_hours_api import UserWorkingHoursApi, UserWorkingHoursRecord

_WRITABLE_FIELDS: tuple[tuple[str, str], ...] = (
    ("valid_from", "validFrom"),
    ("monday_hours", "mondayHours"),
    ("tuesday_hours", "tuesdayHours"),
    ("wednesday_hours", "wednesdayHours"),
    ("thursday_hours", "thursdayHours"),
    ("friday_hours", "fridayHours"),
    ("saturday_hours", "saturdayHours"),
    ("sunday_hours", "sundayHours"),
    ("availability_factor", "availabilityFactor"),
)


class UserWorkingHoursService:
    def __init__(self, *, api: UserWorkingHoursApi, settings: Settings) -> None:
        self._api = api
        self._settings = settings

    def _stamp(self, record: UserWorkingHoursRecord) -> UserWorkingHoursSummary:
        return hidden_fields.apply_hidden_fields("user_working_hours", record.summary, settings=self._settings)

    async def list_for_user(
        self, user_ref: str, *, offset: int = 1, limit: int | None = None
    ) -> UserWorkingHoursListResult:
        access.ensure_read_enabled("user_schedule", settings=self._settings)
        effective_limit = _effective_limit(limit, settings=self._settings)
        # NB: the server ignores offset/pageSize here and always returns the
        # full collection -- fetch everything once (bounded by max_results,
        # not effective_limit) and slice locally instead of trusting a
        # server-side page that never actually happens. See
        # RoleService.list_roles for the identical precedent.
        records, _server_total = await self._api.list_for_user(user_ref, offset=1, page_size=self._settings.max_results)
        all_results = [self._stamp(record) for record in records]
        page, total, next_offset, truncated = paginate_client(offset=offset, limit=effective_limit, results=all_results)
        return UserWorkingHoursListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(page),
            next_offset=next_offset,
            truncated=truncated,
            results=page,
        )

    async def get(self, user_ref: str, working_hours_id: int) -> UserWorkingHoursSummary:
        access.ensure_read_enabled("user_schedule", settings=self._settings)
        record = await self._api.get(user_ref, working_hours_id)
        return self._stamp(record)

    async def create(
        self,
        user_ref: str,
        *,
        valid_from: str,
        monday_hours: float | None = None,
        tuesday_hours: float | None = None,
        wednesday_hours: float | None = None,
        thursday_hours: float | None = None,
        friday_hours: float | None = None,
        saturday_hours: float | None = None,
        sunday_hours: float | None = None,
        availability_factor: float | None = None,
        confirm: bool = False,
    ) -> UserWorkingHoursWriteResult:
        access.ensure_read_enabled("user_schedule", settings=self._settings)
        hidden_fields.ensure_field_writable("user_working_hours", "valid_from", settings=self._settings)
        supplied = {
            "monday_hours": monday_hours,
            "tuesday_hours": tuesday_hours,
            "wednesday_hours": wednesday_hours,
            "thursday_hours": thursday_hours,
            "friday_hours": friday_hours,
            "saturday_hours": saturday_hours,
            "sunday_hours": sunday_hours,
            "availability_factor": availability_factor,
        }
        payload: dict[str, object] = {"validFrom": valid_from}
        for field_name, wire_key in _WRITABLE_FIELDS[1:]:
            value = supplied[field_name]
            if value is not None:
                hidden_fields.ensure_field_writable("user_working_hours", field_name, settings=self._settings)
                payload[wire_key] = value
        if not confirm:
            return UserWorkingHoursWriteResult(
                action="create",
                state="preview",
                ready=True,
                message=(
                    "OpenProject is ready to create this working-hours schedule. Ask for confirmation, "
                    "then call again with confirm=true."
                ),
                working_hours_id=None,
                user_id=None,
                payload=payload,
                validation_errors={},
                result=None,
            )
        access.ensure_write_enabled("user_schedule", settings=self._settings)
        record = await self._api.create(
            user_ref,
            valid_from=valid_from,
            monday_hours=monday_hours,
            tuesday_hours=tuesday_hours,
            wednesday_hours=wednesday_hours,
            thursday_hours=thursday_hours,
            friday_hours=friday_hours,
            saturday_hours=saturday_hours,
            sunday_hours=sunday_hours,
            availability_factor=availability_factor,
        )
        result = self._stamp(record)
        return UserWorkingHoursWriteResult(
            action="create",
            state="confirmed",
            ready=True,
            message="Working-hours schedule created successfully.",
            working_hours_id=result.id,
            user_id=result.user_id,
            payload=payload,
            validation_errors={},
            result=result,
        )

    async def update(
        self,
        user_ref: str,
        working_hours_id: int,
        *,
        valid_from: str | None = None,
        monday_hours: float | None = None,
        tuesday_hours: float | None = None,
        wednesday_hours: float | None = None,
        thursday_hours: float | None = None,
        friday_hours: float | None = None,
        saturday_hours: float | None = None,
        sunday_hours: float | None = None,
        availability_factor: float | None = None,
        confirm: bool = False,
    ) -> UserWorkingHoursWriteResult:
        access.ensure_read_enabled("user_schedule", settings=self._settings)
        current = await self._api.get(user_ref, working_hours_id)
        supplied = {
            "valid_from": valid_from,
            "monday_hours": monday_hours,
            "tuesday_hours": tuesday_hours,
            "wednesday_hours": wednesday_hours,
            "thursday_hours": thursday_hours,
            "friday_hours": friday_hours,
            "saturday_hours": saturday_hours,
            "sunday_hours": sunday_hours,
            "availability_factor": availability_factor,
        }
        payload: dict[str, object] = {}
        for field_name, wire_key in _WRITABLE_FIELDS:
            value = supplied[field_name]
            if value is not None:
                hidden_fields.ensure_field_writable("user_working_hours", field_name, settings=self._settings)
                payload[wire_key] = value
        if not confirm:
            return UserWorkingHoursWriteResult(
                action="update",
                state="preview",
                ready=True,
                message="Ask for confirmation, then call again with confirm=true to write it.",
                working_hours_id=working_hours_id,
                user_id=current.summary.user_id,
                payload=payload,
                validation_errors={},
                result=None,
            )
        access.ensure_write_enabled("user_schedule", settings=self._settings)
        record = await self._api.update(user_ref, working_hours_id, payload=payload)
        result = self._stamp(record)
        return UserWorkingHoursWriteResult(
            action="update",
            state="confirmed",
            ready=True,
            message="Working-hours schedule updated successfully.",
            working_hours_id=result.id,
            user_id=result.user_id,
            payload=payload,
            validation_errors={},
            result=result,
        )

    async def delete(
        self, user_ref: str, working_hours_id: int, *, confirm: bool = False
    ) -> UserWorkingHoursWriteResult:
        access.ensure_read_enabled("user_schedule", settings=self._settings)
        current = await self._api.get(user_ref, working_hours_id)
        payload = {"id": working_hours_id}
        if not confirm:
            return UserWorkingHoursWriteResult(
                action="delete",
                state="preview",
                ready=True,
                message="Ask for confirmation, then call again with confirm=true to delete it.",
                working_hours_id=working_hours_id,
                user_id=current.summary.user_id,
                payload=payload,
                validation_errors={},
                result=None,
            )
        access.ensure_write_enabled("user_schedule", settings=self._settings)
        await self._api.delete(user_ref, working_hours_id)
        return UserWorkingHoursWriteResult(
            action="delete",
            state="confirmed",
            ready=True,
            message="Working-hours schedule deleted successfully.",
            working_hours_id=working_hours_id,
            user_id=current.summary.user_id,
            payload=payload,
            validation_errors={},
            result=None,
        )
