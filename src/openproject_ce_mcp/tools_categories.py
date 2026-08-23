"""Category tool handlers: list_categories, get_category.

A small read-only pair -- OpenProject's Categories API has no POST/PATCH/DELETE
(see the project's own docs/architecture notes on API stubs), so there is
nothing to write here.

Their `@register_tool` decorators come from `tools_runtime`, never from
`tools.py` -- see that module's own docstring for why. `tools.py` imports this
module for the decorator's registration side effect and re-exports both public
names because an existing test (`tests/unit/test_project_and_domain_tools.py`)
imports `get_category`/`list_categories` directly from `openproject_ce_mcp.tools`.
"""

from __future__ import annotations

from mcp.server.mcpserver import Context

from .models import CategoryListResult, CategorySummary
from .tools_runtime import _client_from_context, _run_tool, register_tool
from .tools_validation import (
    _validate_optional_project_ref,
    _validate_positive_int,
    _validate_project_ref,
    _validate_select,
)


@register_tool
async def list_categories(
    ctx: Context,
    project: str,
    select: list[str] | None = None,
) -> CategoryListResult:
    """List work-package categories configured for a project.

    select fields: id, name (see server instructions for select's general semantics).
    """
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    _validate_select(select, row_type=CategorySummary)
    return await _run_tool(client.category.list(safe_project))


@register_tool
async def get_category(
    ctx: Context,
    category_id: int,
    project: str | None = None,
) -> CategorySummary:
    """Get a single category by id.

    project is optional: when given, it's cross-checked against the
    category's real project and a mismatch raises a not-found error, rather
    than being the sole source of authorization.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_optional_project_ref(project)
    safe_id = _validate_positive_int(category_id, field_name="category_id")
    return await _run_tool(client.category.get(category_id=safe_id, project_ref=safe_project))
