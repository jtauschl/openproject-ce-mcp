"""Characterization test: freezes the 4 Costs MCP tool schemas.

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


def test_get_cost_entry_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_cost_entry"]
    assert (
        tool.description
        == "Get a single cost entry by id.\n\nCost entries are entirely read-only in OpenProject's API (Community\nEdition) -- there is no create/update/delete endpoint for this resource.\n"
    )
    assert tool.output_schema == {
        "properties": {
            "id": {
                "title": "Id",
                "type": "integer",
            },
            "project": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Project",
            },
            "cost_type": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Cost Type",
            },
            "user": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "User",
            },
            "entity_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Entity Id",
            },
            "entity_name": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Entity Name",
            },
            "spent_units": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Spent Units",
            },
            "spent_on": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Spent On",
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
        "required": [
            "id",
            "project",
            "cost_type",
            "user",
            "entity_id",
            "entity_name",
            "spent_units",
            "spent_on",
            "created_at",
            "updated_at",
        ],
        "title": "CostEntrySummary",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {
            "cost_entry_id": {
                "title": "Cost Entry Id",
                "type": "integer",
            },
        },
        "required": ["cost_entry_id"],
        "title": "get_cost_entryArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["cost_entry_id"]


def test_list_work_package_cost_entries_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_work_package_cost_entries"]
    assert (
        tool.description
        == 'List all cost entries recorded against a work package.\n\nwork_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.\n\nReturns every cost entry for the work package in one call -- this endpoint\nis unpaginated on OpenProject\'s side (no offset/limit parameters exist).\n'
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "work_package_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "string",
                    },
                ],
                "title": "Work Package Id",
            },
        },
        "required": ["work_package_id"],
        "title": "list_work_package_cost_entriesArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["work_package_id"]


def test_get_work_package_costs_by_type_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_work_package_costs_by_type"]
    assert (
        tool.description
        == "Get a work package's costs aggregated by cost type.\n\nwork_package_id: internal id (e.g., 952) or display_id (e.g., \"PROJ-51\"), not UI display number.\n\ncount is the number of distinct cost types with recorded spend on this\nwork package, not a monetary total. Each result's spent_units is a\nquantity in that cost type's own unit (see get_cost_type for the unit\nname) -- there is no currency conversion or grand total computed here or\nby OpenProject's own API.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "work_package_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "string",
                    },
                ],
                "title": "Work Package Id",
            },
        },
        "required": ["work_package_id"],
        "title": "get_work_package_costs_by_typeArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["work_package_id"]


def test_get_cost_type_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_cost_type"]
    assert (
        tool.description
        == "Get a cost type by id.\n\nCost types are entirely read-only in OpenProject's API (Community\nEdition) -- there is no create/update/delete endpoint, and no collection\nGET either (no list_cost_types tool exists because the endpoint does not\nexist upstream).\n"
    )
    assert tool.output_schema == {
        "properties": {
            "id": {
                "title": "Id",
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
                "title": "Name",
            },
            "unit": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Unit",
            },
            "unit_plural": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Unit Plural",
            },
            "is_default": {
                "title": "Is Default",
                "type": "boolean",
            },
        },
        "required": ["id", "name", "unit", "unit_plural", "is_default"],
        "title": "CostTypeSummary",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {
            "cost_type_id": {
                "title": "Cost Type Id",
                "type": "integer",
            },
        },
        "required": ["cost_type_id"],
        "title": "get_cost_typeArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["cost_type_id"]
