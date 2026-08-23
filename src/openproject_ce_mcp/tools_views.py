"""Views (saved OpenProject queries) tool handlers: list_views, get_view.

Their `@register_tool` decorators come from `tools_runtime`, never from
`tools.py` -- see that module's own docstring for why. `tools.py` imports
this module for the decorator's registration side effect and re-exports both
public names because `tests/unit/test_project_and_domain_tools.py` imports
them directly from `openproject_ce_mcp.tools`.
"""

from __future__ import annotations

from mcp.server.mcpserver import Context

from .models import ViewDetail, ViewListResult, ViewSummary
from .tools_runtime import _client_from_context, _run_tool, register_tool
from .tools_validation import (
    _validate_list_query_params,
    _validate_optional_project_ref,
    _validate_optional_query,
    _validate_positive_int,
    _validate_select,
)


@register_tool
async def list_views(
    ctx: Context,
    project: str | None = None,
    type: str | None = None,
    search: str | None = None,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
) -> ViewListResult:
    """List saved OpenProject views, optionally filtered by project, view subtype, or name search.

    select fields: id, name (see server instructions for select's general semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap. total is only
    the count of allowed views returned on THIS page, not a full count of all
    matches — the search stops as soon as it has enough, so an exact total
    would need an extra full walk. Page until next_offset is null.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_optional_project_ref(project)
    safe_type = _validate_optional_query(type, field_name="type", max_length=120)
    safe_search, safe_offset, safe_limit = _validate_list_query_params(search, offset, limit)
    _validate_select(select, row_type=ViewSummary)
    return await _run_tool(
        client.list_views(
            project=safe_project,
            view_type=safe_type,
            search=safe_search,
            offset=safe_offset,
            limit=safe_limit,
        )
    )


@register_tool
async def get_view(
    ctx: Context,
    view_id: int,
) -> ViewDetail:
    """Get a single OpenProject view by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(view_id, field_name="view_id")
    return await _run_tool(client.get_view(safe_id))
