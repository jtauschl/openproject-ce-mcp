"""Characterization test: freezes the 8 Time Entries MCP tool schemas.

Proves that where these tool functions live (tools.py vs. their own per-domain
file) has zero effect on what an MCP client actually sees -- parameter names/
order/types, descriptions, required fields, and whether the tool carries an
output_schema (trimmed tools register with structured_output=False and have
none, see test_trimming.py). A future relocation of any of these functions to
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
        == "List time entries with optional project, work package, user, and date filters.\n\nwork_package_id: internal id (e.g., 952) or display_id (e.g., \"PROJ-51\"), not UI display number.\n\nselect fields: id, hours, spent_on, comment, activity, user, work_package_id\n(see server instructions for select's general semantics).\n\nlimit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned\nnext_offset as the next call's offset to page past the cap. total is only\nthe count of allowed time entries returned on THIS page, not a full\ncount of all matches — the search stops as soon as it has enough, so an\nexact total would need an extra full walk. Page until next_offset is\nnull.\n\ninclude_total_hours=true sums `hours` (as an ISO 8601 duration) across\nevery matching entry, independent of limit/offset — this runs its own\nfull walk of the filtered collection (bounded; see\ntotal_hours_truncated), since OpenProject has no server-side sum for\ntime entries (unlike list_work_packages's include_sums). Leave false\nunless the total is actually needed: it costs extra requests on top of\nthe page this call already returns.\n"
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
            "user": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "User",
            },
            "spent_on_from": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Spent On From",
            },
            "spent_on_to": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Spent On To",
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
            "include_total_hours": {
                "default": False,
                "title": "Include Total Hours",
                "type": "boolean",
            },
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
    assert tool.output_schema == {
        "properties": {
            "id": {
                "title": "Id",
                "type": "integer",
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
            "entity_type": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Entity Type",
            },
            "entity_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Entity Id",
            },
            "entity_name": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Entity Name",
            },
            "user": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "User",
            },
            "activity": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Activity",
            },
            "hours": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Hours",
            },
            "spent_on": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Spent On",
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
            "ongoing": {
                "title": "Ongoing",
                "type": "boolean",
            },
            "comment": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Comment",
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
            "comment_truncated": {
                "default": False,
                "title": "Comment Truncated",
                "type": "boolean",
            },
            "comment_length": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Comment Length",
            },
        },
        "required": [
            "id",
            "project",
            "entity_type",
            "entity_id",
            "entity_name",
            "user",
            "activity",
            "hours",
            "spent_on",
            "start_time",
            "end_time",
            "ongoing",
            "comment",
            "created_at",
            "updated_at",
        ],
        "title": "TimeEntrySummary",
        "type": "object",
    }
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
        == "Prepare or create a time entry.\n\nwork_package_id: internal id (e.g., 952) or display_id (e.g., \"PROJ-51\"), not UI display number.\nhours accepts an ISO8601 duration string (e.g., 'PT8H' for 8 hours, 'P1D' for 1 day).\nstart_time is an ISO 8601 date-time and requires the instance setting \"allow\ntracking of start and end times\"; ignored otherwise. No end_time parameter --\nOpenProject derives it read-only from start_time + hours. Use\ncreate_time_entry_until to specify an end time instead of hours directly.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "activity": {
                "title": "Activity",
                "type": "string",
            },
            "hours": {
                "title": "Hours",
                "type": "string",
            },
            "spent_on": {
                "title": "Spent On",
                "type": "string",
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
                "default": None,
                "title": "Project",
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
            "user": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "User",
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
            "comment": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Comment",
            },
            "ongoing": {
                "anyOf": [
                    {
                        "type": "boolean",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Ongoing",
            },
            "confirm": {
                "default": False,
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
        "confirm",
    ]


def test_update_time_entry_schema() -> None:
    tool = _tools(create_app(_make_settings()))["update_time_entry"]
    assert (
        tool.description
        == "Prepare or update a time entry.\n\nhours accepts an ISO8601 duration string (e.g., 'PT8H' for 8 hours, 'P1D' for 1 day).\nstart_time is an ISO 8601 date-time. No end_time parameter -- OpenProject\nderives it read-only from start_time + hours. Use update_time_entry_until\nto specify an end time instead of hours directly.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "time_entry_id": {
                "title": "Time Entry Id",
                "type": "integer",
            },
            "user": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "User",
            },
            "activity": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Activity",
            },
            "hours": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Hours",
            },
            "spent_on": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Spent On",
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
            "comment": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Comment",
            },
            "ongoing": {
                "anyOf": [
                    {
                        "type": "boolean",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Ongoing",
            },
            "confirm": {
                "default": False,
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
        == "Prepare or create a time entry by start/end time instead of a duration.\n\nComputes hours = end_time - start_time locally; only hours and start_time\nare sent to OpenProject (end_time itself is never accepted by the server,\nsee create_time_entry's docstring). end_time must be strictly after\nstart_time. There is no ongoing parameter here -- a time entry with a\nknown end time is complete, not still running; use create_time_entry for\nan ongoing entry.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "activity": {
                "title": "Activity",
                "type": "string",
            },
            "start_time": {
                "title": "Start Time",
                "type": "string",
            },
            "end_time": {
                "title": "End Time",
                "type": "string",
            },
            "spent_on": {
                "title": "Spent On",
                "type": "string",
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
                "default": None,
                "title": "Project",
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
            "user": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "User",
            },
            "comment": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Comment",
            },
            "confirm": {
                "default": False,
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
        "confirm",
    ]


def test_update_time_entry_until_schema() -> None:
    tool = _tools(create_app(_make_settings()))["update_time_entry_until"]
    assert (
        tool.description
        == "Prepare or update a time entry by start/end time instead of a duration.\n\nComputes hours = end_time - start_time locally; only hours and start_time\nare sent to OpenProject (end_time itself is never accepted by the server,\nsee update_time_entry's docstring). end_time must be strictly after\nstart_time. Always sets ongoing=False, since a completed time span with a\nknown end time cannot still be running.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "time_entry_id": {
                "title": "Time Entry Id",
                "type": "integer",
            },
            "start_time": {
                "title": "Start Time",
                "type": "string",
            },
            "end_time": {
                "title": "End Time",
                "type": "string",
            },
            "user": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "User",
            },
            "activity": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Activity",
            },
            "spent_on": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Spent On",
            },
            "comment": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Comment",
            },
            "confirm": {
                "default": False,
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
    assert tool.description == "Prepare or delete a time entry."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "time_entry_id": {
                "title": "Time Entry Id",
                "type": "integer",
            },
            "confirm": {
                "default": False,
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
