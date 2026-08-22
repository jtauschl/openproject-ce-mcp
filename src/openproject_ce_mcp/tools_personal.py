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

from mcp.server.mcpserver import Context

from .models import (
    NotificationListResult,
    NotificationMarkResult,
    NotificationSummary,
    UserPreferences,
    UserPreferencesWriteResult,
)
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
    unread_only: bool = False,
    limit: int | None = None,
    offset: int = 1,
    select: list[str] | None = None,
) -> NotificationListResult:
    """List in-app notifications for the current user.

    select fields: id, subject, reason, read, work_package_id (see server
    instructions for select's general semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap.
    """
    client = _client_from_context(ctx)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    _validate_select(select, row_type=NotificationSummary)
    return await _run_tool(client.list_notifications(unread_only=unread_only, limit=safe_limit, offset=safe_offset))


@register_tool
async def mark_notifications_read(
    ctx: Context, notification_id: int | None = None, confirm: bool = False
) -> NotificationMarkResult:
    """Mark a single notification, or all unread notifications, as read.

    notification_id: mark just this notification read. Omit it (default) to
    mark every currently unread notification read instead.
    Set confirm=true to write, or call without confirm=true first for a preview.
    """
    client = _client_from_context(ctx)
    if notification_id is None:
        return await _run_tool(client.mark_all_notifications_read(confirm=confirm))
    safe_id = _validate_positive_int(notification_id, field_name="notification_id")
    return await _run_tool(client.mark_notification_read(safe_id, confirm=confirm))


@register_tool
async def get_my_preferences(ctx: Context) -> UserPreferences:
    """Return the current user's OpenProject preferences (timezone, sorting, popups, …).

    Note: language is a User attribute, not a preference -- use update_user's
    "language" field to change it.
    """
    client = _client_from_context(ctx)
    return await _run_tool(client.get_my_preferences())


@register_tool
async def update_my_preferences(
    ctx: Context,
    time_zone: str | None = None,
    comment_sort_descending: bool | None = None,
    warn_on_leaving_unsaved: bool | None = None,
    auto_hide_popups: bool | None = None,
    confirm: bool = False,
) -> UserPreferencesWriteResult:
    """Prepare or update the current user's preferences (timezone, comment sort order, popups, …).
    Set confirm=true to write.

    Note: language is a User attribute, not a preference -- use update_user's
    "language" field to change it.
    """
    client = _client_from_context(ctx)
    return await _run_tool(
        client.update_my_preferences(
            time_zone=time_zone,
            comment_sort_descending=comment_sort_descending,
            warn_on_leaving_unsaved=warn_on_leaving_unsaved,
            auto_hide_popups=auto_hide_popups,
            confirm=confirm,
        )
    )
