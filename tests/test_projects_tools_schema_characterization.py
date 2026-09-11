"""Characterization test: freezes the 18 Projects MCP tool schemas.

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


def test_list_projects_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_projects"]
    assert (
        tool.description
        == "List visible projects with optional name or identifier search.\n\nselect fields: id, name, identifier, active, public, status, parent_name,\ncreated_at, updated_at (see server instructions for select's general semantics).\n\nlimit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned\nnext_offset as the next call's offset to page past the cap. Under a\nrestrictive OPENPROJECT_READ_PROJECTS, total reflects only the allowed\nprojects already scanned to fill this page, not a full count of all\nmatches — the search stops as soon as it has enough, so an exact total\nwould need an extra full walk. Page until next_offset is null.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "search": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Search",
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
        "title": "list_projectsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["search", "offset", "limit", "select"]


def test_get_project_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_project"]
    assert (
        tool.description
        == 'Get a project by id or identifier, including its ancestor chain.\n\nproject: numeric id (e.g., 7) or identifier (e.g., "my-project"), not display name.\n\ndescription/status_explanation are returned in full by default (single projects\nare not truncated). Pass ``text_limit`` to cap them at that many characters; when\ncut, ``description_truncated``/``status_explanation_truncated`` are true and\n``description_length``/``status_explanation_length`` report the real length.\n'
    )
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
            "identifier": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Identifier",
            },
            "active": {
                "anyOf": [
                    {
                        "type": "boolean",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Active",
            },
            "description": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Description",
            },
            "public": {
                "anyOf": [
                    {
                        "type": "boolean",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Public",
            },
            "status": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Status",
            },
            "status_explanation": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Status Explanation",
            },
            "parent_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Parent Id",
            },
            "parent_name": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Parent Name",
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
            "can_update": {
                "default": False,
                "title": "Can Update",
                "type": "boolean",
            },
            "can_delete": {
                "default": False,
                "title": "Can Delete",
                "type": "boolean",
            },
            "favorited": {
                "anyOf": [
                    {
                        "type": "boolean",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Favorited",
            },
            "description_truncated": {
                "default": False,
                "title": "Description Truncated",
                "type": "boolean",
            },
            "description_length": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Description Length",
            },
            "status_explanation_truncated": {
                "default": False,
                "title": "Status Explanation Truncated",
                "type": "boolean",
            },
            "status_explanation_length": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Status Explanation Length",
            },
            "ancestors": {
                "anyOf": [
                    {
                        "items": {
                            "additionalProperties": {
                                "anyOf": [
                                    {
                                        "type": "string",
                                    },
                                    {
                                        "type": "null",
                                    },
                                ],
                            },
                            "type": "object",
                        },
                        "type": "array",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Ancestors",
            },
            "ancestors_truncated": {
                "default": False,
                "title": "Ancestors Truncated",
                "type": "boolean",
            },
        },
        "required": ["id", "name", "identifier", "active", "description"],
        "title": "ProjectDetail",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {
            "project": {
                "title": "Project",
                "type": "string",
            },
            "text_limit": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Text Limit",
            },
        },
        "required": ["project"],
        "title": "get_projectArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["project", "text_limit"]


def test_get_project_admin_context_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_project_admin_context"]
    assert (
        tool.description
        == "Return project admin metadata such as lifecycle statuses, parent options, and writable fields."
    )
    assert "description" not in tool.output_schema["$defs"]["ProjectRef"]
    assert tool.output_schema == {
        "$defs": {
            "OptionValue": {
                "properties": {
                    "id": {
                        "anyOf": [
                            {
                                "type": "integer",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "title": "Id",
                    },
                    "title": {
                        "title": "Title",
                        "type": "string",
                    },
                    "href": {
                        "anyOf": [
                            {
                                "type": "string",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "title": "Href",
                    },
                },
                "required": ["id", "title", "href"],
                "title": "OptionValue",
                "type": "object",
            },
            "ProjectFieldSchema": {
                "properties": {
                    "key": {
                        "title": "Key",
                        "type": "string",
                    },
                    "name": {
                        "title": "Name",
                        "type": "string",
                    },
                    "type": {
                        "anyOf": [
                            {
                                "type": "string",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "title": "Type",
                    },
                    "required": {
                        "title": "Required",
                        "type": "boolean",
                    },
                    "writable": {
                        "title": "Writable",
                        "type": "boolean",
                    },
                    "has_default": {
                        "title": "Has Default",
                        "type": "boolean",
                    },
                    "location": {
                        "anyOf": [
                            {
                                "type": "string",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "title": "Location",
                    },
                    "allowed_values": {
                        "items": {
                            "$ref": "#/$defs/OptionValue",
                        },
                        "title": "Allowed Values",
                        "type": "array",
                    },
                },
                "required": [
                    "key",
                    "name",
                    "type",
                    "required",
                    "writable",
                    "has_default",
                    "location",
                    "allowed_values",
                ],
                "title": "ProjectFieldSchema",
                "type": "object",
            },
            "ProjectRef": {
                "properties": {
                    "id": {
                        "title": "Id",
                        "type": "integer",
                    },
                    "identifier": {
                        "anyOf": [
                            {
                                "type": "string",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "title": "Identifier",
                    },
                    "name": {
                        "title": "Name",
                        "type": "string",
                    },
                },
                "required": ["id", "identifier", "name"],
                "title": "ProjectRef",
                "type": "object",
            },
            "ProjectSummary": {
                "properties": {
                    "id": {
                        "title": "Id",
                        "type": "integer",
                    },
                    "name": {
                        "title": "Name",
                        "type": "string",
                    },
                    "identifier": {
                        "anyOf": [
                            {
                                "type": "string",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "title": "Identifier",
                    },
                    "active": {
                        "anyOf": [
                            {
                                "type": "boolean",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "title": "Active",
                    },
                    "description": {
                        "anyOf": [
                            {
                                "type": "string",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "title": "Description",
                    },
                    "public": {
                        "anyOf": [
                            {
                                "type": "boolean",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "default": None,
                        "title": "Public",
                    },
                    "status": {
                        "anyOf": [
                            {
                                "type": "string",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "default": None,
                        "title": "Status",
                    },
                    "status_explanation": {
                        "anyOf": [
                            {
                                "type": "string",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "default": None,
                        "title": "Status Explanation",
                    },
                    "parent_id": {
                        "anyOf": [
                            {
                                "type": "integer",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "default": None,
                        "title": "Parent Id",
                    },
                    "parent_name": {
                        "anyOf": [
                            {
                                "type": "string",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "default": None,
                        "title": "Parent Name",
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
                    "can_update": {
                        "default": False,
                        "title": "Can Update",
                        "type": "boolean",
                    },
                    "can_delete": {
                        "default": False,
                        "title": "Can Delete",
                        "type": "boolean",
                    },
                    "favorited": {
                        "anyOf": [
                            {
                                "type": "boolean",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "default": None,
                        "title": "Favorited",
                    },
                    "description_truncated": {
                        "default": False,
                        "title": "Description Truncated",
                        "type": "boolean",
                    },
                    "description_length": {
                        "anyOf": [
                            {
                                "type": "integer",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "default": None,
                        "title": "Description Length",
                    },
                    "status_explanation_truncated": {
                        "default": False,
                        "title": "Status Explanation Truncated",
                        "type": "boolean",
                    },
                    "status_explanation_length": {
                        "anyOf": [
                            {
                                "type": "integer",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "default": None,
                        "title": "Status Explanation Length",
                    },
                },
                "required": ["id", "name", "identifier", "active", "description"],
                "title": "ProjectSummary",
                "type": "object",
            },
        },
        "properties": {
            "project": {
                "anyOf": [
                    {
                        "$ref": "#/$defs/ProjectSummary",
                    },
                    {
                        "type": "null",
                    },
                ],
            },
            "available_statuses": {
                "items": {
                    "$ref": "#/$defs/OptionValue",
                },
                "title": "Available Statuses",
                "type": "array",
            },
            "available_parent_projects": {
                "items": {
                    "$ref": "#/$defs/ProjectRef",
                },
                "title": "Available Parent Projects",
                "type": "array",
            },
            "fields": {
                "items": {
                    "$ref": "#/$defs/ProjectFieldSchema",
                },
                "title": "Fields",
                "type": "array",
            },
        },
        "required": ["project", "available_statuses", "available_parent_projects", "fields"],
        "title": "ProjectAdminContext",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {
            "project": {
                "title": "Project",
                "type": "string",
            },
        },
        "required": ["project"],
        "title": "get_project_admin_contextArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["project"]


def test_get_project_configuration_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_project_configuration"]
    assert tool.description == "Return project-scoped configuration such as internal comment support."
    assert tool.output_schema == {
        "properties": {
            "project_id": {
                "title": "Project Id",
                "type": "integer",
            },
            "project_name": {
                "title": "Project Name",
                "type": "string",
            },
            "maximum_attachment_file_size_bytes": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Maximum Attachment File Size Bytes",
            },
            "maximum_api_v3_page_size": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Maximum Api V3 Page Size",
            },
            "per_page_options": {
                "items": {
                    "type": "integer",
                },
                "title": "Per Page Options",
                "type": "array",
            },
            "duration_format": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Duration Format",
            },
            "hours_per_day": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "number",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Hours Per Day",
            },
            "days_per_month": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "number",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Days Per Month",
            },
            "active_feature_flags": {
                "items": {
                    "type": "string",
                },
                "title": "Active Feature Flags",
                "type": "array",
            },
            "available_features": {
                "items": {
                    "type": "string",
                },
                "title": "Available Features",
                "type": "array",
            },
            "trialling_features": {
                "items": {
                    "type": "string",
                },
                "title": "Trialling Features",
                "type": "array",
            },
            "enabled_internal_comments": {
                "anyOf": [
                    {
                        "type": "boolean",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Enabled Internal Comments",
            },
        },
        "required": [
            "project_id",
            "project_name",
            "maximum_attachment_file_size_bytes",
            "maximum_api_v3_page_size",
            "per_page_options",
            "duration_format",
            "hours_per_day",
            "days_per_month",
            "active_feature_flags",
            "available_features",
            "trialling_features",
            "enabled_internal_comments",
        ],
        "title": "ProjectConfiguration",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {
            "project": {
                "title": "Project",
                "type": "string",
            },
        },
        "required": ["project"],
        "title": "get_project_configurationArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["project"]


def test_create_project_schema() -> None:
    tool = _tools(create_app(_make_settings()))["create_project"]
    assert (
        tool.description
        == "Prepare or create a project.\n\nA rejected validation preview is not a tool error; inspect `ready` and\n`validation_errors` in the result rather than the MCP error envelope.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "name": {
                "title": "Name",
                "type": "string",
            },
            "identifier": {
                "title": "Identifier",
                "type": "string",
            },
            "description": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Description",
            },
            "public": {
                "anyOf": [
                    {
                        "type": "boolean",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Public",
            },
            "active": {
                "anyOf": [
                    {
                        "type": "boolean",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Active",
            },
            "status": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Status",
            },
            "status_explanation": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Status Explanation",
            },
            "parent": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Parent",
            },
            "confirm": {
                "default": False,
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["name", "identifier"],
        "title": "create_projectArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "name",
        "identifier",
        "description",
        "public",
        "active",
        "status",
        "status_explanation",
        "parent",
        "confirm",
    ]


def test_copy_project_schema() -> None:
    tool = _tools(create_app(_make_settings()))["copy_project"]
    assert (
        tool.description
        == "Prepare or copy an existing project into a new project.\n\nA rejected validation preview is not a tool error; inspect `ready` and\n`validation_errors` in the result rather than the MCP error envelope.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "source_project": {
                "title": "Source Project",
                "type": "string",
            },
            "name": {
                "title": "Name",
                "type": "string",
            },
            "identifier": {
                "title": "Identifier",
                "type": "string",
            },
            "description": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Description",
            },
            "public": {
                "anyOf": [
                    {
                        "type": "boolean",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Public",
            },
            "active": {
                "anyOf": [
                    {
                        "type": "boolean",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Active",
            },
            "status": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Status",
            },
            "status_explanation": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Status Explanation",
            },
            "parent": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Parent",
            },
            "confirm": {
                "default": False,
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["source_project", "name", "identifier"],
        "title": "copy_projectArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "source_project",
        "name",
        "identifier",
        "description",
        "public",
        "active",
        "status",
        "status_explanation",
        "parent",
        "confirm",
    ]


def test_get_job_status_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_job_status"]
    assert tool.description == "Get the current status of a background job such as project copy."
    assert tool.output_schema == {
        "properties": {
            "id": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Id",
            },
            "type": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Type",
            },
            "status": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Status",
            },
            "message": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Message",
            },
            "project_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Project Id",
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
            "created_resource_type": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Created Resource Type",
            },
            "created_resource_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Created Resource Id",
            },
            "created_resource_name": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Created Resource Name",
            },
        },
        "required": [
            "id",
            "type",
            "status",
            "message",
            "project_id",
            "project",
            "created_resource_type",
            "created_resource_id",
            "created_resource_name",
        ],
        "title": "JobStatusDetail",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {
            "job_status_id": {
                "title": "Job Status Id",
                "type": "string",
            },
        },
        "required": ["job_status_id"],
        "title": "get_job_statusArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["job_status_id"]


def test_update_project_schema() -> None:
    tool = _tools(create_app(_make_settings()))["update_project"]
    assert (
        tool.description
        == "Prepare or update a project.\n\nPass 'none' to parent to make the project top-level (remove its parent).\nA rejected validation preview is not a tool error; inspect `ready` and\n`validation_errors` in the result rather than the MCP error envelope.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {
                "title": "Project",
                "type": "string",
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
            "identifier": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Identifier",
            },
            "description": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Description",
            },
            "public": {
                "anyOf": [
                    {
                        "type": "boolean",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Public",
            },
            "active": {
                "anyOf": [
                    {
                        "type": "boolean",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Active",
            },
            "status": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Status",
            },
            "status_explanation": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Status Explanation",
            },
            "parent": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Parent",
            },
            "confirm": {
                "default": False,
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["project"],
        "title": "update_projectArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "project",
        "name",
        "identifier",
        "description",
        "public",
        "active",
        "status",
        "status_explanation",
        "parent",
        "confirm",
    ]


def test_delete_project_schema() -> None:
    tool = _tools(create_app(_make_settings()))["delete_project"]
    assert tool.description == "Prepare or delete a project."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {
                "title": "Project",
                "type": "string",
            },
            "confirm": {
                "default": False,
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["project"],
        "title": "delete_projectArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["project", "confirm"]


def test_get_my_project_access_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_my_project_access"]
    assert tool.description == "Return the current user's membership and inferred access hints for a project."
    assert tool.output_schema == {
        "$defs": {
            "MembershipSummary": {
                "properties": {
                    "id": {
                        "title": "Id",
                        "type": "integer",
                    },
                    "principal_id": {
                        "anyOf": [
                            {
                                "type": "integer",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "title": "Principal Id",
                    },
                    "principal_name": {
                        "anyOf": [
                            {
                                "type": "string",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "title": "Principal Name",
                    },
                    "project_id": {
                        "anyOf": [
                            {
                                "type": "integer",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "title": "Project Id",
                    },
                    "project_name": {
                        "anyOf": [
                            {
                                "type": "string",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "title": "Project Name",
                    },
                    "role_ids": {
                        "items": {
                            "type": "integer",
                        },
                        "title": "Role Ids",
                        "type": "array",
                    },
                    "role_names": {
                        "items": {
                            "type": "string",
                        },
                        "title": "Role Names",
                        "type": "array",
                    },
                    "can_update": {
                        "title": "Can Update",
                        "type": "boolean",
                    },
                    "can_update_immediately": {
                        "title": "Can Update Immediately",
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
                "required": [
                    "id",
                    "principal_id",
                    "principal_name",
                    "project_id",
                    "project_name",
                    "role_ids",
                    "role_names",
                    "can_update",
                    "can_update_immediately",
                ],
                "title": "MembershipSummary",
                "type": "object",
            },
        },
        "properties": {
            "project_id": {
                "title": "Project Id",
                "type": "integer",
            },
            "project_name": {
                "title": "Project Name",
                "type": "string",
            },
            "project_identifier": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Project Identifier",
            },
            "current_user_id": {
                "title": "Current User Id",
                "type": "integer",
            },
            "current_user_name": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Current User Name",
            },
            "membership": {
                "anyOf": [
                    {
                        "$ref": "#/$defs/MembershipSummary",
                    },
                    {
                        "type": "null",
                    },
                ],
            },
            "inferred_is_project_admin": {
                "title": "Inferred Is Project Admin",
                "type": "boolean",
            },
            "inferred_can_edit_project": {
                "title": "Inferred Can Edit Project",
                "type": "boolean",
            },
            "inferred_can_manage_memberships": {
                "title": "Inferred Can Manage Memberships",
                "type": "boolean",
            },
            "inference_basis": {
                "title": "Inference Basis",
                "type": "string",
            },
        },
        "required": [
            "project_id",
            "project_name",
            "project_identifier",
            "current_user_id",
            "current_user_name",
            "membership",
            "inferred_is_project_admin",
            "inferred_can_edit_project",
            "inferred_can_manage_memberships",
            "inference_basis",
        ],
        "title": "ProjectAccessSummary",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {
            "project": {
                "title": "Project",
                "type": "string",
            },
        },
        "required": ["project"],
        "title": "get_my_project_accessArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["project"]


def test_get_instance_configuration_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_instance_configuration"]
    assert tool.description == "Return instance-level OpenProject configuration and active feature flags."
    assert tool.output_schema == {
        "properties": {
            "host_name": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Host Name",
            },
            "maximum_attachment_file_size_bytes": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Maximum Attachment File Size Bytes",
            },
            "maximum_api_v3_page_size": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Maximum Api V3 Page Size",
            },
            "per_page_options": {
                "items": {
                    "type": "integer",
                },
                "title": "Per Page Options",
                "type": "array",
            },
            "duration_format": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Duration Format",
            },
            "hours_per_day": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "number",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Hours Per Day",
            },
            "days_per_month": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "number",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Days Per Month",
            },
            "active_feature_flags": {
                "items": {
                    "type": "string",
                },
                "title": "Active Feature Flags",
                "type": "array",
            },
            "available_features": {
                "items": {
                    "type": "string",
                },
                "title": "Available Features",
                "type": "array",
            },
            "trialling_features": {
                "items": {
                    "type": "string",
                },
                "title": "Trialling Features",
                "type": "array",
            },
        },
        "required": [
            "host_name",
            "maximum_attachment_file_size_bytes",
            "maximum_api_v3_page_size",
            "per_page_options",
            "duration_format",
            "hours_per_day",
            "days_per_month",
            "active_feature_flags",
            "available_features",
            "trialling_features",
        ],
        "title": "InstanceConfiguration",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {},
        "title": "get_instance_configurationArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == []


def test_list_project_phase_definitions_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_project_phase_definitions"]
    assert tool.description == "List available project lifecycle phase definitions exposed by OpenProject."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {},
        "title": "list_project_phase_definitionsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == []


def test_get_project_phase_definition_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_project_phase_definition"]
    assert tool.description == "Get a single project lifecycle phase definition by id."
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
            "start_gate": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Start Gate",
            },
            "finish_gate": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Finish Gate",
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
        "required": ["id", "name", "start_gate", "finish_gate", "created_at", "updated_at"],
        "title": "ProjectPhaseDefinition",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {
            "phase_definition_id": {
                "title": "Phase Definition Id",
                "type": "integer",
            },
        },
        "required": ["phase_definition_id"],
        "title": "get_project_phase_definitionArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["phase_definition_id"]


def test_get_project_phase_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_project_phase"]
    assert tool.description == "Get a single project lifecycle phase by id."
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
            "project_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Project Id",
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
            "phase_definition_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Phase Definition Id",
            },
            "phase_definition": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Phase Definition",
            },
            "start_date": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Start Date",
            },
            "finish_date": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Finish Date",
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
            "name",
            "project_id",
            "project",
            "phase_definition_id",
            "phase_definition",
            "start_date",
            "finish_date",
            "created_at",
            "updated_at",
        ],
        "title": "ProjectPhase",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {
            "phase_id": {
                "title": "Phase Id",
                "type": "integer",
            },
        },
        "required": ["phase_id"],
        "title": "get_project_phaseArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["phase_id"]


def test_list_project_storages_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_project_storages"]
    assert (
        tool.description
        == "List a project's links to configured external file storages, optionally filtered to one project.\n\nRead-only in OpenProject's API -- no create/update/delete endpoint exists\nfor this resource; manage the underlying connection with the storages\ntools instead.\n\nselect fields: id, project, storage_name, project_folder_mode (see server\ninstructions for select's general semantics).\n\nlimit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned\nnext_offset as the next call's offset to page past the cap.\n"
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
        "title": "list_project_storagesArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["project", "offset", "limit", "select"]


def test_get_project_storage_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_project_storage"]
    assert tool.description == "Get a single project's link to a configured external file storage by id."
    assert tool.output_schema == {
        "properties": {
            "id": {
                "title": "Id",
                "type": "integer",
            },
            "project_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Project Id",
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
            "storage_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Storage Id",
            },
            "storage_name": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Storage Name",
            },
            "project_folder_mode": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Project Folder Mode",
            },
            "creator_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Creator Id",
            },
            "creator": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Creator",
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
            "project_id",
            "project",
            "storage_id",
            "storage_name",
            "project_folder_mode",
            "creator_id",
            "creator",
            "created_at",
            "updated_at",
        ],
        "title": "ProjectStorageDetail",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {
            "project_storage_id": {
                "title": "Project Storage Id",
                "type": "integer",
            },
        },
        "required": ["project_storage_id"],
        "title": "get_project_storageArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["project_storage_id"]


def test_get_project_work_package_context_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_project_work_package_context"]
    assert (
        tool.description
        == "Return project metadata and, optionally, the writable work-package schema for a given type."
    )
    assert tool.output_schema == {
        "$defs": {
            "OptionValue": {
                "properties": {
                    "id": {
                        "anyOf": [
                            {
                                "type": "integer",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "title": "Id",
                    },
                    "title": {
                        "title": "Title",
                        "type": "string",
                    },
                    "href": {
                        "anyOf": [
                            {
                                "type": "string",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "title": "Href",
                    },
                },
                "required": ["id", "title", "href"],
                "title": "OptionValue",
                "type": "object",
            },
            "VersionSummary": {
                "properties": {
                    "id": {
                        "title": "Id",
                        "type": "integer",
                    },
                    "name": {
                        "title": "Name",
                        "type": "string",
                    },
                    "status": {
                        "anyOf": [
                            {
                                "type": "string",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "title": "Status",
                    },
                    "sharing": {
                        "anyOf": [
                            {
                                "type": "string",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "title": "Sharing",
                    },
                    "start_date": {
                        "anyOf": [
                            {
                                "type": "string",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "title": "Start Date",
                    },
                    "end_date": {
                        "anyOf": [
                            {
                                "type": "string",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "title": "End Date",
                    },
                    "defining_project": {
                        "anyOf": [
                            {
                                "type": "string",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "title": "Defining Project",
                    },
                    "description": {
                        "anyOf": [
                            {
                                "type": "string",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "title": "Description",
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
                    "description_truncated": {
                        "default": False,
                        "title": "Description Truncated",
                        "type": "boolean",
                    },
                    "description_length": {
                        "anyOf": [
                            {
                                "type": "integer",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "default": None,
                        "title": "Description Length",
                    },
                },
                "required": [
                    "id",
                    "name",
                    "status",
                    "sharing",
                    "start_date",
                    "end_date",
                    "defining_project",
                    "description",
                ],
                "title": "VersionSummary",
                "type": "object",
            },
            "WorkPackageFieldSchema": {
                "properties": {
                    "key": {
                        "title": "Key",
                        "type": "string",
                    },
                    "name": {
                        "title": "Name",
                        "type": "string",
                    },
                    "type": {
                        "anyOf": [
                            {
                                "type": "string",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "title": "Type",
                    },
                    "required": {
                        "title": "Required",
                        "type": "boolean",
                    },
                    "writable": {
                        "title": "Writable",
                        "type": "boolean",
                    },
                    "has_default": {
                        "title": "Has Default",
                        "type": "boolean",
                    },
                    "placeholder": {
                        "anyOf": [
                            {
                                "type": "string",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "title": "Placeholder",
                    },
                    "location": {
                        "anyOf": [
                            {
                                "type": "string",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "title": "Location",
                    },
                    "allowed_values": {
                        "items": {
                            "$ref": "#/$defs/OptionValue",
                        },
                        "title": "Allowed Values",
                        "type": "array",
                    },
                },
                "required": [
                    "key",
                    "name",
                    "type",
                    "required",
                    "writable",
                    "has_default",
                    "placeholder",
                    "location",
                    "allowed_values",
                ],
                "title": "WorkPackageFieldSchema",
                "type": "object",
            },
        },
        "properties": {
            "project_id": {
                "title": "Project Id",
                "type": "integer",
            },
            "project_name": {
                "title": "Project Name",
                "type": "string",
            },
            "project_identifier": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Project Identifier",
            },
            "selected_type_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Selected Type Id",
            },
            "selected_type_name": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Selected Type Name",
            },
            "available_types": {
                "items": {
                    "$ref": "#/$defs/OptionValue",
                },
                "title": "Available Types",
                "type": "array",
            },
            "available_statuses": {
                "items": {
                    "$ref": "#/$defs/OptionValue",
                },
                "title": "Available Statuses",
                "type": "array",
            },
            "available_priorities": {
                "items": {
                    "$ref": "#/$defs/OptionValue",
                },
                "title": "Available Priorities",
                "type": "array",
            },
            "available_categories": {
                "items": {
                    "$ref": "#/$defs/OptionValue",
                },
                "title": "Available Categories",
                "type": "array",
            },
            "available_project_phases": {
                "items": {
                    "$ref": "#/$defs/OptionValue",
                },
                "title": "Available Project Phases",
                "type": "array",
            },
            "available_versions": {
                "items": {
                    "$ref": "#/$defs/VersionSummary",
                },
                "title": "Available Versions",
                "type": "array",
            },
            "fields": {
                "items": {
                    "$ref": "#/$defs/WorkPackageFieldSchema",
                },
                "title": "Fields",
                "type": "array",
            },
            "custom_fields": {
                "items": {
                    "$ref": "#/$defs/WorkPackageFieldSchema",
                },
                "title": "Custom Fields",
                "type": "array",
            },
        },
        "required": [
            "project_id",
            "project_name",
            "project_identifier",
            "selected_type_id",
            "selected_type_name",
            "available_types",
            "available_statuses",
            "available_priorities",
            "available_categories",
            "available_project_phases",
            "available_versions",
            "fields",
            "custom_fields",
        ],
        "title": "ProjectWorkPackageContext",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {
            "project": {
                "title": "Project",
                "type": "string",
            },
            "type": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Type",
            },
        },
        "required": ["project"],
        "title": "get_project_work_package_contextArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["project", "type"]


def test_set_project_favorite_schema() -> None:
    tool = _tools(create_app(_make_settings()))["set_project_favorite"]
    assert (
        tool.description
        == 'Prepare or mark/unmark a project as a favorite; only writes when called again with confirm=true.\n\nproject: numeric id (e.g., 7) or identifier (e.g., "my-project"), not display name.\nfavorite=true marks it as a favorite; favorite=false removes it.\n'
    )
    assert tool.output_schema == {
        "properties": {
            "action": {
                "title": "Action",
                "type": "string",
            },
            "state": {
                "enum": ["rejected", "invalid", "preview", "confirmed"],
                "title": "State",
                "type": "string",
            },
            "ready": {
                "title": "Ready",
                "type": "boolean",
            },
            "message": {
                "title": "Message",
                "type": "string",
            },
            "project_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Project Id",
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
        },
        "required": ["action", "state", "ready", "message", "project_id", "project"],
        "title": "FavoriteWriteResult",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {
            "project": {
                "title": "Project",
                "type": "string",
            },
            "favorite": {
                "title": "Favorite",
                "type": "boolean",
            },
            "confirm": {
                "default": False,
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["project", "favorite"],
        "title": "set_project_favoriteArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["project", "favorite", "confirm"]
