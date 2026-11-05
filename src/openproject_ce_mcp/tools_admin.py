"""Admin domain MCP tool handlers: list_principals, list_users, get_user,
list_groups, get_group, list_storages, get_storage, create_user, update_user,
delete_user, set_user_locked, create_group, update_group, delete_group,
create_storage, update_storage, delete_storage.

Their `@register_tool` decorators come from `tools_runtime`, never from
`tools.py` -- see that module's own docstring for why. `tools.py` imports
this module for the decorator's registration side effect and re-exports all
seventeen names: seven of them (`create_user`, `update_user`, `delete_user`,
`set_user_locked`, `create_group`, `update_group`, `delete_group`) because
existing tests (`tests/unit/test_project_and_domain_tools.py`) import them
directly from `openproject_ce_mcp.tools`; the other ten are re-exported
alongside for consistency.
"""

from __future__ import annotations

from typing import Annotated

from mcp.server.mcpserver import Context
from pydantic import Field

from .models import (
    GroupDetail,
    GroupListResult,
    GroupSummary,
    GroupWriteResult,
    PrincipalListResult,
    PrincipalSummary,
    StorageDetail,
    StorageListResult,
    StorageSummary,
    StorageWriteResult,
    UserDetail,
    UserListResult,
    UserSummary,
    UserWriteResult,
)
from .tool_params import Confirm, Limit, Offset, select_field
from .tool_types import IdOrName
from .tools_runtime import _client_from_context, _run_tool, register_tool
from .tools_validation import (
    _require_at_least_one,
    _validate_limit,
    _validate_list_query_params,
    _validate_offset,
    _validate_optional_query,
    _validate_positive_int,
    _validate_ref,
    _validate_required_query,
    _validate_select,
)


@register_tool
async def list_principals(
    ctx: Context,
    search: str | None = None,
    offset: Offset = 1,
    limit: Limit = None,
    select: Annotated[list[str] | None, select_field(PrincipalSummary)] = None,
) -> PrincipalListResult:
    """List users and groups that can be used for project memberships."""
    client = _client_from_context(ctx)
    safe_search, safe_offset, safe_limit = _validate_list_query_params(search, offset, limit)
    _validate_select(select, row_type=PrincipalSummary)
    return await _run_tool(client.principal.list_principals(search=safe_search, offset=safe_offset, limit=safe_limit))


@register_tool
async def list_users(
    ctx: Context,
    search: str | None = None,
    offset: Offset = 1,
    limit: Limit = None,
    select: Annotated[list[str] | None, select_field(UserSummary)] = None,
) -> UserListResult:
    """List users visible to the current token.

    With search, total is only the count of matching users returned on THIS page, not a full count of all matches;
    the search stops as soon as it has enough, so an exact total would need an extra full walk. Page until
    next_offset is null."""
    client = _client_from_context(ctx)
    safe_search, safe_offset, safe_limit = _validate_list_query_params(search, offset, limit)
    _validate_select(select, row_type=UserSummary)
    return await _run_tool(client.user.list_users(search=safe_search, offset=safe_offset, limit=safe_limit))


@register_tool
async def get_user(
    ctx: Context,
    user: IdOrName,
) -> UserDetail:
    """Get a user by id, login, or `me` when supported by OpenProject."""
    client = _client_from_context(ctx)
    safe_user = _validate_ref(user, field_name="user", max_length=100)
    return await _run_tool(client.user.get_user(safe_user))


@register_tool
async def list_groups(
    ctx: Context,
    search: str | None = None,
    offset: Offset = 1,
    limit: Limit = None,
    select: Annotated[list[str] | None, select_field(GroupSummary)] = None,
) -> GroupListResult:
    """List groups visible to the current token.

    With search, total is only the count of matching groups returned on THIS page, not a full count of all matches;
    the search stops as soon as it has enough, so an exact total would need an extra full walk. Page until
    next_offset is null."""
    client = _client_from_context(ctx)
    safe_search, safe_offset, safe_limit = _validate_list_query_params(search, offset, limit)
    _validate_select(select, row_type=GroupSummary)
    return await _run_tool(client.group.list_groups(search=safe_search, offset=safe_offset, limit=safe_limit))


@register_tool
async def get_group(
    ctx: Context,
    group_id: Annotated[int, Field(description="Group id, from list_groups.")],
) -> GroupDetail:
    """Get a single group by id."""
    client = _client_from_context(ctx)
    safe_group_id = _validate_positive_int(group_id, field_name="group_id")
    return await _run_tool(client.group.get_group(safe_group_id))


@register_tool
async def list_storages(
    ctx: Context,
    select: Annotated[list[str] | None, select_field(StorageSummary)] = None,
    offset: Offset = 1,
    limit: Limit = None,
) -> StorageListResult:
    """List configured OpenProject external file storage connections (Nextcloud/OneDrive/Sharepoint).

    These are the instance-wide connections; list_project_storages lists which projects use them.
    """
    client = _client_from_context(ctx)
    _validate_select(select, row_type=StorageSummary)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(client.storage.list_storages(offset=safe_offset, limit=safe_limit))


@register_tool
async def get_storage(
    ctx: Context,
    storage_id: int,
) -> StorageDetail:
    """Get a single OpenProject external file storage connection by id."""
    client = _client_from_context(ctx)
    safe_storage_id = _validate_positive_int(storage_id, field_name="storage_id")
    return await _run_tool(client.storage.get_storage(safe_storage_id))


@register_tool
async def create_user(
    ctx: Context,
    login: Annotated[str, Field(description="Login name used to sign in.")],
    email: Annotated[str, Field(description="Email address.")],
    firstname: Annotated[str, Field(description="Given name.")],
    lastname: Annotated[str, Field(description="Family name.")],
    password: Annotated[str | None, Field(description="Initial password; not sent when omitted.")] = None,
    admin: Annotated[bool, Field(description="true grants OpenProject administrator rights.")] = False,
    status: Annotated[str, Field(description="Initial account status, checked by OpenProject's user form.")] = "active",
    language: Annotated[str | None, Field(description='Language code such as "en".')] = None,
    confirm: Confirm = False,
) -> UserWriteResult:
    """Create a new user (admin operation).

    The preview is validated by OpenProject; problems come back in validation_errors, each with a message and error_codes (OpenProject's error classes)."""
    client = _client_from_context(ctx)
    safe_login = _validate_required_query(login, field_name="login", max_length=100)
    safe_email = _validate_required_query(email, field_name="email", max_length=255)
    safe_firstname = _validate_required_query(firstname, field_name="firstname", max_length=255)
    safe_lastname = _validate_required_query(lastname, field_name="lastname", max_length=255)
    safe_status = _validate_optional_query(status, field_name="status", max_length=50) or "active"
    safe_language = _validate_optional_query(language, field_name="language", max_length=10)
    return await _run_tool(
        client.user.create(
            login=safe_login,
            email=safe_email,
            firstname=safe_firstname,
            lastname=safe_lastname,
            password=password,
            admin=admin,
            status=safe_status,
            language=safe_language,
            confirm=confirm,
        )
    )


@register_tool
async def update_user(
    ctx: Context,
    user_id: Annotated[int, Field(description="User id, from list_users.")],
    login: Annotated[str | None, Field(description="Login name used to sign in.")] = None,
    email: Annotated[str | None, Field(description="Email address.")] = None,
    firstname: Annotated[str | None, Field(description="Given name.")] = None,
    lastname: Annotated[str | None, Field(description="Family name.")] = None,
    admin: Annotated[bool | None, Field(description="true grants, false revokes administrator rights.")] = None,
    language: Annotated[str | None, Field(description='Language code such as "en".')] = None,
    confirm: Confirm = False,
) -> UserWriteResult:
    """Update an existing user (admin operation).

    Pass at least one field; omitted fields stay unchanged. The preview is
    validated by OpenProject; problems come back in validation_errors, each with a message and error_codes (OpenProject's error classes)."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(user_id, field_name="user_id")
    safe_login = _validate_optional_query(login, field_name="login", max_length=100)
    safe_email = _validate_optional_query(email, field_name="email", max_length=255)
    safe_firstname = _validate_optional_query(firstname, field_name="firstname", max_length=255)
    safe_lastname = _validate_optional_query(lastname, field_name="lastname", max_length=255)
    safe_language = _validate_optional_query(language, field_name="language", max_length=10)
    _require_at_least_one(
        safe_login,
        safe_email,
        safe_firstname,
        safe_lastname,
        admin,
        safe_language,
        message="At least one field must be provided to update.",
    )
    return await _run_tool(
        client.user.update(
            user_id=safe_id,
            login=safe_login,
            email=safe_email,
            firstname=safe_firstname,
            lastname=safe_lastname,
            admin=admin,
            language=safe_language,
            confirm=confirm,
        )
    )


@register_tool
async def delete_user(
    ctx: Context,
    user_id: Annotated[int, Field(description="User id, from list_users.")],
    confirm: Confirm = False,
) -> UserWriteResult:
    """Delete a user (admin operation).

    Runs in the background (OpenProject answers 202): the account is blocked at once, then everything the
    user authored is reassigned to "Deleted user" and their memberships, private queries, notifications and
    tokens are deleted; this cannot be undone. Needs the setting users_deletable_by_admins
    (users_deletable_by_self to delete yourself). 17.1+: the last active admin cannot be deleted.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(user_id, field_name="user_id")
    return await _run_tool(client.user.delete(safe_id, confirm=confirm))


@register_tool
async def set_user_locked(
    ctx: Context,
    user_id: Annotated[int, Field(description="User id, from list_users.")],
    locked: Annotated[bool, Field(description="true locks the account, false unlocks it.")],
    confirm: Confirm = False,
) -> UserWriteResult:
    """Lock or unlock a user account (admin operation).

    A locked user cannot sign in until unlocked; the account and its data stay. To remove the account use
    delete_user.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(user_id, field_name="user_id")
    if locked:
        return await _run_tool(client.user.lock(safe_id, confirm=confirm))
    return await _run_tool(client.user.unlock(safe_id, confirm=confirm))


@register_tool
async def create_group(
    ctx: Context,
    name: Annotated[str, Field(description="Group display name.")],
    user_ids: Annotated[
        list[int] | None, Field(description="User ids to add as initial members; omit for an empty group.")
    ] = None,
    confirm: Confirm = False,
) -> GroupWriteResult:
    """Create a new group (admin operation).

    The preview makes no request to OpenProject, so OpenProject's own checks run only on confirm. To give the
    group roles in a project use create_membership with the group as principal; change its members later with
    update_group.
    """
    client = _client_from_context(ctx)
    safe_name = _validate_required_query(name, field_name="name", max_length=255)
    return await _run_tool(client.group.create(name=safe_name, user_ids=user_ids, confirm=confirm))


@register_tool
async def update_group(
    ctx: Context,
    group_id: Annotated[int, Field(description="Group id, from list_groups.")],
    name: Annotated[str | None, Field(description="New group display name; omit to keep it.")] = None,
    add_user_ids: Annotated[list[int] | None, Field(description="User ids to add; other current members stay.")] = None,
    remove_user_ids: Annotated[
        list[int] | None, Field(description="User ids to remove; wins over add_user_ids.")
    ] = None,
    confirm: Confirm = False,
) -> GroupWriteResult:
    """Update an existing group (admin operation). Pass at least one of name, add_user_ids, remove_user_ids."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(group_id, field_name="group_id")
    safe_name = _validate_optional_query(name, field_name="name", max_length=255)
    _require_at_least_one(
        safe_name, add_user_ids, remove_user_ids, message="At least one field must be provided to update."
    )
    return await _run_tool(
        client.group.update(
            safe_id, name=safe_name, add_user_ids=add_user_ids, remove_user_ids=remove_user_ids, confirm=confirm
        )
    )


@register_tool
async def delete_group(
    ctx: Context,
    group_id: Annotated[int, Field(description="Group id, from list_groups.")],
    confirm: Confirm = False,
) -> GroupWriteResult:
    """Delete a group (admin operation).

    Runs in the background (OpenProject answers 202). Members lose the roles they had only through the group;
    work packages assigned to the group go to "Deleted user"; this cannot be undone. 17.7+: groups synchronised
    from LDAP are rejected.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(group_id, field_name="group_id")
    return await _run_tool(client.group.delete(safe_id, confirm=confirm))


@register_tool
async def create_storage(
    ctx: Context,
    name: str,
    provider_type: str,
    host: str | None = None,
    authentication_method: str | None = None,
    tenant_id: str | None = None,
    drive_id: str | None = None,
    confirm: Confirm = False,
) -> StorageWriteResult:
    """Create an external file storage connection (admin operation).

    provider_type must be one of "Nextcloud", "OneDrive", "Sharepoint". Field
    requirements differ genuinely by provider, per OpenProject's own
    validation (only the values of provider_type and authentication_method are
    pre-checked here):
    - Nextcloud: host required; authentication_method required, one of
      "two_way_oauth2" or "oauth2_sso". OpenProject synchronously probes the
      host for live Nextcloud reachability/setup-completeness at
      confirm=true -- an unreachable or non-Nextcloud host is rejected there.
    - OneDrive: host must be omitted; tenant_id required (a GUID, or the
      literal string "consumers").
    - Sharepoint: host required, matching "https://<tenant>/sites/<site>";
      tenant_id required (same format as OneDrive).

    Creating a OneDrive or Sharepoint storage on a Community Edition instance
    without an Enterprise token is rejected by OpenProject itself at
    confirm=true with a clear validation error; Nextcloud is unrestricted.
    """
    client = _client_from_context(ctx)
    safe_name = _validate_required_query(name, field_name="name", max_length=255)
    safe_provider_type = _validate_required_query(provider_type, field_name="provider_type", max_length=100)
    safe_host = _validate_optional_query(host, field_name="host", max_length=255)
    safe_authentication_method = _validate_optional_query(
        authentication_method, field_name="authentication_method", max_length=100
    )
    safe_tenant_id = _validate_optional_query(tenant_id, field_name="tenant_id", max_length=100)
    safe_drive_id = _validate_optional_query(drive_id, field_name="drive_id", max_length=255)
    return await _run_tool(
        client.storage.create(
            name=safe_name,
            provider_type=safe_provider_type,
            host=safe_host,
            authentication_method=safe_authentication_method,
            tenant_id=safe_tenant_id,
            drive_id=safe_drive_id,
            confirm=confirm,
        )
    )


@register_tool
async def update_storage(
    ctx: Context,
    storage_id: Annotated[int, Field(description="Storage id, from list_storages.")],
    name: Annotated[str | None, Field(description="New display name; omit to keep it.")] = None,
    host: Annotated[
        str | None,
        Field(
            description=(
                "New host URL; on Nextcloud, confirm=true re-runs OpenProject's live reachability/setup probe."
            )
        ),
    ] = None,
    confirm: Confirm = False,
) -> StorageWriteResult:
    """Update an external file storage connection (admin operation).

    Pass at least one of name or host. The preview returns the current storage as result.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(storage_id, field_name="storage_id")
    safe_name = _validate_optional_query(name, field_name="name", max_length=255)
    safe_host = _validate_optional_query(host, field_name="host", max_length=255)
    _require_at_least_one(safe_name, safe_host, message="At least one field must be provided to update.")
    return await _run_tool(client.storage.update(storage_id=safe_id, name=safe_name, host=safe_host, confirm=confirm))


@register_tool
async def delete_storage(
    ctx: Context,
    storage_id: int,
    confirm: Confirm = False,
) -> StorageWriteResult:
    """Delete an external file storage connection (admin operation); this cannot be undone.

    Deleting a storage cascades: every project's link to it and the work
    packages' file links to it are deleted, and for each project link whose
    folders are managed automatically, OpenProject also tries to delete that
    project folder and its files in the external storage during the request.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(storage_id, field_name="storage_id")
    return await _run_tool(client.storage.delete(safe_id, confirm=confirm))
