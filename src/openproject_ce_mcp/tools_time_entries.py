"""Time entries domain MCP tool handlers: list_time_entry_activities,
list_time_entries, get_time_entry, create_time_entry, update_time_entry,
create_time_entry_until, update_time_entry_until, delete_time_entry.

Also holds two private helpers used only by create_time_entry_until/
update_time_entry_until: `_pad_fractional_seconds` (normalizes a date-time's
fractional-seconds fragment to exactly 6 digits before `fromisoformat`) and
`_duration_between` (derives the ISO 8601 `hours` duration OpenProject's API
actually accepts from a caller-supplied start_time/end_time pair, since the
API has no `end_time` write field of its own -- see create_time_entry's
docstring). Neither helper has any caller outside this module.

Their `@register_tool` decorators come from `tools_runtime`, never from
`tools.py` -- see that module's own docstring for why. `tools.py` imports
this module for the decorator's registration side effect and re-exports all
ten names: the eight tool functions because existing tests
(`tests/unit/test_project_and_domain_tools.py`) import all of them directly
from `openproject_ce_mcp.tools`, and both private helpers because
`tests/unit/test_tool_validation.py` imports `_duration_between` and
`_pad_fractional_seconds` directly from `openproject_ce_mcp.tools` too.
"""

from __future__ import annotations

import datetime
import re

from mcp.server.mcpserver import Context

from .models import (
    TimeEntryActivityListResult,
    TimeEntryListResult,
    TimeEntrySummary,
    TimeEntryWriteResult,
)
from .tools_runtime import _client_from_context, _run_tool, register_tool
from .tools_validation import (
    _require_at_least_one,
    _validate_limit,
    _validate_offset,
    _validate_optional_date,
    _validate_optional_datetime,
    _validate_optional_duration,
    _validate_optional_project_ref,
    _validate_optional_query,
    _validate_optional_text,
    _validate_optional_text_limit,
    _validate_optional_update_text,
    _validate_optional_user_or_principal_ref,
    _validate_optional_work_package_ref,
    _validate_positive_int,
    _validate_required_date,
    _validate_required_datetime,
    _validate_required_duration,
    _validate_required_query,
    _validate_select,
)


@register_tool
async def list_time_entry_activities(ctx: Context) -> TimeEntryActivityListResult:
    """List available time entry activities."""
    client = _client_from_context(ctx)
    return await _run_tool(client.time_entry.list_activities())


@register_tool
async def list_time_entries(
    ctx: Context,
    project: str | None = None,
    work_package_id: int | str | None = None,
    user: str | None = None,
    spent_on_from: str | None = None,
    spent_on_to: str | None = None,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
    include_total_hours: bool = False,
) -> TimeEntryListResult:
    """List time entries with optional project, work package, user, and date filters.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.

    select fields: id, hours, spent_on, comment, activity, user, work_package_id
    (see server instructions for select's general semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap. total is only
    the count of allowed time entries returned on THIS page, not a full
    count of all matches — the search stops as soon as it has enough, so an
    exact total would need an extra full walk. Page until next_offset is
    null.

    include_total_hours=true sums `hours` (as an ISO 8601 duration) across
    every matching entry, independent of limit/offset — this runs its own
    full walk of the filtered collection (bounded; see
    total_hours_truncated), since OpenProject has no server-side sum for
    time entries (unlike list_work_packages's include_sums). Leave false
    unless the total is actually needed: it costs extra requests on top of
    the page this call already returns.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_optional_project_ref(project)
    safe_work_package_id = _validate_optional_work_package_ref(work_package_id)
    safe_user = _validate_optional_user_or_principal_ref(user)
    safe_spent_on_from = _validate_optional_date(spent_on_from, field_name="spent_on_from")
    safe_spent_on_to = _validate_optional_date(spent_on_to, field_name="spent_on_to")
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    _validate_select(select, row_type=TimeEntrySummary)
    return await _run_tool(
        client.time_entry.list_all(
            project=safe_project,
            work_package_id=safe_work_package_id,
            user=safe_user,
            spent_on_from=safe_spent_on_from,
            spent_on_to=safe_spent_on_to,
            offset=safe_offset,
            limit=safe_limit,
            include_total_hours=include_total_hours,
        )
    )


@register_tool
async def get_time_entry(
    ctx: Context,
    time_entry_id: int,
    text_limit: int | None = None,
) -> TimeEntrySummary:
    """Get a single time entry by id, including its full comment.

    The comment is returned in full by default (single time entries are not
    truncated). Pass ``text_limit`` to cap it at that many characters; when the
    text is cut, ``comment_truncated`` is true and ``comment_length`` reports
    the real length.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(time_entry_id, field_name="time_entry_id")
    safe_text_limit = _validate_optional_text_limit(text_limit)
    return await _run_tool(client.time_entry.get(safe_id, text_limit=safe_text_limit))


@register_tool
async def create_time_entry(
    ctx: Context,
    activity: str,
    hours: str,
    spent_on: str,
    project: str | None = None,
    work_package_id: int | str | None = None,
    user: str | None = None,
    start_time: str | None = None,
    comment: str | None = None,
    ongoing: bool | None = None,
    confirm: bool = False,
) -> TimeEntryWriteResult:
    """Prepare or create a time entry.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.
    hours accepts an ISO8601 duration string (e.g., 'PT8H' for 8 hours, 'P1D' for 1 day).
    start_time is an ISO 8601 date-time and requires the instance setting "allow
    tracking of start and end times"; ignored otherwise. No end_time parameter --
    OpenProject derives it read-only from start_time + hours. Use
    create_time_entry_until to specify an end time instead of hours directly.
    """
    client = _client_from_context(ctx)
    safe_activity = _validate_required_query(activity, field_name="activity", max_length=100)
    safe_hours = _validate_required_duration(hours, field_name="hours")
    safe_spent_on = _validate_required_date(spent_on, field_name="spent_on")
    safe_project = _validate_optional_project_ref(project)
    safe_work_package_id = _validate_optional_work_package_ref(work_package_id)
    safe_user = _validate_optional_user_or_principal_ref(user)
    safe_start_time = _validate_optional_datetime(start_time, field_name="start_time")
    safe_comment = _validate_optional_text(comment, field_name="comment", max_length=10_000)
    if safe_project is None and safe_work_package_id is None:
        raise ValueError("Either project or work_package_id is required.")
    return await _run_tool(
        client.time_entry.create(
            project=safe_project,
            work_package_id=safe_work_package_id,
            user=safe_user,
            activity=safe_activity,
            hours=safe_hours,
            spent_on=safe_spent_on,
            start_time=safe_start_time,
            comment=safe_comment,
            ongoing=ongoing,
            confirm=confirm,
        )
    )


@register_tool
async def update_time_entry(
    ctx: Context,
    time_entry_id: int,
    user: str | None = None,
    activity: str | None = None,
    hours: str | None = None,
    spent_on: str | None = None,
    start_time: str | None = None,
    comment: str | None = None,
    ongoing: bool | None = None,
    confirm: bool = False,
) -> TimeEntryWriteResult:
    """Prepare or update a time entry.

    hours accepts an ISO8601 duration string (e.g., 'PT8H' for 8 hours, 'P1D' for 1 day).
    start_time is an ISO 8601 date-time. No end_time parameter -- OpenProject
    derives it read-only from start_time + hours. Use update_time_entry_until
    to specify an end time instead of hours directly.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(time_entry_id, field_name="time_entry_id")
    safe_user = _validate_optional_user_or_principal_ref(user)
    safe_activity = _validate_optional_query(activity, field_name="activity", max_length=100)
    safe_hours = _validate_optional_duration(hours, field_name="hours")
    safe_spent_on = _validate_optional_date(spent_on, field_name="spent_on")
    safe_start_time = _validate_optional_datetime(start_time, field_name="start_time")
    safe_comment = _validate_optional_update_text(comment, field_name="comment", max_length=10_000)
    _require_at_least_one(
        safe_user,
        safe_activity,
        safe_hours,
        safe_spent_on,
        safe_start_time,
        safe_comment,
        ongoing,
        message="At least one field to update is required.",
    )
    return await _run_tool(
        client.time_entry.update(
            time_entry_id=safe_id,
            user=safe_user,
            activity=safe_activity,
            hours=safe_hours,
            spent_on=safe_spent_on,
            start_time=safe_start_time,
            comment=safe_comment,
            ongoing=ongoing,
            confirm=confirm,
        )
    )


@register_tool
async def create_time_entry_until(
    ctx: Context,
    activity: str,
    start_time: str,
    end_time: str,
    spent_on: str,
    project: str | None = None,
    work_package_id: int | str | None = None,
    user: str | None = None,
    comment: str | None = None,
    confirm: bool = False,
) -> TimeEntryWriteResult:
    """Prepare or create a time entry by start/end time instead of a duration.

    Computes hours = end_time - start_time locally; only hours and start_time
    are sent to OpenProject (end_time itself is never accepted by the server,
    see create_time_entry's docstring). end_time must be strictly after
    start_time. There is no ongoing parameter here -- a time entry with a
    known end time is complete, not still running; use create_time_entry for
    an ongoing entry.
    """
    client = _client_from_context(ctx)
    safe_activity = _validate_required_query(activity, field_name="activity", max_length=100)
    safe_start_time = _validate_required_datetime(start_time, field_name="start_time")
    safe_end_time = _validate_required_datetime(end_time, field_name="end_time")
    safe_hours = _validate_required_duration(_duration_between(safe_start_time, safe_end_time), field_name="hours")
    safe_spent_on = _validate_required_date(spent_on, field_name="spent_on")
    safe_project = _validate_optional_project_ref(project)
    safe_work_package_id = _validate_optional_work_package_ref(work_package_id)
    safe_user = _validate_optional_user_or_principal_ref(user)
    safe_comment = _validate_optional_text(comment, field_name="comment", max_length=10_000)
    if safe_project is None and safe_work_package_id is None:
        raise ValueError("Either project or work_package_id is required.")
    return await _run_tool(
        client.time_entry.create(
            project=safe_project,
            work_package_id=safe_work_package_id,
            user=safe_user,
            activity=safe_activity,
            hours=safe_hours,
            spent_on=safe_spent_on,
            start_time=safe_start_time,
            comment=safe_comment,
            confirm=confirm,
        )
    )


@register_tool
async def update_time_entry_until(
    ctx: Context,
    time_entry_id: int,
    start_time: str,
    end_time: str,
    user: str | None = None,
    activity: str | None = None,
    spent_on: str | None = None,
    comment: str | None = None,
    confirm: bool = False,
) -> TimeEntryWriteResult:
    """Prepare or update a time entry by start/end time instead of a duration.

    Computes hours = end_time - start_time locally; only hours and start_time
    are sent to OpenProject (end_time itself is never accepted by the server,
    see update_time_entry's docstring). end_time must be strictly after
    start_time. Always sets ongoing=False, since a completed time span with a
    known end time cannot still be running.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(time_entry_id, field_name="time_entry_id")
    safe_start_time = _validate_required_datetime(start_time, field_name="start_time")
    safe_end_time = _validate_required_datetime(end_time, field_name="end_time")
    safe_hours = _validate_required_duration(_duration_between(safe_start_time, safe_end_time), field_name="hours")
    safe_user = _validate_optional_user_or_principal_ref(user)
    safe_activity = _validate_optional_query(activity, field_name="activity", max_length=100)
    safe_spent_on = _validate_optional_date(spent_on, field_name="spent_on")
    safe_comment = _validate_optional_update_text(comment, field_name="comment", max_length=10_000)
    return await _run_tool(
        client.time_entry.update(
            time_entry_id=safe_id,
            user=safe_user,
            activity=safe_activity,
            hours=safe_hours,
            spent_on=safe_spent_on,
            start_time=safe_start_time,
            comment=safe_comment,
            ongoing=False,
            confirm=confirm,
        )
    )


@register_tool
async def delete_time_entry(
    ctx: Context,
    time_entry_id: int,
    confirm: bool = False,
) -> TimeEntryWriteResult:
    """Prepare or delete a time entry."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(time_entry_id, field_name="time_entry_id")
    return await _run_tool(client.time_entry.delete(time_entry_id=safe_id, confirm=confirm))


def _pad_fractional_seconds(value: str) -> str:
    """Pad a `.d{1,6}` fractional-seconds fragment to exactly 6 digits.

    Python's `datetime.fromisoformat` only accepts 0, 3, or 6 fractional
    digits before 3.11 (this project supports 3.10+); the date-time validator
    in tools_validation.py accepts any count from 1 to 6 (matching what
    OpenProject itself accepts), so a value like "09:00:07.5Z" must be
    normalized to "09:00:07.500000Z" before parsing, not just have "Z"
    swapped for "+00:00".
    """
    return re.sub(r"\.(\d{1,6})(?=Z|[+-]\d{2}:\d{2}$)", lambda m: f".{m.group(1):0<6}", value)


def _duration_between(start_time: str, end_time: str) -> str:
    """Compute an ISO 8601 duration string for end_time - start_time.

    Used by create_time_entry_until/update_time_entry_until to derive `hours`
    locally, since OpenProject's API accepts an ISO 8601 duration in `hours`,
    not `end_time`, as a write field (see the create_time_entry docstring).
    Uses timedelta's own exact integer fields (days/seconds/microseconds),
    never total_seconds() -- a float -- for the whole-unit breakdown, so the
    hours/minutes/seconds split is exact by construction.
    """
    start = datetime.datetime.fromisoformat(_pad_fractional_seconds(start_time).replace("Z", "+00:00"))
    end = datetime.datetime.fromisoformat(_pad_fractional_seconds(end_time).replace("Z", "+00:00"))
    delta = end - start
    if delta <= datetime.timedelta(0):
        raise ValueError("end_time must be after start_time.")
    total_seconds = delta.days * 86400 + delta.seconds
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    microseconds = delta.microseconds
    # Durations generated here use a fractional value only on the seconds
    # component; the ISO 8601 duration validator in tools_validation.py
    # accepts that shape. `microseconds` is an exact integer (0-999999) added
    # to the already-whole `seconds`, then formatted with a fixed decimal
    # count (never `%g`/`str(float)`), avoiding both scientific notation on
    # tiny fractions and any rounding-induced carry.
    if microseconds:
        seconds_str = f"{seconds + microseconds / 1_000_000:.6f}".rstrip("0").rstrip(".")
    else:
        seconds_str = str(seconds)
    parts = [
        f"{hours}H" if hours else "",
        f"{minutes}M" if minutes else "",
        f"{seconds_str}S" if seconds or microseconds else "",
    ]
    body = "".join(p for p in parts if p)
    return f"PT{body}"
