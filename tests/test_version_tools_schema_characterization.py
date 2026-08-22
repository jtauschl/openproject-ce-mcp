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
        "case-insensitive name substring.\n\n"
        "select fields: id, name (see server instructions for select's general semantics).\n\n"
        "limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned\n"
        "next_offset as the next call's offset to page past the cap. Without project,\n"
        "total is only the count of allowed versions returned on THIS page, not a\n"
        "full count of all matches — the search stops as soon as it has enough, so\n"
        "an exact total would need an extra full walk. Page until next_offset is\n"
        "null.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Project",
            },
            "search": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Search",
            },
            "offset": {"default": 1, "title": "Offset", "type": "integer"},
            "limit": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "title": "Limit",
            },
            "select": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
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
    assert tool.output_schema is not None
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
        "Prepare or create a version for a project.\n\n"
        "A rejected validation preview is not a tool error; inspect `ready` and\n"
        "`validation_errors` in the result rather than the MCP error envelope.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {"title": "Project", "type": "string"},
            "name": {"title": "Name", "type": "string"},
            "description": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Description",
            },
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
            "status": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Status",
            },
            "sharing": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Sharing",
            },
            "confirm": {"default": False, "title": "Confirm", "type": "boolean"},
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
        "Prepare or update a version.\n\n"
        "A rejected validation preview is not a tool error; inspect `ready` and\n"
        "`validation_errors` in the result rather than the MCP error envelope.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "version_id": {"title": "Version Id", "type": "integer"},
            "name": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Name",
            },
            "description": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Description",
            },
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
            "status": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Status",
            },
            "sharing": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Sharing",
            },
            "confirm": {"default": False, "title": "Confirm", "type": "boolean"},
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
        "start_date",
        "end_date",
        "status",
        "sharing",
        "confirm",
    ]


def test_delete_version_schema() -> None:
    tool = _tools(create_app(_make_settings()))["delete_version"]
    assert tool.description == "Prepare or delete a version."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "version_id": {"title": "Version Id", "type": "integer"},
            "confirm": {"default": False, "title": "Confirm", "type": "boolean"},
        },
        "required": ["version_id"],
        "title": "delete_versionArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["version_id", "confirm"]
