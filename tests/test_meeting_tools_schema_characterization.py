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
        == "List OpenProject meetings, optionally scoped to a project.\n\nRequires OpenProject 17.4+ — the meetings module's agenda/section/\nparticipant shape used here does not exist on 16.6, which only exposes\nan incompatible legacy \"meeting contents\" representation.\n\nproject: identifier, name, or numeric id. Omit to list across all\nreadable projects.\n\nlimit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the\nreturned next_offset as the next call's offset to page past the cap.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Project",
            },
            "offset": {
                "default": 1,
                "title": "Offset",
                "type": "integer",
            },
            "limit": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Limit",
            },
        },
        "title": "list_meetingsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["project", "offset", "limit"]


def test_get_meeting_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_meeting"]
    assert tool.description == "Get a single OpenProject meeting by id.\n\nRequires OpenProject 17.4+.\n"
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
            "meeting_id": {
                "title": "Meeting Id",
                "type": "integer",
            },
        },
        "required": [
            "meeting_id",
        ],
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
        == 'Prepare or create an OpenProject meeting; only writes when called\nagain with confirm=true.\n\nRequires OpenProject 17.4+.\n\nproject: identifier, name, or numeric id — required, every meeting\nbelongs to exactly one project.\nduration: an ISO 8601 duration like "PT1H30M" (hours/minutes only).\nstate: meeting state (e.g. "open", "closed") — pass the value as\nreturned by list_meetings/get_meeting.\nparticipant_user_refs: list of user references (numeric id, login, or\nname) to invite as participants.\n'
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {
                "title": "Project",
                "type": "string",
            },
            "title": {
                "title": "Title",
                "type": "string",
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
                "default": None,
                "title": "Location",
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
                "default": None,
                "title": "Start Time",
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
                "default": None,
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
                "default": None,
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
                "default": None,
                "title": "Sharing",
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
                "default": None,
                "title": "Notify",
            },
            "participant_user_refs": {
                "anyOf": [
                    {
                        "items": {
                            "type": "string",
                        },
                        "type": "array",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Participant User Refs",
            },
            "confirm": {
                "default": False,
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": [
            "project",
            "title",
        ],
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
        == "Prepare or update an OpenProject meeting; only writes when called\nagain with confirm=true.\n\nRequires OpenProject 17.4+.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "meeting_id": {
                "title": "Meeting Id",
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
                "default": None,
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
                "default": None,
                "title": "Location",
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
                "default": None,
                "title": "Start Time",
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
                "default": None,
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
                "default": None,
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
                "default": None,
                "title": "Sharing",
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
                "default": None,
                "title": "Notify",
            },
            "participant_user_refs": {
                "anyOf": [
                    {
                        "items": {
                            "type": "string",
                        },
                        "type": "array",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Participant User Refs",
            },
            "lock_version": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Lock Version",
            },
            "confirm": {
                "default": False,
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": [
            "meeting_id",
        ],
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
        == "Prepare or delete an OpenProject meeting; only deletes when called\nagain with confirm=true.\n\nRequires OpenProject 17.4+.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "meeting_id": {
                "title": "Meeting Id",
                "type": "integer",
            },
            "confirm": {
                "default": False,
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": [
            "meeting_id",
        ],
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
        == "List agenda items of an OpenProject meeting.\n\nRequires OpenProject 17.4+.\n\nThis list is unpaginated server-side (OpenProject returns every agenda\nitem of the meeting in one response) — offset/limit are applied\nclient-side by this MCP.\n\nselect fields: id, title, notes (see server instructions for select's\ngeneral semantics).\n\ntext_limit caps each item's notes at that many characters (default: the\nserver's configured OPENPROJECT_TEXT_LIMIT, NOT unlimited). When text is\ncut, notes_truncated is true and notes_length reports the real length.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "meeting_id": {
                "title": "Meeting Id",
                "type": "integer",
            },
            "offset": {
                "default": 1,
                "title": "Offset",
                "type": "integer",
            },
            "limit": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Limit",
            },
            "select": {
                "anyOf": [
                    {
                        "items": {
                            "type": "string",
                        },
                        "type": "array",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Select",
            },
            "text_limit": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Text Limit",
            },
        },
        "required": [
            "meeting_id",
        ],
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
        == "List meeting agenda items linked to a work package.\n\nRequires OpenProject 17.4+.\n\nwork_package_id: internal id (e.g., 952) or display_id (e.g., \"PROJ-51\"), not UI display number.\n\nThis list is unpaginated server-side — offset/limit are applied\nclient-side by this MCP.\n\nselect fields: id, title, notes (see server instructions for select's\ngeneral semantics).\n\ntext_limit caps each item's notes at that many characters (default: the\nserver's configured OPENPROJECT_TEXT_LIMIT, NOT unlimited). When text is\ncut, notes_truncated is true and notes_length reports the real length.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "work_package_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "string",
                    },
                ],
                "title": "Work Package Id",
            },
            "offset": {
                "default": 1,
                "title": "Offset",
                "type": "integer",
            },
            "limit": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Limit",
            },
            "select": {
                "anyOf": [
                    {
                        "items": {
                            "type": "string",
                        },
                        "type": "array",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Select",
            },
            "text_limit": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Text Limit",
            },
        },
        "required": [
            "work_package_id",
        ],
        "title": "list_work_package_meeting_agenda_itemsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["work_package_id", "offset", "limit", "select", "text_limit"]


def test_get_meeting_agenda_item_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_meeting_agenda_item"]
    assert tool.description == "Get a single meeting agenda item by id.\n\nRequires OpenProject 17.4+.\n"
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
                "title": "Agenda Item Id",
                "type": "integer",
            },
        },
        "required": [
            "agenda_item_id",
        ],
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
        == 'Prepare or create a meeting agenda item; only writes when called\nagain with confirm=true.\n\nRequires OpenProject 17.4+.\n\nwork_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number; optional.\nmeeting_section_id: an existing section\'s id (from list_meeting_sections); optional.\n'
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "meeting_id": {
                "title": "Meeting Id",
                "type": "integer",
            },
            "title": {
                "title": "Title",
                "type": "string",
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
                "default": None,
                "title": "Notes",
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
                "default": None,
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
                "default": None,
                "title": "Item Type",
            },
            "work_package_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
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
                "default": None,
                "title": "Meeting Section Id",
            },
            "confirm": {
                "default": False,
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": [
            "meeting_id",
            "title",
        ],
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
        == "Prepare or update a meeting agenda item; only writes when called\nagain with confirm=true.\n\nRequires OpenProject 17.4+.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "agenda_item_id": {
                "title": "Agenda Item Id",
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
                "default": None,
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
                "default": None,
                "title": "Notes",
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
                "default": None,
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
                "default": None,
                "title": "Item Type",
            },
            "work_package_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
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
                "default": None,
                "title": "Meeting Section Id",
            },
            "confirm": {
                "default": False,
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": [
            "agenda_item_id",
        ],
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
        == "Prepare or delete a meeting agenda item; only deletes when called\nagain with confirm=true.\n\nRequires OpenProject 17.4+.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "agenda_item_id": {
                "title": "Agenda Item Id",
                "type": "integer",
            },
            "confirm": {
                "default": False,
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": [
            "agenda_item_id",
        ],
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
        == "List outcomes of a meeting agenda item.\n\nRequires OpenProject 17.6+ — the meeting_outcomes endpoint does not exist\non 17.4/17.5.\n\nThis list is unpaginated server-side — offset/limit are applied\nclient-side by this MCP.\n\nselect fields: id, kind, notes (see server instructions for select's\ngeneral semantics).\n\ntext_limit caps each outcome's notes at that many characters (default:\nthe server's configured OPENPROJECT_TEXT_LIMIT, NOT unlimited). When text\nis cut, notes_truncated is true and notes_length reports the real length.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "agenda_item_id": {
                "title": "Agenda Item Id",
                "type": "integer",
            },
            "offset": {
                "default": 1,
                "title": "Offset",
                "type": "integer",
            },
            "limit": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Limit",
            },
            "select": {
                "anyOf": [
                    {
                        "items": {
                            "type": "string",
                        },
                        "type": "array",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Select",
            },
            "text_limit": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Text Limit",
            },
        },
        "required": [
            "agenda_item_id",
        ],
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
        == 'Prepare or create a meeting outcome on an agenda item; only writes\nwhen called again with confirm=true.\n\nRequires OpenProject 17.6+.\n\nkind must be one of "information", "decision", "work_package" (OpenProject\'s\nreal enum values — not e.g. "info" or "action", which OpenProject rejects\nwith an internal server error rather than a clean validation error).\n"information"-kind outcomes require notes; "work_package"-kind outcomes\nrequire work_package_id.\n\nwork_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number; optional.\n'
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "agenda_item_id": {
                "title": "Agenda Item Id",
                "type": "integer",
            },
            "kind": {
                "title": "Kind",
                "type": "string",
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
                "default": None,
                "title": "Notes",
            },
            "work_package_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Work Package Id",
            },
            "confirm": {
                "default": False,
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": [
            "agenda_item_id",
            "kind",
        ],
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
        == 'Prepare or update a meeting outcome; only writes when called again\nwith confirm=true.\n\nRequires OpenProject 17.6+.\n\nkind, if given, must be one of "information", "decision", "work_package"\n(OpenProject\'s real enum values — not e.g. "info" or "action", which\nOpenProject rejects with an internal server error rather than a clean\nvalidation error).\n'
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "outcome_id": {
                "title": "Outcome Id",
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
                "default": None,
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
                "default": None,
                "title": "Notes",
            },
            "work_package_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Work Package Id",
            },
            "confirm": {
                "default": False,
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": [
            "outcome_id",
        ],
        "title": "update_meeting_outcomeArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["outcome_id", "kind", "notes", "work_package_id", "confirm"]


def test_delete_meeting_outcome_schema() -> None:
    tool = _tools(create_app(_make_settings()))["delete_meeting_outcome"]
    assert (
        tool.description
        == "Prepare or delete a meeting outcome; only deletes when called again\nwith confirm=true.\n\nRequires OpenProject 17.6+.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "outcome_id": {
                "title": "Outcome Id",
                "type": "integer",
            },
            "confirm": {
                "default": False,
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": [
            "outcome_id",
        ],
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
        == "List sections of an OpenProject meeting.\n\nRequires OpenProject 17.4+.\n\nThis list is unpaginated server-side — offset/limit are applied\nclient-side by this MCP.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "meeting_id": {
                "title": "Meeting Id",
                "type": "integer",
            },
            "offset": {
                "default": 1,
                "title": "Offset",
                "type": "integer",
            },
            "limit": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Limit",
            },
        },
        "required": [
            "meeting_id",
        ],
        "title": "list_meeting_sectionsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["meeting_id", "offset", "limit"]


def test_get_meeting_section_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_meeting_section"]
    assert tool.description == "Get a single meeting section by id.\n\nRequires OpenProject 17.4+.\n"
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
                "title": "Section Id",
                "type": "integer",
            },
        },
        "required": [
            "section_id",
        ],
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
        == "Prepare or create a meeting section; only writes when called again\nwith confirm=true.\n\nRequires OpenProject 17.4+.\n\nbacklog cannot be changed after creation via update_meeting_section —\npass it only here, on create.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "meeting_id": {
                "title": "Meeting Id",
                "type": "integer",
            },
            "title": {
                "title": "Title",
                "type": "string",
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
                "default": None,
                "title": "Position",
            },
            "backlog": {
                "anyOf": [
                    {
                        "type": "boolean",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Backlog",
            },
            "confirm": {
                "default": False,
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": [
            "meeting_id",
            "title",
        ],
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
        == "Prepare or update a meeting section's title/position; only writes\nwhen called again with confirm=true.\n\nRequires OpenProject 17.4+.\n\nbacklog cannot be changed after creation — this tool does not accept it.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "section_id": {
                "title": "Section Id",
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
                "default": None,
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
                "default": None,
                "title": "Position",
            },
            "confirm": {
                "default": False,
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": [
            "section_id",
        ],
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
        == "Prepare or delete a meeting section; only deletes when called again\nwith confirm=true.\n\nRequires OpenProject 17.4+.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "section_id": {
                "title": "Section Id",
                "type": "integer",
            },
            "confirm": {
                "default": False,
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": [
            "section_id",
        ],
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
        == "List OpenProject recurring meeting series, optionally scoped to a project.\n\nRequires OpenProject 17.4+.\n\nproject: identifier, name, or numeric id. Omit to list across all\nreadable projects.\n\nlimit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the\nreturned next_offset as the next call's offset to page past the cap.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Project",
            },
            "offset": {
                "default": 1,
                "title": "Offset",
                "type": "integer",
            },
            "limit": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
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
        == 'Prepare or create an OpenProject recurring meeting series; only\nwrites when called again with confirm=true.\n\nRequires OpenProject 17.4+.\n\nproject: identifier, name, or numeric id — required, every recurring\nmeeting belongs to exactly one project.\nfrequency: e.g. "daily", "weekly", "monthly" — pass the value as\nreturned by list_recurring_meetings/get_recurring_meeting.\nend_after: e.g. "date", "iterations", "never" — governs which of\nend_date/iterations is used.\n'
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {
                "title": "Project",
                "type": "string",
            },
            "title": {
                "title": "Title",
                "type": "string",
            },
            "frequency": {
                "title": "Frequency",
                "type": "string",
            },
            "start_time": {
                "title": "Start Time",
                "type": "string",
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
                "default": None,
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
                "default": None,
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
                "default": None,
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
                "default": None,
                "title": "Iterations",
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
                "default": None,
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
                "default": None,
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
                "default": None,
                "title": "Monthly Weekday",
            },
            "confirm": {
                "default": False,
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": [
            "project",
            "title",
            "frequency",
            "start_time",
        ],
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
        == "Prepare or update an OpenProject recurring meeting series; only\nwrites when called again with confirm=true.\n\nRequires OpenProject 17.4+.\n\nNote: this does not affect meetings already materialized from this\nseries (via init_recurring_meeting_occurrence) — update those directly\nwith update_meeting.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "recurring_meeting_id": {
                "title": "Recurring Meeting Id",
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
                "default": None,
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
                "default": None,
                "title": "Frequency",
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
                "default": None,
                "title": "Start Time",
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
                "default": None,
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
                "default": None,
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
                "default": None,
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
                "default": None,
                "title": "Iterations",
            },
            "confirm": {
                "default": False,
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": [
            "recurring_meeting_id",
        ],
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
        == "Prepare or delete an OpenProject recurring meeting series; only\ndeletes when called again with confirm=true.\n\nRequires OpenProject 17.4+.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "recurring_meeting_id": {
                "title": "Recurring Meeting Id",
                "type": "integer",
            },
            "confirm": {
                "default": False,
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": [
            "recurring_meeting_id",
        ],
        "title": "delete_recurring_meetingArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["recurring_meeting_id", "confirm"]


def test_list_recurring_meeting_occurrences_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_recurring_meeting_occurrences"]
    assert (
        tool.description
        == 'List virtual occurrences of a recurring meeting.\n\nRequires OpenProject 17.4+.\n\nfilter: one of "upcoming", "past", "cancelled", "open".\nlimit: only applies when filter="upcoming" (OpenProject default: 20);\nignored for the other three filters, which always return their full set.\nOccurrences are virtual (synthesized from the recurrence rule) except\nwhere a real Meeting has already been materialized via\ninit_recurring_meeting_occurrence — this list has no offset/pagination,\nunlike list_meetings/list_recurring_meetings.\n'
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "recurring_meeting_id": {
                "title": "Recurring Meeting Id",
                "type": "integer",
            },
            "filter": {
                "default": "upcoming",
                "title": "Filter",
                "type": "string",
            },
            "limit": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Limit",
            },
        },
        "required": [
            "recurring_meeting_id",
        ],
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
        == "Prepare or materialize a virtual recurring-meeting occurrence into a\nreal, standalone Meeting; only writes when called again with confirm=true.\n\nRequires OpenProject 17.4+.\n\nstart_time: the occurrence's exact start time (ISO 8601, matching a\nstart_time value from list_recurring_meeting_occurrences) — occurrences\nhave no numeric id, they are addressed by this timestamp.\nOn success, result is a full Meeting (use its id with get_meeting/\nupdate_meeting/delete_meeting), not an occurrence.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "recurring_meeting_id": {
                "title": "Recurring Meeting Id",
                "type": "integer",
            },
            "start_time": {
                "title": "Start Time",
                "type": "string",
            },
            "confirm": {
                "default": False,
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": [
            "recurring_meeting_id",
            "start_time",
        ],
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
        == "Prepare or cancel a virtual (not-yet-materialized) recurring-meeting\noccurrence; only writes when called again with confirm=true.\n\nRequires OpenProject 17.4+.\n\nstart_time: the occurrence's exact start time (ISO 8601), matching\ninit_recurring_meeting_occurrence's addressing scheme.\n\nIf the occurrence has already been materialized into a real Meeting and\nis not itself cancelled, this fails with an error (delete_meeting the\nmaterialized meeting directly instead). If NOT yet materialized,\nOpenProject creates a new, PERMANENTLY cancelled Meeting server-side to\nrecord the cancellation — this call's result does not report that new\nmeeting's id; list_meetings/list_recurring_meeting_occurrences(filter=\n\"cancelled\") can be used to find it afterward if needed.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "recurring_meeting_id": {
                "title": "Recurring Meeting Id",
                "type": "integer",
            },
            "start_time": {
                "title": "Start Time",
                "type": "string",
            },
            "confirm": {
                "default": False,
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": [
            "recurring_meeting_id",
            "start_time",
        ],
        "title": "cancel_recurring_meeting_occurrenceArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["recurring_meeting_id", "start_time", "confirm"]
