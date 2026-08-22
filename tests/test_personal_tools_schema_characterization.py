"""Characterization test: freezes the 4 Personal MCP tool schemas
(list_notifications, mark_notifications_read, get_my_preferences,
update_my_preferences).

Proves that where these tool functions live (tools.py vs. their own per-domain
file) has zero effect on what an MCP client actually sees -- parameter names/
order/types, descriptions, required fields, and whether the tool carries an
output_schema. A future relocation of any of these functions to a different
module must leave this file completely unmodified; a diff to it would mean
the move changed the public tool contract, not just its location.
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
        "enable_metadata_tools": True,
        "read_projects": ("*",),
        "write_projects": ("*",),
        "enable_personal_read": True,
        "enable_personal_write": True,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _tools(mcp) -> dict:
    return {t.name: t for t in mcp._tool_manager.list_tools()}


def test_list_notifications_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_notifications"]
    assert tool.description == (
        "List in-app notifications for the current user.\n\n"
        "select fields: id, subject, reason, read, work_package_id (see server\n"
        "instructions for select's general semantics).\n\n"
        "limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned\n"
        "next_offset as the next call's offset to page past the cap.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "unread_only": {"default": False, "title": "Unread Only", "type": "boolean"},
            "limit": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "title": "Limit",
            },
            "offset": {"default": 1, "title": "Offset", "type": "integer"},
            "select": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "title": "Select",
            },
        },
        "title": "list_notificationsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["unread_only", "limit", "offset", "select"]


def test_mark_notifications_read_schema() -> None:
    tool = _tools(create_app(_make_settings()))["mark_notifications_read"]
    assert tool.description == (
        "Mark a single notification, or all unread notifications, as read.\n\n"
        "notification_id: mark just this notification read. Omit it (default) to\n"
        "mark every currently unread notification read instead.\n"
        "Set confirm=true to write, or call without confirm=true first for a preview.\n"
    )
    assert tool.output_schema == {
        "properties": {
            "action": {"title": "Action", "type": "string"},
            "state": {
                "enum": ["rejected", "invalid", "preview", "confirmed"],
                "title": "State",
                "type": "string",
            },
            "ready": {"title": "Ready", "type": "boolean"},
            "message": {"title": "Message", "type": "string"},
            "notification_id": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "title": "Notification Id",
            },
        },
        "required": ["action", "state", "ready", "message", "notification_id"],
        "title": "NotificationMarkResult",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {
            "notification_id": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "title": "Notification Id",
            },
            "confirm": {"default": False, "title": "Confirm", "type": "boolean"},
        },
        "title": "mark_notifications_readArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["notification_id", "confirm"]


def test_get_my_preferences_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_my_preferences"]
    assert tool.description == (
        "Return the current user's OpenProject preferences (timezone, sorting, popups, …).\n\n"
        "Note: language is a User attribute, not a preference -- use update_user's\n"
        '"language" field to change it.\n'
    )
    assert tool.output_schema == {
        "properties": {
            "time_zone": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "title": "Time Zone",
            },
            "comment_sort_descending": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "title": "Comment Sort Descending",
            },
            "warn_on_leaving_unsaved": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "title": "Warn On Leaving Unsaved",
            },
            "auto_hide_popups": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "title": "Auto Hide Popups",
            },
        },
        "required": [
            "time_zone",
            "comment_sort_descending",
            "warn_on_leaving_unsaved",
            "auto_hide_popups",
        ],
        "title": "UserPreferences",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {},
        "title": "get_my_preferencesArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == []


def test_update_my_preferences_schema() -> None:
    tool = _tools(create_app(_make_settings()))["update_my_preferences"]
    assert tool.description == (
        "Prepare or update the current user's preferences (timezone, comment sort order, popups, …).\n"
        "Set confirm=true to write.\n\n"
        "Note: language is a User attribute, not a preference -- use update_user's\n"
        '"language" field to change it.\n'
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "time_zone": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Time Zone",
            },
            "comment_sort_descending": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "default": None,
                "title": "Comment Sort Descending",
            },
            "warn_on_leaving_unsaved": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "default": None,
                "title": "Warn On Leaving Unsaved",
            },
            "auto_hide_popups": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "default": None,
                "title": "Auto Hide Popups",
            },
            "confirm": {"default": False, "title": "Confirm", "type": "boolean"},
        },
        "title": "update_my_preferencesArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "time_zone",
        "comment_sort_descending",
        "warn_on_leaving_unsaved",
        "auto_hide_popups",
        "confirm",
    ]
