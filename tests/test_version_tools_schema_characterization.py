"""Characterization test: freezes the 5 Versions MCP tool schemas.

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
        "enable_version_write": True,
        "read_projects": ("*",),
        "write_projects": ("*",),
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _tools(mcp) -> dict:
    return {t.name: t for t in mcp._tool_manager.list_tools()}


def test_list_versions_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_versions"]
    assert tool.description == (
        "List versions globally or for a specific project, optionally filtered by a\n"
        "case-insensitive name substring.\n"
        "\n"
        "Without project, total is only the count of allowed versions returned on THIS page, not a full count of all\n"
        "matches; the search stops as soon as it has enough, so an exact total would need an extra full walk. Page until\n"
        "next_offset is null."
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
            "search": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Search"},
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
                "description": "Fields to return; a requested unset field comes back as null. Allowed: created_at, defining_project, description, description_length, description_truncated, end_date, id, name, sharing, start_date, status, updated_at.",
                "title": "Select",
            },
        },
        "title": "list_versionsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["project", "search", "offset", "limit", "select"]


def test_get_version_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_version"]
    assert tool.description == (
        "Get a version by id, including its full description.\n\n"
        "The description is returned in full by default (single versions are not\n"
        "truncated). Pass ``text_limit`` to cap it at that many characters; when the\n"
        "text is cut, ``description_truncated`` is true and ``description_length``\n"
        "reports the real length.\n"
    )
    # get_version is not trimmed (single-item read), unlike the list/write tools --
    # it carries a real output_schema; this test only proves the move leaves its
    # presence unchanged, not its full nested shape.
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "version_id": {"title": "Version Id", "type": "integer"},
            "text_limit": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "title": "Text Limit",
            },
        },
        "required": ["version_id"],
        "title": "get_versionArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["version_id", "text_limit"]


def test_create_version_schema() -> None:
    tool = _tools(create_app(_make_settings()))["create_version"]
    assert tool.description == (
        "Create a version for a project.\n"
        "\n"
        "A rejected validation preview is not a tool error; inspect `ready` and\n"
        "`validation_errors` in the result rather than the MCP error envelope. Each entry has a `message`\nand `error_codes` (OpenProject's error classes, the same in every language).\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {
                "anyOf": [{"type": "integer"}, {"type": "string"}],
                "description": "Project identifier, id, or name; a unique part of a name or identifier also matches.",
                "title": "Project",
            },
            "name": {"description": "Display name, at most 60 characters.", "title": "Name", "type": "string"},
            "description": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Plain text, not Markdown.",
                "title": "Description",
            },
            "start_date": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "ISO 8601 date (YYYY-MM-DD).",
                "title": "Start Date",
            },
            "end_date": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "ISO 8601 date (YYYY-MM-DD).",
                "title": "End Date",
            },
            "status": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": 'One of "open", "locked", "closed".',
                "title": "Status",
            },
            "sharing": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": 'One of "none", "descendants", "hierarchy", "tree".',
                "title": "Sharing",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["project", "name"],
        "title": "create_versionArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "project",
        "name",
        "description",
        "start_date",
        "end_date",
        "status",
        "sharing",
        "confirm",
    ]


def test_update_version_schema() -> None:
    tool = _tools(create_app(_make_settings()))["update_version"]
    assert tool.description == (
        "Update a version.\n"
        "\n"
        "Omitted fields stay unchanged.\n"
        "Prefer description_append and description_replace to a full description: they edit the stored text, while a\n"
        "read cuts it and flattens its line breaks. Pass only one of the three.\n"
        "A rejected validation preview is not a tool error; inspect `ready` and\n"
        "`validation_errors` in the result rather than the MCP error envelope. Each entry has a `message`\n"
        "and `error_codes` (OpenProject's error classes, the same in every language).\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "$defs": {
            "TextReplace": {
                "additionalProperties": False,
                "properties": {"old": {"title": "Old", "type": "string"}, "new": {"title": "New", "type": "string"}},
                "required": ["old", "new"],
                "title": "TextReplace",
                "type": "object",
            }
        },
        "properties": {
            "version_id": {
                "description": "Numeric version id, as returned by list_versions.",
                "title": "Version Id",
                "type": "integer",
            },
            "name": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Display name, at most 60 characters.",
                "title": "Name",
            },
            "description": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": 'Plain text, not Markdown; "" clears it.',
                "title": "Description",
            },
            "description_append": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Paragraph added after the stored text.",
                "title": "Description Append",
            },
            "description_replace": {
                "anyOf": [{"$ref": "#/$defs/TextReplace"}, {"type": "null"}],
                "default": None,
                "description": "Replaces the one passage old names with new (may be empty).",
            },
            "start_date": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "ISO 8601 date (YYYY-MM-DD).",
                "title": "Start Date",
            },
            "end_date": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "ISO 8601 date (YYYY-MM-DD).",
                "title": "End Date",
            },
            "status": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": 'One of "open", "locked", "closed".',
                "title": "Status",
            },
            "sharing": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": 'One of "none", "descendants", "hierarchy", "tree".',
                "title": "Sharing",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["version_id"],
        "title": "update_versionArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "version_id",
        "name",
        "description",
        "description_append",
        "description_replace",
        "start_date",
        "end_date",
        "status",
        "sharing",
        "confirm",
    ]


def test_delete_version_schema() -> None:
    tool = _tools(create_app(_make_settings()))["delete_version"]
    assert (
        tool.description
        == 'Delete a version; this cannot be undone.\n\nRejected while any work package, in any project, uses it (17.8+: also as its "found in" version).\n'
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "version_id": {
                "description": "Numeric version id, as returned by list_versions.",
                "title": "Version Id",
                "type": "integer",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["version_id"],
        "title": "delete_versionArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["version_id", "confirm"]
