"""Characterization test: freezes the 8 Time Entries MCP tool schemas.

Proves that where these tool functions live (tools.py vs. their own per-domain
file) has zero effect on what an MCP client actually sees -- parameter names/
order/types, descriptions, required fields, and whether the tool carries an
output_schema (no tool carries one, see test_compact_result_seam.py). A future relocation of any of these functions to
a different module must leave this file completely unmodified; a diff to it
would mean the move changed the public tool contract, not just its location.
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
        "enable_work_package_write": True,
        "enable_project_write": True,
        "enable_membership_write": True,
        "enable_version_write": True,
        "enable_board_write": True,
        "enable_admin_write": True,
        "read_projects": ("*",),
        "write_projects": ("*",),
        "enable_metadata_tools": True,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _tools(mcp) -> dict:
    return {t.name: t for t in mcp._tool_manager.list_tools()}


def test_list_time_entry_activities_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_time_entry_activities"]
    assert tool.description == "List available time entry activities."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {},
        "title": "list_time_entry_activitiesArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == []


def test_list_time_entries_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_time_entries"]
    assert (
        tool.description
        == "List time entries with optional project, work package, user, and date filters.\n\ntotal is only the count of allowed time entries returned on THIS page, not a full count of all matches; the\nsearch stops as soon as it has enough, so an exact total would need an extra full walk. Page until next_offset\nis null.\n\ninclude_total_hours=true sums `hours` (as an ISO 8601 duration) across\nevery matching entry, independent of limit/offset; this runs its own\nfull walk of the filtered collection (bounded; see\ntotal_hours_truncated), since OpenProject has no server-side sum for\ntime entries (unlike list_work_packages's include_sums). Leave false\nunless the total is actually needed: it costs extra requests on top of\nthe page this call already returns.\n"
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
            "work_package_id": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "description": 'Work package id (e.g. 952) or display id (e.g. "PROJ-51"), not the bare number 51.',
                "title": "Work Package Id",
            },
            "user": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "User",
            },
            "spent_on_from": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Spent On From",
            },
            "spent_on_to": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Spent On To"},
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
                "description": "Fields to return; a requested unset field comes back as null. Allowed: activity, comment, comment_length, comment_truncated, created_at, end_time, entity_id, entity_name, entity_type, hours, id, ongoing, project, spent_on, start_time, updated_at, user, user_id.",
                "title": "Select",
            },
            "include_total_hours": {"default": False, "title": "Include Total Hours", "type": "boolean"},
        },
        "title": "list_time_entriesArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "project",
        "work_package_id",
        "user",
        "spent_on_from",
        "spent_on_to",
        "offset",
        "limit",
        "select",
        "include_total_hours",
    ]


def test_get_time_entry_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_time_entry"]
    assert (
        tool.description
        == "Get a single time entry by id, including its full comment.\n\nThe comment is returned in full by default (single time entries are not\ntruncated). Pass ``text_limit`` to cap it at that many characters; when the\ntext is cut, ``comment_truncated`` is true and ``comment_length`` reports\nthe real length.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "time_entry_id": {
                "title": "Time Entry Id",
                "type": "integer",
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
        "required": ["time_entry_id"],
        "title": "get_time_entryArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["time_entry_id", "text_limit"]


def test_create_time_entry_schema() -> None:
    tool = _tools(create_app(_make_settings()))["create_time_entry"]
    assert (
        tool.description
        == "Create a time entry.\n\nhours accepts an ISO8601 duration string (e.g., 'PT8H' for 8 hours). A day in a duration string is 24 hours, so write 'PT8H' for a working day.\nstart_time is an ISO 8601 date-time and requires the instance setting \"allow\ntracking of start and end times\"; ignored otherwise. No end_time parameter --\nOpenProject derives it read-only from start_time + hours. Use\ncreate_time_entry_until to specify an end time instead of hours directly.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "activity": {"anyOf": [{"type": "integer"}, {"type": "string"}], "title": "Activity"},
            "hours": {"title": "Hours", "type": "string"},
            "spent_on": {"title": "Spent On", "type": "string"},
            "project": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Project identifier, id, or name; a unique part of a name or identifier also matches.",
                "title": "Project",
            },
            "work_package_id": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "description": 'Work package id (e.g. 952) or display id (e.g. "PROJ-51"), not the bare number 51.',
                "title": "Work Package Id",
            },
            "user": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "User",
            },
            "start_time": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Start Time"},
            "comment": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Comment"},
            "ongoing": {"anyOf": [{"type": "boolean"}, {"type": "null"}], "default": None, "title": "Ongoing"},
            "expect_display_id": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": 'Display id of the work package you mean, e.g. "PROJ-51"; see the server instructions.',
                "title": "Expect Display Id",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["activity", "hours", "spent_on"],
        "title": "create_time_entryArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "activity",
        "hours",
        "spent_on",
        "project",
        "work_package_id",
        "user",
        "start_time",
        "comment",
        "ongoing",
        "expect_display_id",
        "confirm",
    ]


def test_update_time_entry_schema() -> None:
    tool = _tools(create_app(_make_settings()))["update_time_entry"]
    assert (
        tool.description
        == "Update a time entry.\n\nhours accepts an ISO8601 duration string (e.g., 'PT8H' for 8 hours). A day in a duration string is 24 hours, so write 'PT8H' for a working day.\nstart_time is an ISO 8601 date-time. No end_time parameter -- OpenProject\nderives it read-only from start_time + hours. Use update_time_entry_until\nto specify an end time instead of hours directly.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "time_entry_id": {"title": "Time Entry Id", "type": "integer"},
            "user": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "User",
            },
            "activity": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Activity",
            },
            "hours": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Hours"},
            "spent_on": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Spent On"},
            "start_time": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Start Time"},
            "comment": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Comment"},
            "ongoing": {"anyOf": [{"type": "boolean"}, {"type": "null"}], "default": None, "title": "Ongoing"},
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["time_entry_id"],
        "title": "update_time_entryArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "time_entry_id",
        "user",
        "activity",
        "hours",
        "spent_on",
        "start_time",
        "comment",
        "ongoing",
        "confirm",
    ]


def test_create_time_entry_until_schema() -> None:
    tool = _tools(create_app(_make_settings()))["create_time_entry_until"]
    assert (
        tool.description
        == "Create a time entry by start/end time instead of a duration.\n\nComputes hours = end_time - start_time locally; only hours and start_time\nare sent to OpenProject (end_time itself is never accepted by the server,\nsee create_time_entry's docstring). end_time must be strictly after\nstart_time. There is no ongoing parameter here -- a time entry with a\nknown end time is complete, not still running; use create_time_entry for\nan ongoing entry.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "activity": {"anyOf": [{"type": "integer"}, {"type": "string"}], "title": "Activity"},
            "start_time": {"title": "Start Time", "type": "string"},
            "end_time": {"title": "End Time", "type": "string"},
            "spent_on": {"title": "Spent On", "type": "string"},
            "project": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Project identifier, id, or name; a unique part of a name or identifier also matches.",
                "title": "Project",
            },
            "work_package_id": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "description": 'Work package id (e.g. 952) or display id (e.g. "PROJ-51"), not the bare number 51.',
                "title": "Work Package Id",
            },
            "user": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "User",
            },
            "comment": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Comment"},
            "expect_display_id": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": 'Display id of the work package you mean, e.g. "PROJ-51"; see the server instructions.',
                "title": "Expect Display Id",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["activity", "start_time", "end_time", "spent_on"],
        "title": "create_time_entry_untilArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "activity",
        "start_time",
        "end_time",
        "spent_on",
        "project",
        "work_package_id",
        "user",
        "comment",
        "expect_display_id",
        "confirm",
    ]


def test_update_time_entry_until_schema() -> None:
    tool = _tools(create_app(_make_settings()))["update_time_entry_until"]
    assert (
        tool.description
        == "Update a time entry by start/end time instead of a duration.\n\nComputes hours = end_time - start_time locally; only hours and start_time\nare sent to OpenProject (end_time itself is never accepted by the server,\nsee update_time_entry's docstring). end_time must be strictly after\nstart_time. Always sets ongoing=False, since a completed time span with a\nknown end time cannot still be running.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "time_entry_id": {"title": "Time Entry Id", "type": "integer"},
            "start_time": {"title": "Start Time", "type": "string"},
            "end_time": {"title": "End Time", "type": "string"},
            "user": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "User",
            },
            "activity": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Activity",
            },
            "spent_on": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Spent On"},
            "comment": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Comment"},
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["time_entry_id", "start_time", "end_time"],
        "title": "update_time_entry_untilArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "time_entry_id",
        "start_time",
        "end_time",
        "user",
        "activity",
        "spent_on",
        "comment",
        "confirm",
    ]


def test_delete_time_entry_schema() -> None:
    tool = _tools(create_app(_make_settings()))["delete_time_entry"]
    assert tool.description == "Delete a time entry; this cannot be undone."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "time_entry_id": {
                "description": "Time entry id, from list_time_entries.",
                "title": "Time Entry Id",
                "type": "integer",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["time_entry_id"],
        "title": "delete_time_entryArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["time_entry_id", "confirm"]
