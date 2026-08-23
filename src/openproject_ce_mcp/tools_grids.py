"""Grids domain MCP tool handlers: list_grids, get_grid, create_grid,
update_grid, delete_grid.

Their `@register_tool` decorators come from `tools_runtime`, never from
`tools.py` -- see that module's own docstring for why. `tools.py` imports
this module for the decorator's registration side effect and re-exports
these five names because `test_project_and_domain_tools.py` imports them
directly from `openproject_ce_mcp.tools`.

Grids is a standalone dashboard-grid CRUD domain, distinct from Boards
(`tools_boards.py`) -- both are saved-layout resources but map to different
OpenProject API resources (`/api/v3/grids` vs `/api/v3/queries`) and are not
otherwise related.
"""

from __future__ import annotations

from mcp.server.mcpserver import Context

from .models import GridListResult, GridSummary, GridWriteResult
from .tools_runtime import _client_from_context, _run_tool, register_tool
from .tools_validation import (
    _require_at_least_one,
    _validate_limit,
    _validate_offset,
    _validate_optional_query,
    _validate_positive_int,
    _validate_required_query,
    _validate_select,
)


@register_tool
async def list_grids(
    ctx: Context,
    scope: str | None = None,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
) -> GridListResult:
    """List dashboard grids, optionally filtered by scope (page path).

    select fields: id, scope (see server instructions for select's general
    semantics). limit is capped at
    OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned next_offset as
    the next call's offset to page past the cap. total is only the count of
    allowed grids returned on THIS page, not a full count of all matches —
    the search stops as soon as it has enough, so an exact total would need
    an extra full walk. Page until next_offset is null.
    """
    client = _client_from_context(ctx)
    safe_scope = _validate_optional_query(scope, field_name="scope", max_length=500)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    _validate_select(select, row_type=GridSummary)
    return await _run_tool(client.list_grids(scope=safe_scope, offset=safe_offset, limit=safe_limit))


@register_tool
async def get_grid(ctx: Context, grid_id: int) -> GridSummary:
    """Get a single dashboard grid by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(grid_id, field_name="grid_id")
    return await _run_tool(client.get_grid(safe_id))


@register_tool
async def create_grid(
    ctx: Context,
    name: str,
    scope: str,
    row_count: int | None = None,
    column_count: int | None = None,
    confirm: bool = False,
) -> GridWriteResult:
    """Prepare or create a dashboard grid for a scope such as `/my/page` or `/projects/<identifier>`."""
    client = _client_from_context(ctx)
    safe_name = _validate_required_query(name, field_name="name", max_length=255)
    safe_scope = _validate_required_query(scope, field_name="scope", max_length=500)
    if not safe_scope.startswith("/"):
        raise ValueError("scope must start with '/'.")
    safe_row_count = _validate_positive_int(row_count, field_name="row_count") if row_count is not None else None
    safe_column_count = (
        _validate_positive_int(column_count, field_name="column_count") if column_count is not None else None
    )
    return await _run_tool(
        client.create_grid(
            name=safe_name,
            scope=safe_scope,
            row_count=safe_row_count,
            column_count=safe_column_count,
            confirm=confirm,
        )
    )


@register_tool
async def update_grid(
    ctx: Context,
    grid_id: int,
    name: str | None = None,
    row_count: int | None = None,
    column_count: int | None = None,
    confirm: bool = False,
) -> GridWriteResult:
    """Prepare or update a dashboard grid.

    Omitted fields stay unchanged. Set confirm=true to write.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(grid_id, field_name="grid_id")
    safe_name = _validate_optional_query(name, field_name="name", max_length=255)
    safe_row_count = _validate_positive_int(row_count, field_name="row_count") if row_count is not None else None
    safe_column_count = (
        _validate_positive_int(column_count, field_name="column_count") if column_count is not None else None
    )
    _require_at_least_one(
        safe_name, safe_row_count, safe_column_count, message="At least one field to update is required."
    )
    return await _run_tool(
        client.update_grid(
            grid_id=safe_id,
            name=safe_name,
            row_count=safe_row_count,
            column_count=safe_column_count,
            confirm=confirm,
        )
    )


@register_tool
async def delete_grid(
    ctx: Context,
    grid_id: int,
    confirm: bool = False,
) -> GridWriteResult:
    """Prepare or delete a dashboard grid. Only deletes when called again with confirm=true."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(grid_id, field_name="grid_id")
    return await _run_tool(client.delete_grid(grid_id=safe_id, confirm=confirm))
