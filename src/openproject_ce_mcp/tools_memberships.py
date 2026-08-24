"""Membership domain MCP tool handlers: list_roles, list_actions,
list_capabilities, list_project_memberships, get_membership, create_membership,
update_membership, delete_membership, get_current_user.

Their `@register_tool` decorators come from `tools_runtime`, never from
`tools.py` -- see that module's own docstring for why. `tools.py` imports
this module for the decorator's registration side effect and re-exports all
nine names: four of them (`list_actions`, `list_capabilities`, `list_roles`,
`list_project_memberships`) because existing tests (`test_trimming.py`,
`tests/unit/test_project_and_domain_tools.py`) import them directly from
`openproject_ce_mcp.tools`; the other five are re-exported alongside for
consistency.
"""

from __future__ import annotations

from mcp.server.mcpserver import Context

from .models import (
    ActionListResult,
    ActionSummary,
    CapabilityListResult,
    CapabilitySummary,
    CurrentUser,
    MembershipListResult,
    MembershipSummary,
    MembershipWriteResult,
    RoleListResult,
    RoleSummary,
)
from .tools_runtime import _client_from_context, _run_tool, register_tool
from .tools_validation import (
    _validate_limit,
    _validate_offset,
    _validate_optional_project_ref,
    _validate_optional_query,
    _validate_optional_text,
    _validate_positive_int,
    _validate_project_ref,
    _validate_required_query,
    _validate_required_string_list,
    _validate_select,
)


@register_tool
async def list_roles(
    ctx: Context,
    select: list[str] | None = None,
    offset: int = 1,
    limit: int | None = None,
) -> RoleListResult:
    """List OpenProject roles visible to the current user.

    select fields: id, name (see server instructions for select's general semantics).
    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap.
    """
    client = _client_from_context(ctx)
    _validate_select(select, row_type=RoleSummary)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(client.role.list_roles(offset=safe_offset, limit=safe_limit))


@register_tool
async def list_actions(
    ctx: Context,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
) -> ActionListResult:
    """List API actions exposed by OpenProject.

    select fields: id, url (see server instructions for select's general semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap.
    """
    client = _client_from_context(ctx)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    _validate_select(select, row_type=ActionSummary)
    return await _run_tool(client.action_capability.list_actions(offset=safe_offset, limit=safe_limit))


@register_tool
async def list_capabilities(
    ctx: Context,
    project: str | None = None,
    capability_id: str | None = None,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
) -> CapabilityListResult:
    """List API capabilities exposed by OpenProject.

    At least one of project or capability_id is required — there is no
    unfiltered global listing, since one would bypass the project read
    allowlist.

    select fields: id, action_id, context (see server instructions for
    select's general semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_optional_project_ref(project)
    safe_capability_id = _validate_optional_query(capability_id, field_name="capability_id", max_length=100)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    _validate_select(select, row_type=CapabilitySummary)
    return await _run_tool(
        client.action_capability.list_capabilities(
            project=safe_project,
            capability_id=safe_capability_id,
            offset=safe_offset,
            limit=safe_limit,
        )
    )


@register_tool
async def list_project_memberships(
    ctx: Context,
    project: str,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
) -> MembershipListResult:
    """List memberships for a project, including principal and role names.

    select fields: id, principal_name, role_names (see server instructions for
    select's general semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    _validate_select(select, row_type=MembershipSummary)
    return await _run_tool(client.membership.list_for_project(safe_project, offset=safe_offset, limit=safe_limit))


@register_tool
async def get_membership(
    ctx: Context,
    membership_id: int,
) -> MembershipSummary:
    """Get a compact membership summary by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(membership_id, field_name="membership_id")
    return await _run_tool(client.membership.get(safe_id))


@register_tool
async def create_membership(
    ctx: Context,
    project: str,
    principal: str,
    roles: list[str],
    notification_message: str | None = None,
    confirm: bool = False,
) -> MembershipWriteResult:
    """Prepare or create a project membership."""
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    safe_principal = _validate_required_query(principal, field_name="principal", max_length=255)
    safe_roles = _validate_required_string_list(roles, field_name="roles", max_items=20, item_max_length=100)
    safe_notification_message = _validate_optional_text(
        notification_message, field_name="notification_message", max_length=10_000
    )
    return await _run_tool(
        client.membership.create(
            project=safe_project,
            principal=safe_principal,
            roles=safe_roles,
            notification_message=safe_notification_message,
            confirm=confirm,
        )
    )


@register_tool
async def update_membership(
    ctx: Context,
    membership_id: int,
    roles: list[str],
    notification_message: str | None = None,
    confirm: bool = False,
) -> MembershipWriteResult:
    """Prepare or update a project membership."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(membership_id, field_name="membership_id")
    safe_roles = _validate_required_string_list(roles, field_name="roles", max_items=20, item_max_length=100)
    safe_notification_message = _validate_optional_text(
        notification_message, field_name="notification_message", max_length=10_000
    )
    return await _run_tool(
        client.membership.update(
            membership_id=safe_id,
            roles=safe_roles,
            notification_message=safe_notification_message,
            confirm=confirm,
        )
    )


@register_tool
async def delete_membership(
    ctx: Context,
    membership_id: int,
    confirm: bool = False,
) -> MembershipWriteResult:
    """Prepare or delete a project membership."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(membership_id, field_name="membership_id")
    return await _run_tool(client.membership.delete(membership_id=safe_id, confirm=confirm))


@register_tool
async def get_current_user(ctx: Context) -> CurrentUser:
    """Return the currently authenticated user's profile."""
    client = _client_from_context(ctx)
    return await _run_tool(client.current_user.get_current_user())
