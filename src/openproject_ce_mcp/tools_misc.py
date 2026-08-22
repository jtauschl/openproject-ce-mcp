"""Misc Extended domain MCP tool handlers: render_text, list_help_texts,
get_help_text, list_working_days, list_non_working_days, get_custom_option.

Their `@register_tool` decorators come from `tools_runtime`, never from
`tools.py` -- see that module's own docstring for why. `tools.py` imports
this module for the decorator's registration side effect only; unlike the
Reminders/Versions/Boards splits, it does not re-export these names, because
no existing test imports any of them directly from `openproject_ce_mcp.tools`.
"""

from __future__ import annotations

from mcp.server.mcpserver import Context

from .models import (
    CustomOptionSummary,
    HelpTextListResult,
    HelpTextSummary,
    NonWorkingDayListResult,
    RenderedText,
    WorkingDayListResult,
)
from .tools_runtime import _client_from_context, _run_tool, register_tool
from .tools_validation import _validate_positive_int, _validate_required_text


@register_tool
async def render_text(
    ctx: Context,
    text: str,
    format: str = "markdown",
) -> RenderedText:
    """Render markdown or plain text to HTML using the OpenProject API. format: 'markdown' or 'plain'."""
    client = _client_from_context(ctx)
    safe_text = _validate_required_text(text, field_name="text", max_length=50_000)
    if format not in ("markdown", "plain"):
        raise ValueError("format must be 'markdown' or 'plain'.")
    return await _run_tool(client.render_text(text=safe_text, format=format))


@register_tool
async def list_help_texts(ctx: Context) -> HelpTextListResult:
    """List all help texts configured for work-package and project attributes."""
    client = _client_from_context(ctx)
    return await _run_tool(client.list_help_texts())


@register_tool
async def get_help_text(ctx: Context, help_text_id: int) -> HelpTextSummary:
    """Get a single help text by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(help_text_id, field_name="help_text_id")
    return await _run_tool(client.get_help_text(safe_id))


@register_tool
async def list_working_days(ctx: Context) -> WorkingDayListResult:
    """List the Mon–Sun working-day configuration (7 entries showing which weekdays are working days)."""
    client = _client_from_context(ctx)
    return await _run_tool(client.list_working_days())


@register_tool
async def list_non_working_days(
    ctx: Context,
    year: int | None = None,
) -> NonWorkingDayListResult:
    """List non-working days (public holidays / closures) for a given year, or the current year."""
    client = _client_from_context(ctx)
    return await _run_tool(client.list_non_working_days(year=year))


@register_tool
async def get_custom_option(ctx: Context, custom_option_id: int) -> CustomOptionSummary:
    """Fetch the label/value of a single custom field option by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(custom_option_id, field_name="custom_option_id")
    return await _run_tool(client.get_custom_option(safe_id))
