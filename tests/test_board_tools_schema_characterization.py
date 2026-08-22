"""Characterization test: freezes the 5 Boards MCP tool schemas.

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


def test_list_boards_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_boards"]
    assert tool.description == (
        "List saved OpenProject boards/queries, optionally scoped to a project.\n\n"
        "select fields: id, name (see server instructions for select's general semantics).\n\n"
        "limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned\n"
        "next_offset as the next call's offset to page past the cap. With project,\n"
        "search, or a restrictive OPENPROJECT_READ_PROJECTS, total is only the\n"
        "count of allowed boards returned on THIS page, not a full count of all\n"
        "matches — the search stops as soon as it has enough, so an exact total\n"
        "would need an extra full walk. Page until next_offset is null.\n"
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
        "title": "list_boardsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["project", "search", "offset", "limit", "select"]


def test_get_board_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_board"]
    assert tool.description == "Get a saved OpenProject board/query by id."
    assert tool.output_schema == {
        "$defs": {
            "BoardFilter": {
                "properties": {
                    "key": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Key"},
                    "name": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Name"},
                    "operator": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Operator"},
                    "values": {"items": {"type": "string"}, "title": "Values", "type": "array"},
                },
                "required": ["key", "name", "operator", "values"],
                "title": "BoardFilter",
                "type": "object",
            }
        },
        "properties": {
            "id": {"title": "Id", "type": "integer"},
            "name": {"title": "Name", "type": "string"},
            "project_id": {"anyOf": [{"type": "integer"}, {"type": "null"}], "title": "Project Id"},
            "project": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Project"},
            "public": {"title": "Public", "type": "boolean"},
            "hidden": {"title": "Hidden", "type": "boolean"},
            "starred": {"title": "Starred", "type": "boolean"},
            "include_subprojects": {"title": "Include Subprojects", "type": "boolean"},
            "show_hierarchies": {"title": "Show Hierarchies", "type": "boolean"},
            "timeline_visible": {"title": "Timeline Visible", "type": "boolean"},
            "timeline_zoom_level": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Timeline Zoom Level"},
            "highlighting_mode": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Highlighting Mode"},
            "group_by": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Group By"},
            "columns": {"items": {"type": "string"}, "title": "Columns", "type": "array"},
            "sort_by": {"items": {"type": "string"}, "title": "Sort By", "type": "array"},
            "highlighted_attributes": {"items": {"type": "string"}, "title": "Highlighted Attributes", "type": "array"},
            "timestamps": {"items": {"type": "string"}, "title": "Timestamps", "type": "array"},
            "filters": {"items": {"$ref": "#/$defs/BoardFilter"}, "title": "Filters", "type": "array"},
            "created_at": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Created At"},
            "updated_at": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Updated At"},
            "can_update": {"title": "Can Update", "type": "boolean"},
            "can_delete": {"title": "Can Delete", "type": "boolean"},
        },
        "required": [
            "id",
            "name",
            "project_id",
            "project",
            "public",
            "hidden",
            "starred",
            "include_subprojects",
            "show_hierarchies",
            "timeline_visible",
            "timeline_zoom_level",
            "highlighting_mode",
            "group_by",
            "columns",
            "sort_by",
            "highlighted_attributes",
            "timestamps",
            "filters",
            "created_at",
            "updated_at",
            "can_update",
            "can_delete",
        ],
        "title": "BoardDetail",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {"board_id": {"title": "Board Id", "type": "integer"}},
        "required": ["board_id"],
        "title": "get_boardArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["board_id"]


def test_create_board_schema() -> None:
    tool = _tools(create_app(_make_settings()))["create_board"]
    assert tool.description == "Prepare or create a saved OpenProject board/query."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "name": {"title": "Name", "type": "string"},
            "project": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Project",
            },
            "public": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "default": None,
                "title": "Public",
            },
            "starred": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "default": None,
                "title": "Starred",
            },
            "hidden": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "default": None,
                "title": "Hidden",
            },
            "include_subprojects": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "default": None,
                "title": "Include Subprojects",
            },
            "show_hierarchies": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "default": None,
                "title": "Show Hierarchies",
            },
            "timeline_visible": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "default": None,
                "title": "Timeline Visible",
            },
            "group_by": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Group By",
            },
            "columns": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "title": "Columns",
            },
            "sort_by": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "title": "Sort By",
            },
            "highlighted_attributes": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "title": "Highlighted Attributes",
            },
            "filters": {
                "anyOf": [
                    {"items": {"additionalProperties": True, "type": "object"}, "type": "array"},
                    {"type": "null"},
                ],
                "default": None,
                "title": "Filters",
            },
            "confirm": {"default": False, "title": "Confirm", "type": "boolean"},
        },
        "required": ["name"],
        "title": "create_boardArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "name",
        "project",
        "public",
        "starred",
        "hidden",
        "include_subprojects",
        "show_hierarchies",
        "timeline_visible",
        "group_by",
        "columns",
        "sort_by",
        "highlighted_attributes",
        "filters",
        "confirm",
    ]


def test_update_board_schema() -> None:
    tool = _tools(create_app(_make_settings()))["update_board"]
    assert tool.description == "Prepare or update a saved OpenProject board/query."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "board_id": {"title": "Board Id", "type": "integer"},
            "name": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Name",
            },
            "project": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Project",
            },
            "public": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "default": None,
                "title": "Public",
            },
            "starred": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "default": None,
                "title": "Starred",
            },
            "hidden": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "default": None,
                "title": "Hidden",
            },
            "include_subprojects": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "default": None,
                "title": "Include Subprojects",
            },
            "show_hierarchies": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "default": None,
                "title": "Show Hierarchies",
            },
            "timeline_visible": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "default": None,
                "title": "Timeline Visible",
            },
            "group_by": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Group By",
            },
            "columns": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "title": "Columns",
            },
            "sort_by": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "title": "Sort By",
            },
            "highlighted_attributes": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "title": "Highlighted Attributes",
            },
            "filters": {
                "anyOf": [
                    {"items": {"additionalProperties": True, "type": "object"}, "type": "array"},
                    {"type": "null"},
                ],
                "default": None,
                "title": "Filters",
            },
            "confirm": {"default": False, "title": "Confirm", "type": "boolean"},
        },
        "required": ["board_id"],
        "title": "update_boardArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "board_id",
        "name",
        "project",
        "public",
        "starred",
        "hidden",
        "include_subprojects",
        "show_hierarchies",
        "timeline_visible",
        "group_by",
        "columns",
        "sort_by",
        "highlighted_attributes",
        "filters",
        "confirm",
    ]


def test_delete_board_schema() -> None:
    tool = _tools(create_app(_make_settings()))["delete_board"]
    assert tool.description == "Prepare or delete a saved OpenProject board/query."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "board_id": {"title": "Board Id", "type": "integer"},
            "confirm": {"default": False, "title": "Confirm", "type": "boolean"},
        },
        "required": ["board_id"],
        "title": "delete_boardArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["board_id", "confirm"]
