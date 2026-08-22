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
    assert tool.description == (
        "List OpenProject roles visible to the current user.\n\n"
        "select fields: id, name (see server instructions for select's general semantics).\n"
        "limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned\n"
        "next_offset as the next call's offset to page past the cap.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "select": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "title": "Select",
            },
            "offset": {"default": 1, "title": "Offset", "type": "integer"},
            "limit": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
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
        "List API actions exposed by OpenProject.\n\n"
        "select fields: id, url (see server instructions for select's general semantics).\n\n"
        "limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned\n"
        "next_offset as the next call's offset to page past the cap.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
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
        "title": "list_actionsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["offset", "limit", "select"]


def test_list_capabilities_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_capabilities"]
    assert tool.description == (
        "List API capabilities exposed by OpenProject.\n\n"
        "At least one of project or capability_id is required — there is no\n"
        "unfiltered global listing, since one would bypass the project read\n"
        "allowlist.\n\n"
        "select fields: id, action_id, context (see server instructions for\n"
        "select's general semantics).\n\n"
        "limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned\n"
        "next_offset as the next call's offset to page past the cap.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Project",
            },
            "capability_id": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Capability Id",
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
        "title": "list_capabilitiesArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["project", "capability_id", "offset", "limit", "select"]


def test_list_project_memberships_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_project_memberships"]
    assert tool.description == (
        "List memberships for a project, including principal and role names.\n\n"
        "select fields: id, principal_name, role_names (see server instructions for\n"
        "select's general semantics).\n\n"
        "limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned\n"
        "next_offset as the next call's offset to page past the cap.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {"title": "Project", "type": "string"},
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
        "required": ["project"],
        "title": "list_project_membershipsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["project", "offset", "limit", "select"]


def test_get_membership_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_membership"]
    assert tool.description == "Get a compact membership summary by id."
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
            "membership_id": {"title": "Membership Id", "type": "integer"},
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
    assert tool.description == "Prepare or create a project membership."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {"title": "Project", "type": "string"},
            "principal": {"title": "Principal", "type": "string"},
            "roles": {"items": {"type": "string"}, "title": "Roles", "type": "array"},
            "notification_message": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Notification Message",
            },
            "confirm": {"default": False, "title": "Confirm", "type": "boolean"},
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
    assert tool.description == "Prepare or update a project membership."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "membership_id": {"title": "Membership Id", "type": "integer"},
            "roles": {"items": {"type": "string"}, "title": "Roles", "type": "array"},
            "notification_message": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Notification Message",
            },
            "confirm": {"default": False, "title": "Confirm", "type": "boolean"},
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
    assert tool.description == "Prepare or delete a project membership."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "membership_id": {"title": "Membership Id", "type": "integer"},
            "confirm": {"default": False, "title": "Confirm", "type": "boolean"},
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
