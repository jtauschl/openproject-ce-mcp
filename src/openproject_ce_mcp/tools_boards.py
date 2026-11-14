"""Boards domain MCP tool handlers: list_boards, get_board, create_board,
update_board, delete_board.

Their `@register_tool` decorators come from `tools_runtime`, never from
`tools.py` -- see that module's own docstring for why. `tools.py` imports
this module for the decorator's registration side effect and, for now,
re-exports these five names so existing test imports keep working unchanged
(a deliberate, temporary transition step, not the long-term shape).
"""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import Context
from pydantic import Field

from .models import BoardDetail, BoardListResult, BoardSummary, BoardWriteResult
from .tool_params import Confirm, Limit, Offset, OptionalProjectRef, select_field
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

_BOARD_ID = "Board (saved query) id, from list_boards."
_NAME = "Board name, at most 255 characters."
_PUBLIC = "Visible to other users; false keeps it to its creator."
_STARRED = "Mark as a favorite query."
# OpenProject's query representer ignores `hidden` on every supported version
# (deprecated, setter is a no-op), so the tools accept the parameter but neither send it nor count it
# as a change.
_HIDDEN = "Ignored by OpenProject; the value is not stored."
_INCLUDE_SUBPROJECTS = "Also show work packages of subprojects."
_SHOW_HIERARCHIES = "Show parent/child tree; cannot combine with group_by, so it defaults to false there."
_TIMELINE_VISIBLE = "Show the Gantt timeline."
_GROUP_BY = 'Group-by attribute id (e.g. "status") or its /api/v3/queries/group_bys/ href.'
_COLUMNS = 'Column attribute ids (e.g. "id", "subject") or /api/v3/queries/columns/ hrefs.'
_SORT_BY = (
    'Sort criteria, each "field:direction" or "field-direction" (e.g. "id:asc"), a bare field (ascending), or a '
    "/api/v3/queries/sort_bys/ href; the direction is case-insensitive."
)
_HIGHLIGHTED_ATTRIBUTES = "Column ids or hrefs whose values are highlighted."
_FILTERS = (
    "OpenProject query filter objects, sent unchanged, e.g. "
    '{"_links": {"filter": {"href": "/api/v3/queries/filters/status"}, '
    '"operator": {"href": "/api/v3/queries/operators/o"}, "values": []}}.'
)


@register_tool
async def list_boards(
    ctx: Context,
    project: OptionalProjectRef = None,
    search: str | None = None,
    offset: Offset = 1,
    limit: Limit = None,
    select: Annotated[list[str] | None, select_field(BoardSummary)] = None,
) -> BoardListResult:
    """List saved OpenProject boards/queries, optionally scoped to a project.

    total is the number of boards you may read after the filters; page until next_offset is null."""
    client = _client_from_context(ctx)
    safe_project = _validate_optional_project_ref(project)
    safe_search, safe_offset, safe_limit = _validate_list_query_params(search, offset, limit)
    _validate_select(select, row_type=BoardSummary)
    return await _run_tool(
        client.board.list(project=safe_project, search=safe_search, offset=safe_offset, limit=safe_limit)
    )


@register_tool
async def get_board(
    ctx: Context,
    board_id: int,
) -> BoardDetail:
    """Get a saved OpenProject board/query by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(board_id, field_name="board_id")
    return await _run_tool(client.board.get(safe_id))


def _validate_board_query_fields(
    *,
    project: int | str | None,
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
    name: Annotated[str, Field(description=_NAME)],
    project: OptionalProjectRef = None,
    public: Annotated[bool | None, Field(description=_PUBLIC)] = None,
    starred: Annotated[bool | None, Field(description=_STARRED)] = None,
    hidden: Annotated[bool | None, Field(description=_HIDDEN)] = None,
    include_subprojects: Annotated[bool | None, Field(description=_INCLUDE_SUBPROJECTS)] = None,
    show_hierarchies: Annotated[bool | None, Field(description=_SHOW_HIERARCHIES)] = None,
    timeline_visible: Annotated[bool | None, Field(description=_TIMELINE_VISIBLE)] = None,
    group_by: Annotated[str | None, Field(description=_GROUP_BY)] = None,
    columns: Annotated[list[str] | None, Field(description=_COLUMNS)] = None,
    sort_by: Annotated[list[str] | None, Field(description=_SORT_BY)] = None,
    highlighted_attributes: Annotated[list[str] | None, Field(description=_HIGHLIGHTED_ATTRIBUTES)] = None,
    filters: Annotated[list[dict[str, Any]] | None, Field(description=_FILTERS)] = None,
    confirm: Confirm = False,
) -> BoardWriteResult:
    """Create a saved OpenProject board/query.

    This saves a work package query (filters, columns, sorting, grouping); a board grid that shows queries as
    columns is created with create_grid.
    """
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
        client.board.create(
            name=safe_name,
            project=common["project"],
            public=public,
            starred=starred,
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
    board_id: Annotated[int, Field(description=_BOARD_ID)],
    name: Annotated[str | None, Field(description=_NAME)] = None,
    project: OptionalProjectRef = None,
    public: Annotated[bool | None, Field(description=_PUBLIC)] = None,
    starred: Annotated[bool | None, Field(description=_STARRED)] = None,
    hidden: Annotated[bool | None, Field(description=_HIDDEN)] = None,
    include_subprojects: Annotated[bool | None, Field(description=_INCLUDE_SUBPROJECTS)] = None,
    show_hierarchies: Annotated[bool | None, Field(description=_SHOW_HIERARCHIES)] = None,
    timeline_visible: Annotated[bool | None, Field(description=_TIMELINE_VISIBLE)] = None,
    group_by: Annotated[str | None, Field(description=_GROUP_BY)] = None,
    columns: Annotated[list[str] | None, Field(description=_COLUMNS)] = None,
    sort_by: Annotated[list[str] | None, Field(description=_SORT_BY)] = None,
    highlighted_attributes: Annotated[list[str] | None, Field(description=_HIGHLIGHTED_ATTRIBUTES)] = None,
    filters: Annotated[list[dict[str, Any]] | None, Field(description=_FILTERS)] = None,
    confirm: Confirm = False,
) -> BoardWriteResult:
    """Update a saved OpenProject board/query.

    Omitted fields stay unchanged; a given list replaces the stored one."""
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
        client.board.update(
            board_id=safe_id,
            name=safe_name,
            project=common["project"],
            public=public,
            starred=starred,
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
    board_id: Annotated[int, Field(description=_BOARD_ID)],
    confirm: Confirm = False,
) -> BoardWriteResult:
    """Delete one saved work package query; this cannot be undone.

    A board grid that shows it as a column keeps a column pointing to the deleted query; board grids
    themselves are deleted with delete_grid.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(board_id, field_name="board_id")
    return await _run_tool(client.board.delete(board_id=safe_id, confirm=confirm))
