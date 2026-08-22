"""Meeting domain MCP tool handlers: list_meetings, get_meeting, create_meeting,
update_meeting, delete_meeting, list_meeting_agenda_items,
list_work_package_meeting_agenda_items, get_meeting_agenda_item,
create_meeting_agenda_item, update_meeting_agenda_item,
delete_meeting_agenda_item, list_meeting_outcomes, get_meeting_outcome,
create_meeting_outcome, update_meeting_outcome, delete_meeting_outcome,
list_meeting_sections, get_meeting_section, create_meeting_section,
update_meeting_section, delete_meeting_section, list_recurring_meetings,
get_recurring_meeting, create_recurring_meeting, update_recurring_meeting,
delete_recurring_meeting, list_recurring_meeting_occurrences,
init_recurring_meeting_occurrence, cancel_recurring_meeting_occurrence.

Their `@register_tool` decorators come from `tools_runtime`, never from
`tools.py` -- see that module's own docstring for why. `tools.py` imports
this module for the decorator's registration side effect and re-exports
three of the twenty-nine names -- `list_meeting_agenda_items`,
`list_meeting_outcomes`, `list_work_package_meeting_agenda_items` -- because
existing tests (`tests/test_trimming.py`) import them directly from
`openproject_ce_mcp.tools`; the other twenty-six are not re-exported.
"""

from __future__ import annotations

from mcp.server.mcpserver import Context

from .models import (
    MeetingAgendaItemListResult,
    MeetingAgendaItemSummary,
    MeetingAgendaItemWriteResult,
    MeetingListResult,
    MeetingOutcomeListResult,
    MeetingOutcomeSummary,
    MeetingOutcomeWriteResult,
    MeetingSectionListResult,
    MeetingSectionSummary,
    MeetingSectionWriteResult,
    MeetingSummary,
    MeetingWriteResult,
    RecurringMeetingListResult,
    RecurringMeetingOccurrenceListResult,
    RecurringMeetingOccurrenceWriteResult,
    RecurringMeetingSummary,
    RecurringMeetingWriteResult,
)
from .tools_runtime import _client_from_context, _run_tool, register_tool
from .tools_validation import (
    _require_at_least_one,
    _validate_choice,
    _validate_limit,
    _validate_offset,
    _validate_optional_choice,
    _validate_optional_date,
    _validate_optional_datetime,
    _validate_optional_duration,
    _validate_optional_project_ref,
    _validate_optional_query,
    _validate_optional_text,
    _validate_optional_text_limit,
    _validate_optional_update_text,
    _validate_optional_work_package_ref,
    _validate_participant_refs,
    _validate_positive_int,
    _validate_project_ref,
    _validate_required_datetime,
    _validate_required_text,
    _validate_select,
    _validate_work_package_ref,
)

# Real enum values from MeetingOutcome (op-sources: modules/meeting/app/models/
# meeting_outcome.rb) -- OpenProject itself rejects any other value with an
# internal server error (500), not a clean 422, so this must be checked
# client-side rather than left to the server's own validation.
_MEETING_OUTCOME_KINDS = {"information", "decision", "work_package"}


@register_tool
async def list_meetings(
    ctx: Context,
    project: str | None = None,
    offset: int = 1,
    limit: int | None = None,
) -> MeetingListResult:
    """List OpenProject meetings, optionally scoped to a project.

    Requires OpenProject 17.4+ — the meetings module's agenda/section/
    participant shape used here does not exist on 16.6, which only exposes
    an incompatible legacy "meeting contents" representation.

    project: identifier, name, or numeric id. Omit to list across all
    readable projects.

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the
    returned next_offset as the next call's offset to page past the cap.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_optional_project_ref(project)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(client.list_meetings(project=safe_project, offset=safe_offset, limit=safe_limit))


@register_tool
async def get_meeting(ctx: Context, meeting_id: int) -> MeetingSummary:
    """Get a single OpenProject meeting by id.

    Requires OpenProject 17.4+.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(meeting_id, field_name="meeting_id")
    return await _run_tool(client.get_meeting(safe_id))


@register_tool
async def create_meeting(
    ctx: Context,
    project: str,
    title: str,
    location: str | None = None,
    start_time: str | None = None,
    duration: str | None = None,
    state: str | None = None,
    sharing: str | None = None,
    notify: bool | None = None,
    participant_user_refs: list[str] | None = None,
    confirm: bool = False,
) -> MeetingWriteResult:
    """Prepare or create an OpenProject meeting; only writes when called
    again with confirm=true.

    Requires OpenProject 17.4+.

    project: identifier, name, or numeric id — required, every meeting
    belongs to exactly one project.
    duration: an ISO 8601 duration like "PT1H30M" (hours/minutes only).
    state: meeting state (e.g. "open", "closed") — pass the value as
    returned by list_meetings/get_meeting.
    participant_user_refs: list of user references (numeric id, login, or
    name) to invite as participants.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    safe_title = _validate_required_text(title, field_name="title", max_length=255)
    safe_location = _validate_optional_text(location, field_name="location", max_length=255)
    safe_start = _validate_optional_datetime(start_time, field_name="start_time")
    safe_duration = _validate_optional_duration(duration, field_name="duration")
    safe_participants = _validate_participant_refs(participant_user_refs)
    return await _run_tool(
        client.create_meeting(
            project=safe_project,
            title=safe_title,
            location=safe_location,
            start_time=safe_start,
            duration=safe_duration,
            state=state,
            sharing=sharing,
            notify=notify,
            participant_user_refs=safe_participants,
            confirm=confirm,
        )
    )


@register_tool
async def update_meeting(
    ctx: Context,
    meeting_id: int,
    title: str | None = None,
    location: str | None = None,
    start_time: str | None = None,
    duration: str | None = None,
    state: str | None = None,
    sharing: str | None = None,
    notify: bool | None = None,
    participant_user_refs: list[str] | None = None,
    lock_version: int | None = None,
    confirm: bool = False,
) -> MeetingWriteResult:
    """Prepare or update an OpenProject meeting; only writes when called
    again with confirm=true.

    Requires OpenProject 17.4+.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(meeting_id, field_name="meeting_id")
    safe_title = _validate_optional_query(title, field_name="title", max_length=255)
    safe_location = _validate_optional_text(location, field_name="location", max_length=255)
    safe_start = _validate_optional_datetime(start_time, field_name="start_time")
    safe_duration = _validate_optional_duration(duration, field_name="duration")
    safe_participants = _validate_participant_refs(participant_user_refs)
    _require_at_least_one(
        safe_title,
        safe_location,
        safe_start,
        safe_duration,
        state,
        sharing,
        notify,
        safe_participants,
        lock_version,
        message="At least one field to update is required.",
    )
    return await _run_tool(
        client.update_meeting(
            meeting_id=safe_id,
            title=safe_title,
            location=safe_location,
            start_time=safe_start,
            duration=safe_duration,
            state=state,
            sharing=sharing,
            notify=notify,
            participant_user_refs=safe_participants,
            lock_version=lock_version,
            confirm=confirm,
        )
    )


@register_tool
async def delete_meeting(ctx: Context, meeting_id: int, confirm: bool = False) -> MeetingWriteResult:
    """Prepare or delete an OpenProject meeting; only deletes when called
    again with confirm=true.

    Requires OpenProject 17.4+.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(meeting_id, field_name="meeting_id")
    return await _run_tool(client.delete_meeting(meeting_id=safe_id, confirm=confirm))


@register_tool
async def list_meeting_agenda_items(
    ctx: Context,
    meeting_id: int,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
    text_limit: int | None = None,
) -> MeetingAgendaItemListResult:
    """List agenda items of an OpenProject meeting.

    Requires OpenProject 17.4+.

    This list is unpaginated server-side (OpenProject returns every agenda
    item of the meeting in one response) — offset/limit are applied
    client-side by this MCP.

    select fields: id, title, notes (see server instructions for select's
    general semantics).

    text_limit caps each item's notes at that many characters (default: the
    server's configured OPENPROJECT_TEXT_LIMIT, NOT unlimited). When text is
    cut, notes_truncated is true and notes_length reports the real length.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(meeting_id, field_name="meeting_id")
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    _validate_select(select, row_type=MeetingAgendaItemSummary)
    safe_text_limit = _validate_optional_text_limit(text_limit)
    return await _run_tool(
        client.list_meeting_agenda_items(safe_id, offset=safe_offset, limit=safe_limit, text_limit=safe_text_limit)
    )


@register_tool
async def list_work_package_meeting_agenda_items(
    ctx: Context,
    work_package_id: int | str,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
    text_limit: int | None = None,
) -> MeetingAgendaItemListResult:
    """List meeting agenda items linked to a work package.

    Requires OpenProject 17.4+.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.

    This list is unpaginated server-side — offset/limit are applied
    client-side by this MCP.

    select fields: id, title, notes (see server instructions for select's
    general semantics).

    text_limit caps each item's notes at that many characters (default: the
    server's configured OPENPROJECT_TEXT_LIMIT, NOT unlimited). When text is
    cut, notes_truncated is true and notes_length reports the real length.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    _validate_select(select, row_type=MeetingAgendaItemSummary)
    safe_text_limit = _validate_optional_text_limit(text_limit)
    return await _run_tool(
        client.list_work_package_meeting_agenda_items(
            safe_id, offset=safe_offset, limit=safe_limit, text_limit=safe_text_limit
        )
    )


@register_tool
async def get_meeting_agenda_item(ctx: Context, agenda_item_id: int) -> MeetingAgendaItemSummary:
    """Get a single meeting agenda item by id.

    Requires OpenProject 17.4+.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(agenda_item_id, field_name="agenda_item_id")
    return await _run_tool(client.get_meeting_agenda_item(safe_id))


@register_tool
async def create_meeting_agenda_item(
    ctx: Context,
    meeting_id: int,
    title: str,
    notes: str | None = None,
    duration_in_minutes: int | None = None,
    item_type: str | None = None,
    work_package_id: int | str | None = None,
    meeting_section_id: int | None = None,
    confirm: bool = False,
) -> MeetingAgendaItemWriteResult:
    """Prepare or create a meeting agenda item; only writes when called
    again with confirm=true.

    Requires OpenProject 17.4+.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number; optional.
    meeting_section_id: an existing section's id (from list_meeting_sections); optional.
    """
    client = _client_from_context(ctx)
    safe_meeting_id = _validate_positive_int(meeting_id, field_name="meeting_id")
    safe_title = _validate_required_text(title, field_name="title", max_length=255)
    safe_notes = _validate_optional_text(notes, field_name="notes", max_length=50_000)
    safe_work_package_id = _validate_optional_work_package_ref(work_package_id)
    safe_section_id = (
        _validate_positive_int(meeting_section_id, field_name="meeting_section_id")
        if meeting_section_id is not None
        else None
    )
    return await _run_tool(
        client.create_meeting_agenda_item(
            meeting_id=safe_meeting_id,
            title=safe_title,
            notes=safe_notes,
            duration_in_minutes=duration_in_minutes,
            item_type=item_type,
            work_package_id=safe_work_package_id,
            meeting_section_id=safe_section_id,
            confirm=confirm,
        )
    )


@register_tool
async def update_meeting_agenda_item(
    ctx: Context,
    agenda_item_id: int,
    title: str | None = None,
    notes: str | None = None,
    duration_in_minutes: int | None = None,
    item_type: str | None = None,
    work_package_id: int | str | None = None,
    meeting_section_id: int | None = None,
    confirm: bool = False,
) -> MeetingAgendaItemWriteResult:
    """Prepare or update a meeting agenda item; only writes when called
    again with confirm=true.

    Requires OpenProject 17.4+.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(agenda_item_id, field_name="agenda_item_id")
    safe_title = _validate_optional_query(title, field_name="title", max_length=255)
    safe_notes = _validate_optional_update_text(notes, field_name="notes", max_length=50_000)
    safe_work_package_id = _validate_optional_work_package_ref(work_package_id)
    safe_section_id = (
        _validate_positive_int(meeting_section_id, field_name="meeting_section_id")
        if meeting_section_id is not None
        else None
    )
    _require_at_least_one(
        safe_title,
        safe_notes,
        duration_in_minutes,
        item_type,
        safe_work_package_id,
        safe_section_id,
        message="At least one field to update is required.",
    )
    return await _run_tool(
        client.update_meeting_agenda_item(
            agenda_item_id=safe_id,
            title=safe_title,
            notes=safe_notes,
            duration_in_minutes=duration_in_minutes,
            item_type=item_type,
            work_package_id=safe_work_package_id,
            meeting_section_id=safe_section_id,
            confirm=confirm,
        )
    )


@register_tool
async def delete_meeting_agenda_item(
    ctx: Context, agenda_item_id: int, confirm: bool = False
) -> MeetingAgendaItemWriteResult:
    """Prepare or delete a meeting agenda item; only deletes when called
    again with confirm=true.

    Requires OpenProject 17.4+.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(agenda_item_id, field_name="agenda_item_id")
    return await _run_tool(client.delete_meeting_agenda_item(agenda_item_id=safe_id, confirm=confirm))


@register_tool
async def list_meeting_outcomes(
    ctx: Context,
    agenda_item_id: int,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
    text_limit: int | None = None,
) -> MeetingOutcomeListResult:
    """List outcomes of a meeting agenda item.

    Requires OpenProject 17.6+ — the meeting_outcomes endpoint does not exist
    on 17.4/17.5.

    This list is unpaginated server-side — offset/limit are applied
    client-side by this MCP.

    select fields: id, kind, notes (see server instructions for select's
    general semantics).

    text_limit caps each outcome's notes at that many characters (default:
    the server's configured OPENPROJECT_TEXT_LIMIT, NOT unlimited). When text
    is cut, notes_truncated is true and notes_length reports the real length.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(agenda_item_id, field_name="agenda_item_id")
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    _validate_select(select, row_type=MeetingOutcomeSummary)
    safe_text_limit = _validate_optional_text_limit(text_limit)
    return await _run_tool(
        client.list_meeting_outcomes(safe_id, offset=safe_offset, limit=safe_limit, text_limit=safe_text_limit)
    )


@register_tool
async def get_meeting_outcome(ctx: Context, outcome_id: int) -> MeetingOutcomeSummary:
    """Get a single meeting outcome by id.

    Requires OpenProject 17.6+.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(outcome_id, field_name="outcome_id")
    return await _run_tool(client.get_meeting_outcome(safe_id))


@register_tool
async def create_meeting_outcome(
    ctx: Context,
    agenda_item_id: int,
    kind: str,
    notes: str | None = None,
    work_package_id: int | str | None = None,
    confirm: bool = False,
) -> MeetingOutcomeWriteResult:
    """Prepare or create a meeting outcome on an agenda item; only writes
    when called again with confirm=true.

    Requires OpenProject 17.6+.

    kind must be one of "information", "decision", "work_package" (OpenProject's
    real enum values — not e.g. "info" or "action", which OpenProject rejects
    with an internal server error rather than a clean validation error).
    "information"-kind outcomes require notes; "work_package"-kind outcomes
    require work_package_id.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number; optional.
    """
    client = _client_from_context(ctx)
    safe_agenda_item_id = _validate_positive_int(agenda_item_id, field_name="agenda_item_id")
    safe_kind = _validate_choice(kind, field_name="kind", allowed_values=_MEETING_OUTCOME_KINDS)
    safe_notes = _validate_optional_text(notes, field_name="notes", max_length=50_000)
    safe_work_package_id = _validate_optional_work_package_ref(work_package_id)
    safe_work_package_numeric_id = (
        int(safe_work_package_id) if safe_work_package_id is not None and safe_work_package_id.isdigit() else None
    )
    return await _run_tool(
        client.create_meeting_outcome(
            agenda_item_id=safe_agenda_item_id,
            kind=safe_kind,
            notes=safe_notes,
            work_package_id=safe_work_package_numeric_id,
            confirm=confirm,
        )
    )


@register_tool
async def update_meeting_outcome(
    ctx: Context,
    outcome_id: int,
    kind: str | None = None,
    notes: str | None = None,
    work_package_id: int | str | None = None,
    confirm: bool = False,
) -> MeetingOutcomeWriteResult:
    """Prepare or update a meeting outcome; only writes when called again
    with confirm=true.

    Requires OpenProject 17.6+.

    kind, if given, must be one of "information", "decision", "work_package"
    (OpenProject's real enum values — not e.g. "info" or "action", which
    OpenProject rejects with an internal server error rather than a clean
    validation error).
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(outcome_id, field_name="outcome_id")
    safe_kind = _validate_optional_choice(kind, field_name="kind", allowed_values=_MEETING_OUTCOME_KINDS)
    safe_notes = _validate_optional_update_text(notes, field_name="notes", max_length=50_000)
    safe_work_package_id = _validate_optional_work_package_ref(work_package_id)
    safe_work_package_numeric_id = (
        int(safe_work_package_id) if safe_work_package_id is not None and safe_work_package_id.isdigit() else None
    )
    _require_at_least_one(
        safe_kind, safe_notes, safe_work_package_numeric_id, message="At least one field to update is required."
    )
    return await _run_tool(
        client.update_meeting_outcome(
            outcome_id=safe_id,
            kind=safe_kind,
            notes=safe_notes,
            work_package_id=safe_work_package_numeric_id,
            confirm=confirm,
        )
    )


@register_tool
async def delete_meeting_outcome(ctx: Context, outcome_id: int, confirm: bool = False) -> MeetingOutcomeWriteResult:
    """Prepare or delete a meeting outcome; only deletes when called again
    with confirm=true.

    Requires OpenProject 17.6+.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(outcome_id, field_name="outcome_id")
    return await _run_tool(client.delete_meeting_outcome(outcome_id=safe_id, confirm=confirm))


@register_tool
async def list_meeting_sections(
    ctx: Context,
    meeting_id: int,
    offset: int = 1,
    limit: int | None = None,
) -> MeetingSectionListResult:
    """List sections of an OpenProject meeting.

    Requires OpenProject 17.4+.

    This list is unpaginated server-side — offset/limit are applied
    client-side by this MCP.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(meeting_id, field_name="meeting_id")
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(client.list_meeting_sections(safe_id, offset=safe_offset, limit=safe_limit))


@register_tool
async def get_meeting_section(ctx: Context, section_id: int) -> MeetingSectionSummary:
    """Get a single meeting section by id.

    Requires OpenProject 17.4+.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(section_id, field_name="section_id")
    return await _run_tool(client.get_meeting_section(safe_id))


@register_tool
async def create_meeting_section(
    ctx: Context,
    meeting_id: int,
    title: str,
    position: int | None = None,
    backlog: bool | None = None,
    confirm: bool = False,
) -> MeetingSectionWriteResult:
    """Prepare or create a meeting section; only writes when called again
    with confirm=true.

    Requires OpenProject 17.4+.

    backlog cannot be changed after creation via update_meeting_section —
    pass it only here, on create.
    """
    client = _client_from_context(ctx)
    safe_meeting_id = _validate_positive_int(meeting_id, field_name="meeting_id")
    safe_title = _validate_required_text(title, field_name="title", max_length=255)
    return await _run_tool(
        client.create_meeting_section(
            meeting_id=safe_meeting_id, title=safe_title, position=position, backlog=backlog, confirm=confirm
        )
    )


@register_tool
async def update_meeting_section(
    ctx: Context,
    section_id: int,
    title: str | None = None,
    position: int | None = None,
    confirm: bool = False,
) -> MeetingSectionWriteResult:
    """Prepare or update a meeting section's title/position; only writes
    when called again with confirm=true.

    Requires OpenProject 17.4+.

    backlog cannot be changed after creation — this tool does not accept it.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(section_id, field_name="section_id")
    safe_title = _validate_optional_query(title, field_name="title", max_length=255)
    _require_at_least_one(safe_title, position, message="At least one field to update is required.")
    return await _run_tool(
        client.update_meeting_section(section_id=safe_id, title=safe_title, position=position, confirm=confirm)
    )


@register_tool
async def delete_meeting_section(ctx: Context, section_id: int, confirm: bool = False) -> MeetingSectionWriteResult:
    """Prepare or delete a meeting section; only deletes when called again
    with confirm=true.

    Requires OpenProject 17.4+.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(section_id, field_name="section_id")
    return await _run_tool(client.delete_meeting_section(section_id=safe_id, confirm=confirm))


@register_tool
async def list_recurring_meetings(
    ctx: Context,
    project: str | None = None,
    offset: int = 1,
    limit: int | None = None,
) -> RecurringMeetingListResult:
    """List OpenProject recurring meeting series, optionally scoped to a project.

    Requires OpenProject 17.4+.

    project: identifier, name, or numeric id. Omit to list across all
    readable projects.

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the
    returned next_offset as the next call's offset to page past the cap.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_optional_project_ref(project)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(client.list_recurring_meetings(project=safe_project, offset=safe_offset, limit=safe_limit))


@register_tool
async def get_recurring_meeting(ctx: Context, recurring_meeting_id: int) -> RecurringMeetingSummary:
    """Get a single OpenProject recurring meeting series by id.

    Requires OpenProject 17.4+.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(recurring_meeting_id, field_name="recurring_meeting_id")
    return await _run_tool(client.get_recurring_meeting(safe_id))


@register_tool
async def create_recurring_meeting(
    ctx: Context,
    project: str,
    title: str,
    frequency: str,
    start_time: str,
    interval: int | None = None,
    end_after: str | None = None,
    end_date: str | None = None,
    iterations: int | None = None,
    monthly_day: int | None = None,
    monthly_ordinal: str | None = None,
    monthly_weekday: str | None = None,
    confirm: bool = False,
) -> RecurringMeetingWriteResult:
    """Prepare or create an OpenProject recurring meeting series; only
    writes when called again with confirm=true.

    Requires OpenProject 17.4+.

    project: identifier, name, or numeric id — required, every recurring
    meeting belongs to exactly one project.
    frequency: e.g. "daily", "weekly", "monthly" — pass the value as
    returned by list_recurring_meetings/get_recurring_meeting.
    end_after: e.g. "date", "iterations", "never" — governs which of
    end_date/iterations is used.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    safe_title = _validate_required_text(title, field_name="title", max_length=255)
    safe_frequency = _validate_required_text(frequency, field_name="frequency", max_length=50)
    safe_start = _validate_required_datetime(start_time, field_name="start_time")
    safe_end_date = _validate_optional_date(end_date, "end_date")
    return await _run_tool(
        client.create_recurring_meeting(
            project=safe_project,
            title=safe_title,
            frequency=safe_frequency,
            start_time=safe_start,
            interval=interval,
            end_after=end_after,
            end_date=safe_end_date,
            iterations=iterations,
            monthly_day=monthly_day,
            monthly_ordinal=monthly_ordinal,
            monthly_weekday=monthly_weekday,
            confirm=confirm,
        )
    )


@register_tool
async def update_recurring_meeting(
    ctx: Context,
    recurring_meeting_id: int,
    title: str | None = None,
    frequency: str | None = None,
    start_time: str | None = None,
    interval: int | None = None,
    end_after: str | None = None,
    end_date: str | None = None,
    iterations: int | None = None,
    confirm: bool = False,
) -> RecurringMeetingWriteResult:
    """Prepare or update an OpenProject recurring meeting series; only
    writes when called again with confirm=true.

    Requires OpenProject 17.4+.

    Note: this does not affect meetings already materialized from this
    series (via init_recurring_meeting_occurrence) — update those directly
    with update_meeting.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(recurring_meeting_id, field_name="recurring_meeting_id")
    safe_title = _validate_optional_query(title, field_name="title", max_length=255)
    safe_frequency = _validate_optional_query(frequency, field_name="frequency", max_length=50)
    safe_start = _validate_optional_datetime(start_time, field_name="start_time")
    safe_end_date = _validate_optional_date(end_date, "end_date")
    _require_at_least_one(
        safe_title,
        safe_frequency,
        safe_start,
        interval,
        end_after,
        safe_end_date,
        iterations,
        message="At least one field to update is required.",
    )
    return await _run_tool(
        client.update_recurring_meeting(
            recurring_meeting_id=safe_id,
            title=safe_title,
            frequency=safe_frequency,
            start_time=safe_start,
            interval=interval,
            end_after=end_after,
            end_date=safe_end_date,
            iterations=iterations,
            confirm=confirm,
        )
    )


@register_tool
async def delete_recurring_meeting(
    ctx: Context, recurring_meeting_id: int, confirm: bool = False
) -> RecurringMeetingWriteResult:
    """Prepare or delete an OpenProject recurring meeting series; only
    deletes when called again with confirm=true.

    Requires OpenProject 17.4+.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(recurring_meeting_id, field_name="recurring_meeting_id")
    return await _run_tool(client.delete_recurring_meeting(recurring_meeting_id=safe_id, confirm=confirm))


_VALID_OCCURRENCE_FILTERS: set[str] = {"upcoming", "past", "cancelled", "open"}


@register_tool
async def list_recurring_meeting_occurrences(
    ctx: Context,
    recurring_meeting_id: int,
    filter: str = "upcoming",
    limit: int | None = None,
) -> RecurringMeetingOccurrenceListResult:
    """List virtual occurrences of a recurring meeting.

    Requires OpenProject 17.4+.

    filter: one of "upcoming", "past", "cancelled", "open".
    limit: only applies when filter="upcoming" (OpenProject default: 20);
    ignored for the other three filters, which always return their full set.
    Occurrences are virtual (synthesized from the recurrence rule) except
    where a real Meeting has already been materialized via
    init_recurring_meeting_occurrence — this list has no offset/pagination,
    unlike list_meetings/list_recurring_meetings.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(recurring_meeting_id, field_name="recurring_meeting_id")
    safe_filter = _validate_optional_choice(filter, field_name="filter", allowed_values=_VALID_OCCURRENCE_FILTERS)
    if safe_filter is None:
        safe_filter = "upcoming"
    safe_limit = _validate_limit(limit)
    return await _run_tool(client.list_recurring_meeting_occurrences(safe_id, filter=safe_filter, limit=safe_limit))


@register_tool
async def init_recurring_meeting_occurrence(
    ctx: Context,
    recurring_meeting_id: int,
    start_time: str,
    confirm: bool = False,
) -> RecurringMeetingOccurrenceWriteResult:
    """Prepare or materialize a virtual recurring-meeting occurrence into a
    real, standalone Meeting; only writes when called again with confirm=true.

    Requires OpenProject 17.4+.

    start_time: the occurrence's exact start time (ISO 8601, matching a
    start_time value from list_recurring_meeting_occurrences) — occurrences
    have no numeric id, they are addressed by this timestamp.
    On success, result is a full Meeting (use its id with get_meeting/
    update_meeting/delete_meeting), not an occurrence.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(recurring_meeting_id, field_name="recurring_meeting_id")
    safe_start = _validate_required_datetime(start_time, field_name="start_time")
    return await _run_tool(
        client.init_recurring_meeting_occurrence(recurring_meeting_id=safe_id, start_time=safe_start, confirm=confirm)
    )


@register_tool
async def cancel_recurring_meeting_occurrence(
    ctx: Context,
    recurring_meeting_id: int,
    start_time: str,
    confirm: bool = False,
) -> RecurringMeetingOccurrenceWriteResult:
    """Prepare or cancel a virtual (not-yet-materialized) recurring-meeting
    occurrence; only writes when called again with confirm=true.

    Requires OpenProject 17.4+.

    start_time: the occurrence's exact start time (ISO 8601), matching
    init_recurring_meeting_occurrence's addressing scheme.

    If the occurrence has already been materialized into a real Meeting and
    is not itself cancelled, this fails with an error (delete_meeting the
    materialized meeting directly instead). If NOT yet materialized,
    OpenProject creates a new, PERMANENTLY cancelled Meeting server-side to
    record the cancellation — this call's result does not report that new
    meeting's id; list_meetings/list_recurring_meeting_occurrences(filter=
    "cancelled") can be used to find it afterward if needed.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(recurring_meeting_id, field_name="recurring_meeting_id")
    safe_start = _validate_required_datetime(start_time, field_name="start_time")
    return await _run_tool(
        client.cancel_recurring_meeting_occurrence(recurring_meeting_id=safe_id, start_time=safe_start, confirm=confirm)
    )
