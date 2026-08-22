"""Boards domain MCP tool handlers: list_boards, get_board, create_board,
update_board, delete_board.

Their `@register_tool` decorators come from `tools_runtime`, never from
`tools.py` -- see that module's own docstring for why. `tools.py` imports
this module for the decorator's registration side effect and, for now,
re-exports these five names so existing test imports keep working unchanged
(a deliberate, temporary transition step, not the long-term shape).
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import Context

from .models import BoardDetail, BoardListResult, BoardSummary, BoardWriteResult
from .tools_runtime import _client_from_context, _run_tool, register_tool
from .tools_validation import (
    _require_at_least_one,
    _validate_list_query_params,
    _validate_optional_filter_list,
    _validate_optional_project_ref,
    _validate_optional_query,
    _validate_optional_string_list,
    _validate_positive_int,
    _validate_required_query,
    _validate_select,
)


@register_tool
async def list_boards(
    ctx: Context,
    project: str | None = None,
    search: str | None = None,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
) -> BoardListResult:
    """List saved OpenProject boards/queries, optionally scoped to a project.

    select fields: id, name (see server instructions for select's general semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap. With project,
    search, or a restrictive OPENPROJECT_READ_PROJECTS, total is only the
    count of allowed boards returned on THIS page, not a full count of all
    matches — the search stops as soon as it has enough, so an exact total
    would need an extra full walk. Page until next_offset is null.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_optional_project_ref(project)
    safe_search, safe_offset, safe_limit = _validate_list_query_params(search, offset, limit)
    _validate_select(select, row_type=BoardSummary)
    return await _run_tool(
        client.list_boards(project=safe_project, search=safe_search, offset=safe_offset, limit=safe_limit)
    )


@register_tool
async def get_board(
    ctx: Context,
    board_id: int,
) -> BoardDetail:
    """Get a saved OpenProject board/query by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(board_id, field_name="board_id")
    return await _run_tool(client.get_board(safe_id))


def _validate_board_query_fields(
    *,
    project: str | None,
    group_by: str | None,
    columns: list[str] | None,
    sort_by: list[str] | None,
    highlighted_attributes: list[str] | None,
    filters: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Shared field validation for create_board/update_board -- byte-identical
    in both.
    """
    return {
        "project": _validate_optional_project_ref(project),
        "group_by": _validate_optional_query(group_by, field_name="group_by", max_length=120),
        "columns": _validate_optional_string_list(columns, field_name="columns", max_items=50, item_max_length=120),
        "sort_by": _validate_optional_string_list(sort_by, field_name="sort_by", max_items=20, item_max_length=120),
        "highlighted_attributes": _validate_optional_string_list(
            highlighted_attributes,
            field_name="highlighted_attributes",
            max_items=20,
            item_max_length=120,
        ),
        "filters": _validate_optional_filter_list(filters),
    }


@register_tool
async def create_board(
    ctx: Context,
    name: str,
    project: str | None = None,
    public: bool | None = None,
    starred: bool | None = None,
    hidden: bool | None = None,
    include_subprojects: bool | None = None,
    show_hierarchies: bool | None = None,
    timeline_visible: bool | None = None,
    group_by: str | None = None,
    columns: list[str] | None = None,
    sort_by: list[str] | None = None,
    highlighted_attributes: list[str] | None = None,
    filters: list[dict[str, Any]] | None = None,
    confirm: bool = False,
) -> BoardWriteResult:
    """Prepare or create a saved OpenProject board/query."""
    client = _client_from_context(ctx)
    safe_name = _validate_required_query(name, field_name="name", max_length=255)
    common = _validate_board_query_fields(
        project=project,
        group_by=group_by,
        columns=columns,
        sort_by=sort_by,
        highlighted_attributes=highlighted_attributes,
        filters=filters,
    )
    return await _run_tool(
        client.create_board(
            name=safe_name,
            project=common["project"],
            public=public,
            starred=starred,
            hidden=hidden,
            include_subprojects=include_subprojects,
            show_hierarchies=show_hierarchies,
            timeline_visible=timeline_visible,
            group_by=common["group_by"],
            columns=common["columns"],
            sort_by=common["sort_by"],
            highlighted_attributes=common["highlighted_attributes"],
            filters=common["filters"],
            confirm=confirm,
        )
    )


@register_tool
async def update_board(
    ctx: Context,
    board_id: int,
    name: str | None = None,
    project: str | None = None,
    public: bool | None = None,
    starred: bool | None = None,
    hidden: bool | None = None,
    include_subprojects: bool | None = None,
    show_hierarchies: bool | None = None,
    timeline_visible: bool | None = None,
    group_by: str | None = None,
    columns: list[str] | None = None,
    sort_by: list[str] | None = None,
    highlighted_attributes: list[str] | None = None,
    filters: list[dict[str, Any]] | None = None,
    confirm: bool = False,
) -> BoardWriteResult:
    """Prepare or update a saved OpenProject board/query."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(board_id, field_name="board_id")
    safe_name = _validate_optional_query(name, field_name="name", max_length=255)
    common = _validate_board_query_fields(
        project=project,
        group_by=group_by,
        columns=columns,
        sort_by=sort_by,
        highlighted_attributes=highlighted_attributes,
        filters=filters,
    )
    _require_at_least_one(
        safe_name,
        common["project"],
        public,
        starred,
        hidden,
        include_subprojects,
        show_hierarchies,
        timeline_visible,
        common["group_by"],
        common["columns"],
        common["sort_by"],
        common["highlighted_attributes"],
        common["filters"],
        message="At least one field to update is required.",
    )
    return await _run_tool(
        client.update_board(
            board_id=safe_id,
            name=safe_name,
            project=common["project"],
            public=public,
            starred=starred,
            hidden=hidden,
            include_subprojects=include_subprojects,
            show_hierarchies=show_hierarchies,
            timeline_visible=timeline_visible,
            group_by=common["group_by"],
            columns=common["columns"],
            sort_by=common["sort_by"],
            highlighted_attributes=common["highlighted_attributes"],
            filters=common["filters"],
            confirm=confirm,
        )
    )


@register_tool
async def delete_board(
    ctx: Context,
    board_id: int,
    confirm: bool = False,
) -> BoardWriteResult:
    """Prepare or delete a saved OpenProject board/query."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(board_id, field_name="board_id")
    return await _run_tool(client.delete_board(board_id=safe_id, confirm=confirm))
