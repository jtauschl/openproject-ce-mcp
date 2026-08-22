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

from mcp.server.mcpserver import Context

from .models import (
    UserNonWorkingTimeListResult,
    UserNonWorkingTimeWriteResult,
    UserWorkingHoursListResult,
    UserWorkingHoursSummary,
    UserWorkingHoursWriteResult,
)
from .tools_runtime import _client_from_context, _run_tool, register_tool
from .tools_validation import (
    _validate_limit,
    _validate_offset,
    _validate_optional_date,
    _validate_optional_non_negative_int,
    _validate_positive_int,
    _validate_required_date,
    _validate_required_query,
)


@register_tool
async def list_user_non_working_times(
    ctx: Context,
    user_ref: str,
    year: int | None = None,
    offset: int = 1,
    limit: int | None = None,
) -> UserNonWorkingTimeListResult:
    """List a user's per-user non-working-time date ranges (e.g. vacation),
    distinct from the instance-wide non-working days (list_non_working_days).

    Requires OpenProject 17.3+ (feature-flag-gated through 17.6, generally
    available from 17.7). Earlier versions return a [server_error] for this
    endpoint — the route does not exist before 17.3.

    OpenProject enforces this at the API level: you may always view your own
    schedule (user_ref="me"); viewing another user's requires the
    manage_working_times global permission, else OpenProject returns 404
    (not 403) to avoid confirming the user exists.

    user_ref: "me" for the current user, a numeric user id, or a login.
    year: filter to this calendar year; defaults to the current year.
    The collection is unpaginated on OpenProject's side — this MCP fetches
    the full requested year and paginates client-side; limit is capped at
    OPENPROJECT_MAX_PAGE_SIZE (default 50).
    """
    client = _client_from_context(ctx)
    safe_user = _validate_required_query(user_ref, field_name="user_ref", max_length=100)
    safe_year = _validate_optional_non_negative_int(year, field_name="year")
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(
        client.list_user_non_working_times(safe_user, year=safe_year, offset=safe_offset, limit=safe_limit)
    )


@register_tool
async def create_user_non_working_time(
    ctx: Context,
    user_ref: str,
    start_date: str,
    end_date: str,
    confirm: bool = False,
) -> UserNonWorkingTimeWriteResult:
    """Prepare or create a non-working-time date range for a user; only
    writes when called again with confirm=true.

    Requires OpenProject 17.3+. Same self-service-or-manage_working_times
    authorization as list_user_non_working_times.

    user_ref: "me" for the current user, a numeric user id, or a login.
    start_date/end_date: ISO 8601 dates (YYYY-MM-DD).
    """
    client = _client_from_context(ctx)
    safe_user = _validate_required_query(user_ref, field_name="user_ref", max_length=100)
    safe_start = _validate_required_date(start_date, field_name="start_date")
    safe_end = _validate_required_date(end_date, field_name="end_date")
    return await _run_tool(
        client.create_user_non_working_time(safe_user, start_date=safe_start, end_date=safe_end, confirm=confirm)
    )


@register_tool
async def update_user_non_working_time(
    ctx: Context,
    user_ref: str,
    non_working_time_id: int,
    start_date: str | None = None,
    end_date: str | None = None,
    confirm: bool = False,
) -> UserNonWorkingTimeWriteResult:
    """Prepare or update a user's non-working-time date range; only writes
    when called again with confirm=true.

    Requires OpenProject 17.3+. Same authorization as
    list_user_non_working_times. No single-item GET exists on OpenProject's
    side for this resource, but the update itself is addressed directly by
    id (no year or other date filter involved) — a non-existent id fails
    with a not-found error.
    """
    client = _client_from_context(ctx)
    safe_user = _validate_required_query(user_ref, field_name="user_ref", max_length=100)
    safe_id = _validate_positive_int(non_working_time_id, field_name="non_working_time_id")
    safe_start = _validate_optional_date(start_date, field_name="start_date")
    safe_end = _validate_optional_date(end_date, field_name="end_date")
    return await _run_tool(
        client.update_user_non_working_time(
            safe_user, safe_id, start_date=safe_start, end_date=safe_end, confirm=confirm
        )
    )


@register_tool
async def delete_user_non_working_time(
    ctx: Context,
    user_ref: str,
    non_working_time_id: int,
    confirm: bool = False,
) -> UserNonWorkingTimeWriteResult:
    """Prepare or delete a user's non-working-time date range; only deletes
    when called again with confirm=true.

    Requires OpenProject 17.3+. Same authorization as
    list_user_non_working_times.
    """
    client = _client_from_context(ctx)
    safe_user = _validate_required_query(user_ref, field_name="user_ref", max_length=100)
    safe_id = _validate_positive_int(non_working_time_id, field_name="non_working_time_id")
    return await _run_tool(client.delete_user_non_working_time(safe_user, safe_id, confirm=confirm))


@register_tool
async def list_user_working_hours(
    ctx: Context,
    user_ref: str,
    offset: int = 1,
    limit: int | None = None,
) -> UserWorkingHoursListResult:
    """List a user's recurring weekly working-hours schedules, ordered by
    valid_from descending (most recent first).

    Requires OpenProject 17.3+ (feature-flag-gated through 17.6, generally
    available from 17.7).

    Same self-service-or-manage_working_times authorization as
    list_user_non_working_times: OpenProject returns 404 (not 403) for an
    unauthorized cross-user request.

    user_ref: "me" for the current user, a numeric user id, or a login.
    The collection is unpaginated on OpenProject's side — this MCP fetches
    the full list and paginates client-side; limit is capped at
    OPENPROJECT_MAX_PAGE_SIZE (default 50).
    """
    client = _client_from_context(ctx)
    safe_user = _validate_required_query(user_ref, field_name="user_ref", max_length=100)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(client.list_user_working_hours(safe_user, offset=safe_offset, limit=safe_limit))


@register_tool
async def get_user_working_hours(
    ctx: Context,
    user_ref: str,
    working_hours_id: int,
) -> UserWorkingHoursSummary:
    """Get a single working-hours schedule entry for a user.

    Requires OpenProject 17.3+. Same authorization as
    list_user_working_hours.
    """
    client = _client_from_context(ctx)
    safe_user = _validate_required_query(user_ref, field_name="user_ref", max_length=100)
    safe_id = _validate_positive_int(working_hours_id, field_name="working_hours_id")
    return await _run_tool(client.get_user_working_hours(safe_user, safe_id))


@register_tool
async def create_user_working_hours(
    ctx: Context,
    user_ref: str,
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
    """Prepare or create a new weekly working-hours schedule version for a
    user, effective from valid_from; only writes when called again with
    confirm=true.

    Requires OpenProject 17.3+. Same self-service-or-manage_working_times
    authorization as list_user_working_hours.

    user_ref: "me" for the current user, a numeric user id, or a login.
    valid_from: ISO 8601 date (YYYY-MM-DD) this schedule version takes effect.
    *_hours: hours worked on that weekday; a weekday you omit is treated as
    0 (not a working day) -- OpenProject requires every weekday to have a
    value on create, so this MCP fills in 0 for you rather than sending an
    incomplete schedule.
    availability_factor: fractional working-time factor (e.g. 0.5 for
    half-time), independent of the per-day hour values.
    """
    client = _client_from_context(ctx)
    safe_user = _validate_required_query(user_ref, field_name="user_ref", max_length=100)
    safe_valid_from = _validate_required_date(valid_from, field_name="valid_from")
    return await _run_tool(
        client.create_user_working_hours(
            safe_user,
            valid_from=safe_valid_from,
            monday_hours=monday_hours,
            tuesday_hours=tuesday_hours,
            wednesday_hours=wednesday_hours,
            thursday_hours=thursday_hours,
            friday_hours=friday_hours,
            saturday_hours=saturday_hours,
            sunday_hours=sunday_hours,
            availability_factor=availability_factor,
            confirm=confirm,
        )
    )


@register_tool
async def update_user_working_hours(
    ctx: Context,
    user_ref: str,
    working_hours_id: int,
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
    """Prepare or update a user's working-hours schedule entry; only writes
    when called again with confirm=true.

    Requires OpenProject 17.3+. Same authorization as list_user_working_hours.
    """
    client = _client_from_context(ctx)
    safe_user = _validate_required_query(user_ref, field_name="user_ref", max_length=100)
    safe_id = _validate_positive_int(working_hours_id, field_name="working_hours_id")
    safe_valid_from = _validate_optional_date(valid_from, field_name="valid_from")
    return await _run_tool(
        client.update_user_working_hours(
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
            availability_factor=availability_factor,
            confirm=confirm,
        )
    )


@register_tool
async def delete_user_working_hours(
    ctx: Context,
    user_ref: str,
    working_hours_id: int,
    confirm: bool = False,
) -> UserWorkingHoursWriteResult:
    """Prepare or delete a user's working-hours schedule entry; only deletes
    when called again with confirm=true.

    Requires OpenProject 17.3+. Same authorization as list_user_working_hours.
    """
    client = _client_from_context(ctx)
    safe_user = _validate_required_query(user_ref, field_name="user_ref", max_length=100)
    safe_id = _validate_positive_int(working_hours_id, field_name="working_hours_id")
    return await _run_tool(client.delete_user_working_hours(safe_user, safe_id, confirm=confirm))
