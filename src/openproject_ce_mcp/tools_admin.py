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

from mcp.server.mcpserver import Context

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
from .tools_runtime import _client_from_context, _run_tool, register_tool
from .tools_validation import (
    _require_at_least_one,
    _validate_limit,
    _validate_list_query_params,
    _validate_offset,
    _validate_optional_query,
    _validate_positive_int,
    _validate_required_query,
    _validate_select,
)


@register_tool
async def list_principals(
    ctx: Context,
    search: str | None = None,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
) -> PrincipalListResult:
    """List users and groups that can be used for project memberships.

    select fields: id, name, type (see server instructions for select's general semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap.
    """
    client = _client_from_context(ctx)
    safe_search, safe_offset, safe_limit = _validate_list_query_params(search, offset, limit)
    _validate_select(select, row_type=PrincipalSummary)
    return await _run_tool(client.list_principals(search=safe_search, offset=safe_offset, limit=safe_limit))


@register_tool
async def list_users(
    ctx: Context,
    search: str | None = None,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
) -> UserListResult:
    """List users visible to the current token.

    select fields: id, name, login, email, status, admin, created_at, updated_at
    (see server instructions for select's general semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap. With search,
    total is only the count of matching users returned on THIS page, not a
    full count of all matches — the search stops as soon as it has enough,
    so an exact total would need an extra full walk. Page until next_offset
    is null.
    """
    client = _client_from_context(ctx)
    safe_search, safe_offset, safe_limit = _validate_list_query_params(search, offset, limit)
    _validate_select(select, row_type=UserSummary)
    return await _run_tool(client.list_users(search=safe_search, offset=safe_offset, limit=safe_limit))


@register_tool
async def get_user(
    ctx: Context,
    user: str,
) -> UserDetail:
    """Get a user by id, login, or `me` when supported by OpenProject."""
    client = _client_from_context(ctx)
    safe_user = _validate_required_query(user, field_name="user", max_length=100)
    return await _run_tool(client.get_user(safe_user))


@register_tool
async def list_groups(
    ctx: Context,
    search: str | None = None,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
) -> GroupListResult:
    """List groups visible to the current token.

    select fields: id, name (see server instructions for select's general semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap. With search,
    total is only the count of matching groups returned on THIS page, not a
    full count of all matches — the search stops as soon as it has enough,
    so an exact total would need an extra full walk. Page until next_offset
    is null.
    """
    client = _client_from_context(ctx)
    safe_search, safe_offset, safe_limit = _validate_list_query_params(search, offset, limit)
    _validate_select(select, row_type=GroupSummary)
    return await _run_tool(client.list_groups(search=safe_search, offset=safe_offset, limit=safe_limit))


@register_tool
async def get_group(
    ctx: Context,
    group_id: int,
) -> GroupDetail:
    """Get a single group by id."""
    client = _client_from_context(ctx)
    safe_group_id = _validate_positive_int(group_id, field_name="group_id")
    return await _run_tool(client.get_group(safe_group_id))


@register_tool
async def list_storages(
    ctx: Context,
    select: list[str] | None = None,
    offset: int = 1,
    limit: int | None = None,
) -> StorageListResult:
    """List configured OpenProject external file storage connections (Nextcloud/OneDrive/Sharepoint).

    select fields: id, name, provider_type, host, configured, created_at, updated_at
    (see server instructions for select's general semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap.
    """
    client = _client_from_context(ctx)
    _validate_select(select, row_type=StorageSummary)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(client.list_storages(offset=safe_offset, limit=safe_limit))


@register_tool
async def get_storage(
    ctx: Context,
    storage_id: int,
) -> StorageDetail:
    """Get a single OpenProject external file storage connection by id."""
    client = _client_from_context(ctx)
    safe_storage_id = _validate_positive_int(storage_id, field_name="storage_id")
    return await _run_tool(client.get_storage(safe_storage_id))


@register_tool
async def create_user(
    ctx: Context,
    login: str,
    email: str,
    firstname: str,
    lastname: str,
    password: str | None = None,
    admin: bool = False,
    status: str = "active",
    language: str | None = None,
    confirm: bool = False,
) -> UserWriteResult:
    """Prepare or create a new user (admin operation)."""
    client = _client_from_context(ctx)
    safe_login = _validate_required_query(login, field_name="login", max_length=100)
    safe_email = _validate_required_query(email, field_name="email", max_length=255)
    safe_firstname = _validate_required_query(firstname, field_name="firstname", max_length=255)
    safe_lastname = _validate_required_query(lastname, field_name="lastname", max_length=255)
    safe_status = _validate_optional_query(status, field_name="status", max_length=50) or "active"
    safe_language = _validate_optional_query(language, field_name="language", max_length=10)
    return await _run_tool(
        client.create_user(
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
    user_id: int,
    login: str | None = None,
    email: str | None = None,
    firstname: str | None = None,
    lastname: str | None = None,
    admin: bool | None = None,
    language: str | None = None,
    confirm: bool = False,
) -> UserWriteResult:
    """Prepare or update an existing user (admin operation)."""
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
        client.update_user(
            safe_id,
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
    user_id: int,
    confirm: bool = False,
) -> UserWriteResult:
    """Prepare or delete a user (admin operation)."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(user_id, field_name="user_id")
    return await _run_tool(client.delete_user(safe_id, confirm=confirm))


@register_tool
async def set_user_locked(
    ctx: Context,
    user_id: int,
    locked: bool,
    confirm: bool = False,
) -> UserWriteResult:
    """Prepare or lock/unlock a user account (admin operation).

    locked=true locks the account; locked=false unlocks it. Preview/confirm
    behavior is identical either way.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(user_id, field_name="user_id")
    if locked:
        return await _run_tool(client.lock_user(safe_id, confirm=confirm))
    return await _run_tool(client.unlock_user(safe_id, confirm=confirm))


@register_tool
async def create_group(
    ctx: Context,
    name: str,
    user_ids: list[int] | None = None,
    confirm: bool = False,
) -> GroupWriteResult:
    """Prepare or create a new group (admin operation)."""
    client = _client_from_context(ctx)
    safe_name = _validate_required_query(name, field_name="name", max_length=255)
    return await _run_tool(client.create_group(name=safe_name, user_ids=user_ids, confirm=confirm))


@register_tool
async def update_group(
    ctx: Context,
    group_id: int,
    name: str | None = None,
    add_user_ids: list[int] | None = None,
    remove_user_ids: list[int] | None = None,
    confirm: bool = False,
) -> GroupWriteResult:
    """Prepare or update an existing group (admin operation)."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(group_id, field_name="group_id")
    safe_name = _validate_optional_query(name, field_name="name", max_length=255)
    _require_at_least_one(
        safe_name, add_user_ids, remove_user_ids, message="At least one field must be provided to update."
    )
    return await _run_tool(
        client.update_group(
            safe_id, name=safe_name, add_user_ids=add_user_ids, remove_user_ids=remove_user_ids, confirm=confirm
        )
    )


@register_tool
async def delete_group(
    ctx: Context,
    group_id: int,
    confirm: bool = False,
) -> GroupWriteResult:
    """Prepare or delete a group (admin operation)."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(group_id, field_name="group_id")
    return await _run_tool(client.delete_group(safe_id, confirm=confirm))


@register_tool
async def create_storage(
    ctx: Context,
    name: str,
    provider_type: str,
    host: str | None = None,
    authentication_method: str | None = None,
    tenant_id: str | None = None,
    drive_id: str | None = None,
    confirm: bool = False,
) -> StorageWriteResult:
    """Prepare or create an external file storage connection (admin operation).

    provider_type must be one of "Nextcloud", "OneDrive", "Sharepoint". Field
    requirements differ genuinely by provider, per OpenProject's own
    validation (not pre-checked here beyond provider_type itself):
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
        client.create_storage(
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
    storage_id: int,
    name: str | None = None,
    host: str | None = None,
    confirm: bool = False,
) -> StorageWriteResult:
    """Prepare or update an external file storage connection (admin operation).

    Changing host on a Nextcloud storage re-runs OpenProject's live
    host-reachability/setup-completeness probe at confirm=true.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(storage_id, field_name="storage_id")
    safe_name = _validate_optional_query(name, field_name="name", max_length=255)
    safe_host = _validate_optional_query(host, field_name="host", max_length=255)
    _require_at_least_one(safe_name, safe_host, message="At least one field must be provided to update.")
    return await _run_tool(client.update_storage(storage_id=safe_id, name=safe_name, host=safe_host, confirm=confirm))


@register_tool
async def delete_storage(
    ctx: Context,
    storage_id: int,
    confirm: bool = False,
) -> StorageWriteResult:
    """Prepare or delete an external file storage connection (admin operation).

    Deleting a storage cascades: every project's link to it (project_storages)
    is deleted along with it, and for a storage with automatically-managed
    project folders, OpenProject may also issue a remote folder-deletion call
    against the external storage itself.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(storage_id, field_name="storage_id")
    return await _run_tool(client.delete_storage(safe_id, confirm=confirm))
