"""Characterization test: freezes the 17 Admin MCP tool schemas
(list_principals, list_users, get_user, list_groups, get_group, list_storages,
get_storage, create_user, update_user, delete_user, set_user_locked,
create_group, update_group, delete_group, create_storage, update_storage,
delete_storage).

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
        "enable_admin_read": True,
        "enable_admin_write": True,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _tools(mcp) -> dict:
    return {t.name: t for t in mcp._tool_manager.list_tools()}


def test_list_principals_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_principals"]
    assert tool.description == (
        "List users and groups that can be used for project memberships.\n\n"
        "select fields: id, name, type (see server instructions for select's general semantics).\n\n"
        "limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned\n"
        "next_offset as the next call's offset to page past the cap.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "search": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Search"},
            "offset": {"default": 1, "title": "Offset", "type": "integer"},
            "limit": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": None, "title": "Limit"},
            "select": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "title": "Select",
            },
        },
        "title": "list_principalsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["search", "offset", "limit", "select"]


def test_list_users_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_users"]
    assert tool.description == (
        "List users visible to the current token.\n\n"
        "select fields: id, name, login, email, status, admin, created_at, updated_at\n"
        "(see server instructions for select's general semantics).\n\n"
        "limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned\n"
        "next_offset as the next call's offset to page past the cap. With search,\n"
        "total is only the count of matching users returned on THIS page, not a\n"
        "full count of all matches — the search stops as soon as it has enough,\n"
        "so an exact total would need an extra full walk. Page until next_offset\n"
        "is null.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "search": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Search"},
            "offset": {"default": 1, "title": "Offset", "type": "integer"},
            "limit": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": None, "title": "Limit"},
            "select": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "title": "Select",
            },
        },
        "title": "list_usersArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["search", "offset", "limit", "select"]


def test_get_user_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_user"]
    assert tool.description == "Get a user by id, login, or `me` when supported by OpenProject."
    assert tool.output_schema == {
        "properties": {
            "id": {"title": "Id", "type": "integer"},
            "name": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Name"},
            "login": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Login"},
            "email": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Email"},
            "status": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Status"},
            "admin": {"anyOf": [{"type": "boolean"}, {"type": "null"}], "title": "Admin"},
            "locked": {"anyOf": [{"type": "boolean"}, {"type": "null"}], "title": "Locked"},
            "avatar_url": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Avatar Url"},
            "created_at": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Created At"},
            "updated_at": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Updated At"},
            "language": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Language"},
            "identity_url": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Identity Url"},
            "auth_source": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Auth Source"},
            "firstname": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Firstname",
            },
            "lastname": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Lastname",
            },
        },
        "required": [
            "id",
            "name",
            "login",
            "email",
            "status",
            "admin",
            "locked",
            "avatar_url",
            "created_at",
            "updated_at",
            "language",
            "identity_url",
            "auth_source",
        ],
        "title": "UserDetail",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {"user": {"title": "User", "type": "string"}},
        "required": ["user"],
        "title": "get_userArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["user"]


def test_list_groups_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_groups"]
    assert tool.description == (
        "List groups visible to the current token.\n\n"
        "select fields: id, name (see server instructions for select's general semantics).\n\n"
        "limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned\n"
        "next_offset as the next call's offset to page past the cap. With search,\n"
        "total is only the count of matching groups returned on THIS page, not a\n"
        "full count of all matches — the search stops as soon as it has enough,\n"
        "so an exact total would need an extra full walk. Page until next_offset\n"
        "is null.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "search": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Search"},
            "offset": {"default": 1, "title": "Offset", "type": "integer"},
            "limit": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": None, "title": "Limit"},
            "select": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "title": "Select",
            },
        },
        "title": "list_groupsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["search", "offset", "limit", "select"]


def test_get_group_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_group"]
    assert tool.description == "Get a single group by id."
    assert tool.output_schema == {
        "properties": {
            "id": {"title": "Id", "type": "integer"},
            "name": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Name"},
            "member_count": {"title": "Member Count", "type": "integer"},
            "members": {"items": {"type": "string"}, "title": "Members", "type": "array"},
            "created_at": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Created At"},
            "updated_at": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Updated At"},
            "can_update": {"title": "Can Update", "type": "boolean"},
            "can_delete": {"title": "Can Delete", "type": "boolean"},
        },
        "required": [
            "id",
            "name",
            "member_count",
            "members",
            "created_at",
            "updated_at",
            "can_update",
            "can_delete",
        ],
        "title": "GroupDetail",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {"group_id": {"title": "Group Id", "type": "integer"}},
        "required": ["group_id"],
        "title": "get_groupArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["group_id"]


def test_list_storages_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_storages"]
    assert tool.description == (
        "List configured OpenProject external file storage connections (Nextcloud/OneDrive/Sharepoint).\n\n"
        "select fields: id, name, provider_type, host, configured, created_at, updated_at\n"
        "(see server instructions for select's general semantics).\n\n"
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
            "limit": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": None, "title": "Limit"},
        },
        "title": "list_storagesArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["select", "offset", "limit"]


def test_get_storage_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_storage"]
    assert tool.description == "Get a single OpenProject external file storage connection by id."
    assert tool.output_schema == {
        "properties": {
            "id": {"title": "Id", "type": "integer"},
            "name": {"title": "Name", "type": "string"},
            "provider_type": {"title": "Provider Type", "type": "string"},
            "host": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Host"},
            "configured": {"title": "Configured", "type": "boolean"},
            "authorization_state": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "title": "Authorization State",
            },
            "authentication_method": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "title": "Authentication Method",
            },
            "created_at": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Created At"},
            "updated_at": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Updated At"},
            "has_application_password": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "default": None,
                "title": "Has Application Password",
            },
            "forbidden_file_name_characters": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Forbidden File Name Characters",
            },
            "tenant_id": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Tenant Id",
            },
            "drive_id": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Drive Id",
            },
        },
        "required": [
            "id",
            "name",
            "provider_type",
            "host",
            "configured",
            "authorization_state",
            "authentication_method",
            "created_at",
            "updated_at",
        ],
        "title": "StorageDetail",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {"storage_id": {"title": "Storage Id", "type": "integer"}},
        "required": ["storage_id"],
        "title": "get_storageArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["storage_id"]


def test_create_user_schema() -> None:
    tool = _tools(create_app(_make_settings()))["create_user"]
    assert tool.description == "Prepare or create a new user (admin operation)."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "login": {"title": "Login", "type": "string"},
            "email": {"title": "Email", "type": "string"},
            "firstname": {"title": "Firstname", "type": "string"},
            "lastname": {"title": "Lastname", "type": "string"},
            "password": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Password",
            },
            "admin": {"default": False, "title": "Admin", "type": "boolean"},
            "status": {"default": "active", "title": "Status", "type": "string"},
            "language": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Language",
            },
            "confirm": {"default": False, "title": "Confirm", "type": "boolean"},
        },
        "required": ["login", "email", "firstname", "lastname"],
        "title": "create_userArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "login",
        "email",
        "firstname",
        "lastname",
        "password",
        "admin",
        "status",
        "language",
        "confirm",
    ]


def test_update_user_schema() -> None:
    tool = _tools(create_app(_make_settings()))["update_user"]
    assert tool.description == "Prepare or update an existing user (admin operation)."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "user_id": {"title": "User Id", "type": "integer"},
            "login": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Login"},
            "email": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Email"},
            "firstname": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Firstname",
            },
            "lastname": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Lastname",
            },
            "admin": {"anyOf": [{"type": "boolean"}, {"type": "null"}], "default": None, "title": "Admin"},
            "language": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Language",
            },
            "confirm": {"default": False, "title": "Confirm", "type": "boolean"},
        },
        "required": ["user_id"],
        "title": "update_userArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "user_id",
        "login",
        "email",
        "firstname",
        "lastname",
        "admin",
        "language",
        "confirm",
    ]


def test_delete_user_schema() -> None:
    tool = _tools(create_app(_make_settings()))["delete_user"]
    assert tool.description == "Prepare or delete a user (admin operation)."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "user_id": {"title": "User Id", "type": "integer"},
            "confirm": {"default": False, "title": "Confirm", "type": "boolean"},
        },
        "required": ["user_id"],
        "title": "delete_userArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["user_id", "confirm"]


def test_set_user_locked_schema() -> None:
    tool = _tools(create_app(_make_settings()))["set_user_locked"]
    assert tool.description == (
        "Prepare or lock/unlock a user account (admin operation).\n\n"
        "locked=true locks the account; locked=false unlocks it. Preview/confirm\n"
        "behavior is identical either way.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "user_id": {"title": "User Id", "type": "integer"},
            "locked": {"title": "Locked", "type": "boolean"},
            "confirm": {"default": False, "title": "Confirm", "type": "boolean"},
        },
        "required": ["user_id", "locked"],
        "title": "set_user_lockedArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["user_id", "locked", "confirm"]


def test_create_group_schema() -> None:
    tool = _tools(create_app(_make_settings()))["create_group"]
    assert tool.description == "Prepare or create a new group (admin operation)."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "name": {"title": "Name", "type": "string"},
            "user_ids": {
                "anyOf": [{"items": {"type": "integer"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "title": "User Ids",
            },
            "confirm": {"default": False, "title": "Confirm", "type": "boolean"},
        },
        "required": ["name"],
        "title": "create_groupArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["name", "user_ids", "confirm"]


def test_update_group_schema() -> None:
    tool = _tools(create_app(_make_settings()))["update_group"]
    assert tool.description == "Prepare or update an existing group (admin operation)."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "group_id": {"title": "Group Id", "type": "integer"},
            "name": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Name"},
            "add_user_ids": {
                "anyOf": [{"items": {"type": "integer"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "title": "Add User Ids",
            },
            "remove_user_ids": {
                "anyOf": [{"items": {"type": "integer"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "title": "Remove User Ids",
            },
            "confirm": {"default": False, "title": "Confirm", "type": "boolean"},
        },
        "required": ["group_id"],
        "title": "update_groupArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "group_id",
        "name",
        "add_user_ids",
        "remove_user_ids",
        "confirm",
    ]


def test_delete_group_schema() -> None:
    tool = _tools(create_app(_make_settings()))["delete_group"]
    assert tool.description == "Prepare or delete a group (admin operation)."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "group_id": {"title": "Group Id", "type": "integer"},
            "confirm": {"default": False, "title": "Confirm", "type": "boolean"},
        },
        "required": ["group_id"],
        "title": "delete_groupArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["group_id", "confirm"]


def test_create_storage_schema() -> None:
    tool = _tools(create_app(_make_settings()))["create_storage"]
    assert tool.description == (
        "Prepare or create an external file storage connection (admin operation).\n\n"
        'provider_type must be one of "Nextcloud", "OneDrive", "Sharepoint". Field\n'
        "requirements differ genuinely by provider, per OpenProject's own\n"
        "validation (not pre-checked here beyond provider_type itself):\n"
        "- Nextcloud: host required; authentication_method required, one of\n"
        '  "two_way_oauth2" or "oauth2_sso". OpenProject synchronously probes the\n'
        "  host for live Nextcloud reachability/setup-completeness at\n"
        "  confirm=true -- an unreachable or non-Nextcloud host is rejected there.\n"
        "- OneDrive: host must be omitted; tenant_id required (a GUID, or the\n"
        '  literal string "consumers").\n'
        '- Sharepoint: host required, matching "https://<tenant>/sites/<site>";\n'
        "  tenant_id required (same format as OneDrive).\n\n"
        "Creating a OneDrive or Sharepoint storage on a Community Edition instance\n"
        "without an Enterprise token is rejected by OpenProject itself at\n"
        "confirm=true with a clear validation error; Nextcloud is unrestricted.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "name": {"title": "Name", "type": "string"},
            "provider_type": {"title": "Provider Type", "type": "string"},
            "host": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Host"},
            "authentication_method": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Authentication Method",
            },
            "tenant_id": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Tenant Id",
            },
            "drive_id": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Drive Id",
            },
            "confirm": {"default": False, "title": "Confirm", "type": "boolean"},
        },
        "required": ["name", "provider_type"],
        "title": "create_storageArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "name",
        "provider_type",
        "host",
        "authentication_method",
        "tenant_id",
        "drive_id",
        "confirm",
    ]


def test_update_storage_schema() -> None:
    tool = _tools(create_app(_make_settings()))["update_storage"]
    assert tool.description == (
        "Prepare or update an external file storage connection (admin operation).\n\n"
        "Changing host on a Nextcloud storage re-runs OpenProject's live\n"
        "host-reachability/setup-completeness probe at confirm=true.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "storage_id": {"title": "Storage Id", "type": "integer"},
            "name": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Name"},
            "host": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Host"},
            "confirm": {"default": False, "title": "Confirm", "type": "boolean"},
        },
        "required": ["storage_id"],
        "title": "update_storageArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["storage_id", "name", "host", "confirm"]


def test_delete_storage_schema() -> None:
    tool = _tools(create_app(_make_settings()))["delete_storage"]
    assert tool.description == (
        "Prepare or delete an external file storage connection (admin operation).\n\n"
        "Deleting a storage cascades: every project's link to it (project_storages)\n"
        "is deleted along with it, and for a storage with automatically-managed\n"
        "project folders, OpenProject may also issue a remote folder-deletion call\n"
        "against the external storage itself.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "storage_id": {"title": "Storage Id", "type": "integer"},
            "confirm": {"default": False, "title": "Confirm", "type": "boolean"},
        },
        "required": ["storage_id"],
        "title": "delete_storageArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["storage_id", "confirm"]
