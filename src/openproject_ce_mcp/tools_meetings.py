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

from typing import Annotated

from mcp.server.mcpserver import Context
from pydantic import Field

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
from .tool_params import (
    Confirm,
    Limit,
    Offset,
    OptionalProjectRef,
    OptionalWorkPackageRef,
    ProjectRef,
    WorkPackageRef,
    select_field,
)
from .tool_types import IdOrName
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

# Real enum values from MeetingOutcome (OpenProject source: modules/meeting/app/models/
# meeting_outcome.rb) -- OpenProject itself rejects any other value with an
# internal server error (500), not a clean 422, so this must be checked
# client-side rather than left to the server's own validation.
_MEETING_OUTCOME_KINDS = {"information", "decision", "work_package"}

_MEETING_ID = "Meeting id, from list_meetings."
_MEETING_TITLE = "Meeting title, at most 255 characters."
_LOCATION = "Free-text location or meeting link, at most 255 characters."
_LOCATION_UPDATE = _LOCATION + ' "" clears it.'
_START_TIME = "ISO 8601 date-time with offset, e.g. 2026-12-01T09:00:00Z."
_DURATION = 'ISO 8601 duration in hours and minutes, e.g. "PT1H30M".'
_MEETING_STATE = 'Meeting state as get_meeting reports it, e.g. "open", "in_progress" or "closed".'
_SHARING = 'Only for meeting templates: "none", "descendants" or "system"; leave it out for a meeting.'
# Meeting#notify? reads the series template's flag for an occurrence, and
# send_emails? gates every invitation, update and cancellation mail on it.
_NOTIFY = (
    "true lets OpenProject email the invited participants about this meeting; for an occurrence of a series the "
    "series' setting applies."
)
_SECTION_ID = "Meeting section id, from list_meeting_sections."
_AGENDA_ITEM_ID = "Agenda item id, from list_meeting_agenda_items."
_AGENDA_TITLE = "Item title, at most 255 characters."
_AGENDA_NOTES = "Notes in Markdown, at most 50,000 characters."
_AGENDA_DURATION = "Planned duration in minutes, 0 to 1440."
_AGENDA_ITEM_TYPE = (
    '"simple" (a titled item) or "work_package" (an item for the work package given in work_package_id, which it '
    "then requires)."
)
_RECURRING_MEETING_ID = "Recurring meeting series id, from list_recurring_meetings."


@register_tool
async def list_meetings(
    ctx: Context,
    project: OptionalProjectRef = None,
    offset: Offset = 1,
    limit: Limit = None,
) -> MeetingListResult:
    """List OpenProject meetings, optionally scoped to a project.

    Requires OpenProject 17.4+; the meetings module's agenda/section/
    participant shape used here does not exist on 16.6, which only exposes
    an incompatible legacy "meeting contents" representation.

    Omit project to list across all readable projects."""
    client = _client_from_context(ctx)
    safe_project = _validate_optional_project_ref(project)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(client.meeting.list_all(project=safe_project, offset=safe_offset, limit=safe_limit))


@register_tool
async def get_meeting(ctx: Context, meeting_id: Annotated[int, Field(description=_MEETING_ID)]) -> MeetingSummary:
    """Get a single OpenProject meeting by id: schedule, state, participants and its lock_version.

    Requires OpenProject 17.4+. Its agenda comes from list_meeting_sections and list_meeting_agenda_items.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(meeting_id, field_name="meeting_id")
    return await _run_tool(client.meeting.get(safe_id))


@register_tool
async def create_meeting(
    ctx: Context,
    project: ProjectRef,
    title: str,
    location: str | None = None,
    start_time: str | None = None,
    duration: str | None = None,
    state: str | None = None,
    sharing: str | None = None,
    notify: bool | None = None,
    participant_user_refs: Annotated[
        list[IdOrName] | None,
        Field(
            description=(
                "Users to invite (id, login or name). The meeting gets exactly these participants, so name yourself "
                "to take part; it cannot be empty. No invitation is sent: a new meeting starts as a draft with "
                "notifications off."
            )
        ),
    ] = None,
    confirm: Confirm = False,
) -> MeetingWriteResult:
    """Create an OpenProject meeting.

    Requires OpenProject 17.4+.

    duration: an ISO 8601 duration like "PT1H30M" (hours/minutes only).
    state and notify cannot be set on create: OpenProject starts a new meeting
    as a draft with notifications off, so passing either is rejected; set them
    afterwards with update_meeting.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    safe_title = _validate_required_text(title, field_name="title", max_length=255)
    safe_location = _validate_optional_text(location, field_name="location", max_length=255)
    safe_start = _validate_optional_datetime(start_time, field_name="start_time")
    safe_duration = _validate_optional_duration(duration, field_name="duration")
    safe_participants = _validate_participant_refs(participant_user_refs)
    return await _run_tool(
        client.meeting.create(
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
    meeting_id: Annotated[int, Field(description=_MEETING_ID)],
    title: Annotated[str | None, Field(description=_MEETING_TITLE)] = None,
    location: Annotated[str | None, Field(description=_LOCATION_UPDATE)] = None,
    start_time: Annotated[str | None, Field(description=_START_TIME)] = None,
    duration: Annotated[str | None, Field(description=_DURATION)] = None,
    state: Annotated[str | None, Field(description=_MEETING_STATE)] = None,
    sharing: Annotated[str | None, Field(description=_SHARING)] = None,
    notify: Annotated[bool | None, Field(description=_NOTIFY)] = None,
    participant_user_refs: Annotated[
        list[IdOrName] | None,
        Field(
            description=(
                "Rejected: OpenProject 17.4 and 17.5 would add a user a second time and cannot remove anyone, and "
                "only administrators can read the server version that tells the releases apart. Change the "
                "participants in OpenProject."
            )
        ),
    ] = None,
    lock_version: Annotated[
        int | None,
        Field(
            description=(
                "The lock_version from get_meeting; the update is rejected if the meeting changed since. "
                "Omit it to skip this check."
            )
        ),
    ] = None,
    confirm: Confirm = False,
) -> MeetingWriteResult:
    """Update one meeting's details; omitted fields stay unchanged.

    Requires OpenProject 17.4+. The meeting's agenda is changed with the agenda item and section tools, and
    a recurring series' schedule with update_recurring_meeting; for an occurrence of a series this changes
    only that occurrence. With notifications on, a change of title, time, duration or location emails the
    invited participants (not for a closed or cancelled meeting). From 17.8, an update that takes a one-time
    meeting out of draft or turns notifications on also sends the invitations; 17.4 to 17.7 send no invitations
    on update.
    Changing participants is not supported: participant_user_refs is rejected.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(meeting_id, field_name="meeting_id")
    safe_title = _validate_optional_query(title, field_name="title", max_length=255)
    safe_location = _validate_optional_update_text(location, field_name="location", max_length=255)
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
        client.meeting.update(
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
async def delete_meeting(ctx: Context, meeting_id: int, confirm: Confirm = False) -> MeetingWriteResult:
    """Delete a meeting with its agenda, outcomes, attachments and the time entries logged on it.

    Requires OpenProject 17.4+. Deleting a one-time meeting cannot be undone. An occurrence of a series is
    only cancelled; init_recurring_meeting_occurrence restores it, reset to the series template. Invited
    participants get a cancellation email when the meeting's notifications are on. The template meeting of a
    recurring series is rejected, because deleting it would break the series. To delete the series with all
    its occurrences use delete_recurring_meeting.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(meeting_id, field_name="meeting_id")
    return await _run_tool(client.meeting.delete(meeting_id=safe_id, confirm=confirm))


@register_tool
async def list_meeting_agenda_items(
    ctx: Context,
    meeting_id: int,
    offset: Offset = 1,
    limit: Limit = None,
    select: Annotated[list[str] | None, select_field(MeetingAgendaItemSummary)] = None,
    text_limit: int | None = None,
) -> MeetingAgendaItemListResult:
    """List the agenda items of one meeting.

    Requires OpenProject 17.4+.

    This list is unpaginated server-side (OpenProject returns every agenda
    item of the meeting in one response); offset/limit are applied
    client-side by this MCP.

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
        client.meeting_agenda_item.list_for_meeting(
            safe_id, offset=safe_offset, limit=safe_limit, text_limit=safe_text_limit
        )
    )


@register_tool
async def list_work_package_meeting_agenda_items(
    ctx: Context,
    work_package_id: WorkPackageRef,
    offset: Offset = 1,
    limit: Limit = None,
    select: Annotated[list[str] | None, select_field(MeetingAgendaItemSummary)] = None,
    text_limit: int | None = None,
) -> MeetingAgendaItemListResult:
    """List the agenda items, across all meetings, that link a work package.

    Requires OpenProject 17.7+.

    Items of meetings in projects outside OPENPROJECT_READ_PROJECTS are left out.

    This list is unpaginated server-side; offset/limit are applied
    client-side by this MCP.

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
        client.meeting_agenda_item.list_for_work_package(
            safe_id, offset=safe_offset, limit=safe_limit, text_limit=safe_text_limit
        )
    )


@register_tool
async def get_meeting_agenda_item(
    ctx: Context,
    agenda_item_id: Annotated[int, Field(description="Agenda item id, from list_meeting_agenda_items.")],
) -> MeetingAgendaItemSummary:
    """Get a single meeting agenda item by id.

    Requires OpenProject 17.6+.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(agenda_item_id, field_name="agenda_item_id")
    return await _run_tool(client.meeting_agenda_item.get(safe_id))


@register_tool
async def create_meeting_agenda_item(
    ctx: Context,
    meeting_id: Annotated[int, Field(description=_MEETING_ID)],
    title: Annotated[str, Field(description="Item title, at most 255 characters; always required here.")],
    notes: Annotated[str | None, Field(description=_AGENDA_NOTES)] = None,
    duration_in_minutes: Annotated[int | None, Field(description=_AGENDA_DURATION)] = None,
    item_type: Annotated[str | None, Field(description=_AGENDA_ITEM_TYPE)] = None,
    work_package_id: OptionalWorkPackageRef = None,
    meeting_section_id: Annotated[
        int | None,
        Field(description="Section of this meeting to add the item to, from list_meeting_sections; default: the last."),
    ] = None,
    confirm: Confirm = False,
) -> MeetingAgendaItemWriteResult:
    """Add an item to a meeting's agenda.

    Requires OpenProject 17.6+. Rejected while the meeting is closed. For a work package, its project must be
    inside OPENPROJECT_WRITE_PROJECTS. To record a result of a discussed item use create_meeting_outcome.
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
        client.meeting_agenda_item.create(
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
    agenda_item_id: Annotated[int, Field(description=_AGENDA_ITEM_ID)],
    title: Annotated[str | None, Field(description=_AGENDA_TITLE)] = None,
    notes: Annotated[str | None, Field(description=_AGENDA_NOTES + ' "" clears them.')] = None,
    duration_in_minutes: Annotated[int | None, Field(description=_AGENDA_DURATION)] = None,
    item_type: Annotated[str | None, Field(description=_AGENDA_ITEM_TYPE)] = None,
    work_package_id: OptionalWorkPackageRef = None,
    meeting_section_id: Annotated[
        int | None,
        Field(
            description=(
                "Section to move the item into, from list_meeting_sections: one of the same meeting, or of another "
                "meeting in the same series."
            )
        ),
    ] = None,
    confirm: Confirm = False,
) -> MeetingAgendaItemWriteResult:
    """Update one agenda item of a meeting; omitted fields stay unchanged.

    Requires OpenProject 17.6+. Rejected while the meeting is closed. Each confirmed update also updates the
    meeting's own timestamp. Outcomes of the item are changed with update_meeting_outcome.
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
        client.meeting_agenda_item.update(
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
    ctx: Context, agenda_item_id: int, confirm: Confirm = False
) -> MeetingAgendaItemWriteResult:
    """Delete a meeting agenda item with its outcomes.

    Requires OpenProject 17.6+. Rejected while the meeting is closed. This cannot be undone.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(agenda_item_id, field_name="agenda_item_id")
    return await _run_tool(client.meeting_agenda_item.delete(agenda_item_id=safe_id, confirm=confirm))


@register_tool
async def list_meeting_outcomes(
    ctx: Context,
    agenda_item_id: int,
    offset: Offset = 1,
    limit: Limit = None,
    select: Annotated[list[str] | None, select_field(MeetingOutcomeSummary)] = None,
    text_limit: int | None = None,
) -> MeetingOutcomeListResult:
    """List outcomes of a meeting agenda item.

    Requires OpenProject 17.6+; the meeting_outcomes endpoint does not exist
    on 17.4/17.5.

    This list is unpaginated server-side; offset/limit are applied
    client-side by this MCP.

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
        client.meeting_outcome.list_for_agenda_item(
            safe_id, offset=safe_offset, limit=safe_limit, text_limit=safe_text_limit
        )
    )


@register_tool
async def get_meeting_outcome(ctx: Context, outcome_id: int) -> MeetingOutcomeSummary:
    """Get a single meeting outcome by id.

    Requires OpenProject 17.6+.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(outcome_id, field_name="outcome_id")
    return await _run_tool(client.meeting_outcome.get(safe_id))


@register_tool
async def create_meeting_outcome(
    ctx: Context,
    agenda_item_id: int,
    kind: str,
    notes: str | None = None,
    work_package_id: OptionalWorkPackageRef = None,
    confirm: Confirm = False,
) -> MeetingOutcomeWriteResult:
    """Create a meeting outcome on an agenda item.

    Requires OpenProject 17.6+.

    kind must be one of "information", "decision", "work_package" (OpenProject's
    real enum values, not e.g. "info" or "action", which OpenProject rejects
    with an internal server error rather than a clean validation error).
    "information"-kind outcomes require notes; "work_package"-kind outcomes
    require work_package_id.
    """
    client = _client_from_context(ctx)
    safe_agenda_item_id = _validate_positive_int(agenda_item_id, field_name="agenda_item_id")
    safe_kind = _validate_choice(kind, field_name="kind", allowed_values=_MEETING_OUTCOME_KINDS)
    safe_notes = _validate_optional_text(notes, field_name="notes", max_length=50_000)
    safe_work_package_id = _validate_optional_work_package_ref(work_package_id)
    return await _run_tool(
        client.meeting_outcome.create(
            agenda_item_id=safe_agenda_item_id,
            kind=safe_kind,
            notes=safe_notes,
            work_package_id=safe_work_package_id,
            confirm=confirm,
        )
    )


@register_tool
async def update_meeting_outcome(
    ctx: Context,
    outcome_id: int,
    kind: str | None = None,
    notes: str | None = None,
    work_package_id: OptionalWorkPackageRef = None,
    confirm: Confirm = False,
) -> MeetingOutcomeWriteResult:
    """Update a meeting outcome.

    Requires OpenProject 17.6+.

    kind, if given, must be one of "information", "decision", "work_package"
    (OpenProject's real enum values, not e.g. "info" or "action", which
    OpenProject rejects with an internal server error rather than a clean
    validation error).
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(outcome_id, field_name="outcome_id")
    safe_kind = _validate_optional_choice(kind, field_name="kind", allowed_values=_MEETING_OUTCOME_KINDS)
    safe_notes = _validate_optional_update_text(notes, field_name="notes", max_length=50_000)
    safe_work_package_id = _validate_optional_work_package_ref(work_package_id)
    _require_at_least_one(
        safe_kind, safe_notes, safe_work_package_id, message="At least one field to update is required."
    )
    return await _run_tool(
        client.meeting_outcome.update(
            outcome_id=safe_id,
            kind=safe_kind,
            notes=safe_notes,
            work_package_id=safe_work_package_id,
            confirm=confirm,
        )
    )


@register_tool
async def delete_meeting_outcome(ctx: Context, outcome_id: int, confirm: Confirm = False) -> MeetingOutcomeWriteResult:
    """Delete a meeting outcome; this cannot be undone.

    Requires OpenProject 17.6+.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(outcome_id, field_name="outcome_id")
    return await _run_tool(client.meeting_outcome.delete(outcome_id=safe_id, confirm=confirm))


@register_tool
async def list_meeting_sections(
    ctx: Context,
    meeting_id: int,
    offset: Offset = 1,
    limit: Limit = None,
) -> MeetingSectionListResult:
    """List sections of an OpenProject meeting.

    Requires OpenProject 17.4+.

    This list is unpaginated server-side; offset/limit are applied
    client-side by this MCP.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(meeting_id, field_name="meeting_id")
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(client.meeting_section.list_for_meeting(safe_id, offset=safe_offset, limit=safe_limit))


@register_tool
async def get_meeting_section(
    ctx: Context, section_id: Annotated[int, Field(description=_SECTION_ID)]
) -> MeetingSectionSummary:
    """Get a single meeting section by id: title, position and whether it is the backlog.

    Requires OpenProject 17.6+. Its agenda items come from list_meeting_agenda_items.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(section_id, field_name="section_id")
    return await _run_tool(client.meeting_section.get(safe_id))


@register_tool
async def create_meeting_section(
    ctx: Context,
    meeting_id: int,
    title: str,
    position: int | None = None,
    backlog: bool | None = None,
    confirm: Confirm = False,
) -> MeetingSectionWriteResult:
    """Create a meeting section.

    Requires OpenProject 17.6+.

    backlog cannot be changed after creation via update_meeting_section;
    pass it only here, on create.
    """
    client = _client_from_context(ctx)
    safe_meeting_id = _validate_positive_int(meeting_id, field_name="meeting_id")
    safe_title = _validate_required_text(title, field_name="title", max_length=255)
    return await _run_tool(
        client.meeting_section.create(
            meeting_id=safe_meeting_id, title=safe_title, position=position, backlog=backlog, confirm=confirm
        )
    )


@register_tool
async def update_meeting_section(
    ctx: Context,
    section_id: Annotated[int, Field(description=_SECTION_ID)],
    title: Annotated[str | None, Field(description="New section title; it cannot be emptied.")] = None,
    position: Annotated[
        int | None, Field(description="New place among the meeting's sections, 1 = first; the others shift.")
    ] = None,
    confirm: Confirm = False,
) -> MeetingSectionWriteResult:
    """Rename or move a meeting section; omitted fields stay unchanged.

    Requires OpenProject 17.6+. Rejected while the meeting is closed, and for the backlog section. Its agenda
    items stay in it. backlog cannot be changed after creation; this tool does not accept it.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(section_id, field_name="section_id")
    safe_title = _validate_optional_query(title, field_name="title", max_length=255)
    _require_at_least_one(safe_title, position, message="At least one field to update is required.")
    return await _run_tool(
        client.meeting_section.update(section_id=safe_id, title=safe_title, position=position, confirm=confirm)
    )


@register_tool
async def delete_meeting_section(ctx: Context, section_id: int, confirm: Confirm = False) -> MeetingSectionWriteResult:
    """Delete a meeting section with its agenda items and their outcomes (they are not moved).

    Requires OpenProject 17.6+. Rejected while the meeting is closed, and for the backlog section. This cannot
    be undone.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(section_id, field_name="section_id")
    return await _run_tool(client.meeting_section.delete(section_id=safe_id, confirm=confirm))


@register_tool
async def list_recurring_meetings(
    ctx: Context,
    project: OptionalProjectRef = None,
    offset: Offset = 1,
    limit: Limit = None,
) -> RecurringMeetingListResult:
    """List OpenProject recurring meeting series, optionally scoped to a project.

    Requires OpenProject 17.4+.

    Omit project to list across all readable projects."""
    client = _client_from_context(ctx)
    safe_project = _validate_optional_project_ref(project)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(
        client.recurring_meeting.list_all(project=safe_project, offset=safe_offset, limit=safe_limit)
    )


@register_tool
async def get_recurring_meeting(
    ctx: Context, recurring_meeting_id: Annotated[int, Field(description=_RECURRING_MEETING_ID)]
) -> RecurringMeetingSummary:
    """Get a single OpenProject recurring meeting series by id.

    Requires OpenProject 17.4+.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(recurring_meeting_id, field_name="recurring_meeting_id")
    return await _run_tool(client.recurring_meeting.get(safe_id))


@register_tool
async def create_recurring_meeting(
    ctx: Context,
    project: ProjectRef,
    title: Annotated[str, Field(description="Series title, at most 255 characters.")],
    frequency: Annotated[
        str,
        Field(
            description=(
                '"daily", "working_days", "weekly", and from 17.5 "monthly_day_of_month" or "monthly_nth_weekday".'
            )
        ),
    ],
    start_time: Annotated[
        str, Field(description="First occurrence, ISO 8601 date-time with offset; its time of day is the series'.")
    ],
    interval: Annotated[
        int | None, Field(description='Every n-th day, week or month, 1 to 100; "working_days" always uses 1.')
    ] = None,
    end_after: Annotated[
        str | None,
        Field(
            description='"never" (default), "specific_date" (requires end_date) or "iterations" (requires iterations).'
        ),
    ] = None,
    end_date: Annotated[
        str | None,
        Field(description='Last date (YYYY-MM-DD); required for end_after "specific_date".'),
    ] = None,
    iterations: Annotated[
        int | None, Field(description='Number of occurrences, 1 to 1000; required for end_after "iterations".')
    ] = None,
    monthly_day: Annotated[
        int | None,
        Field(description='Day of month, 1 to 31; required for "monthly_day_of_month".'),
    ] = None,
    monthly_ordinal: Annotated[
        str | None,
        Field(description='"1" to "4", or "-1" for the last; required for "monthly_nth_weekday".'),
    ] = None,
    monthly_weekday: Annotated[
        str | None,
        Field(description='Lowercase English weekday, e.g. "monday"; required for "monthly_nth_weekday".'),
    ] = None,
    confirm: Confirm = False,
) -> RecurringMeetingWriteResult:
    """Create a recurring meeting series; its template meeting starts as a draft.

    Requires OpenProject 17.4+. For a single meeting use create_meeting. Occurrences are virtual until
    init_recurring_meeting_occurrence creates one; the series is changed with update_recurring_meeting.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    safe_title = _validate_required_text(title, field_name="title", max_length=255)
    safe_frequency = _validate_required_text(frequency, field_name="frequency", max_length=50)
    safe_start = _validate_required_datetime(start_time, field_name="start_time")
    safe_end_date = _validate_optional_date(end_date, "end_date")
    return await _run_tool(
        client.recurring_meeting.create(
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
    recurring_meeting_id: Annotated[int, Field(description=_RECURRING_MEETING_ID)],
    title: str | None = None,
    frequency: str | None = None,
    start_time: str | None = None,
    interval: int | None = None,
    end_after: str | None = None,
    end_date: str | None = None,
    iterations: int | None = None,
    confirm: Confirm = False,
) -> RecurringMeetingWriteResult:
    """Update an OpenProject recurring meeting series.

    Requires OpenProject 17.4+.

    Already created future occurrences move and are renamed with the series. A schedule change other than
    the time of day can delete cancelled occurrences; on 17.4 to 17.8 a time-of-day change also rewrites the
    slot times of past occurrences. When the schedule changes, invited participants get an update email if
    notifications are on.
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
        client.recurring_meeting.update(
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
    ctx: Context,
    recurring_meeting_id: Annotated[int, Field(description=_RECURRING_MEETING_ID)],
    confirm: Confirm = False,
) -> RecurringMeetingWriteResult:
    """Delete a recurring meeting series with all its occurrences, past and future.

    Requires OpenProject 17.4+. Each occurrence goes with its agenda, outcomes, attachments and time entries;
    this cannot be undone. Invited participants get a cancellation email when notifications are on.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(recurring_meeting_id, field_name="recurring_meeting_id")
    return await _run_tool(client.recurring_meeting.delete(recurring_meeting_id=safe_id, confirm=confirm))


_VALID_OCCURRENCE_FILTERS: set[str] = {"upcoming", "past", "cancelled", "open"}


@register_tool
async def list_recurring_meeting_occurrences(
    ctx: Context,
    recurring_meeting_id: Annotated[int, Field(description=_RECURRING_MEETING_ID)],
    filter: str = "upcoming",
    limit: Annotated[
        int | None,
        Field(
            description=(
                'Number of occurrences, only for filter="upcoming" (OpenProject default: 20); the other filters '
                "return their full set. Not paged."
            )
        ),
    ] = None,
) -> RecurringMeetingOccurrenceListResult:
    """List virtual occurrences of a recurring meeting.

    Requires OpenProject 17.4+.

    filter: one of "upcoming", "past", "cancelled", "open".
    Occurrences are virtual (synthesized from the recurrence rule) except
    where a real Meeting has already been materialized via
    init_recurring_meeting_occurrence; this list has no offset/pagination,
    unlike list_meetings/list_recurring_meetings.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(recurring_meeting_id, field_name="recurring_meeting_id")
    safe_filter = _validate_optional_choice(filter, field_name="filter", allowed_values=_VALID_OCCURRENCE_FILTERS)
    if safe_filter is None:
        safe_filter = "upcoming"
    safe_limit = _validate_limit(limit)
    return await _run_tool(client.recurring_meeting.list_occurrences(safe_id, filter=safe_filter, limit=safe_limit))


@register_tool
async def init_recurring_meeting_occurrence(
    ctx: Context,
    recurring_meeting_id: Annotated[int, Field(description=_RECURRING_MEETING_ID)],
    start_time: str,
    confirm: Confirm = False,
) -> RecurringMeetingOccurrenceWriteResult:
    """Materialize a virtual recurring-meeting occurrence into a
    real, standalone Meeting.

    Requires OpenProject 17.4+.

    start_time: the occurrence's exact start time (ISO 8601, matching a
    start_time value from list_recurring_meeting_occurrences); occurrences
    have no numeric id, they are addressed by this timestamp.
    On success, result is a full Meeting (use its id with get_meeting/
    update_meeting/delete_meeting), not an occurrence. A cancelled occurrence is restored and its content
    reset to the template. If the series template is still a draft, this first sets it to open, which stays
    even if the init fails; on 17.6 and later OpenProject creates further occurrences automatically only once
    the template is open.
    On OpenProject 17.4 and 17.5, initializing an occurrence that already exists fails with a server error
    instead of returning it; 17.6 and later return the existing occurrence.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(recurring_meeting_id, field_name="recurring_meeting_id")
    safe_start = _validate_required_datetime(start_time, field_name="start_time")
    return await _run_tool(
        client.recurring_meeting.init_occurrence(recurring_meeting_id=safe_id, start_time=safe_start, confirm=confirm)
    )


@register_tool
async def cancel_recurring_meeting_occurrence(
    ctx: Context,
    recurring_meeting_id: Annotated[int, Field(description=_RECURRING_MEETING_ID)],
    start_time: str,
    confirm: Confirm = False,
) -> RecurringMeetingOccurrenceWriteResult:
    """Cancel a virtual (not-yet-materialized) recurring-meeting
    occurrence.

    Requires OpenProject 17.4+.

    start_time: the occurrence's exact start time (ISO 8601), matching
    init_recurring_meeting_occurrence's addressing scheme.

    If the occurrence has already been materialized into a real Meeting and
    is not itself cancelled, this fails with an error (delete_meeting the
    materialized meeting directly instead). If NOT yet materialized,
    OpenProject records the cancellation as a cancelled Meeting
    (init_recurring_meeting_occurrence restores it, a later schedule change of
    the series other than the time of day can delete it); this call's result
    does not report that new meeting's id; list_meetings/
    list_recurring_meeting_occurrences(filter="cancelled") can be used to find
    it afterward if needed.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(recurring_meeting_id, field_name="recurring_meeting_id")
    safe_start = _validate_required_datetime(start_time, field_name="start_time")
    return await _run_tool(
        client.recurring_meeting.cancel_occurrence(recurring_meeting_id=safe_id, start_time=safe_start, confirm=confirm)
    )
