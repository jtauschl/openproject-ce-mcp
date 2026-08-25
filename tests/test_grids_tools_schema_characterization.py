"""Characterization test: freezes the 5 Grids MCP tool schemas.

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
        == "List dashboard grids, optionally filtered by scope (page path).\n\nselect fields: id, scope (see server instructions for select's general\nsemantics). limit is capped at\nOPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned next_offset as\nthe next call's offset to page past the cap. total is only the count of\nallowed grids returned on THIS page, not a full count of all matches —\nthe search stops as soon as it has enough, so an exact total would need\nan extra full walk. Page until next_offset is null.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "scope": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Scope",
            },
            "offset": {
                "default": 1,
                "title": "Offset",
                "type": "integer",
            },
            "limit": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Limit",
            },
            "select": {
                "anyOf": [
                    {
                        "items": {
                            "type": "string",
                        },
                        "type": "array",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
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
    assert tool.output_schema == {
        "properties": {
            "id": {
                "title": "Id",
                "type": "integer",
            },
            "row_count": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Row Count",
            },
            "column_count": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Column Count",
            },
            "scope": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Scope",
            },
            "created_at": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Created At",
            },
            "updated_at": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Updated At",
            },
        },
        "required": ["id", "row_count", "column_count", "scope", "created_at", "updated_at"],
        "title": "GridSummary",
        "type": "object",
    }
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
        == "Prepare or create a dashboard grid for a scope such as `/my/page` or `/projects/<identifier>`."
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "name": {
                "title": "Name",
                "type": "string",
            },
            "scope": {
                "title": "Scope",
                "type": "string",
            },
            "row_count": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Row Count",
            },
            "column_count": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Column Count",
            },
            "confirm": {
                "default": False,
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
        == "Prepare or update a dashboard grid.\n\nOmitted fields stay unchanged. Set confirm=true to write.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "grid_id": {
                "title": "Grid Id",
                "type": "integer",
            },
            "name": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Name",
            },
            "row_count": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Row Count",
            },
            "column_count": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Column Count",
            },
            "confirm": {
                "default": False,
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
    assert tool.description == "Prepare or delete a dashboard grid. Only deletes when called again with confirm=true."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "grid_id": {
                "title": "Grid Id",
                "type": "integer",
            },
            "confirm": {
                "default": False,
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
