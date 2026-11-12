"""Reference-data tool handlers: list_statuses, list_priorities, list_types.

The three functions form one domain of read-only lookups for work-package
statuses, priorities, and types. Principal and capability tools belong to
their respective admin and membership modules.

All three sub-resources are entirely read-only in OpenProject's API
(Community Edition) -- there is no create/update/delete endpoint for
statuses, priorities, or types; they are configured only in the web admin
UI (see each function's own docstring).

Their `@register_tool` decorators come from `tools_runtime`, never from
`tools.py` -- see that module's own docstring for why. `tools.py` imports
this module for the decorator's registration side effect and re-exports all
three public names because an existing test imports them directly from
`openproject_ce_mcp.tools`: `tests/unit/test_project_and_domain_tools.py`.
"""

from __future__ import annotations

from mcp.server.mcpserver import Context

from .models import PriorityListResult, StatusListResult, TypeListResult
from .tool_params import OptionalProjectRef
from .tools_runtime import _client_from_context, _run_tool, register_tool
from .tools_validation import _validate_optional_project_ref


@register_tool
async def list_statuses(ctx: Context) -> StatusListResult:
    """List all available work package statuses.

    Read-only: statuses cannot be created or modified via the OpenProject API
    (Community Edition); configure them in the web admin UI.
    """
    client = _client_from_context(ctx)
    return await _run_tool(client.status_priority_type.list_statuses())


@register_tool
async def list_priorities(ctx: Context) -> PriorityListResult:
    """List all available work package priorities."""
    client = _client_from_context(ctx)
    return await _run_tool(client.status_priority_type.list_priorities())


@register_tool
async def list_types(
    ctx: Context,
    project: OptionalProjectRef = None,
) -> TypeListResult:
    """List all available work package types, optionally filtered by project.

    Read-only: types cannot be created or modified via the OpenProject API
    (Community Edition); configure them in the web admin UI.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_optional_project_ref(project)
    return await _run_tool(client.status_priority_type.list_types(project=safe_project))
