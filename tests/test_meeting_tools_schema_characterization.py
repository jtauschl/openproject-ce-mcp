"""Characterization test: freezes the 29 Meeting domain MCP tool schemas
(list_meetings, get_meeting, create_meeting, update_meeting, delete_meeting,
list_meeting_agenda_items, list_work_package_meeting_agenda_items,
get_meeting_agenda_item, create_meeting_agenda_item, update_meeting_agenda_item,
delete_meeting_agenda_item, list_meeting_outcomes, get_meeting_outcome,
create_meeting_outcome, update_meeting_outcome, delete_meeting_outcome,
list_meeting_sections, get_meeting_section, create_meeting_section,
update_meeting_section, delete_meeting_section, list_recurring_meetings,
get_recurring_meeting, create_recurring_meeting, update_recurring_meeting,
delete_recurring_meeting, list_recurring_meeting_occurrences,
init_recurring_meeting_occurrence, cancel_recurring_meeting_occurrence).

Proves that where these tool functions live (tools.py vs. their own per-domain
file) has zero effect on what an MCP client actually sees -- parameter names/
order/types, descriptions, required fields, and whether the tool carries an
output_schema. A future relocation of any of these functions to a different
module must leave this file completely unmodified; a diff to it would mean the
move changed the public tool contract, not just its location.
"""

from __future__ import annotations

from openproject_ce_mcp.config import Settings
from openproject_ce_mcp.server import create_app


def _make_settings(**overrides) -> Settings:
    defaults = {
        "base_url": "https://op.example.com",
        "api_token": "token",
        "timeout": 12,
        "verify_ssl": True,
        "default_page_size": 20,
        "max_page_size": 50,
        "max_results": 100,
        "log_level": "WARNING",
        "read_projects": ("*",),
        "write_projects": ("*",),
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _tools(mcp) -> dict:
    return {t.name: t for t in mcp._tool_manager.list_tools()}


def test_list_meetings_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_meetings"]
    assert (
        tool.description
        == 'List OpenProject meetings, optionally scoped to a project.\n\nRequires OpenProject 17.4+; the meetings module\'s agenda/section/\nparticipant shape used here does not exist on 16.6, which only exposes\nan incompatible legacy "meeting contents" representation.\n\nOmit project to list across all readable projects.'
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Project identifier, id, or name; a unique part of a name or identifier also matches.",
                "title": "Project",
            },
            "title": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Case-insensitive substring of the meeting title; an occurrence of a recurring meeting also matches on its series title. Requires OpenProject 17.9+ (older servers reject the filter).",
                "title": "Title",
            },
            "offset": {
                "default": 1,
                "description": "1-based page number; pass the previous result's next_offset.",
                "title": "Offset",
                "type": "integer",
            },
            "limit": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "description": "Page size, capped at OPENPROJECT_MAX_PAGE_SIZE.",
                "title": "Limit",
            },
        },
        "title": "list_meetingsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["project", "title", "offset", "limit"]


def test_get_meeting_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_meeting"]
    assert (
        tool.description
        == "Get a single OpenProject meeting by id: schedule, state, participants and its lock_version.\n\nRequires OpenProject 17.4+. Its agenda comes from list_meeting_sections and list_meeting_agenda_items.\n"
    )
    assert tool.output_schema == {
        "$defs": {
            "MeetingParticipantSummary": {
                "properties": {
                    "id": {
                        "title": "Id",
                        "type": "integer",
                    },
                    "name": {
                        "anyOf": [
                            {
                                "type": "string",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "title": "Name",
                    },
                },
                "required": [
                    "id",
                    "name",
                ],
                "title": "MeetingParticipantSummary",
                "type": "object",
            },
        },
        "properties": {
            "id": {
                "title": "Id",
                "type": "integer",
            },
            "title": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Title",
            },
            "location": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Location",
            },
            "lock_version": {
                "title": "Lock Version",
                "type": "integer",
            },
            "start_time": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Start Time",
            },
            "end_time": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "End Time",
            },
            "duration": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Duration",
            },
            "state": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "State",
            },
            "sharing": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Sharing",
            },
            "template": {
                "title": "Template",
                "type": "boolean",
            },
            "notify": {
                "title": "Notify",
                "type": "boolean",
            },
            "author": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Author",
            },
            "participants": {
                "items": {
                    "$ref": "#/$defs/MeetingParticipantSummary",
                },
                "title": "Participants",
                "type": "array",
            },
            "project_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Project Id",
            },
            "project": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Project",
            },
            "recurring_meeting_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Recurring Meeting Id",
            },
            "created_at": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Created At",
            },
            "updated_at": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Updated At",
            },
        },
        "required": [
            "id",
            "title",
            "location",
            "lock_version",
            "start_time",
            "end_time",
            "duration",
            "state",
            "sharing",
            "template",
            "notify",
            "author",
            "participants",
            "project_id",
            "project",
            "recurring_meeting_id",
            "created_at",
            "updated_at",
        ],
        "title": "MeetingSummary",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {
            "meeting_id": {"description": "Meeting id, from list_meetings.", "title": "Meeting Id", "type": "integer"}
        },
        "required": ["meeting_id"],
        "title": "get_meetingArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["meeting_id"]


def test_create_meeting_schema() -> None:
    tool = _tools(create_app(_make_settings()))["create_meeting"]
    assert (
        tool.description
        == 'Create an OpenProject meeting.\n\nRequires OpenProject 17.4+.\n\nduration: an ISO 8601 duration like "PT1H30M" (hours/minutes only).\nstate and notify cannot be set on create: OpenProject starts a new meeting\nas a draft with notifications off, so passing either is rejected; set them\nafterwards with update_meeting.\n'
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {
                "anyOf": [{"type": "integer"}, {"type": "string"}],
                "description": "Project identifier, id, or name; a unique part of a name or identifier also matches.",
                "title": "Project",
            },
            "title": {"title": "Title", "type": "string"},
            "location": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Location"},
            "start_time": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Start Time"},
            "duration": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Duration"},
            "state": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "State"},
            "sharing": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Sharing"},
            "notify": {"anyOf": [{"type": "boolean"}, {"type": "null"}], "default": None, "title": "Notify"},
            "participant_user_refs": {
                "anyOf": [
                    {"items": {"anyOf": [{"type": "integer"}, {"type": "string"}]}, "type": "array"},
                    {"type": "null"},
                ],
                "default": None,
                "description": "Users to invite (id, login or name). The meeting gets exactly these participants, so name yourself to take part; it cannot be empty. No invitation is sent: a new meeting starts as a draft with notifications off.",
                "title": "Participant User Refs",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["project", "title"],
        "title": "create_meetingArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "project",
        "title",
        "location",
        "start_time",
        "duration",
        "state",
        "sharing",
        "notify",
        "participant_user_refs",
        "confirm",
    ]


def test_update_meeting_schema() -> None:
    tool = _tools(create_app(_make_settings()))["update_meeting"]
    assert (
        tool.description
        == "Update one meeting's details; omitted fields stay unchanged.\n\nRequires OpenProject 17.4+. The meeting's agenda is changed with the agenda item and section tools, and\na recurring series' schedule with update_recurring_meeting; for an occurrence of a series this changes\nonly that occurrence. With notifications on, a change of title, time, duration or location emails the\ninvited participants (not for a closed or cancelled meeting). From 17.8, an update that takes a one-time\nmeeting out of draft or turns notifications on also sends the invitations; 17.4 to 17.7 send no invitations\non update.\nChanging participants is not supported: participant_user_refs is rejected.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "meeting_id": {"description": "Meeting id, from list_meetings.", "title": "Meeting Id", "type": "integer"},
            "title": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Meeting title, at most 255 characters.",
                "title": "Title",
            },
            "location": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": 'Free-text location or meeting link, at most 255 characters. "" clears it.',
                "title": "Location",
            },
            "start_time": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "ISO 8601 date-time with offset, e.g. 2026-12-01T09:00:00Z.",
                "title": "Start Time",
            },
            "duration": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": 'ISO 8601 duration in hours and minutes, e.g. "PT1H30M".',
                "title": "Duration",
            },
            "state": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": 'Meeting state as get_meeting reports it, e.g. "open", "in_progress" or "closed".',
                "title": "State",
            },
            "sharing": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": 'Only for meeting templates: "none", "descendants" or "system"; leave it out for a meeting.',
                "title": "Sharing",
            },
            "notify": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "default": None,
                "description": "true lets OpenProject email the invited participants about this meeting; for an occurrence of a series the series' setting applies.",
                "title": "Notify",
            },
            "participant_user_refs": {
                "anyOf": [
                    {"items": {"anyOf": [{"type": "integer"}, {"type": "string"}]}, "type": "array"},
                    {"type": "null"},
                ],
                "default": None,
                "description": "Rejected: OpenProject 17.4 and 17.5 would add a user a second time and cannot remove anyone, and only administrators can read the server version that tells the releases apart. Change the participants in OpenProject.",
                "title": "Participant User Refs",
            },
            "lock_version": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "description": "The lock_version from get_meeting; the update is rejected if the meeting changed since. Omit it to skip this check.",
                "title": "Lock Version",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["meeting_id"],
        "title": "update_meetingArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "meeting_id",
        "title",
        "location",
        "start_time",
        "duration",
        "state",
        "sharing",
        "notify",
        "participant_user_refs",
        "lock_version",
        "confirm",
    ]


def test_delete_meeting_schema() -> None:
    tool = _tools(create_app(_make_settings()))["delete_meeting"]
    assert (
        tool.description
        == "Delete a meeting with its agenda, outcomes, attachments and the time entries logged on it.\n\nRequires OpenProject 17.4+. Deleting a one-time meeting cannot be undone. An occurrence of a series is\nonly cancelled; init_recurring_meeting_occurrence restores it, reset to the series template. Invited\nparticipants get a cancellation email when the meeting's notifications are on. The template meeting of a\nrecurring series is rejected, because deleting it would break the series. To stop a series and keep its\npast occurrences use end_recurring_meeting (17.8+); to delete the series with all its occurrences use\ndelete_recurring_meeting.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "meeting_id": {"title": "Meeting Id", "type": "integer"},
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["meeting_id"],
        "title": "delete_meetingArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["meeting_id", "confirm"]


def test_list_meeting_agenda_items_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_meeting_agenda_items"]
    assert (
        tool.description
        == "List the agenda items of one meeting.\n\nRequires OpenProject 17.4+.\n\nThis list is unpaginated server-side (OpenProject returns every agenda\nitem of the meeting in one response); offset/limit are applied\nclient-side by this MCP.\n\ntext_limit caps each item's notes at that many characters (default: the\nserver's configured OPENPROJECT_TEXT_LIMIT, NOT unlimited). When text is\ncut, notes_truncated is true and notes_length reports the real length.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "meeting_id": {"title": "Meeting Id", "type": "integer"},
            "offset": {
                "default": 1,
                "description": "1-based page number; pass the previous result's next_offset.",
                "title": "Offset",
                "type": "integer",
            },
            "limit": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "description": "Page size, capped at OPENPROJECT_MAX_PAGE_SIZE.",
                "title": "Limit",
            },
            "select": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "description": "Fields to return; a requested unset field comes back as null. Allowed: author, created_at, duration_in_minutes, id, item_type, lock_version, meeting_id, meeting_section_id, notes, notes_length, notes_truncated, outcome_ids, position, presenter, title, updated_at, work_package_id.",
                "title": "Select",
            },
            "text_limit": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": None, "title": "Text Limit"},
        },
        "required": ["meeting_id"],
        "title": "list_meeting_agenda_itemsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["meeting_id", "offset", "limit", "select", "text_limit"]


def test_list_work_package_meeting_agenda_items_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_work_package_meeting_agenda_items"]
    assert (
        tool.description
        == "List the agenda items, across all meetings, that link a work package.\n\nRequires OpenProject 17.7+.\n\nItems of meetings in projects outside OPENPROJECT_READ_PROJECTS are left out.\n\nThis list is unpaginated server-side; offset/limit are applied\nclient-side by this MCP.\n\ntext_limit caps each item's notes at that many characters (default: the\nserver's configured OPENPROJECT_TEXT_LIMIT, NOT unlimited). When text is\ncut, notes_truncated is true and notes_length reports the real length.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "work_package_id": {
                "anyOf": [{"type": "integer"}, {"type": "string"}],
                "description": 'Work package id (e.g. 952) or display id (e.g. "PROJ-51"), not the bare number 51.',
                "title": "Work Package Id",
            },
            "offset": {
                "default": 1,
                "description": "1-based page number; pass the previous result's next_offset.",
                "title": "Offset",
                "type": "integer",
            },
            "limit": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "description": "Page size, capped at OPENPROJECT_MAX_PAGE_SIZE.",
                "title": "Limit",
            },
            "select": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "description": "Fields to return; a requested unset field comes back as null. Allowed: author, created_at, duration_in_minutes, id, item_type, lock_version, meeting_id, meeting_section_id, notes, notes_length, notes_truncated, outcome_ids, position, presenter, title, updated_at, work_package_id.",
                "title": "Select",
            },
            "text_limit": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": None, "title": "Text Limit"},
        },
        "required": ["work_package_id"],
        "title": "list_work_package_meeting_agenda_itemsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["work_package_id", "offset", "limit", "select", "text_limit"]


def test_get_meeting_agenda_item_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_meeting_agenda_item"]
    assert tool.description == "Get a single meeting agenda item by id.\n\nRequires OpenProject 17.6+.\n"
    assert tool.output_schema == {
        "properties": {
            "id": {
                "title": "Id",
                "type": "integer",
            },
            "title": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Title",
            },
            "notes": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Notes",
            },
            "notes_truncated": {
                "title": "Notes Truncated",
                "type": "boolean",
            },
            "notes_length": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Notes Length",
            },
            "position": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Position",
            },
            "duration_in_minutes": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Duration In Minutes",
            },
            "item_type": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Item Type",
            },
            "lock_version": {
                "title": "Lock Version",
                "type": "integer",
            },
            "meeting_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Meeting Id",
            },
            "author": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Author",
            },
            "presenter": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Presenter",
            },
            "work_package_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Work Package Id",
            },
            "meeting_section_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Meeting Section Id",
            },
            "outcome_ids": {
                "items": {
                    "type": "integer",
                },
                "title": "Outcome Ids",
                "type": "array",
            },
            "created_at": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Created At",
            },
            "updated_at": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Updated At",
            },
        },
        "required": [
            "id",
            "title",
            "notes",
            "notes_truncated",
            "notes_length",
            "position",
            "duration_in_minutes",
            "item_type",
            "lock_version",
            "meeting_id",
            "author",
            "presenter",
            "work_package_id",
            "meeting_section_id",
            "outcome_ids",
            "created_at",
            "updated_at",
        ],
        "title": "MeetingAgendaItemSummary",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {
            "agenda_item_id": {
                "description": "Agenda item id, from list_meeting_agenda_items.",
                "title": "Agenda Item Id",
                "type": "integer",
            }
        },
        "required": ["agenda_item_id"],
        "title": "get_meeting_agenda_itemArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["agenda_item_id"]


def test_create_meeting_agenda_item_schema() -> None:
    tool = _tools(create_app(_make_settings()))["create_meeting_agenda_item"]
    assert (
        tool.description
        == "Add an item to a meeting's agenda.\n\nRequires OpenProject 17.6+. Rejected while the meeting is closed. For a work package, its project must be\ninside OPENPROJECT_WRITE_PROJECTS. To record a result of a discussed item use create_meeting_outcome.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "meeting_id": {"description": "Meeting id, from list_meetings.", "title": "Meeting Id", "type": "integer"},
            "title": {
                "description": "Item title, at most 255 characters; always required here.",
                "title": "Title",
                "type": "string",
            },
            "notes": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Notes in Markdown, at most 50,000 characters.",
                "title": "Notes",
            },
            "duration_in_minutes": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "description": "Planned duration in minutes, 0 to 1440.",
                "title": "Duration In Minutes",
            },
            "item_type": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": '"simple" (a titled item) or "work_package" (an item for the work package given in work_package_id, which it then requires).',
                "title": "Item Type",
            },
            "work_package_id": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "description": 'Work package id (e.g. 952) or display id (e.g. "PROJ-51"), not the bare number 51.',
                "title": "Work Package Id",
            },
            "meeting_section_id": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "description": "Section of this meeting to add the item to, from list_meeting_sections; default: the last.",
                "title": "Meeting Section Id",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["meeting_id", "title"],
        "title": "create_meeting_agenda_itemArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "meeting_id",
        "title",
        "notes",
        "duration_in_minutes",
        "item_type",
        "work_package_id",
        "meeting_section_id",
        "confirm",
    ]


def test_update_meeting_agenda_item_schema() -> None:
    tool = _tools(create_app(_make_settings()))["update_meeting_agenda_item"]
    assert (
        tool.description
        == "Update one agenda item of a meeting; omitted fields stay unchanged.\n\nRequires OpenProject 17.6+. Rejected while the meeting is closed. Each confirmed update also updates the\nmeeting's own timestamp. Outcomes of the item are changed with update_meeting_outcome.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "agenda_item_id": {
                "description": "Agenda item id, from list_meeting_agenda_items.",
                "title": "Agenda Item Id",
                "type": "integer",
            },
            "title": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Item title, at most 255 characters.",
                "title": "Title",
            },
            "notes": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": 'Notes in Markdown, at most 50,000 characters. "" clears them.',
                "title": "Notes",
            },
            "duration_in_minutes": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "description": "Planned duration in minutes, 0 to 1440.",
                "title": "Duration In Minutes",
            },
            "item_type": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": '"simple" (a titled item) or "work_package" (an item for the work package given in work_package_id, which it then requires).',
                "title": "Item Type",
            },
            "work_package_id": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "description": 'Work package id (e.g. 952) or display id (e.g. "PROJ-51"), not the bare number 51.',
                "title": "Work Package Id",
            },
            "meeting_section_id": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "description": "Section to move the item into, from list_meeting_sections: one of the same meeting, or of another meeting in the same series.",
                "title": "Meeting Section Id",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["agenda_item_id"],
        "title": "update_meeting_agenda_itemArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "agenda_item_id",
        "title",
        "notes",
        "duration_in_minutes",
        "item_type",
        "work_package_id",
        "meeting_section_id",
        "confirm",
    ]


def test_delete_meeting_agenda_item_schema() -> None:
    tool = _tools(create_app(_make_settings()))["delete_meeting_agenda_item"]
    assert (
        tool.description
        == "Delete a meeting agenda item with its outcomes.\n\nRequires OpenProject 17.6+. Rejected while the meeting is closed. This cannot be undone.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "agenda_item_id": {"title": "Agenda Item Id", "type": "integer"},
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["agenda_item_id"],
        "title": "delete_meeting_agenda_itemArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["agenda_item_id", "confirm"]


def test_list_meeting_outcomes_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_meeting_outcomes"]
    assert (
        tool.description
        == "List outcomes of a meeting agenda item.\n\nRequires OpenProject 17.6+; the meeting_outcomes endpoint does not exist\non 17.4/17.5.\n\nThis list is unpaginated server-side; offset/limit are applied\nclient-side by this MCP.\n\ntext_limit caps each outcome's notes at that many characters (default:\nthe server's configured OPENPROJECT_TEXT_LIMIT, NOT unlimited). When text\nis cut, notes_truncated is true and notes_length reports the real length.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "agenda_item_id": {"title": "Agenda Item Id", "type": "integer"},
            "offset": {
                "default": 1,
                "description": "1-based page number; pass the previous result's next_offset.",
                "title": "Offset",
                "type": "integer",
            },
            "limit": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "description": "Page size, capped at OPENPROJECT_MAX_PAGE_SIZE.",
                "title": "Limit",
            },
            "select": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "description": "Fields to return; a requested unset field comes back as null. Allowed: author, created_at, id, kind, meeting_agenda_item_id, notes, notes_length, notes_truncated, updated_at, work_package_id.",
                "title": "Select",
            },
            "text_limit": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": None, "title": "Text Limit"},
        },
        "required": ["agenda_item_id"],
        "title": "list_meeting_outcomesArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["agenda_item_id", "offset", "limit", "select", "text_limit"]


def test_get_meeting_outcome_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_meeting_outcome"]
    assert tool.description == "Get a single meeting outcome by id.\n\nRequires OpenProject 17.6+.\n"
    assert tool.output_schema == {
        "properties": {
            "id": {
                "title": "Id",
                "type": "integer",
            },
            "kind": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Kind",
            },
            "notes": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Notes",
            },
            "notes_truncated": {
                "title": "Notes Truncated",
                "type": "boolean",
            },
            "notes_length": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Notes Length",
            },
            "author": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Author",
            },
            "meeting_agenda_item_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Meeting Agenda Item Id",
            },
            "work_package_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Work Package Id",
            },
            "created_at": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Created At",
            },
            "updated_at": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Updated At",
            },
        },
        "required": [
            "id",
            "kind",
            "notes",
            "notes_truncated",
            "notes_length",
            "author",
            "meeting_agenda_item_id",
            "work_package_id",
            "created_at",
            "updated_at",
        ],
        "title": "MeetingOutcomeSummary",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {
            "outcome_id": {
                "title": "Outcome Id",
                "type": "integer",
            },
        },
        "required": [
            "outcome_id",
        ],
        "title": "get_meeting_outcomeArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["outcome_id"]


def test_create_meeting_outcome_schema() -> None:
    tool = _tools(create_app(_make_settings()))["create_meeting_outcome"]
    assert (
        tool.description
        == 'Create a meeting outcome on an agenda item.\n\nRequires OpenProject 17.6+.\n\nkind must be one of "information", "decision", "work_package" (OpenProject\'s\nreal enum values, not e.g. "info" or "action", which OpenProject rejects\nwith an internal server error rather than a clean validation error).\n"information"-kind outcomes require notes; "work_package"-kind outcomes\nrequire work_package_id.\n'
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "agenda_item_id": {"title": "Agenda Item Id", "type": "integer"},
            "kind": {"title": "Kind", "type": "string"},
            "notes": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Notes"},
            "work_package_id": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "description": 'Work package id (e.g. 952) or display id (e.g. "PROJ-51"), not the bare number 51.',
                "title": "Work Package Id",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["agenda_item_id", "kind"],
        "title": "create_meeting_outcomeArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["agenda_item_id", "kind", "notes", "work_package_id", "confirm"]


def test_update_meeting_outcome_schema() -> None:
    tool = _tools(create_app(_make_settings()))["update_meeting_outcome"]
    assert (
        tool.description
        == 'Update a meeting outcome.\n\nRequires OpenProject 17.6+.\n\nkind, if given, must be one of "information", "decision", "work_package"\n(OpenProject\'s real enum values, not e.g. "info" or "action", which\nOpenProject rejects with an internal server error rather than a clean\nvalidation error).\n'
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "outcome_id": {"title": "Outcome Id", "type": "integer"},
            "kind": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Kind"},
            "notes": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Notes"},
            "work_package_id": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "description": 'Work package id (e.g. 952) or display id (e.g. "PROJ-51"), not the bare number 51.',
                "title": "Work Package Id",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["outcome_id"],
        "title": "update_meeting_outcomeArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["outcome_id", "kind", "notes", "work_package_id", "confirm"]


def test_delete_meeting_outcome_schema() -> None:
    tool = _tools(create_app(_make_settings()))["delete_meeting_outcome"]
    assert tool.description == "Delete a meeting outcome; this cannot be undone.\n\nRequires OpenProject 17.6+.\n"
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "outcome_id": {"title": "Outcome Id", "type": "integer"},
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["outcome_id"],
        "title": "delete_meeting_outcomeArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["outcome_id", "confirm"]


def test_list_meeting_sections_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_meeting_sections"]
    assert (
        tool.description
        == "List sections of an OpenProject meeting.\n\nRequires OpenProject 17.4+.\n\nThis list is unpaginated server-side; offset/limit are applied\nclient-side by this MCP.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "meeting_id": {"title": "Meeting Id", "type": "integer"},
            "offset": {
                "default": 1,
                "description": "1-based page number; pass the previous result's next_offset.",
                "title": "Offset",
                "type": "integer",
            },
            "limit": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "description": "Page size, capped at OPENPROJECT_MAX_PAGE_SIZE.",
                "title": "Limit",
            },
        },
        "required": ["meeting_id"],
        "title": "list_meeting_sectionsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["meeting_id", "offset", "limit"]


def test_get_meeting_section_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_meeting_section"]
    assert (
        tool.description
        == "Get a single meeting section by id: title, position and whether it is the backlog.\n\nRequires OpenProject 17.6+. Its agenda items come from list_meeting_agenda_items.\n"
    )
    assert tool.output_schema == {
        "properties": {
            "id": {
                "title": "Id",
                "type": "integer",
            },
            "title": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Title",
            },
            "position": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Position",
            },
            "backlog": {
                "title": "Backlog",
                "type": "boolean",
            },
            "meeting_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Meeting Id",
            },
            "created_at": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Created At",
            },
            "updated_at": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Updated At",
            },
        },
        "required": [
            "id",
            "title",
            "position",
            "backlog",
            "meeting_id",
            "created_at",
            "updated_at",
        ],
        "title": "MeetingSectionSummary",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {
            "section_id": {
                "description": "Meeting section id, from list_meeting_sections.",
                "title": "Section Id",
                "type": "integer",
            }
        },
        "required": ["section_id"],
        "title": "get_meeting_sectionArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["section_id"]


def test_create_meeting_section_schema() -> None:
    tool = _tools(create_app(_make_settings()))["create_meeting_section"]
    assert (
        tool.description
        == "Create a meeting section.\n\nRequires OpenProject 17.6+.\n\nbacklog cannot be changed after creation via update_meeting_section;\npass it only here, on create.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "meeting_id": {"title": "Meeting Id", "type": "integer"},
            "title": {"title": "Title", "type": "string"},
            "position": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": None, "title": "Position"},
            "backlog": {"anyOf": [{"type": "boolean"}, {"type": "null"}], "default": None, "title": "Backlog"},
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["meeting_id", "title"],
        "title": "create_meeting_sectionArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["meeting_id", "title", "position", "backlog", "confirm"]


def test_update_meeting_section_schema() -> None:
    tool = _tools(create_app(_make_settings()))["update_meeting_section"]
    assert (
        tool.description
        == "Rename or move a meeting section; omitted fields stay unchanged.\n\nRequires OpenProject 17.6+. Rejected while the meeting is closed, and for the backlog section. Its agenda\nitems stay in it. backlog cannot be changed after creation; this tool does not accept it.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "section_id": {
                "description": "Meeting section id, from list_meeting_sections.",
                "title": "Section Id",
                "type": "integer",
            },
            "title": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "New section title; it cannot be emptied.",
                "title": "Title",
            },
            "position": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "description": "New place among the meeting's sections, 1 = first; the others shift.",
                "title": "Position",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["section_id"],
        "title": "update_meeting_sectionArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["section_id", "title", "position", "confirm"]


def test_delete_meeting_section_schema() -> None:
    tool = _tools(create_app(_make_settings()))["delete_meeting_section"]
    assert (
        tool.description
        == "Delete a meeting section with its agenda items and their outcomes (they are not moved).\n\nRequires OpenProject 17.6+. Rejected while the meeting is closed, and for the backlog section. This cannot\nbe undone.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "section_id": {"title": "Section Id", "type": "integer"},
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["section_id"],
        "title": "delete_meeting_sectionArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["section_id", "confirm"]


def test_list_recurring_meetings_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_recurring_meetings"]
    assert (
        tool.description
        == "List OpenProject recurring meeting series, optionally scoped to a project.\n\nRequires OpenProject 17.4+.\n\nOmit project to list across all readable projects."
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Project identifier, id, or name; a unique part of a name or identifier also matches.",
                "title": "Project",
            },
            "offset": {
                "default": 1,
                "description": "1-based page number; pass the previous result's next_offset.",
                "title": "Offset",
                "type": "integer",
            },
            "limit": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "description": "Page size, capped at OPENPROJECT_MAX_PAGE_SIZE.",
                "title": "Limit",
            },
        },
        "title": "list_recurring_meetingsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["project", "offset", "limit"]


def test_get_recurring_meeting_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_recurring_meeting"]
    assert (
        tool.description == "Get a single OpenProject recurring meeting series by id.\n\nRequires OpenProject 17.4+.\n"
    )
    assert tool.output_schema == {
        "properties": {
            "id": {
                "title": "Id",
                "type": "integer",
            },
            "title": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Title",
            },
            "frequency": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Frequency",
            },
            "monthly_day": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Monthly Day",
            },
            "monthly_ordinal": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Monthly Ordinal",
            },
            "monthly_weekday": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Monthly Weekday",
            },
            "interval": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Interval",
            },
            "end_after": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "End After",
            },
            "end_date": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "End Date",
            },
            "iterations": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Iterations",
            },
            "time_zone": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Time Zone",
            },
            "start_time": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Start Time",
            },
            "location": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Location",
            },
            "duration": {
                "anyOf": [
                    {
                        "type": "number",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Duration",
            },
            "notify": {
                "anyOf": [
                    {
                        "type": "boolean",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Notify",
            },
            "author": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Author",
            },
            "project_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Project Id",
            },
            "project": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Project",
            },
            "template_meeting_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Template Meeting Id",
            },
            "created_at": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Created At",
            },
            "updated_at": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Updated At",
            },
        },
        "required": [
            "id",
            "title",
            "frequency",
            "monthly_day",
            "monthly_ordinal",
            "monthly_weekday",
            "interval",
            "end_after",
            "end_date",
            "iterations",
            "time_zone",
            "start_time",
            "location",
            "duration",
            "notify",
            "author",
            "project_id",
            "project",
            "template_meeting_id",
            "created_at",
            "updated_at",
        ],
        "title": "RecurringMeetingSummary",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {
            "recurring_meeting_id": {
                "description": "Recurring meeting series id, from list_recurring_meetings.",
                "title": "Recurring Meeting Id",
                "type": "integer",
            },
        },
        "required": [
            "recurring_meeting_id",
        ],
        "title": "get_recurring_meetingArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["recurring_meeting_id"]


def test_create_recurring_meeting_schema() -> None:
    tool = _tools(create_app(_make_settings()))["create_recurring_meeting"]
    assert (
        tool.description
        == "Create a recurring meeting series; its template meeting starts as a draft.\n\nRequires OpenProject 17.4+. For a single meeting use create_meeting. Occurrences are virtual until\ninit_recurring_meeting_occurrence creates one; the series is changed with update_recurring_meeting.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {
                "anyOf": [{"type": "integer"}, {"type": "string"}],
                "description": "Project identifier, id, or name; a unique part of a name or identifier also matches.",
                "title": "Project",
            },
            "title": {"description": "Series title, at most 255 characters.", "title": "Title", "type": "string"},
            "frequency": {
                "description": '"daily", "working_days", "weekly", and from 17.5 "monthly_day_of_month" or "monthly_nth_weekday".',
                "title": "Frequency",
                "type": "string",
            },
            "start_time": {
                "description": "First occurrence, ISO 8601 date-time with offset; its time of day is the series'.",
                "title": "Start Time",
                "type": "string",
            },
            "interval": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "description": 'Every n-th day, week or month, 1 to 100; "working_days" always uses 1.',
                "title": "Interval",
            },
            "end_after": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": '"never" (default), "specific_date" (requires end_date) or "iterations" (requires iterations).',
                "title": "End After",
            },
            "end_date": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": 'Last date (YYYY-MM-DD); required for end_after "specific_date".',
                "title": "End Date",
            },
            "iterations": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "description": 'Number of occurrences, 1 to 1000; required for end_after "iterations".',
                "title": "Iterations",
            },
            "monthly_day": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "description": 'Day of month, 1 to 31; required for "monthly_day_of_month".',
                "title": "Monthly Day",
            },
            "monthly_ordinal": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": '"1" to "4", or "-1" for the last; required for "monthly_nth_weekday".',
                "title": "Monthly Ordinal",
            },
            "monthly_weekday": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": 'Lowercase English weekday, e.g. "monday"; required for "monthly_nth_weekday".',
                "title": "Monthly Weekday",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["project", "title", "frequency", "start_time"],
        "title": "create_recurring_meetingArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "project",
        "title",
        "frequency",
        "start_time",
        "interval",
        "end_after",
        "end_date",
        "iterations",
        "monthly_day",
        "monthly_ordinal",
        "monthly_weekday",
        "confirm",
    ]


def test_update_recurring_meeting_schema() -> None:
    tool = _tools(create_app(_make_settings()))["update_recurring_meeting"]
    assert (
        tool.description
        == "Update an OpenProject recurring meeting series.\n\nRequires OpenProject 17.4+.\n\nAlready created future occurrences move and are renamed with the series. A schedule change other than\nthe time of day can delete cancelled occurrences; on 17.4 to 17.8 a time-of-day change also rewrites the\nslot times of past occurrences. When the schedule changes, invited participants get an update email if\nnotifications are on.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "recurring_meeting_id": {
                "description": "Recurring meeting series id, from list_recurring_meetings.",
                "title": "Recurring Meeting Id",
                "type": "integer",
            },
            "title": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Title"},
            "frequency": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Frequency"},
            "start_time": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Start Time"},
            "interval": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": None, "title": "Interval"},
            "end_after": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "End After"},
            "end_date": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "End Date"},
            "iterations": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": None, "title": "Iterations"},
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["recurring_meeting_id"],
        "title": "update_recurring_meetingArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "recurring_meeting_id",
        "title",
        "frequency",
        "start_time",
        "interval",
        "end_after",
        "end_date",
        "iterations",
        "confirm",
    ]


def test_delete_recurring_meeting_schema() -> None:
    tool = _tools(create_app(_make_settings()))["delete_recurring_meeting"]
    assert (
        tool.description
        == "Delete a recurring meeting series with all its occurrences, past and future.\n\nRequires OpenProject 17.4+. Each occurrence goes with its agenda, outcomes, attachments and time entries;\nthis cannot be undone. Invited participants get a cancellation email when notifications are on.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "recurring_meeting_id": {
                "description": "Recurring meeting series id, from list_recurring_meetings.",
                "title": "Recurring Meeting Id",
                "type": "integer",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["recurring_meeting_id"],
        "title": "delete_recurring_meetingArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["recurring_meeting_id", "confirm"]


def test_end_recurring_meeting_schema() -> None:
    tool = _tools(create_app(_make_settings()))["end_recurring_meeting"]
    assert (
        tool.description
        == "End a recurring meeting series.\n\nEnding keeps the series and its past occurrences but schedules no\nfurther ones, unlike delete_recurring_meeting. OpenProject sets the\nseries' end date to yesterday, so a series whose first occurrence still\nlies in the future is rejected with a validation error. It deletes the\nalready created future occurrences with their content, cancelled ones\nincluded. When the series' notifications are on, invitees of the deleted\nopen occurrences get a cancellation email, and the series' invitees get a\n\"series ended\" email, which a repeated call sends again.\n\nRequires OpenProject 17.8+.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "recurring_meeting_id": {
                "description": "Recurring meeting series id, from list_recurring_meetings.",
                "title": "Recurring Meeting Id",
                "type": "integer",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["recurring_meeting_id"],
        "title": "end_recurring_meetingArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["recurring_meeting_id", "confirm"]


def test_list_recurring_meeting_occurrences_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_recurring_meeting_occurrences"]
    assert (
        tool.description
        == 'List virtual occurrences of a recurring meeting.\n\nRequires OpenProject 17.4+.\n\nfilter: one of "upcoming", "past", "cancelled", "open".\nOccurrences are virtual (synthesized from the recurrence rule) except\nwhere a real Meeting has already been materialized via\ninit_recurring_meeting_occurrence; this list has no offset/pagination,\nunlike list_meetings/list_recurring_meetings.\n'
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "recurring_meeting_id": {
                "description": "Recurring meeting series id, from list_recurring_meetings.",
                "title": "Recurring Meeting Id",
                "type": "integer",
            },
            "filter": {"default": "upcoming", "title": "Filter", "type": "string"},
            "limit": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "description": 'Number of occurrences, only for filter="upcoming" (OpenProject default: 20); the other filters return their full set. Not paged.',
                "title": "Limit",
            },
        },
        "required": ["recurring_meeting_id"],
        "title": "list_recurring_meeting_occurrencesArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["recurring_meeting_id", "filter", "limit"]


def test_init_recurring_meeting_occurrence_schema() -> None:
    tool = _tools(create_app(_make_settings()))["init_recurring_meeting_occurrence"]
    assert (
        tool.description
        == "Materialize a virtual recurring-meeting occurrence into a\nreal, standalone Meeting.\n\nRequires OpenProject 17.4+.\n\nstart_time: the occurrence's exact start time (ISO 8601, matching a\nstart_time value from list_recurring_meeting_occurrences); occurrences\nhave no numeric id, they are addressed by this timestamp.\nOn success, result is a full Meeting (use its id with get_meeting/\nupdate_meeting/delete_meeting), not an occurrence. A cancelled occurrence is restored and its content\nreset to the template. If the series template is still a draft, this first sets it to open, which stays\neven if the init fails; on 17.6 and later OpenProject creates further occurrences automatically only once\nthe template is open.\nOn OpenProject 17.4 and 17.5, initializing an occurrence that already exists fails with a server error\ninstead of returning it; 17.6 and later return the existing occurrence.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "recurring_meeting_id": {
                "description": "Recurring meeting series id, from list_recurring_meetings.",
                "title": "Recurring Meeting Id",
                "type": "integer",
            },
            "start_time": {"title": "Start Time", "type": "string"},
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["recurring_meeting_id", "start_time"],
        "title": "init_recurring_meeting_occurrenceArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["recurring_meeting_id", "start_time", "confirm"]


def test_cancel_recurring_meeting_occurrence_schema() -> None:
    tool = _tools(create_app(_make_settings()))["cancel_recurring_meeting_occurrence"]
    assert (
        tool.description
        == "Cancel a virtual (not-yet-materialized) recurring-meeting\noccurrence.\n\nRequires OpenProject 17.4+.\n\nstart_time: the occurrence's exact start time (ISO 8601), matching\ninit_recurring_meeting_occurrence's addressing scheme.\n\nIf the occurrence has already been materialized into a real Meeting and\nis not itself cancelled, this fails with an error (delete_meeting the\nmaterialized meeting directly instead). If NOT yet materialized,\nOpenProject records the cancellation as a cancelled Meeting\n(init_recurring_meeting_occurrence restores it, a later schedule change of\nthe series other than the time of day can delete it); this call's result\ndoes not report that new meeting's id; list_meetings/\nlist_recurring_meeting_occurrences(filter=\"cancelled\") can be used to find\nit afterward if needed.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "recurring_meeting_id": {
                "description": "Recurring meeting series id, from list_recurring_meetings.",
                "title": "Recurring Meeting Id",
                "type": "integer",
            },
            "start_time": {"title": "Start Time", "type": "string"},
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["recurring_meeting_id", "start_time"],
        "title": "cancel_recurring_meeting_occurrenceArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["recurring_meeting_id", "start_time", "confirm"]
