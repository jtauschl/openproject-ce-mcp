"""Reference-data tool handlers: list_statuses, get_status, list_priorities,
get_priority, list_types, get_type.

OPM-395's ticket originally labelled this boundary "principals_capabilities",
but list_principals and list_capabilities were already migrated in a prior
session -- list_principals to tools_admin.py, list_capabilities to
tools_memberships.py (see those modules' own docstrings). The six functions
left behind are a different real domain: read-only lookups for work-package
statuses, priorities, and types. This module is named for what it actually
contains rather than the stale ticket label.

All three sub-resources are entirely read-only in OpenProject's API
(Community Edition) -- there is no create/update/delete endpoint for
statuses, priorities, or types; they are configured only in the web admin
UI (see each function's own docstring).

Their `@register_tool` decorators come from `tools_runtime`, never from
`tools.py` -- see that module's own docstring for why. `tools.py` imports
this module for the decorator's registration side effect and re-exports all
six public names because two existing tests depend on importing them
directly from `openproject_ce_mcp.tools`:
`tests/unit/test_project_and_domain_tools.py` imports all six, and
`tests/test_trimming.py` additionally imports `get_status` on its own.
"""

from __future__ import annotations

from mcp.server.mcpserver import Context

from .models import (
    PriorityListResult,
    PrioritySummary,
    StatusListResult,
    StatusSummary,
    TypeListResult,
    TypeSummary,
)
from .tools_runtime import _client_from_context, _run_tool, register_tool
from .tools_validation import _validate_optional_project_ref, _validate_positive_int


@register_tool
async def list_statuses(ctx: Context) -> StatusListResult:
    """List all available work package statuses.

    Read-only: statuses cannot be created or modified via the OpenProject API
    (Community Edition); configure them in the web admin UI.
    """
    client = _client_from_context(ctx)
    return await _run_tool(client.list_statuses())


@register_tool
async def get_status(ctx: Context, status_id: int) -> StatusSummary:
    """Get a single work package status by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(status_id, field_name="status_id")
    return await _run_tool(client.get_status(safe_id))


@register_tool
async def list_priorities(ctx: Context) -> PriorityListResult:
    """List all available work package priorities."""
    client = _client_from_context(ctx)
    return await _run_tool(client.list_priorities())


@register_tool
async def get_priority(ctx: Context, priority_id: int) -> PrioritySummary:
    """Get a single work package priority by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(priority_id, field_name="priority_id")
    return await _run_tool(client.get_priority(safe_id))


@register_tool
async def list_types(
    ctx: Context,
    project: str | None = None,
) -> TypeListResult:
    """List all available work package types, optionally filtered by project.

    Read-only: types cannot be created or modified via the OpenProject API
    (Community Edition); configure them in the web admin UI.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_optional_project_ref(project)
    return await _run_tool(client.list_types(project=safe_project))


@register_tool
async def get_type(ctx: Context, type_id: int) -> TypeSummary:
    """Get a single work package type by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(type_id, field_name="type_id")
    return await _run_tool(client.get_type(safe_id))
