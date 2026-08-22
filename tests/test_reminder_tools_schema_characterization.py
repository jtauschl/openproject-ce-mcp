"""Characterization test: freezes the 4 Reminders MCP tool schemas.

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
        "read_projects": ("*",),
        "write_projects": ("*",),
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _tools(mcp) -> dict:
    return {t.name: t for t in mcp._tool_manager.list_tools()}


def test_list_reminders_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_reminders"]
    assert tool.description == (
        "List the current user's active reminders across all work packages.\n\n"
        "select fields: id, remind_at (see server instructions for select's general semantics).\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "select": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "title": "Select",
            }
        },
        "title": "list_remindersArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["select"]


def test_create_work_package_reminder_schema() -> None:
    tool = _tools(create_app(_make_settings()))["create_work_package_reminder"]
    assert tool.description == (
        "Prepare or create a reminder on a work package.\n\n"
        "`remind_at` is an ISO 8601 date-time (e.g. 2026-12-01T09:00:00Z). Only one\n"
        "active reminder per work package is allowed; creating a second one fails.\n"
        'work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.\n'
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "work_package_id": {
                "anyOf": [{"type": "integer"}, {"type": "string"}],
                "title": "Work Package Id",
            },
            "remind_at": {"title": "Remind At", "type": "string"},
            "note": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Note",
            },
            "confirm": {"default": False, "title": "Confirm", "type": "boolean"},
        },
        "required": ["work_package_id", "remind_at"],
        "title": "create_work_package_reminderArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["work_package_id", "remind_at", "note", "confirm"]


def test_update_reminder_schema() -> None:
    tool = _tools(create_app(_make_settings()))["update_reminder"]
    assert tool.description == "Prepare or update a reminder's time or note. At least one field is required."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "reminder_id": {"title": "Reminder Id", "type": "integer"},
            "remind_at": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Remind At",
            },
            "note": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Note",
            },
            "confirm": {"default": False, "title": "Confirm", "type": "boolean"},
        },
        "required": ["reminder_id"],
        "title": "update_reminderArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["reminder_id", "remind_at", "note", "confirm"]


def test_delete_reminder_schema() -> None:
    tool = _tools(create_app(_make_settings()))["delete_reminder"]
    assert tool.description == "Prepare or delete a reminder; only deletes when called again with confirm=true."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "reminder_id": {"title": "Reminder Id", "type": "integer"},
            "confirm": {"default": False, "title": "Confirm", "type": "boolean"},
        },
        "required": ["reminder_id"],
        "title": "delete_reminderArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["reminder_id", "confirm"]
