"""Characterization test: freezes the 9 Membership MCP tool schemas
(list_roles, list_actions, list_capabilities, list_project_memberships,
get_membership, create_membership, update_membership, delete_membership,
get_current_user).

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
        "enable_metadata_tools": True,
        "read_projects": ("*",),
        "write_projects": ("*",),
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _tools(mcp) -> dict:
    return {t.name: t for t in mcp._tool_manager.list_tools()}


def test_list_roles_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_roles"]
    assert tool.description == ("List OpenProject roles visible to the current user.")
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "select": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "description": "Fields to return; a requested unset field comes back as null. Allowed: id, name.",
                "title": "Select",
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
        },
        "title": "list_rolesArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["select", "offset", "limit"]


def test_list_actions_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_actions"]
    assert tool.description == (
        'List the action ids OpenProject\'s API defines, e.g. "work_packages/create".\n\nThis is the vocabulary only; which user or group may perform an action in which project comes from\nlist_capabilities.\n'
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
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
                "description": "Fields to return; a requested unset field comes back as null. Allowed: id, url.",
                "title": "Select",
            },
        },
        "title": "list_actionsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["offset", "limit", "select"]


def test_list_capabilities_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_capabilities"]
    assert tool.description == (
        "List API capabilities exposed by OpenProject.\n\nAt least one of project or capability_id is required; there is no\nunfiltered global listing, since one would bypass the project read\nallowlist.\n"
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
            "capability_id": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Capability Id",
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
                "description": "Fields to return; a requested unset field comes back as null. Allowed: action_id, context, id, principal_id, principal_name, url.",
                "title": "Select",
            },
        },
        "title": "list_capabilitiesArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["project", "capability_id", "offset", "limit", "select"]


def test_list_project_memberships_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_project_memberships"]
    assert tool.description == ("List memberships for a project, including principal and role names.")
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {
                "anyOf": [{"type": "integer"}, {"type": "string"}],
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
                "description": "Fields to return; a requested unset field comes back as null. Allowed: can_update, can_update_immediately, created_at, id, principal_id, principal_name, project_id, project_name, role_ids, role_names, updated_at.",
                "title": "Select",
            },
        },
        "required": ["project"],
        "title": "list_project_membershipsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["project", "offset", "limit", "select"]


def test_get_membership_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_membership"]
    assert (
        tool.description
        == "Get one project membership by id: the user or group, the project and the role names.\n\nTo list a project's members use list_project_memberships.\n"
    )
    assert tool.output_schema == {
        "properties": {
            "id": {"title": "Id", "type": "integer"},
            "principal_id": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "title": "Principal Id",
            },
            "principal_name": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "title": "Principal Name",
            },
            "project_id": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "title": "Project Id",
            },
            "project_name": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "title": "Project Name",
            },
            "role_ids": {"items": {"type": "integer"}, "title": "Role Ids", "type": "array"},
            "role_names": {"items": {"type": "string"}, "title": "Role Names", "type": "array"},
            "can_update": {"title": "Can Update", "type": "boolean"},
            "can_update_immediately": {"title": "Can Update Immediately", "type": "boolean"},
            "created_at": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Created At",
            },
            "updated_at": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
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
    }
    assert tool.parameters == {
        "properties": {
            "membership_id": {
                "description": "Membership id, from list_project_memberships.",
                "title": "Membership Id",
                "type": "integer",
            }
        },
        "required": ["membership_id"],
        "title": "get_membershipArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["membership_id"]


def test_create_membership_schema() -> None:
    tool = _tools(create_app(_make_settings()))["create_membership"]
    assert (
        tool.description
        == "Create a project membership.\n\nThe preview is validated by OpenProject; problems come back in validation_errors."
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {
                "anyOf": [{"type": "integer"}, {"type": "string"}],
                "description": "Project identifier, id, or name; a unique part of a name or identifier also matches.",
                "title": "Project",
            },
            "principal": {
                "anyOf": [{"type": "integer"}, {"type": "string"}],
                "description": 'User or group: numeric id, exact name (case-insensitive), or "me".',
                "title": "Principal",
            },
            "roles": {
                "description": "At least one; role ids or exact role names (case-insensitive), from list_roles.",
                "items": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
                "title": "Roles",
                "type": "array",
            },
            "notification_message": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Markdown text for OpenProject's membership notification.",
                "title": "Notification Message",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["project", "principal", "roles"],
        "title": "create_membershipArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "project",
        "principal",
        "roles",
        "notification_message",
        "confirm",
    ]


def test_update_membership_schema() -> None:
    tool = _tools(create_app(_make_settings()))["update_membership"]
    assert (
        tool.description
        == "Update a project membership's roles.\n\nThe preview is validated by OpenProject; problems come back in validation_errors."
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "membership_id": {
                "description": "Membership id, from list_project_memberships.",
                "title": "Membership Id",
                "type": "integer",
            },
            "roles": {
                "description": "Replaces all current roles; role ids or exact role names (case-insensitive), from list_roles.",
                "items": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
                "title": "Roles",
                "type": "array",
            },
            "notification_message": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Markdown text for OpenProject's membership notification; sent with this change only, so a blank text is the same as none.",
                "title": "Notification Message",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["membership_id", "roles"],
        "title": "update_membershipArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "membership_id",
        "roles",
        "notification_message",
        "confirm",
    ]


def test_delete_membership_schema() -> None:
    tool = _tools(create_app(_make_settings()))["delete_membership"]
    assert (
        tool.description
        == "Delete a project membership; this cannot be undone.\n\nRoles inherited from a group stay: if some roles come from a group, only the direct ones are removed;\nif all do, the call is rejected.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "membership_id": {
                "description": "Membership id, from list_project_memberships.",
                "title": "Membership Id",
                "type": "integer",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["membership_id"],
        "title": "delete_membershipArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["membership_id", "confirm"]


def test_get_current_user_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_current_user"]
    assert tool.description == "Return the currently authenticated user's profile."
    assert tool.output_schema == {
        "properties": {
            "id": {"title": "Id", "type": "integer"},
            "name": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Name"},
            "login": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Login"},
        },
        "required": ["id", "name", "login"],
        "title": "CurrentUser",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {},
        "title": "get_current_userArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == []
