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
        "List in-app notifications for the current user.\n\nReading them does not mark them read; use mark_notifications_read for that.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "unread_only": {
                "default": False,
                "description": "true returns only notifications not yet read.",
                "title": "Unread Only",
                "type": "boolean",
            },
            "limit": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "description": "Page size, capped at OPENPROJECT_MAX_PAGE_SIZE.",
                "title": "Limit",
            },
            "offset": {
                "default": 1,
                "description": "1-based page number; pass the previous result's next_offset.",
                "title": "Offset",
                "type": "integer",
            },
            "select": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "description": "Fields to return; a requested unset field comes back as null. Allowed: created_at, id, project_id, project_name, read, reason, subject, work_package_id, work_package_subject.",
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
        "Mark a single notification, or all unread notifications, as read.\n"
        "\n"
        "notification_id: mark just this notification read. Omit it (default) to\n"
        "mark every currently unread notification read instead.\n"
        "Under a restricted OPENPROJECT_READ_PROJECTS, a notification about a\n"
        "project outside it is refused (in the preview too), and omitting\n"
        "notification_id marks only notifications about the projects it covers.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "notification_id": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "title": "Notification Id",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
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
    assert tool.output_schema is None
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
        "Update the current user's preferences; omitted fields stay unchanged.\n"
        "\n"
        "Note: language is a User attribute, not a preference -- use update_user's\n"
        '"language" field to change it.\n'
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "time_zone": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": 'Time zone name, e.g. "Europe/Berlin".',
                "title": "Time Zone",
            },
            "comment_sort_descending": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "default": None,
                "description": "true shows comments newest first.",
                "title": "Comment Sort Descending",
            },
            "warn_on_leaving_unsaved": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "default": None,
                "description": "true warns before leaving a page with unsaved changes.",
                "title": "Warn On Leaving Unsaved",
            },
            "auto_hide_popups": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "default": None,
                "description": "true makes popups close automatically.",
                "title": "Auto Hide Popups",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
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


def test_mark_notifications_unread_schema() -> None:
    tool = _tools(create_app(_make_settings()))["mark_notifications_unread"]
    assert tool.description == (
        "Mark a single notification, or all read notifications, as unread.\n"
        "\n"
        "notification_id: mark just this notification unread. Omit it (default) to\n"
        "mark every currently read notification unread instead.\n"
        "Under a restricted OPENPROJECT_READ_PROJECTS, a notification about a\n"
        "project outside it is refused (in the preview too), and omitting\n"
        "notification_id marks only notifications about the projects it covers.\n"
    )
    assert tool.output_schema is None
    assert list(tool.parameters["properties"]) == ["notification_id", "confirm"]
    assert tool.parameters["properties"]["confirm"]["default"] is False
    assert tool.parameters["additionalProperties"] is False


def test_get_notification_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_notification"]
    assert tool.description == (
        "Get one in-app notification with its details: the dates of a date alert, the note of a reminder, and the\n"
        "activity it points at.\n"
        "\n"
        "Under a restricted OPENPROJECT_READ_PROJECTS, a notification about a project outside it, or one that names no\n"
        "project at all, is refused. A reminder note is user text and is delimited as untrusted content."
    )
    assert tool.output_schema is None
    assert list(tool.parameters["properties"]) == ["notification_id"]
    assert tool.parameters["required"] == ["notification_id"]
    assert tool.parameters["additionalProperties"] is False
