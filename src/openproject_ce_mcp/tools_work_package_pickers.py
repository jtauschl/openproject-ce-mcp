"""Work package picker MCP tool handlers: list_available_assignees,
list_work_package_available_relation_candidates, list_work_package_available_watchers,
list_work_package_available_projects.

Read-only lookups for filling a work package field with a value OpenProject
will accept, delegating to `app/services/work_package_picker_service.py`'s
`WorkPackagePickerService`. Only input validation and `select` validation
remain at this presentation layer.

Their `@register_tool` decorators come from `tools_runtime`, never from
`tools.py` -- see that module's own docstring for why. `tools.py` imports
this module for the decorator's registration side effect and re-exports its
public names alongside every other tools_* module's.
"""

from __future__ import annotations

from typing import Annotated

from mcp.server.mcpserver import Context
from pydantic import Field

from .models import (
    PROJECT_ATTRIBUTE_FIELDS,
    AvailableWatcherListResult,
    PrincipalCollectionResult,
    PrincipalSummary,
    ProjectListResult,
    ProjectSummary,
    RelationCandidateListResult,
    RelationCandidateSummary,
    WatcherSummary,
)
from .tool_params import Limit, Offset, OptionalProjectRef, OptionalWorkPackageRef, WorkPackageRef, select_field
from .tools_runtime import _client_from_context, _run_tool, register_tool
from .tools_validation import (
    _validate_limit,
    _validate_list_query_params,
    _validate_optional_choice,
    _validate_optional_project_ref,
    _validate_optional_query,
    _validate_optional_work_package_ref,
    _validate_select,
    _validate_work_package_ref,
)

#: Relation types OpenProject's available_relation_candidates `type` filter accepts.
RELATION_CANDIDATE_TYPES = {
    "relates",
    "duplicates",
    "duplicated",
    "blocks",
    "blocked",
    "precedes",
    "follows",
    "includes",
    "partof",
    "requires",
    "required",
    "parent",
    "child",
}


@register_tool
async def list_available_assignees(
    ctx: Context,
    work_package_id: OptionalWorkPackageRef = None,
    project: OptionalProjectRef = None,
    select: Annotated[list[str] | None, select_field(PrincipalSummary)] = None,
) -> PrincipalCollectionResult:
    """List the users and groups OpenProject accepts as assignee.

    Pass work_package_id for an existing work package, or project for one not
    created yet -- exactly one of the two. The same principals are valid as
    responsible (accountable).
    """
    client = _client_from_context(ctx)
    safe_wp = _validate_optional_work_package_ref(work_package_id)
    safe_project = _validate_optional_project_ref(project)
    _validate_select(select, row_type=PrincipalSummary)
    return await _run_tool(
        client.work_package_picker.available_assignees(work_package_id=safe_wp, project_ref=safe_project)
    )


@register_tool
async def list_work_package_available_relation_candidates(
    ctx: Context,
    work_package_id: WorkPackageRef,
    query: str | None = None,
    relation_type: str | None = None,
    limit: Annotated[
        int | None,
        Field(description="Maximum number of candidates, capped at OPENPROJECT_MAX_PAGE_SIZE. Not paged."),
    ] = None,
    select: Annotated[list[str] | None, select_field(RelationCandidateSummary)] = None,
) -> RelationCandidateListResult:
    """List work packages that can be the other end of a new relation.

    query: text matching subject, project, type, status or display identifier.
    Bare digits match the internal id on older/classic-identifier instances,
    but the project sequence number on 17.8+ with semantic identifiers;
    use a subject substring for a version-independent search.
    relation_type: only candidates valid for this relation (relates,
    duplicates, duplicated, blocks, blocked, precedes, follows, includes,
    partof, requires, required, parent, child) -- OpenProject leaves out e.g. a work package
    that would create a cycle. Candidates in projects outside
    OPENPROJECT_READ_PROJECTS are left out.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    safe_query = _validate_optional_query(query, field_name="query", max_length=200)
    safe_type = _validate_optional_choice(
        relation_type, field_name="relation_type", allowed_values=RELATION_CANDIDATE_TYPES
    )
    safe_limit = _validate_limit(limit)
    _validate_select(select, row_type=RelationCandidateSummary)
    return await _run_tool(
        client.work_package_picker.relation_candidates(
            safe_id, query=safe_query, relation_type=safe_type, limit=safe_limit
        )
    )


@register_tool
async def list_work_package_available_watchers(
    ctx: Context,
    work_package_id: WorkPackageRef,
    offset: Offset = 1,
    limit: Limit = None,
    select: Annotated[list[str] | None, select_field(WatcherSummary)] = None,
) -> AvailableWatcherListResult:
    """List the users that can be added as watchers of a work package.

    OpenProject answers only a caller who may add watchers in the work package's project. Page until next_offset
    is null."""
    client = _client_from_context(ctx)
    safe_wp = _validate_work_package_ref(work_package_id)
    _, safe_offset, safe_limit = _validate_list_query_params(None, offset, limit)
    _validate_select(select, row_type=WatcherSummary)
    return await _run_tool(client.work_package_picker.available_watchers(safe_wp, offset=safe_offset, limit=safe_limit))


@register_tool
async def list_work_package_available_projects(
    ctx: Context,
    work_package_id: WorkPackageRef,
    offset: Offset = 1,
    limit: Limit = None,
    select: Annotated[list[str] | None, select_field(ProjectSummary, unfilled=PROJECT_ATTRIBUTE_FIELDS)] = None,
) -> ProjectListResult:
    """List the projects a work package can be moved to, limited to projects the read scope covers.

    OpenProject answers only a caller who may edit the work package. total is the count of allowed projects returned
    on THIS page, not a full count; page until next_offset is null."""
    client = _client_from_context(ctx)
    safe_wp = _validate_work_package_ref(work_package_id)
    _, safe_offset, safe_limit = _validate_list_query_params(None, offset, limit)
    _validate_select(select, row_type=ProjectSummary, unfilled=PROJECT_ATTRIBUTE_FIELDS)
    return await _run_tool(client.work_package_picker.available_projects(safe_wp, offset=safe_offset, limit=safe_limit))
