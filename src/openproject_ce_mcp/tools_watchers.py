"""Watchers domain MCP tool handlers: list_work_package_watchers,
set_work_package_watcher.

This module covers watchers only. Notifications (`list_notifications`,
`mark_notifications_read`) belong to `tools_personal.py`.

Their `@register_tool` decorators come from `tools_runtime`, never from
`tools.py` -- see that module's own docstring for why. `tools.py` imports
this module for the decorator's registration side effect and re-exports both
public names because existing tests (`tests/unit/test_work_package_tools.py`)
import them directly from `openproject_ce_mcp.tools`.
"""

from __future__ import annotations

from mcp.server.mcpserver import Context

from .models import WatcherListResult, WatcherSummary, WatcherWriteResult
from .tools_runtime import _client_from_context, _run_tool, register_tool
from .tools_validation import _validate_positive_int, _validate_select, _validate_work_package_ref


@register_tool
async def list_work_package_watchers(
    ctx: Context,
    work_package_id: int | str,
    select: list[str] | None = None,
) -> WatcherListResult:
    """List watchers of a work package.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.

    select fields: id, name (see server instructions for select's general semantics).
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    _validate_select(select, row_type=WatcherSummary)
    return await _run_tool(client.watcher.list_for_work_package(safe_id))


@register_tool
async def set_work_package_watcher(
    ctx: Context,
    work_package_id: int | str,
    user_id: int,
    watching: bool,
    confirm: bool = False,
) -> WatcherWriteResult:
    """Prepare or add/remove a watcher on a work package.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.
    watching=true adds the watcher; watching=false removes it. The two
    previews are NOT symmetric: watching=true's preview looks up and returns
    the real watcher's summary (result is populated); watching=false's
    preview makes no extra lookup and always returns result=null.
    """
    client = _client_from_context(ctx)
    safe_wp_id = _validate_work_package_ref(work_package_id)
    safe_user_id = _validate_positive_int(user_id, field_name="user_id")
    if watching:
        return await _run_tool(client.watcher.add(safe_wp_id, safe_user_id, confirm=confirm))
    return await _run_tool(client.watcher.remove(safe_wp_id, safe_user_id, confirm=confirm))
