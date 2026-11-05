"""Personal domain MCP tool handlers: list_notifications,
mark_notifications_read, get_my_preferences, update_my_preferences.

Their `@register_tool` decorators come from `tools_runtime`, never from
`tools.py` -- see that module's own docstring for why. `tools.py` imports
this module for the decorator's registration side effect and re-exports all
four names: `list_notifications` and `mark_notifications_read` because
existing tests (`tests/unit/test_project_and_domain_tools.py`) import them
directly from `openproject_ce_mcp.tools`; the other two are re-exported
alongside for consistency.
"""

from __future__ import annotations

from typing import Annotated

from mcp.server.mcpserver import Context
from pydantic import Field

from .models import (
    NotificationListResult,
    NotificationMarkResult,
    NotificationSummary,
    UserPreferences,
    UserPreferencesWriteResult,
)
from .tool_params import Confirm, Limit, Offset, select_field
from .tools_runtime import _client_from_context, _run_tool, register_tool
from .tools_validation import (
    _validate_limit,
    _validate_offset,
    _validate_positive_int,
    _validate_select,
)


@register_tool
async def list_notifications(
    ctx: Context,
    unread_only: Annotated[bool, Field(description="true returns only notifications not yet read.")] = False,
    limit: Limit = None,
    offset: Offset = 1,
    select: Annotated[list[str] | None, select_field(NotificationSummary)] = None,
) -> NotificationListResult:
    """List in-app notifications for the current user.

    Reading them does not mark them read.
    """
    client = _client_from_context(ctx)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    _validate_select(select, row_type=NotificationSummary)
    return await _run_tool(client.notification.list_all(unread_only=unread_only, limit=safe_limit, offset=safe_offset))


@register_tool
async def mark_notifications_read(
    ctx: Context, notification_id: int | None = None, confirm: Confirm = False
) -> NotificationMarkResult:
    """Mark a single notification, or all unread notifications, as read.

    notification_id: mark just this notification read. Omit it (default) to
    mark every currently unread notification read instead.
    Under a restricted OPENPROJECT_READ_PROJECTS, a notification about a
    project outside it is refused (in the preview too), and omitting
    notification_id marks only notifications about the projects it covers.
    """
    client = _client_from_context(ctx)
    if notification_id is None:
        return await _run_tool(client.notification.mark_all_read(confirm=confirm))
    safe_id = _validate_positive_int(notification_id, field_name="notification_id")
    return await _run_tool(client.notification.mark_read(safe_id, confirm=confirm))


@register_tool
async def get_my_preferences(ctx: Context) -> UserPreferences:
    """Return the current user's OpenProject preferences (timezone, sorting, popups, …).

    Note: language is a User attribute, not a preference, so it is not set here.
    """
    client = _client_from_context(ctx)
    return await _run_tool(client.user_preferences.get())


@register_tool
async def update_my_preferences(
    ctx: Context,
    time_zone: Annotated[str | None, Field(description='Time zone name, e.g. "Europe/Berlin".')] = None,
    comment_sort_descending: Annotated[bool | None, Field(description="true shows comments newest first.")] = None,
    warn_on_leaving_unsaved: Annotated[
        bool | None, Field(description="true warns before leaving a page with unsaved changes.")
    ] = None,
    auto_hide_popups: Annotated[bool | None, Field(description="true makes popups close automatically.")] = None,
    confirm: Confirm = False,
) -> UserPreferencesWriteResult:
    """Update the current user's preferences; omitted fields stay unchanged.

    Note: language is a User attribute, not a preference, so it is not set here.
    """
    client = _client_from_context(ctx)
    return await _run_tool(
        client.user_preferences.update(
            time_zone=time_zone,
            comment_sort_descending=comment_sort_descending,
            warn_on_leaving_unsaved=warn_on_leaving_unsaved,
            auto_hide_popups=auto_hide_popups,
            confirm=confirm,
        )
    )
