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
    assert tool.description == ("List users and groups that can be used for project memberships.")
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
                "description": "Fields to return; a requested unset field comes back as null. Allowed: email, id, name, type.",
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
        "List users visible to the current token.\n"
        "\n"
        "With search, total is only the count of matching users returned on THIS page, not a full count of all matches;\n"
        "the search stops as soon as it has enough, so an exact total would need an extra full walk. Page until\n"
        "next_offset is null."
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
                "description": "Fields to return; a requested unset field comes back as null. Allowed: admin, avatar_url, created_at, email, firstname, id, lastname, locked, login, name, status, updated_at.",
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
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {"user": {"anyOf": [{"type": "integer"}, {"type": "string"}], "title": "User"}},
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
        "List groups visible to the current token.\n"
        "\n"
        "With search, total is only the count of matching groups returned on THIS page, not a full count of all matches;\n"
        "the search stops as soon as it has enough, so an exact total would need an extra full walk. Page until\n"
        "next_offset is null."
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
                "description": "Fields to return; a requested unset field comes back as null. Allowed: can_delete, can_update, created_at, id, member_count, name, updated_at.",
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
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "group_id": {"description": "Group id, from list_groups.", "title": "Group Id", "type": "integer"}
        },
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
        "List configured OpenProject external file storage connections (Nextcloud/OneDrive/Sharepoint).\n\nThese are the instance-wide connections; list_project_storages lists which projects use them.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "select": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "description": "Fields to return; a requested unset field comes back as null. Allowed: configured, created_at, drive_id, forbidden_file_name_characters, has_application_password, host, id, name, provider_type, tenant_id, updated_at.",
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
        "title": "list_storagesArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["select", "offset", "limit"]


def test_get_storage_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_storage"]
    assert tool.description == "Get a single OpenProject external file storage connection by id."
    assert tool.output_schema is None
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
    assert (
        tool.description
        == "Create a new user (admin operation).\n\nThe preview is validated by OpenProject; problems come back in validation_errors."
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "login": {"description": "Login name used to sign in.", "title": "Login", "type": "string"},
            "email": {"description": "Email address.", "title": "Email", "type": "string"},
            "firstname": {"description": "Given name.", "title": "Firstname", "type": "string"},
            "lastname": {"description": "Family name.", "title": "Lastname", "type": "string"},
            "password": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Initial password; not sent when omitted.",
                "title": "Password",
            },
            "admin": {
                "default": False,
                "description": "true grants OpenProject administrator rights.",
                "title": "Admin",
                "type": "boolean",
            },
            "status": {
                "default": "active",
                "description": "Initial account status, checked by OpenProject's user form.",
                "title": "Status",
                "type": "string",
            },
            "language": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": 'Language code such as "en".',
                "title": "Language",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
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
    assert (
        tool.description
        == "Update an existing user (admin operation).\n\nPass at least one field; omitted fields stay unchanged. The preview is\nvalidated by OpenProject; problems come back in validation_errors."
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "user_id": {"description": "User id, from list_users.", "title": "User Id", "type": "integer"},
            "login": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Login name used to sign in.",
                "title": "Login",
            },
            "email": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Email address.",
                "title": "Email",
            },
            "firstname": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Given name.",
                "title": "Firstname",
            },
            "lastname": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Family name.",
                "title": "Lastname",
            },
            "admin": {
                "anyOf": [{"type": "boolean"}, {"type": "null"}],
                "default": None,
                "description": "true grants, false revokes administrator rights.",
                "title": "Admin",
            },
            "language": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": 'Language code such as "en".',
                "title": "Language",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
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
    assert (
        tool.description
        == 'Delete a user (admin operation).\n\nRuns in the background (OpenProject answers 202): the account is blocked at once, then everything the\nuser authored is reassigned to "Deleted user" and their memberships, private queries, notifications and\ntokens are deleted; this cannot be undone. Needs the setting users_deletable_by_admins\n(users_deletable_by_self to delete yourself). 17.1+: the last active admin cannot be deleted.\n'
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "user_id": {"description": "User id, from list_users.", "title": "User Id", "type": "integer"},
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
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
        "Lock or unlock a user account (admin operation).\n\nA locked user cannot sign in until unlocked; the account and its data stay. To remove the account use\ndelete_user.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "user_id": {"description": "User id, from list_users.", "title": "User Id", "type": "integer"},
            "locked": {
                "description": "true locks the account, false unlocks it.",
                "title": "Locked",
                "type": "boolean",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
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
    assert (
        tool.description
        == "Create a new group (admin operation).\n\nThe preview makes no request to OpenProject, so OpenProject's own checks run only on confirm. To give the\ngroup roles in a project use create_membership with the group as principal; change its members later with\nupdate_group.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "name": {"description": "Group display name.", "title": "Name", "type": "string"},
            "user_ids": {
                "anyOf": [{"items": {"type": "integer"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "description": "User ids to add as initial members; omit for an empty group.",
                "title": "User Ids",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
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
    assert (
        tool.description
        == "Update an existing group (admin operation). Pass at least one of name, add_user_ids, remove_user_ids."
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "group_id": {"description": "Group id, from list_groups.", "title": "Group Id", "type": "integer"},
            "name": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "New group display name; omit to keep it.",
                "title": "Name",
            },
            "add_user_ids": {
                "anyOf": [{"items": {"type": "integer"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "description": "User ids to add; other current members stay.",
                "title": "Add User Ids",
            },
            "remove_user_ids": {
                "anyOf": [{"items": {"type": "integer"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "description": "User ids to remove; wins over add_user_ids.",
                "title": "Remove User Ids",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
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
    assert (
        tool.description
        == 'Delete a group (admin operation).\n\nRuns in the background (OpenProject answers 202). Members lose the roles they had only through the group;\nwork packages assigned to the group go to "Deleted user"; this cannot be undone. 17.7+: groups synchronised\nfrom LDAP are rejected.\n'
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "group_id": {"description": "Group id, from list_groups.", "title": "Group Id", "type": "integer"},
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
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
        "Create an external file storage connection (admin operation).\n"
        "\n"
        'provider_type must be one of "Nextcloud", "OneDrive", "Sharepoint". Field\n'
        "requirements differ genuinely by provider, per OpenProject's own\n"
        "validation (only the values of provider_type and authentication_method are\n"
        "pre-checked here):\n"
        "- Nextcloud: host required; authentication_method required, one of\n"
        '  "two_way_oauth2" or "oauth2_sso". OpenProject synchronously probes the\n'
        "  host for live Nextcloud reachability/setup-completeness at\n"
        "  confirm=true -- an unreachable or non-Nextcloud host is rejected there.\n"
        "- OneDrive: host must be omitted; tenant_id required (a GUID, or the\n"
        '  literal string "consumers").\n'
        '- Sharepoint: host required, matching "https://<tenant>/sites/<site>";\n'
        "  tenant_id required (same format as OneDrive).\n"
        "\n"
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
            "tenant_id": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Tenant Id"},
            "drive_id": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Drive Id"},
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
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
        "Update an external file storage connection (admin operation).\n"
        "\n"
        "Pass at least one of name or host. The preview returns the current storage as result.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "storage_id": {"description": "Storage id, from list_storages.", "title": "Storage Id", "type": "integer"},
            "name": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "New display name; omit to keep it.",
                "title": "Name",
            },
            "host": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "New host URL; on Nextcloud, confirm=true re-runs OpenProject's live reachability/setup probe.",
                "title": "Host",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
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
        "Delete an external file storage connection (admin operation); this cannot be undone.\n"
        "\n"
        "Deleting a storage cascades: every project's link to it and the work\n"
        "packages' file links to it are deleted, and for each project link whose\n"
        "folders are managed automatically, OpenProject also tries to delete that\n"
        "project folder and its files in the external storage during the request.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "storage_id": {"title": "Storage Id", "type": "integer"},
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["storage_id"],
        "title": "delete_storageArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["storage_id", "confirm"]
