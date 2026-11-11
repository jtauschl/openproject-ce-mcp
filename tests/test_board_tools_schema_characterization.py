"""Characterization test: freezes the 5 Boards MCP tool schemas.

Proves that where these tool functions live (tools.py vs. their own per-domain
file) has zero effect on what an MCP client actually sees -- parameter names/
order/types, descriptions, required fields, and whether the tool carries an
output_schema. A future relocation of any of these functions to a different
module must leave this file completely unmodified; a diff to it would mean the
move changed the public tool contract, not just its location.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from openproject_ce_mcp.config import Settings
from openproject_ce_mcp.server import create_app


def _make_settings(**overrides) -> Settings:
    defaults = {
        "base_url": "https://op.example.com",
        "api_token": SecretStr("token"),
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
        "List saved OpenProject boards/queries, optionally scoped to a project.\n"
        "\n"
        "With project, search, or a restrictive OPENPROJECT_READ_PROJECTS, total is only the count of allowed boards\n"
        "returned on THIS page, not a full count of all matches; the search stops as soon as it has enough, so an exact\n"
        "total would need an extra full walk. Page until next_offset is null."
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
                "description": "Fields to return; a requested unset field comes back as null. Allowed: can_delete, can_update, filter_count, hidden, id, include_subprojects, name, project, project_id, public, show_hierarchies, starred, timeline_visible.",
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
    assert tool.output_schema is None
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
    assert tool.description == (
        "Create a saved OpenProject board/query.\n\nThis saves a work package query (filters, columns, sorting, grouping); a board grid that shows queries as\ncolumns is created with create_grid.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "name": {"description": "Board name, at most 255 characters.", "title": "Name", "type": "string"},
            "project": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Project identifier, id, or name; a unique part of a name or identifier also matches.",
                "title": "Project",
            },
            "public": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "default": None,
                "description": "Visible to other users; false keeps it to its creator.",
                "title": "Public",
            },
            "starred": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "default": None,
                "description": "Mark as a favorite query.",
                "title": "Starred",
            },
            "include_subprojects": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "default": None,
                "description": "Also show work packages of subprojects.",
                "title": "Include Subprojects",
            },
            "show_hierarchies": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "default": None,
                "description": "Show parent/child tree; cannot combine with group_by, so it defaults to false there.",
                "title": "Show Hierarchies",
            },
            "timeline_visible": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "default": None,
                "description": "Show the Gantt timeline.",
                "title": "Timeline Visible",
            },
            "group_by": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": 'Group-by attribute id (e.g. "status") or its /api/v3/queries/group_bys/ href.',
                "title": "Group By",
            },
            "columns": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "description": 'Column attribute ids (e.g. "id", "subject") or /api/v3/queries/columns/ hrefs.',
                "title": "Columns",
            },
            "sort_by": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "description": 'Sort criteria, each "field:direction" or "field-direction" (e.g. "id:asc"), a bare field (ascending), or a /api/v3/queries/sort_bys/ href; the direction is case-insensitive.',
                "title": "Sort By",
            },
            "highlighted_attributes": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "description": "Column ids or hrefs whose values are highlighted.",
                "title": "Highlighted Attributes",
            },
            "filters": {
                "anyOf": [
                    {"items": {"additionalProperties": True, "type": "object"}, "type": "array"},
                    {"type": "null"},
                ],
                "default": None,
                "description": 'OpenProject query filter objects, sent unchanged, e.g. {"_links": {"filter": {"href": "/api/v3/queries/filters/status"}, "operator": {"href": "/api/v3/queries/operators/o"}, "values": []}}.',
                "title": "Filters",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
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
    assert tool.description == (
        "Update a saved OpenProject board/query.\n\nOmitted fields stay unchanged; a given list replaces the stored one."
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "board_id": {
                "description": "Board (saved query) id, from list_boards.",
                "title": "Board Id",
                "type": "integer",
            },
            "name": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Board name, at most 255 characters.",
                "title": "Name",
            },
            "project": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Project identifier, id, or name; a unique part of a name or identifier also matches.",
                "title": "Project",
            },
            "public": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "default": None,
                "description": "Visible to other users; false keeps it to its creator.",
                "title": "Public",
            },
            "starred": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "default": None,
                "description": "Mark as a favorite query.",
                "title": "Starred",
            },
            "include_subprojects": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "default": None,
                "description": "Also show work packages of subprojects.",
                "title": "Include Subprojects",
            },
            "show_hierarchies": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "default": None,
                "description": "Show parent/child tree; cannot combine with group_by, so it defaults to false there.",
                "title": "Show Hierarchies",
            },
            "timeline_visible": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "default": None,
                "description": "Show the Gantt timeline.",
                "title": "Timeline Visible",
            },
            "group_by": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": 'Group-by attribute id (e.g. "status") or its /api/v3/queries/group_bys/ href.',
                "title": "Group By",
            },
            "columns": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "description": 'Column attribute ids (e.g. "id", "subject") or /api/v3/queries/columns/ hrefs.',
                "title": "Columns",
            },
            "sort_by": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "description": 'Sort criteria, each "field:direction" or "field-direction" (e.g. "id:asc"), a bare field (ascending), or a /api/v3/queries/sort_bys/ href; the direction is case-insensitive.',
                "title": "Sort By",
            },
            "highlighted_attributes": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "description": "Column ids or hrefs whose values are highlighted.",
                "title": "Highlighted Attributes",
            },
            "filters": {
                "anyOf": [
                    {"items": {"additionalProperties": True, "type": "object"}, "type": "array"},
                    {"type": "null"},
                ],
                "default": None,
                "description": 'OpenProject query filter objects, sent unchanged, e.g. {"_links": {"filter": {"href": "/api/v3/queries/filters/status"}, "operator": {"href": "/api/v3/queries/operators/o"}, "values": []}}.',
                "title": "Filters",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
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


@pytest.mark.parametrize("tool_name", ["create_board", "update_board"])
def test_the_board_write_tools_do_not_accept_the_parameter_openproject_ignores(tool_name: str) -> None:
    tool = _tools(create_app(_make_settings()))[tool_name]

    assert "hidden" not in tool.parameters["properties"]
    assert tool.parameters["additionalProperties"] is False


def test_delete_board_schema() -> None:
    tool = _tools(create_app(_make_settings()))["delete_board"]
    assert (
        tool.description
        == "Delete one saved work package query; this cannot be undone.\n\nA board grid that shows it as a column keeps a column pointing to the deleted query; board grids\nthemselves are deleted with delete_grid.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "board_id": {
                "description": "Board (saved query) id, from list_boards.",
                "title": "Board Id",
                "type": "integer",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["board_id"],
        "title": "delete_boardArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["board_id", "confirm"]
