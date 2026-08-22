"""Characterization test: freezes the 9 User Schedule MCP tool schemas.

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
        "List a user's per-user non-working-time date ranges (e.g. vacation),\n"
        "distinct from the instance-wide non-working days (list_non_working_days).\n\n"
        "Requires OpenProject 17.3+ (feature-flag-gated through 17.6, generally\n"
        "available from 17.7). Earlier versions return a [server_error] for this\n"
        "endpoint — the route does not exist before 17.3.\n\n"
        "OpenProject enforces this at the API level: you may always view your own\n"
        'schedule (user_ref="me"); viewing another user\'s requires the\n'
        "manage_working_times global permission, else OpenProject returns 404\n"
        "(not 403) to avoid confirming the user exists.\n\n"
        'user_ref: "me" for the current user, a numeric user id, or a login.\n'
        "year: filter to this calendar year; defaults to the current year.\n"
        "The collection is unpaginated on OpenProject's side — this MCP fetches\n"
        "the full requested year and paginates client-side; limit is capped at\n"
        "OPENPROJECT_MAX_PAGE_SIZE (default 50).\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "user_ref": {"title": "User Ref", "type": "string"},
            "year": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "title": "Year",
            },
            "offset": {"default": 1, "title": "Offset", "type": "integer"},
            "limit": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
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
        "Prepare or create a non-working-time date range for a user; only\n"
        "writes when called again with confirm=true.\n\n"
        "Requires OpenProject 17.3+. Same self-service-or-manage_working_times\n"
        "authorization as list_user_non_working_times.\n\n"
        'user_ref: "me" for the current user, a numeric user id, or a login.\n'
        "start_date/end_date: ISO 8601 dates (YYYY-MM-DD).\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "user_ref": {"title": "User Ref", "type": "string"},
            "start_date": {"title": "Start Date", "type": "string"},
            "end_date": {"title": "End Date", "type": "string"},
            "confirm": {"default": False, "title": "Confirm", "type": "boolean"},
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
        "Prepare or update a user's non-working-time date range; only writes\n"
        "when called again with confirm=true.\n\n"
        "Requires OpenProject 17.3+. Same authorization as\n"
        "list_user_non_working_times. No single-item GET exists on OpenProject's\n"
        "side for this resource, but the update itself is addressed directly by\n"
        "id (no year or other date filter involved) — a non-existent id fails\n"
        "with a not-found error.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "user_ref": {"title": "User Ref", "type": "string"},
            "non_working_time_id": {"title": "Non Working Time Id", "type": "integer"},
            "start_date": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Start Date",
            },
            "end_date": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "End Date",
            },
            "confirm": {"default": False, "title": "Confirm", "type": "boolean"},
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
        "Prepare or delete a user's non-working-time date range; only deletes\n"
        "when called again with confirm=true.\n\n"
        "Requires OpenProject 17.3+. Same authorization as\n"
        "list_user_non_working_times.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "user_ref": {"title": "User Ref", "type": "string"},
            "non_working_time_id": {"title": "Non Working Time Id", "type": "integer"},
            "confirm": {"default": False, "title": "Confirm", "type": "boolean"},
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
        "List a user's recurring weekly working-hours schedules, ordered by\n"
        "valid_from descending (most recent first).\n\n"
        "Requires OpenProject 17.3+ (feature-flag-gated through 17.6, generally\n"
        "available from 17.7).\n\n"
        "Same self-service-or-manage_working_times authorization as\n"
        "list_user_non_working_times: OpenProject returns 404 (not 403) for an\n"
        "unauthorized cross-user request.\n\n"
        'user_ref: "me" for the current user, a numeric user id, or a login.\n'
        "The collection is unpaginated on OpenProject's side — this MCP fetches\n"
        "the full list and paginates client-side; limit is capped at\n"
        "OPENPROJECT_MAX_PAGE_SIZE (default 50).\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "user_ref": {"title": "User Ref", "type": "string"},
            "offset": {"default": 1, "title": "Offset", "type": "integer"},
            "limit": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
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
    assert tool.output_schema is not None
    assert tool.parameters == {
        "properties": {
            "user_ref": {"title": "User Ref", "type": "string"},
            "working_hours_id": {"title": "Working Hours Id", "type": "integer"},
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
        "Prepare or create a new weekly working-hours schedule version for a\n"
        "user, effective from valid_from; only writes when called again with\n"
        "confirm=true.\n\n"
        "Requires OpenProject 17.3+. Same self-service-or-manage_working_times\n"
        "authorization as list_user_working_hours.\n\n"
        'user_ref: "me" for the current user, a numeric user id, or a login.\n'
        "valid_from: ISO 8601 date (YYYY-MM-DD) this schedule version takes effect.\n"
        "*_hours: hours worked on that weekday; a weekday you omit is treated as\n"
        "0 (not a working day) -- OpenProject requires every weekday to have a\n"
        "value on create, so this MCP fills in 0 for you rather than sending an\n"
        "incomplete schedule.\n"
        "availability_factor: fractional working-time factor (e.g. 0.5 for\n"
        "half-time), independent of the per-day hour values.\n"
    )
    assert tool.output_schema is None
    day_props = {
        day: {
            "anyOf": [{"type": "number"}, {"type": "null"}],
            "default": None,
            "title": title,
        }
        for day, title in [
            ("monday_hours", "Monday Hours"),
            ("tuesday_hours", "Tuesday Hours"),
            ("wednesday_hours", "Wednesday Hours"),
            ("thursday_hours", "Thursday Hours"),
            ("friday_hours", "Friday Hours"),
            ("saturday_hours", "Saturday Hours"),
            ("sunday_hours", "Sunday Hours"),
        ]
    }
    assert tool.parameters == {
        "properties": {
            "user_ref": {"title": "User Ref", "type": "string"},
            "valid_from": {"title": "Valid From", "type": "string"},
            **day_props,
            "availability_factor": {
                "anyOf": [{"type": "number"}, {"type": "null"}],
                "default": None,
                "title": "Availability Factor",
            },
            "confirm": {"default": False, "title": "Confirm", "type": "boolean"},
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
        "Prepare or update a user's working-hours schedule entry; only writes\n"
        "when called again with confirm=true.\n\n"
        "Requires OpenProject 17.3+. Same authorization as list_user_working_hours.\n"
    )
    assert tool.output_schema is None
    day_props = {
        day: {
            "anyOf": [{"type": "number"}, {"type": "null"}],
            "default": None,
            "title": title,
        }
        for day, title in [
            ("monday_hours", "Monday Hours"),
            ("tuesday_hours", "Tuesday Hours"),
            ("wednesday_hours", "Wednesday Hours"),
            ("thursday_hours", "Thursday Hours"),
            ("friday_hours", "Friday Hours"),
            ("saturday_hours", "Saturday Hours"),
            ("sunday_hours", "Sunday Hours"),
        ]
    }
    assert tool.parameters == {
        "properties": {
            "user_ref": {"title": "User Ref", "type": "string"},
            "working_hours_id": {"title": "Working Hours Id", "type": "integer"},
            "valid_from": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Valid From",
            },
            **day_props,
            "availability_factor": {
                "anyOf": [{"type": "number"}, {"type": "null"}],
                "default": None,
                "title": "Availability Factor",
            },
            "confirm": {"default": False, "title": "Confirm", "type": "boolean"},
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
        "Prepare or delete a user's working-hours schedule entry; only deletes\n"
        "when called again with confirm=true.\n\n"
        "Requires OpenProject 17.3+. Same authorization as list_user_working_hours.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "user_ref": {"title": "User Ref", "type": "string"},
            "working_hours_id": {"title": "Working Hours Id", "type": "integer"},
            "confirm": {"default": False, "title": "Confirm", "type": "boolean"},
        },
        "required": ["user_ref", "working_hours_id"],
        "title": "delete_user_working_hoursArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["user_ref", "working_hours_id", "confirm"]
