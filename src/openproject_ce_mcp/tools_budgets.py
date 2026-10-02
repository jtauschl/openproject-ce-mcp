"""Budgets tool handler: list_project_budgets.

Read-only, delegating to `app/services/budget_service.py`'s `BudgetService`.

Its `@register_tool` decorator comes from `tools_runtime`, never from
`tools.py` -- see that module's own docstring for why. `tools.py` imports
this module for the decorator's registration side effect and re-exports the
public name for consistency with every other domain module.
"""

from __future__ import annotations

from mcp.server.mcpserver import Context

from .models import BudgetListResult
from .tools_runtime import _client_from_context, _run_tool, register_tool
from .tools_validation import _validate_project_ref


@register_tool
async def list_project_budgets(ctx: Context, project: str) -> BudgetListResult:
    """List the budgets of a project (id and subject).

    project: id or identifier. A budget id is what a work package's budget
    field refers to.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    return await _run_tool(client.budget.list_for_project(safe_project))
