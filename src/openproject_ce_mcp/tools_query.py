"""Query Execution domain MCP tool handler: execute_query.

Deliberately a separate file from `tools_query_schema.py`, despite the
similar module name -- the two hold unrelated concerns. `tools_query_schema.py`
holds the query METADATA/schema tools (`get_query_filter`, `get_query_column`,
`get_query_operator`, `get_query_sort_by`, `list_query_filter_instance_schemas`,
`get_query_filter_instance_schema`): they describe a query's *shape*, are
gated under the `"extended"` read scope (`OPENPROJECT_ENABLE_EXTENDED_READ`,
legacy alias `OPENPROJECT_ENABLE_METADATA_TOOLS`), and validate their string
ids with `_validate_required_query`/`_validate_optional_project_ref`.
`execute_query` instead *runs* a saved query server-side and returns its
resolved work packages (`WorkPackageListResult`); it is classified under the
ordinary `"work_package"` read scope in `READ_TOOLS_BY_SCOPE` (the same scope
as `list_work_packages`/`get_work_package`) and also appears in
`_PROJECT_SCOPED_READ_TOOLS`, and it validates its numeric id/paging
arguments with `_validate_positive_int`/`_validate_offset`/`_validate_limit`
-- the same validators `list_work_packages` and similar tools use in
`tools_work_packages.py`. The two modules share only the generic `tools_runtime` helpers
every domain module uses (`_client_from_context`/`_run_tool`/`register_tool`);
they share no domain-specific validator or return model, so folding
`execute_query` into `tools_query_schema.py` would misrepresent it as a
schema/metadata tool it is not; a separate one-function file keeps the
domain boundary honest.

Its `@register_tool` decorator comes from `tools_runtime`, never from
`tools.py` -- see that module's own docstring for why. `tools.py` imports
this module for the decorator's registration side effect only, matching the
`tools_misc`/`tools_user_schedule` precedent: it does not re-export
`execute_query`, because no existing test imports it directly from
`openproject_ce_mcp.tools` (integration tests call `OpenProjectClient.execute_query`
instead).
"""

from __future__ import annotations

from mcp.server.mcpserver import Context

from .models import WorkPackageListResult
from .tools_runtime import _client_from_context, _run_tool, register_tool
from .tools_validation import _validate_limit, _validate_offset, _validate_positive_int


@register_tool
async def execute_query(
    ctx: Context,
    query_id: int,
    offset: int = 1,
    limit: int | None = None,
) -> WorkPackageListResult:
    """Execute a saved OpenProject query by id and return its resolved work packages.

    query_id: the query's own numeric id — obtain it from get_view/list_views's
    query_id field, or from list_boards/get_board (a board's id IS its
    underlying query id, since OpenProject Boards are Query resources).

    Runs the query server-side (OpenProject resolves its stored filters/sort/
    group_by and returns real work packages, not just the query's
    definition) — no client-side filter translation happens here. Results are
    still filtered against this MCP's own OPENPROJECT_READ_PROJECTS allowlist
    before being returned, since the query itself executes with the API
    token's full server-side permissions.

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap.
    """
    client = _client_from_context(ctx)
    safe_query_id = _validate_positive_int(query_id, field_name="query_id")
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(client.query_execution.execute(safe_query_id, offset=safe_offset, limit=safe_limit))
