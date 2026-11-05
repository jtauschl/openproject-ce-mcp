"""Characterization test: freezes the 9 User Schedule MCP tool schemas.

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
        "enable_user_schedule_read": True,
        "enable_user_schedule_write": True,
        "read_projects": ("*",),
        "write_projects": ("*",),
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _tools(mcp) -> dict:
    return {t.name: t for t in mcp._tool_manager.list_tools()}


def test_list_user_non_working_times_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_user_non_working_times"]
    assert tool.description == (
        'List a user\'s per-user non-working-time date ranges (e.g. vacation),\ndistinct from the instance-wide non-working days.\n\nRequires OpenProject 17.3+ (feature-flag-gated through 17.6, generally\navailable from 17.7). On an older server, or on 17.3 to 17.6 with the\nfeature flag off, the route answers 404 and the tool returns a\n[RESOURCE_NOT_FOUND] naming the 17.3 floor.\n\nOpenProject enforces this at the API level: you may always view your own\nschedule (user_ref="me"); viewing another user\'s requires the\nmanage_working_times global permission, else OpenProject returns 404\n(not 403) to avoid confirming the user exists.\n\nuser_ref: "me" for the current user, a numeric user id, or a login.\nyear: filter to this calendar year; defaults to the current year.\nThe collection is unpaginated on OpenProject\'s side; this MCP fetches\nthe full requested year and paginates client-side; limit is capped at\nOPENPROJECT_MAX_PAGE_SIZE (default 50).\n'
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "user_ref": {"anyOf": [{"type": "integer"}, {"type": "string"}], "title": "User Ref"},
            "year": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": None, "title": "Year"},
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
        "required": ["user_ref"],
        "title": "list_user_non_working_timesArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["user_ref", "year", "offset", "limit"]


def test_create_user_non_working_time_schema() -> None:
    tool = _tools(create_app(_make_settings()))["create_user_non_working_time"]
    assert tool.description == (
        "Create a non-working-time date range for a user.\n"
        "\n"
        "Requires OpenProject 17.3+. Same self-service-or-manage_working_times\n"
        "authorization as list_user_non_working_times.\n"
        "\n"
        'user_ref: "me" for the current user, a numeric user id, or a login.\n'
        "start_date/end_date: ISO 8601 dates (YYYY-MM-DD).\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "user_ref": {"anyOf": [{"type": "integer"}, {"type": "string"}], "title": "User Ref"},
            "start_date": {"title": "Start Date", "type": "string"},
            "end_date": {"title": "End Date", "type": "string"},
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["user_ref", "start_date", "end_date"],
        "title": "create_user_non_working_timeArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["user_ref", "start_date", "end_date", "confirm"]


def test_update_user_non_working_time_schema() -> None:
    tool = _tools(create_app(_make_settings()))["update_user_non_working_time"]
    assert tool.description == (
        "Update a user's non-working-time date range.\n\nRequires OpenProject 17.3+. Same authorization as\nlist_user_non_working_times. No single-item GET exists on OpenProject's\nside for this resource, but the update itself is addressed directly by\nid (no year or other date filter involved); a non-existent id fails\nwith a not-found error on confirm; the preview does not look it up.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "user_ref": {"anyOf": [{"type": "integer"}, {"type": "string"}], "title": "User Ref"},
            "non_working_time_id": {"title": "Non Working Time Id", "type": "integer"},
            "start_date": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Start Date"},
            "end_date": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "End Date"},
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["user_ref", "non_working_time_id"],
        "title": "update_user_non_working_timeArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "user_ref",
        "non_working_time_id",
        "start_date",
        "end_date",
        "confirm",
    ]


def test_delete_user_non_working_time_schema() -> None:
    tool = _tools(create_app(_make_settings()))["delete_user_non_working_time"]
    assert tool.description == (
        "Delete a user's non-working-time date range; this cannot be undone.\n"
        "\n"
        "Requires OpenProject 17.3+. Same authorization as\n"
        "list_user_non_working_times.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "user_ref": {"anyOf": [{"type": "integer"}, {"type": "string"}], "title": "User Ref"},
            "non_working_time_id": {"title": "Non Working Time Id", "type": "integer"},
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["user_ref", "non_working_time_id"],
        "title": "delete_user_non_working_timeArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["user_ref", "non_working_time_id", "confirm"]


def test_list_user_working_hours_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_user_working_hours"]
    assert tool.description == (
        "List a user's recurring weekly working-hours schedules, ordered by\nvalid_from descending (most recent first).\n\nRequires OpenProject 17.3+ (feature-flag-gated through 17.6, generally\navailable from 17.7).\n\nSame self-service-or-manage_working_times authorization as\nlist_user_non_working_times: OpenProject returns 404 (not 403) for an\nunauthorized cross-user request.\n\nuser_ref: \"me\" for the current user, a numeric user id, or a login.\nThe collection is unpaginated on OpenProject's side; this MCP fetches\nthe full list and paginates client-side; limit is capped at\nOPENPROJECT_MAX_PAGE_SIZE (default 50).\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "user_ref": {"anyOf": [{"type": "integer"}, {"type": "string"}], "title": "User Ref"},
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
        "required": ["user_ref"],
        "title": "list_user_working_hoursArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["user_ref", "offset", "limit"]


def test_get_user_working_hours_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_user_working_hours"]
    assert tool.description == (
        "Get a single working-hours schedule entry for a user.\n\n"
        "Requires OpenProject 17.3+. Same authorization as\n"
        "list_user_working_hours.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "user_ref": {
                "anyOf": [{"type": "integer"}, {"type": "string"}],
                "description": '"me", a numeric user id, or a login.',
                "title": "User Ref",
            },
            "working_hours_id": {
                "description": "Schedule entry id, from list_user_working_hours.",
                "title": "Working Hours Id",
                "type": "integer",
            },
        },
        "required": ["user_ref", "working_hours_id"],
        "title": "get_user_working_hoursArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["user_ref", "working_hours_id"]


def test_create_user_working_hours_schema() -> None:
    tool = _tools(create_app(_make_settings()))["create_user_working_hours"]
    assert tool.description == (
        "Create a new weekly working-hours schedule version for a user, effective from valid_from.\n"
        "\n"
        "Requires OpenProject 17.3+. Same self-service-or-manage_working_times\n"
        "authorization as list_user_working_hours. The earlier version keeps\n"
        "applying to the dates before valid_from.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "user_ref": {
                "anyOf": [{"type": "integer"}, {"type": "string"}],
                "description": '"me", a numeric user id, or a login.',
                "title": "User Ref",
            },
            "valid_from": {
                "description": "Date (YYYY-MM-DD) this schedule version takes effect; unique per user.",
                "title": "Valid From",
                "type": "string",
            },
            "monday_hours": {
                "anyOf": [{"type": "number"}, {"type": "null"}],
                "default": None,
                "description": "Hours that day, 0 to 24; omitted means 0 (not a working day). At least one day must be above 0.",
                "title": "Monday Hours",
            },
            "tuesday_hours": {
                "anyOf": [{"type": "number"}, {"type": "null"}],
                "default": None,
                "description": "Hours that day, 0 to 24; omitted means 0 (not a working day). At least one day must be above 0.",
                "title": "Tuesday Hours",
            },
            "wednesday_hours": {
                "anyOf": [{"type": "number"}, {"type": "null"}],
                "default": None,
                "description": "Hours that day, 0 to 24; omitted means 0 (not a working day). At least one day must be above 0.",
                "title": "Wednesday Hours",
            },
            "thursday_hours": {
                "anyOf": [{"type": "number"}, {"type": "null"}],
                "default": None,
                "description": "Hours that day, 0 to 24; omitted means 0 (not a working day). At least one day must be above 0.",
                "title": "Thursday Hours",
            },
            "friday_hours": {
                "anyOf": [{"type": "number"}, {"type": "null"}],
                "default": None,
                "description": "Hours that day, 0 to 24; omitted means 0 (not a working day). At least one day must be above 0.",
                "title": "Friday Hours",
            },
            "saturday_hours": {
                "anyOf": [{"type": "number"}, {"type": "null"}],
                "default": None,
                "description": "Hours that day, 0 to 24; omitted means 0 (not a working day). At least one day must be above 0.",
                "title": "Saturday Hours",
            },
            "sunday_hours": {
                "anyOf": [{"type": "number"}, {"type": "null"}],
                "default": None,
                "description": "Hours that day, 0 to 24; omitted means 0 (not a working day). At least one day must be above 0.",
                "title": "Sunday Hours",
            },
            "availability_factor": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "description": "Percentage of the working time dedicated to project work: pass a whole number 0 to 100.",
                "title": "Availability Factor",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["user_ref", "valid_from"],
        "title": "create_user_working_hoursArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "user_ref",
        "valid_from",
        "monday_hours",
        "tuesday_hours",
        "wednesday_hours",
        "thursday_hours",
        "friday_hours",
        "saturday_hours",
        "sunday_hours",
        "availability_factor",
        "confirm",
    ]


def test_update_user_working_hours_schema() -> None:
    tool = _tools(create_app(_make_settings()))["update_user_working_hours"]
    assert tool.description == (
        "Correct an existing working-hours schedule entry in place; omitted fields stay unchanged.\n"
        "\n"
        "Requires OpenProject 17.3+. Same authorization as list_user_working_hours. The entry applies from its\n"
        "valid_from until the next entry's; to change a schedule from a later date on, add a new entry with\n"
        "create_user_working_hours instead, which keeps the earlier one for the dates before.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "user_ref": {
                "anyOf": [{"type": "integer"}, {"type": "string"}],
                "description": '"me", a numeric user id, or a login.',
                "title": "User Ref",
            },
            "working_hours_id": {
                "description": "Schedule entry id, from list_user_working_hours.",
                "title": "Working Hours Id",
                "type": "integer",
            },
            "valid_from": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "New start date (YYYY-MM-DD) of this entry; unique per user.",
                "title": "Valid From",
            },
            "monday_hours": {
                "anyOf": [{"type": "number"}, {"type": "null"}],
                "default": None,
                "description": "Hours that day, 0 to 24; at least one day must be above 0.",
                "title": "Monday Hours",
            },
            "tuesday_hours": {
                "anyOf": [{"type": "number"}, {"type": "null"}],
                "default": None,
                "description": "Hours that day, 0 to 24; at least one day must be above 0.",
                "title": "Tuesday Hours",
            },
            "wednesday_hours": {
                "anyOf": [{"type": "number"}, {"type": "null"}],
                "default": None,
                "description": "Hours that day, 0 to 24; at least one day must be above 0.",
                "title": "Wednesday Hours",
            },
            "thursday_hours": {
                "anyOf": [{"type": "number"}, {"type": "null"}],
                "default": None,
                "description": "Hours that day, 0 to 24; at least one day must be above 0.",
                "title": "Thursday Hours",
            },
            "friday_hours": {
                "anyOf": [{"type": "number"}, {"type": "null"}],
                "default": None,
                "description": "Hours that day, 0 to 24; at least one day must be above 0.",
                "title": "Friday Hours",
            },
            "saturday_hours": {
                "anyOf": [{"type": "number"}, {"type": "null"}],
                "default": None,
                "description": "Hours that day, 0 to 24; at least one day must be above 0.",
                "title": "Saturday Hours",
            },
            "sunday_hours": {
                "anyOf": [{"type": "number"}, {"type": "null"}],
                "default": None,
                "description": "Hours that day, 0 to 24; at least one day must be above 0.",
                "title": "Sunday Hours",
            },
            "availability_factor": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "description": "Percentage of the working time dedicated to project work: pass a whole number 0 to 100.",
                "title": "Availability Factor",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["user_ref", "working_hours_id"],
        "title": "update_user_working_hoursArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "user_ref",
        "working_hours_id",
        "valid_from",
        "monday_hours",
        "tuesday_hours",
        "wednesday_hours",
        "thursday_hours",
        "friday_hours",
        "saturday_hours",
        "sunday_hours",
        "availability_factor",
        "confirm",
    ]


def test_delete_user_working_hours_schema() -> None:
    tool = _tools(create_app(_make_settings()))["delete_user_working_hours"]
    assert tool.description == (
        "Delete a user's working-hours schedule entry; this cannot be undone.\n"
        "\n"
        "Requires OpenProject 17.3+. Same authorization as list_user_working_hours. For the dates it covered, the\n"
        "previous entry applies again.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "user_ref": {"anyOf": [{"type": "integer"}, {"type": "string"}], "title": "User Ref"},
            "working_hours_id": {"title": "Working Hours Id", "type": "integer"},
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["user_ref", "working_hours_id"],
        "title": "delete_user_working_hoursArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["user_ref", "working_hours_id", "confirm"]
