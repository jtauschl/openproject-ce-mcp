"""Characterization test: freezes the 18 Projects MCP tool schemas.

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


def test_list_projects_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_projects"]
    assert (
        tool.description
        == "List visible projects with optional name or identifier search.\n\nUnder a restrictive OPENPROJECT_READ_PROJECTS, total reflects only the allowed projects already scanned to fill\nthis page, not a full count of all matches; the search stops as soon as it has enough, so an exact total would\nneed an extra full walk. Page until next_offset is null.\n\nEach row carries the project attributes the token may see as `custom_fields`, keyed by customField<N>\n(see get_project); with select, name custom_fields to keep them. custom_field_filters and sort_by take a project attribute\nas cf_<N>."
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
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
                "description": "Fields to return; a requested unset field comes back as null. Allowed: active, can_delete, can_update, created_at, custom_comments, custom_comments_truncated, custom_fields, custom_fields_truncated, description, description_length, description_truncated, favorited, id, identifier, name, parent_id, parent_name, public, status, status_explanation, status_explanation_length, status_explanation_truncated, updated_at.",
                "title": "Select",
            },
            "custom_field_filters": {
                "anyOf": [
                    {"additionalProperties": {"additionalProperties": True, "type": "object"}, "type": "object"},
                    {"type": "null"},
                ],
                "default": None,
                "description": 'Filter by custom field values: {"cf_<N>": {"operator": "=", "values": ["x"]}}, N from a customField<N> key. The operators a field takes depend on its format (docs/filters.md). At most 20 filters, 100 values each. A project matches only where the token may see the field.',
                "title": "Custom Field Filters",
            },
            "sort_by": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "description": 'Sort criteria as "field:direction" or "field-direction" (e.g. ["name:desc", "created_at-asc"]); the direction defaults to asc. Fields: created_at, id, identifier, latest_activity_at, lft, name, project_status, public, required_disk_space, typeahead, updated_at, a custom field\'s cf_<id> (not a text field), or project_phase_<id>. Newer columns need an OpenProject release: updated_at 16.5+.',
                "title": "Sort By",
            },
        },
        "title": "list_projectsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "search",
        "offset",
        "limit",
        "select",
        "custom_field_filters",
        "sort_by",
    ]


def test_get_project_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_project"]
    assert (
        tool.description
        == "Get a project by id, identifier or name, including its ancestor chain.\n\ndescription/status_explanation are returned in full by default (single projects\nare not truncated). Pass ``text_limit`` to cap them at that many characters; when\ncut, ``description_truncated``/``status_explanation_truncated`` are true and\n``description_length``/``status_explanation_length`` report the real length.\n\n``custom_fields`` holds the project attributes the token may see, keyed by customField<N>: a link\nvalue (list, user, version) as its title or a list of titles, a text value capped by ``text_limit``,\na version defined outside OPENPROJECT_READ_PROJECTS as null. From OpenProject 17.2\n``custom_comments`` holds a field's comment, keyed customComment<N> with the same N. ``custom_fields_truncated`` is true\nwhen more than 50 entries or a long value were cut.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {
                "anyOf": [{"type": "integer"}, {"type": "string"}],
                "description": "Project identifier, id, or name; a unique part of a name or identifier also matches.",
                "title": "Project",
            },
            "text_limit": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": None, "title": "Text Limit"},
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
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {
                "anyOf": [{"type": "integer"}, {"type": "string"}],
                "description": "Project identifier, id, or name; a unique part of a name or identifier also matches.",
                "title": "Project",
            }
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
    assert (
        tool.description
        == "Return a project's configuration: get_instance_configuration's fields plus enabled_internal_comments."
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {
                "anyOf": [{"type": "integer"}, {"type": "string"}],
                "description": "Project identifier, id, or name; a unique part of a name or identifier also matches.",
                "title": "Project",
            }
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
        == "Create a project.\n\nOmitted optional fields are not sent, so OpenProject's defaults apply.\n`parent_target` names the project `parent` resolved to.\n`custom_fields` sets project attributes; one the token may not edit comes back in `validation_errors`.\nA rejected validation preview is not a tool error; inspect `ready` and\n`validation_errors` in the result rather than the MCP error envelope. Each entry has a `message`\nand `error_codes` (OpenProject's error classes, the same in every language).\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "name": {"description": "Display name, at most 255 characters.", "title": "Name", "type": "string"},
            "identifier": {
                "description": 'URL identifier such as "my-proj": letters, digits, ".", "_" and "-".',
                "title": "Identifier",
                "type": "string",
            },
            "description": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Markdown text.",
                "title": "Description",
            },
            "public": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "default": None,
                "description": "Whether the project is public.",
                "title": "Public",
            },
            "active": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "default": None,
                "description": "false means archived.",
                "title": "Active",
            },
            "status": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Status title, any case, as listed in get_project_admin_context's available_statuses.",
                "title": "Status",
            },
            "status_explanation": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Markdown text explaining the status.",
                "title": "Status Explanation",
            },
            "parent": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Parent project identifier, id, or name; omit for a top-level project.",
                "title": "Parent",
            },
            "custom_fields": {
                "anyOf": [{"additionalProperties": True, "type": "object"}, {"type": "null"}],
                "default": None,
                "description": "Custom field values by customField<N> key or field name, at most 50. Text, number or boolean as is; list, user and version fields take an option id or title (a list for several values); null clears.",
                "title": "Custom Fields",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
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
        "custom_fields",
        "confirm",
    ]


def test_copy_project_schema() -> None:
    tool = _tools(create_app(_make_settings()))["copy_project"]
    assert (
        tool.description
        == "Copy an existing project into a new project.\n\nname, identifier and the optional fields describe the new project. A confirmed\ncopy starts a background job; poll get_job_status with the returned job_status_id.\n`parent_target` names the project `parent` resolved to.\n`custom_fields` sets project attributes; one the token may not edit comes back in `validation_errors`.\nA rejected validation preview is not a tool error; inspect `ready` and\n`validation_errors` in the result rather than the MCP error envelope. Each entry has a `message`\nand `error_codes` (OpenProject's error classes, the same in every language).\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "source_project": {
                "anyOf": [{"type": "integer"}, {"type": "string"}],
                "description": "Project identifier, id, or name; a unique part of a name or identifier also matches.",
                "title": "Source Project",
            },
            "name": {"description": "Display name, at most 255 characters.", "title": "Name", "type": "string"},
            "identifier": {
                "description": 'URL identifier such as "my-proj": letters, digits, ".", "_" and "-".',
                "title": "Identifier",
                "type": "string",
            },
            "description": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Markdown text.",
                "title": "Description",
            },
            "public": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "default": None,
                "description": "Whether the project is public.",
                "title": "Public",
            },
            "active": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "default": None,
                "description": "false means archived.",
                "title": "Active",
            },
            "status": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Status title, any case, as listed in get_project_admin_context's available_statuses.",
                "title": "Status",
            },
            "status_explanation": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Markdown text explaining the status.",
                "title": "Status Explanation",
            },
            "parent": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Parent project identifier, id, or name; omit for a top-level project.",
                "title": "Parent",
            },
            "custom_fields": {
                "anyOf": [{"additionalProperties": True, "type": "object"}, {"type": "null"}],
                "default": None,
                "description": "Custom field values by customField<N> key or field name, at most 50. Text, number or boolean as is; list, user and version fields take an option id or title (a list for several values); null clears.",
                "title": "Custom Fields",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
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
        "custom_fields",
        "confirm",
    ]


def test_get_job_status_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_job_status"]
    assert tool.description == "Get the current status of a background job such as project copy."
    assert tool.output_schema is None
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
    assert tool.description == (
        "Update a project.\n"
        "\n"
        "Omitted fields stay unchanged.\n"
        "`<field>_append` and `<field>_replace` edit the stored description or status_explanation and leave the rest\n"
        "untouched; a read cuts a long text, so prefer them to a full text. Pass only one of the three per field.\n"
        "`parent_target` names the project `parent` resolved to.\n"
        "`custom_fields` sets project attributes; one the token may not edit comes back in `validation_errors`.\n"
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
            "project": {
                "anyOf": [{"type": "integer"}, {"type": "string"}],
                "description": "Project identifier, id, or name; a unique part of a name or identifier also matches.",
                "title": "Project",
            },
            "name": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Display name, at most 255 characters.",
                "title": "Name",
            },
            "identifier": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": 'URL identifier such as "my-proj": letters, digits, ".", "_" and "-".',
                "title": "Identifier",
            },
            "description": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": 'Markdown text; "" clears it.',
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
            "public": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "default": None,
                "description": "Whether the project is public.",
                "title": "Public",
            },
            "active": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "default": None,
                "description": "false means archived.",
                "title": "Active",
            },
            "status": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Status title, any case, as listed in get_project_admin_context's available_statuses.",
                "title": "Status",
            },
            "status_explanation": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": 'Markdown text explaining the status; "" clears it.',
                "title": "Status Explanation",
            },
            "status_explanation_append": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Paragraph added after the stored text.",
                "title": "Status Explanation Append",
            },
            "status_explanation_replace": {
                "anyOf": [{"$ref": "#/$defs/TextReplace"}, {"type": "null"}],
                "default": None,
                "description": "Replaces the one passage old names with new (may be empty).",
            },
            "parent": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Parent project identifier, id, or name; 'none' makes the project top-level.",
                "title": "Parent",
            },
            "custom_fields": {
                "anyOf": [{"additionalProperties": True, "type": "object"}, {"type": "null"}],
                "default": None,
                "description": "Custom field values by customField<N> key or field name, at most 50. Text, number or boolean as is; list, user and version fields take an option id or title (a list for several values); null clears.",
                "title": "Custom Fields",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
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
        "description_append",
        "description_replace",
        "public",
        "active",
        "status",
        "status_explanation",
        "status_explanation_append",
        "status_explanation_replace",
        "parent",
        "custom_fields",
        "confirm",
    ]


def test_delete_project_schema() -> None:
    tool = _tools(create_app(_make_settings()))["delete_project"]
    assert (
        tool.description
        == "Delete a project and its subprojects (admin operation).\n\nOpenProject archives them at once and deletes them in a background job, with their work packages,\nmemberships, versions, time entries, news, wiki, forums, meetings, documents and storage links; this\ncannot be undone. OpenProject also tries to delete storage project folders managed automatically, with\ntheir files. Unless the project is already archived, rejected while work packages of other projects use\none of their versions.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {
                "anyOf": [{"type": "integer"}, {"type": "string"}],
                "description": "Project identifier, id, or name; a unique part of a name or identifier also matches.",
                "title": "Project",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
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
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {
                "anyOf": [{"type": "integer"}, {"type": "string"}],
                "description": "Project identifier, id, or name; a unique part of a name or identifier also matches.",
                "title": "Project",
            }
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
    assert tool.output_schema is None
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
    assert tool.output_schema is None
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
    assert tool.description == (
        "Get a single project lifecycle phase by id. "
        "`start_date` and `finish_date` stay null: the API does not provide them."
    )
    assert tool.output_schema is None
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
        == "List a project's links to configured external file storages, optionally filtered to one project.\n\nRead-only in OpenProject's API -- no create/update/delete endpoint exists\nfor this resource; manage the underlying connection with the storages\ntools instead.\n"
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
                "description": "Fields to return; a requested unset field comes back as null. Allowed: created_at, id, project, project_folder_mode, project_id, storage_id, storage_name, updated_at.",
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
    assert tool.output_schema is None
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
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {
                "anyOf": [{"type": "integer"}, {"type": "string"}],
                "description": "Project identifier, id, or name; a unique part of a name or identifier also matches.",
                "title": "Project",
            },
            "type": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
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
    assert tool.description == "Mark or unmark a project as a favorite. Requires OpenProject 17.0 or later."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {
                "anyOf": [{"type": "integer"}, {"type": "string"}],
                "description": "Project identifier, id, or name; a unique part of a name or identifier also matches.",
                "title": "Project",
            },
            "favorite": {
                "description": "true adds the project to favorites, false removes it.",
                "title": "Favorite",
                "type": "boolean",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
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
