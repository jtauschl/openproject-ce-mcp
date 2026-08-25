"""Characterization test: freezes the 6 Reference Data MCP tool schemas.

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


def test_list_statuses_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_statuses"]
    assert (
        tool.description
        == "List all available work package statuses.\n\nRead-only: statuses cannot be created or modified via the OpenProject API\n(Community Edition); configure them in the web admin UI.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {},
        "title": "list_statusesArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == []


def test_get_status_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_status"]
    assert tool.description == "Get a single work package status by id."
    assert tool.output_schema == {
        "properties": {
            "id": {
                "title": "Id",
                "type": "integer",
            },
            "name": {
                "title": "Name",
                "type": "string",
            },
            "is_default": {
                "title": "Is Default",
                "type": "boolean",
            },
            "is_closed": {
                "title": "Is Closed",
                "type": "boolean",
            },
            "color": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Color",
            },
            "position": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Position",
            },
            "is_readonly": {
                "anyOf": [
                    {
                        "type": "boolean",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Is Readonly",
            },
            "default_done_ratio": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Default Done Ratio",
            },
            "excluded_from_totals": {
                "anyOf": [
                    {
                        "type": "boolean",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Excluded From Totals",
            },
        },
        "required": ["id", "name", "is_default", "is_closed", "color", "position"],
        "title": "StatusSummary",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {
            "status_id": {
                "title": "Status Id",
                "type": "integer",
            },
        },
        "required": ["status_id"],
        "title": "get_statusArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["status_id"]


def test_list_priorities_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_priorities"]
    assert tool.description == "List all available work package priorities."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {},
        "title": "list_prioritiesArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == []


def test_get_priority_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_priority"]
    assert tool.description == "Get a single work package priority by id."
    assert tool.output_schema == {
        "properties": {
            "id": {
                "title": "Id",
                "type": "integer",
            },
            "name": {
                "title": "Name",
                "type": "string",
            },
            "is_default": {
                "title": "Is Default",
                "type": "boolean",
            },
            "is_active": {
                "title": "Is Active",
                "type": "boolean",
            },
            "color": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Color",
            },
            "position": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Position",
            },
        },
        "required": ["id", "name", "is_default", "is_active", "color", "position"],
        "title": "PrioritySummary",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {
            "priority_id": {
                "title": "Priority Id",
                "type": "integer",
            },
        },
        "required": ["priority_id"],
        "title": "get_priorityArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["priority_id"]


def test_list_types_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_types"]
    assert (
        tool.description
        == "List all available work package types, optionally filtered by project.\n\nRead-only: types cannot be created or modified via the OpenProject API\n(Community Edition); configure them in the web admin UI.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Project",
            },
        },
        "title": "list_typesArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["project"]


def test_get_type_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_type"]
    assert tool.description == "Get a single work package type by id."
    assert tool.output_schema == {
        "properties": {
            "id": {
                "title": "Id",
                "type": "integer",
            },
            "name": {
                "title": "Name",
                "type": "string",
            },
            "color": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Color",
            },
            "position": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Position",
            },
            "is_default": {
                "title": "Is Default",
                "type": "boolean",
            },
            "is_milestone": {
                "title": "Is Milestone",
                "type": "boolean",
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
                "default": None,
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
                "default": None,
                "title": "Updated At",
            },
        },
        "required": ["id", "name", "color", "position", "is_default", "is_milestone"],
        "title": "TypeSummary",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {
            "type_id": {
                "title": "Type Id",
                "type": "integer",
            },
        },
        "required": ["type_id"],
        "title": "get_typeArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["type_id"]
