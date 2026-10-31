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

from typing import Annotated

from mcp.server.mcpserver import Context
from pydantic import Field

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
from .tool_params import Confirm, Limit, Offset, OptionalProjectRef, ProjectRef, select_field
from .tool_types import IdOrName
from .tools_runtime import _client_from_context, _run_tool, register_tool
from .tools_validation import (
    _validate_limit,
    _validate_offset,
    _validate_optional_project_ref,
    _validate_optional_query,
    _validate_optional_text,
    _validate_positive_int,
    _validate_project_ref,
    _validate_ref,
    _validate_required_ref_list,
    _validate_select,
)


@register_tool
async def list_roles(
    ctx: Context,
    select: Annotated[list[str] | None, select_field(RoleSummary)] = None,
    offset: Offset = 1,
    limit: Limit = None,
) -> RoleListResult:
    """List OpenProject roles visible to the current user."""
    client = _client_from_context(ctx)
    _validate_select(select, row_type=RoleSummary)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(client.role.list_roles(offset=safe_offset, limit=safe_limit))


@register_tool
async def list_actions(
    ctx: Context,
    offset: Offset = 1,
    limit: Limit = None,
    select: Annotated[list[str] | None, select_field(ActionSummary)] = None,
) -> ActionListResult:
    """List the action ids OpenProject's API defines, e.g. "work_packages/create".

    This is the vocabulary only; which user or group may perform an action in which project comes from
    list_capabilities.
    """
    client = _client_from_context(ctx)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    _validate_select(select, row_type=ActionSummary)
    return await _run_tool(client.action_capability.list_actions(offset=safe_offset, limit=safe_limit))


@register_tool
async def list_capabilities(
    ctx: Context,
    project: OptionalProjectRef = None,
    capability_id: str | None = None,
    offset: Offset = 1,
    limit: Limit = None,
    select: Annotated[list[str] | None, select_field(CapabilitySummary)] = None,
) -> CapabilityListResult:
    """List API capabilities exposed by OpenProject.

    At least one of project or capability_id is required; there is no
    unfiltered global listing, since one would bypass the project read
    allowlist.
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
    project: ProjectRef,
    offset: Offset = 1,
    limit: Limit = None,
    select: Annotated[list[str] | None, select_field(MembershipSummary)] = None,
) -> MembershipListResult:
    """List memberships for a project, including principal and role names."""
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    _validate_select(select, row_type=MembershipSummary)
    return await _run_tool(client.membership.list_for_project(safe_project, offset=safe_offset, limit=safe_limit))


@register_tool
async def get_membership(
    ctx: Context,
    membership_id: Annotated[int, Field(description="Membership id, from list_project_memberships.")],
) -> MembershipSummary:
    """Get one project membership by id: the user or group, the project and the role names.

    To list a project's members use list_project_memberships.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(membership_id, field_name="membership_id")
    return await _run_tool(client.membership.get(safe_id))


@register_tool
async def create_membership(
    ctx: Context,
    project: ProjectRef,
    principal: Annotated[
        IdOrName, Field(description='User or group: numeric id, exact name (case-insensitive), or "me".')
    ],
    roles: Annotated[
        list[IdOrName],
        Field(description="At least one; role ids or exact role names (case-insensitive), from list_roles."),
    ],
    notification_message: Annotated[
        str | None, Field(description="Markdown text for OpenProject's membership notification.")
    ] = None,
    confirm: Confirm = False,
) -> MembershipWriteResult:
    """Create a project membership.

    The preview is validated by OpenProject; problems come back in validation_errors."""
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    safe_principal = _validate_ref(principal, field_name="principal", max_length=255)
    safe_roles = _validate_required_ref_list(roles, field_name="roles", max_items=20, item_max_length=100)
    safe_notification_message = _validate_optional_text(
        notification_message, field_name="notification_message", max_length=None
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
    membership_id: Annotated[int, Field(description="Membership id, from list_project_memberships.")],
    roles: Annotated[
        list[IdOrName],
        Field(
            description="Replaces all current roles; role ids or exact role names (case-insensitive), from list_roles."
        ),
    ],
    notification_message: Annotated[
        str | None,
        Field(
            description="Markdown text for OpenProject's membership notification; sent with this change only, "
            "so a blank text is the same as none."
        ),
    ] = None,
    confirm: Confirm = False,
) -> MembershipWriteResult:
    """Update a project membership's roles.

    The preview is validated by OpenProject; problems come back in validation_errors."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(membership_id, field_name="membership_id")
    safe_roles = _validate_required_ref_list(roles, field_name="roles", max_items=20, item_max_length=100)
    safe_notification_message = _validate_optional_text(
        notification_message, field_name="notification_message", max_length=None
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
    membership_id: Annotated[int, Field(description="Membership id, from list_project_memberships.")],
    confirm: Confirm = False,
) -> MembershipWriteResult:
    """Delete a project membership; this cannot be undone.

    Roles inherited from a group stay: if some roles come from a group, only the direct ones are removed;
    if all do, the call is rejected.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(membership_id, field_name="membership_id")
    return await _run_tool(client.membership.delete(membership_id=safe_id, confirm=confirm))


@register_tool
async def get_current_user(ctx: Context) -> CurrentUser:
    """Return the currently authenticated user's profile."""
    client = _client_from_context(ctx)
    return await _run_tool(client.current_user.get_current_user())
