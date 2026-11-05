"""Reminders domain MCP tool handlers: list_reminders, create_work_package_reminder,
update_reminder, delete_reminder.

Their `@register_tool` decorators come from `tools_runtime`, never from
`tools.py` -- see that module's own docstring for why. `tools.py` imports
this module for the decorator's registration side effect and, for now,
re-exports these four names so existing test imports keep working unchanged
(a deliberate, temporary transition step, not the long-term shape).
"""

from __future__ import annotations

from typing import Annotated

from mcp.server.mcpserver import Context
from pydantic import Field

from .models import ReminderListResult, ReminderSummary, ReminderWriteResult
from .tool_params import Confirm, ExpectDisplayId, WorkPackageRef, select_field
from .tools_runtime import _client_from_context, _run_tool, register_tool
from .tools_validation import (
    _validate_expect_display_id,
    _validate_optional_datetime,
    _validate_optional_text,
    _validate_optional_update_text,
    _validate_positive_int,
    _validate_required_datetime,
    _validate_select,
    _validate_work_package_ref,
)


@register_tool
async def list_reminders(
    ctx: Context, select: Annotated[list[str] | None, select_field(ReminderSummary)] = None
) -> ReminderListResult:
    """List the current user's active reminders across all work packages. Requires OpenProject 16.1+."""
    client = _client_from_context(ctx)
    _validate_select(select, row_type=ReminderSummary)
    return await _run_tool(client.reminder.list_all())


@register_tool
async def create_work_package_reminder(
    ctx: Context,
    work_package_id: WorkPackageRef,
    remind_at: str,
    note: str | None = None,
    expect_display_id: ExpectDisplayId = None,
    confirm: Confirm = False,
) -> ReminderWriteResult:
    """Create a reminder on a work package.

    `remind_at` is an ISO 8601 date-time (e.g. 2026-12-01T09:00:00Z). Only one
    active reminder per work package is allowed; creating a second one fails.
    Requires OpenProject 16.1+.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    safe_expect = _validate_expect_display_id(expect_display_id)
    safe_remind_at = _validate_required_datetime(remind_at, field_name="remind_at")
    safe_note = _validate_optional_text(note, field_name="note", max_length=2000, wrapped_on_read=True)
    return await _run_tool(
        client.reminder.create(
            work_package_id=safe_id,
            remind_at=safe_remind_at,
            note=safe_note,
            expect_display_id=safe_expect,
            confirm=confirm,
        )
    )


@register_tool
async def update_reminder(
    ctx: Context,
    reminder_id: Annotated[int, Field(description="Reminder id, from list_reminders.")],
    remind_at: Annotated[
        str | None, Field(description="New ISO 8601 date-time with offset, e.g. 2026-12-01T09:00:00Z.")
    ] = None,
    note: Annotated[str | None, Field(description='New note, at most 2000 characters; "" clears it.')] = None,
    confirm: Confirm = False,
) -> ReminderWriteResult:
    """Update a reminder's time or note; at least one is required, an omitted one stays unchanged.

    Requires OpenProject 16.1+.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(reminder_id, field_name="reminder_id")
    safe_remind_at = _validate_optional_datetime(remind_at, field_name="remind_at")
    safe_note = _validate_optional_update_text(note, field_name="note", max_length=2000, wrapped_on_read=True)
    return await _run_tool(
        client.reminder.update(
            reminder_id=safe_id,
            remind_at=safe_remind_at,
            note=safe_note,
            confirm=confirm,
        )
    )


@register_tool
async def delete_reminder(
    ctx: Context,
    reminder_id: int,
    confirm: Confirm = False,
) -> ReminderWriteResult:
    """Delete a pending reminder so it never fires; this cannot be undone.

    Its unread notifications are marked read. Only its creator can; requires OpenProject 16.1+.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(reminder_id, field_name="reminder_id")
    return await _run_tool(client.reminder.delete(reminder_id=safe_id, confirm=confirm))
