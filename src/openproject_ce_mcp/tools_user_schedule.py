"""User Schedule domain MCP tool handlers: list_user_non_working_times,
create_user_non_working_time, update_user_non_working_time,
delete_user_non_working_time, list_user_working_hours, get_user_working_hours,
create_user_working_hours, update_user_working_hours,
delete_user_working_hours.

Their `@register_tool` decorators come from `tools_runtime`, never from
`tools.py` -- see that module's own docstring for why. `tools.py` imports
this module for the decorator's registration side effect only; unlike the
Reminders/Versions/Boards splits, it does not re-export these names, because
no existing test imports any of them directly from `openproject_ce_mcp.tools`
(the integration tests that reference names like `create_user_working_hours`
call the `OpenProjectClient` method of that name, not this MCP-wrapper
function).
"""

from __future__ import annotations

from typing import Annotated

from mcp.server.mcpserver import Context
from pydantic import Field

from .models import (
    UserNonWorkingTimeListResult,
    UserNonWorkingTimeWriteResult,
    UserWorkingHoursListResult,
    UserWorkingHoursSummary,
    UserWorkingHoursWriteResult,
)
from .tool_params import Confirm, Limit, Offset
from .tool_types import IdOrName
from .tools_runtime import _client_from_context, _run_tool, register_tool
from .tools_validation import (
    _validate_limit,
    _validate_offset,
    _validate_optional_date,
    _validate_optional_non_negative_int,
    _validate_optional_percentage,
    _validate_positive_int,
    _validate_ref,
    _validate_required_date,
)

_USER_REF = '"me", a numeric user id, or a login.'
_HOURS = "Hours that day, 0 to 24; at least one day must be above 0."
# OpenProject requires every day on create, and 17.3 to 17.8 answer a missing
# one with a raw 500 instead of a validation error, so an omitted day is sent as 0.
_NEW_HOURS = "Hours that day, 0 to 24; omitted means 0 (not a working day). At least one day must be above 0."
_AVAILABILITY = "Percentage of the working time dedicated to project work: pass a whole number 0 to 100."


@register_tool
async def list_user_non_working_times(
    ctx: Context,
    user_ref: IdOrName,
    year: int | None = None,
    offset: Offset = 1,
    limit: Limit = None,
) -> UserNonWorkingTimeListResult:
    """List a user's per-user non-working-time date ranges (e.g. vacation),
    distinct from the instance-wide non-working days.

    Requires OpenProject 17.3+ (feature-flag-gated through 17.6, generally
    available from 17.7). On an older server, or on 17.3 to 17.6 with the
    feature flag off, the route answers 404 and the tool returns a
    [RESOURCE_NOT_FOUND] naming the 17.3 floor.

    OpenProject enforces this at the API level: you may always view your own
    schedule (user_ref="me"); viewing another user's requires the
    manage_working_times global permission, else OpenProject returns 404
    (not 403) to avoid confirming the user exists.

    user_ref: "me" for the current user, a numeric user id, or a login.
    year: filter to this calendar year; defaults to the current year.
    The collection is unpaginated on OpenProject's side; this MCP fetches
    the full requested year and paginates client-side; limit is capped at
    OPENPROJECT_MAX_PAGE_SIZE (default 50).
    """
    client = _client_from_context(ctx)
    safe_user = _validate_ref(user_ref, field_name="user_ref", max_length=100)
    safe_year = _validate_optional_non_negative_int(year, field_name="year")
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(
        client.user_non_working_time.list_for_user(safe_user, year=safe_year, offset=safe_offset, limit=safe_limit)
    )


@register_tool
async def create_user_non_working_time(
    ctx: Context,
    user_ref: IdOrName,
    start_date: str,
    end_date: str,
    confirm: Confirm = False,
) -> UserNonWorkingTimeWriteResult:
    """Create a non-working-time date range for a user.

    Requires OpenProject 17.3+. Same self-service-or-manage_working_times
    authorization as list_user_non_working_times.

    user_ref: "me" for the current user, a numeric user id, or a login.
    start_date/end_date: ISO 8601 dates (YYYY-MM-DD).
    """
    client = _client_from_context(ctx)
    safe_user = _validate_ref(user_ref, field_name="user_ref", max_length=100)
    safe_start = _validate_required_date(start_date, field_name="start_date")
    safe_end = _validate_required_date(end_date, field_name="end_date")
    return await _run_tool(
        client.user_non_working_time.create(safe_user, start_date=safe_start, end_date=safe_end, confirm=confirm)
    )


@register_tool
async def update_user_non_working_time(
    ctx: Context,
    user_ref: IdOrName,
    non_working_time_id: int,
    start_date: str | None = None,
    end_date: str | None = None,
    confirm: Confirm = False,
) -> UserNonWorkingTimeWriteResult:
    """Update a user's non-working-time date range.

    Requires OpenProject 17.3+. Same authorization as
    list_user_non_working_times. No single-item GET exists on OpenProject's
    side for this resource, but the update itself is addressed directly by
    id (no year or other date filter involved); a non-existent id fails
    with a not-found error on confirm; the preview does not look it up.
    """
    client = _client_from_context(ctx)
    safe_user = _validate_ref(user_ref, field_name="user_ref", max_length=100)
    safe_id = _validate_positive_int(non_working_time_id, field_name="non_working_time_id")
    safe_start = _validate_optional_date(start_date, field_name="start_date")
    safe_end = _validate_optional_date(end_date, field_name="end_date")
    return await _run_tool(
        client.user_non_working_time.update(
            safe_user, safe_id, start_date=safe_start, end_date=safe_end, confirm=confirm
        )
    )


@register_tool
async def delete_user_non_working_time(
    ctx: Context,
    user_ref: IdOrName,
    non_working_time_id: int,
    confirm: Confirm = False,
) -> UserNonWorkingTimeWriteResult:
    """Delete a user's non-working-time date range; this cannot be undone.

    Requires OpenProject 17.3+. Same authorization as
    list_user_non_working_times.
    """
    client = _client_from_context(ctx)
    safe_user = _validate_ref(user_ref, field_name="user_ref", max_length=100)
    safe_id = _validate_positive_int(non_working_time_id, field_name="non_working_time_id")
    return await _run_tool(client.user_non_working_time.delete(safe_user, safe_id, confirm=confirm))


@register_tool
async def list_user_working_hours(
    ctx: Context,
    user_ref: IdOrName,
    offset: Offset = 1,
    limit: Limit = None,
) -> UserWorkingHoursListResult:
    """List a user's recurring weekly working-hours schedules, ordered by
    valid_from descending (most recent first).

    Requires OpenProject 17.3+ (feature-flag-gated through 17.6, generally
    available from 17.7).

    Same self-service-or-manage_working_times authorization as
    list_user_non_working_times: OpenProject returns 404 (not 403) for an
    unauthorized cross-user request.

    user_ref: "me" for the current user, a numeric user id, or a login.
    The collection is unpaginated on OpenProject's side; this MCP fetches
    the full list and paginates client-side; limit is capped at
    OPENPROJECT_MAX_PAGE_SIZE (default 50).
    """
    client = _client_from_context(ctx)
    safe_user = _validate_ref(user_ref, field_name="user_ref", max_length=100)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(client.user_working_hours.list_for_user(safe_user, offset=safe_offset, limit=safe_limit))


@register_tool
async def get_user_working_hours(
    ctx: Context,
    user_ref: Annotated[IdOrName, Field(description=_USER_REF)],
    working_hours_id: Annotated[int, Field(description="Schedule entry id, from list_user_working_hours.")],
) -> UserWorkingHoursSummary:
    """Get a single working-hours schedule entry for a user.

    Requires OpenProject 17.3+. Same authorization as
    list_user_working_hours.
    """
    client = _client_from_context(ctx)
    safe_user = _validate_ref(user_ref, field_name="user_ref", max_length=100)
    safe_id = _validate_positive_int(working_hours_id, field_name="working_hours_id")
    return await _run_tool(client.user_working_hours.get(safe_user, safe_id))


@register_tool
async def create_user_working_hours(
    ctx: Context,
    user_ref: Annotated[IdOrName, Field(description=_USER_REF)],
    valid_from: Annotated[
        str, Field(description="Date (YYYY-MM-DD) this schedule version takes effect; unique per user.")
    ],
    monday_hours: Annotated[float | None, Field(description=_NEW_HOURS)] = None,
    tuesday_hours: Annotated[float | None, Field(description=_NEW_HOURS)] = None,
    wednesday_hours: Annotated[float | None, Field(description=_NEW_HOURS)] = None,
    thursday_hours: Annotated[float | None, Field(description=_NEW_HOURS)] = None,
    friday_hours: Annotated[float | None, Field(description=_NEW_HOURS)] = None,
    saturday_hours: Annotated[float | None, Field(description=_NEW_HOURS)] = None,
    sunday_hours: Annotated[float | None, Field(description=_NEW_HOURS)] = None,
    availability_factor: Annotated[int | None, Field(description=_AVAILABILITY)] = None,
    confirm: Confirm = False,
) -> UserWorkingHoursWriteResult:
    """Create a new weekly working-hours schedule version for a user, effective from valid_from.

    Requires OpenProject 17.3+. Same self-service-or-manage_working_times
    authorization as list_user_working_hours. The earlier version keeps
    applying to the dates before valid_from.
    """
    client = _client_from_context(ctx)
    safe_user = _validate_ref(user_ref, field_name="user_ref", max_length=100)
    safe_valid_from = _validate_required_date(valid_from, field_name="valid_from")
    safe_availability = _validate_optional_percentage(availability_factor, field_name="availability_factor")
    return await _run_tool(
        client.user_working_hours.create(
            safe_user,
            valid_from=safe_valid_from,
            monday_hours=monday_hours,
            tuesday_hours=tuesday_hours,
            wednesday_hours=wednesday_hours,
            thursday_hours=thursday_hours,
            friday_hours=friday_hours,
            saturday_hours=saturday_hours,
            sunday_hours=sunday_hours,
            availability_factor=safe_availability,
            confirm=confirm,
        )
    )


@register_tool
async def update_user_working_hours(
    ctx: Context,
    user_ref: Annotated[IdOrName, Field(description=_USER_REF)],
    working_hours_id: Annotated[int, Field(description="Schedule entry id, from list_user_working_hours.")],
    valid_from: Annotated[
        str | None,
        Field(description="New start date (YYYY-MM-DD) of this entry; unique per user."),
    ] = None,
    monday_hours: Annotated[float | None, Field(description=_HOURS)] = None,
    tuesday_hours: Annotated[float | None, Field(description=_HOURS)] = None,
    wednesday_hours: Annotated[float | None, Field(description=_HOURS)] = None,
    thursday_hours: Annotated[float | None, Field(description=_HOURS)] = None,
    friday_hours: Annotated[float | None, Field(description=_HOURS)] = None,
    saturday_hours: Annotated[float | None, Field(description=_HOURS)] = None,
    sunday_hours: Annotated[float | None, Field(description=_HOURS)] = None,
    availability_factor: Annotated[int | None, Field(description=_AVAILABILITY)] = None,
    confirm: Confirm = False,
) -> UserWorkingHoursWriteResult:
    """Correct an existing working-hours schedule entry in place; omitted fields stay unchanged.

    Requires OpenProject 17.3+. Same authorization as list_user_working_hours. The entry applies from its
    valid_from until the next entry's; to change a schedule from a later date on, add a new entry with
    create_user_working_hours instead, which keeps the earlier one for the dates before.
    """
    client = _client_from_context(ctx)
    safe_user = _validate_ref(user_ref, field_name="user_ref", max_length=100)
    safe_id = _validate_positive_int(working_hours_id, field_name="working_hours_id")
    safe_valid_from = _validate_optional_date(valid_from, field_name="valid_from")
    safe_availability = _validate_optional_percentage(availability_factor, field_name="availability_factor")
    return await _run_tool(
        client.user_working_hours.update(
            safe_user,
            safe_id,
            valid_from=safe_valid_from,
            monday_hours=monday_hours,
            tuesday_hours=tuesday_hours,
            wednesday_hours=wednesday_hours,
            thursday_hours=thursday_hours,
            friday_hours=friday_hours,
            saturday_hours=saturday_hours,
            sunday_hours=sunday_hours,
            availability_factor=safe_availability,
            confirm=confirm,
        )
    )


@register_tool
async def delete_user_working_hours(
    ctx: Context,
    user_ref: IdOrName,
    working_hours_id: int,
    confirm: Confirm = False,
) -> UserWorkingHoursWriteResult:
    """Delete a user's working-hours schedule entry; this cannot be undone.

    Requires OpenProject 17.3+. Same authorization as list_user_working_hours. For the dates it covered, the
    previous entry applies again.
    """
    client = _client_from_context(ctx)
    safe_user = _validate_ref(user_ref, field_name="user_ref", max_length=100)
    safe_id = _validate_positive_int(working_hours_id, field_name="working_hours_id")
    return await _run_tool(client.user_working_hours.delete(safe_user, safe_id, confirm=confirm))
