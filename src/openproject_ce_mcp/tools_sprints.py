"""Sprints and Backlog Buckets (OpenProject Backlogs module) tool handlers:
list_sprints, get_sprint, list_backlog_buckets, get_backlog_bucket.

Not merged into tools_versions.py despite the historical "versions_sprints"
ticket grouping: Sprints/Backlog Buckets share no real coupling with Versions
beyond facade-method/model file proximity in client.py/models.py.
tools_versions.py holds five genuine CRUD handlers plus its own
domain-specific helper (_validate_version_schedule_fields) that neither
Sprints nor Backlog Buckets uses. Sprints and Backlog Buckets instead share a
real domain boundary with each other: the Backlogs module, a read-only
list/get surface, global-vs-project-scoped access via the same
`list_X`/`list_project_X` client-method pairing, `defining_workspace`
semantics, and the same "project" read scope (see tools.py's
READ_TOOLS_BY_SCOPE/_PROJECT_SCOPED_READ_TOOLS).

Their `@register_tool` decorators come from `tools_runtime`, never from
`tools.py` -- see that module's own docstring for why. `tools.py` imports
this module for the decorator's registration side effect and re-exports all
four public names: two of them (`list_sprints`, `get_sprint`) because
`tests/unit/test_project_and_domain_tools.py` imports them directly from
`openproject_ce_mcp.tools`; the other two (`list_backlog_buckets`,
`get_backlog_bucket`) alongside for consistency, matching `tools_admin.py`'s
precedent of re-exporting a domain's full public surface even where tests
only import a subset by name.
"""

from __future__ import annotations

from mcp.server.mcpserver import Context

from .models import (
    BacklogBucketDetail,
    BacklogBucketListResult,
    BacklogBucketSummary,
    SprintDetail,
    SprintListResult,
    SprintSummary,
)
from .tools_runtime import _client_from_context, _run_tool, register_tool
from .tools_validation import (
    _validate_list_query_params,
    _validate_positive_int,
    _validate_project_ref,
    _validate_select,
)


@register_tool
async def list_sprints(
    ctx: Context,
    project: str | None = None,
    search: str | None = None,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
) -> SprintListResult:
    """List Backlogs sprints, optionally filtered by name search.

    project: numeric id (e.g., 7) or identifier (e.g., "my-project"), not display
    name. Omit it to list every sprint visible to the current token across all
    projects; pass it to list only sprints for that project.

    Requires the OpenProject Backlogs module; unavailable instances return a clear not-found message.

    select fields: id, name (see server instructions for select's general semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap. total is only
    the count of allowed sprints returned on THIS page, not a full count of
    all matches — the search stops as soon as it has enough, so an exact
    total would need an extra full walk. Page until next_offset is null.
    """
    client = _client_from_context(ctx)
    safe_search, safe_offset, safe_limit = _validate_list_query_params(search, offset, limit)
    _validate_select(select, row_type=SprintSummary)
    if project is None:
        return await _run_tool(client.sprint.list(search=safe_search, offset=safe_offset, limit=safe_limit))
    safe_project = _validate_project_ref(project)
    return await _run_tool(
        client.sprint.list_for_project(safe_project, search=safe_search, offset=safe_offset, limit=safe_limit)
    )


@register_tool
async def get_sprint(
    ctx: Context,
    sprint_id: int,
) -> SprintDetail:
    """Get a Backlogs sprint by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(sprint_id, field_name="sprint_id")
    return await _run_tool(client.sprint.get(safe_id))


@register_tool
async def list_backlog_buckets(
    ctx: Context,
    project: str | None = None,
    search: str | None = None,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
) -> BacklogBucketListResult:
    """List Backlogs backlog buckets, optionally filtered by name search.

    project: numeric id (e.g., 7), identifier (e.g., "my-project"), or display
    name. Omit it to list every backlog bucket visible to the current token
    across all projects; pass it to list only backlog buckets for that project.

    Requires the OpenProject Backlogs module and OpenProject 17.6 or newer;
    unavailable instances return a clear not-found message.

    select fields: id, name, defining_workspace_id, defining_workspace,
    created_at, updated_at (see server instructions for select's general
    semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap. total is only
    the count of allowed backlog buckets returned on THIS page, not a full count
    of all matches — the search stops as soon as it has enough, so an exact
    total would need an extra full walk. Page until next_offset is null.
    """
    client = _client_from_context(ctx)
    safe_search, safe_offset, safe_limit = _validate_list_query_params(search, offset, limit)
    _validate_select(select, row_type=BacklogBucketSummary)
    if project is None:
        return await _run_tool(client.backlog_bucket.list(search=safe_search, offset=safe_offset, limit=safe_limit))
    safe_project = _validate_project_ref(project)
    return await _run_tool(
        client.backlog_bucket.list_for_project(safe_project, search=safe_search, offset=safe_offset, limit=safe_limit)
    )


@register_tool
async def get_backlog_bucket(
    ctx: Context,
    backlog_bucket_id: int,
) -> BacklogBucketDetail:
    """Get a Backlogs backlog bucket by id. Requires OpenProject 17.6 or newer."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(backlog_bucket_id, field_name="backlog_bucket_id")
    return await _run_tool(client.backlog_bucket.get(safe_id))
