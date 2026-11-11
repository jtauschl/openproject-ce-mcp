"""Characterization test: freezes the 5 Grids MCP tool schemas.

Proves that where these tool functions live (tools.py vs. their own per-domain
file) has zero effect on what an MCP client actually sees -- parameter names/
order/types, descriptions, required fields, and whether the tool carries an
output_schema (no tool carries one, see test_compact_result_seam.py). A future relocation of any of these functions to
a different module must leave this file completely unmodified; a diff to it
would mean the move changed the public tool contract, not just its location.
"""

from __future__ import annotations

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


def test_list_grids_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_grids"]
    assert (
        tool.description
        == "List dashboard grids, optionally filtered by scope (page path).\n\ntotal is only the count of allowed grids returned on THIS page, not a full count of all matches; the search\nstops as soon as it has enough, so an exact total would need an extra full walk. Page until next_offset is null.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "scope": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Scope"},
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
                "description": "Fields to return; a requested unset field comes back as null. Allowed: column_count, created_at, id, row_count, scope, updated_at.",
                "title": "Select",
            },
        },
        "title": "list_gridsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["scope", "offset", "limit", "select"]


def test_get_grid_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_grid"]
    assert tool.description == "Get a single dashboard grid by id."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "grid_id": {
                "title": "Grid Id",
                "type": "integer",
            },
        },
        "required": ["grid_id"],
        "title": "get_gridArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["grid_id"]


def test_create_grid_schema() -> None:
    tool = _tools(create_app(_make_settings()))["create_grid"]
    assert (
        tool.description
        == "Create a dashboard grid on a page.\n\nA grid is the widget layout of My Page, a project overview or a board. The grid starts with OpenProject's\ndefault widgets for that page; other widgets are added in OpenProject. A board's saved work package\nqueries are created with create_board.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "name": {"description": "Display name, at most 255 characters.", "title": "Name", "type": "string"},
            "scope": {
                "description": 'Page path: "/my/page", "/projects/<identifier>" or "/projects/<identifier>/boards", after the instance\'s root path on a subpath install. Any other scope is rejected before a request.',
                "title": "Scope",
                "type": "string",
            },
            "row_count": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "description": "Positive integer; omitted lets OpenProject choose.",
                "title": "Row Count",
            },
            "column_count": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "description": "Positive integer; omitted lets OpenProject choose.",
                "title": "Column Count",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["name", "scope"],
        "title": "create_gridArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["name", "scope", "row_count", "column_count", "confirm"]


def test_update_grid_schema() -> None:
    tool = _tools(create_app(_make_settings()))["update_grid"]
    assert (
        tool.description
        == "Rename or resize a dashboard grid; omitted fields stay unchanged.\n\nThe widgets stay as they are; a size that would leave a widget outside the grid is rejected.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "grid_id": {"description": "Grid id, from list_grids.", "title": "Grid Id", "type": "integer"},
            "name": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "New display name, at most 255 characters.",
                "title": "Name",
            },
            "row_count": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "description": "New number of rows, a positive integer.",
                "title": "Row Count",
            },
            "column_count": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "description": "New number of columns, a positive integer.",
                "title": "Column Count",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["grid_id"],
        "title": "update_gridArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["grid_id", "name", "row_count", "column_count", "confirm"]


def test_delete_grid_schema() -> None:
    tool = _tools(create_app(_make_settings()))["delete_grid"]
    assert (
        tool.description
        == "Delete a board grid; My Page and project overview grids cannot be deleted.\n\n17.0+: its column queries are deleted too, as far as you may delete them. This cannot be undone.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "grid_id": {"title": "Grid Id", "type": "integer"},
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["grid_id"],
        "title": "delete_gridArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["grid_id", "confirm"]
