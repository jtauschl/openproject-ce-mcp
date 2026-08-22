"""Query Schema Extended domain MCP tool handlers: get_query_filter,
get_query_column, get_query_operator, get_query_sort_by,
list_query_filter_instance_schemas, get_query_filter_instance_schema.

Their `@register_tool` decorators come from `tools_runtime`, never from
`tools.py` -- see that module's own docstring for why. `tools.py` imports
this module for the decorator's registration side effect only; it does not
re-export these names, because no existing test imports any of them directly
from `openproject_ce_mcp.tools`.
"""

from __future__ import annotations

from mcp.server.mcpserver import Context

from .models import (
    QueryColumnSummary,
    QueryFilterInstanceSchemaListResult,
    QueryFilterInstanceSchemaSummary,
    QueryFilterSummary,
    QueryOperatorSummary,
    QuerySortBySummary,
)
from .tools_runtime import _client_from_context, _run_tool, register_tool
from .tools_validation import _validate_optional_project_ref, _validate_required_query


@register_tool
async def get_query_filter(
    ctx: Context,
    filter_id: str,
) -> QueryFilterSummary:
    """Get a single query filter by id."""
    client = _client_from_context(ctx)
    safe_filter_id = _validate_required_query(filter_id, field_name="filter_id", max_length=100)
    return await _run_tool(client.get_query_filter(safe_filter_id))


@register_tool
async def get_query_column(
    ctx: Context,
    column_id: str,
) -> QueryColumnSummary:
    """Get a single query column by id."""
    client = _client_from_context(ctx)
    safe_column_id = _validate_required_query(column_id, field_name="column_id", max_length=100)
    return await _run_tool(client.get_query_column(safe_column_id))


@register_tool
async def get_query_operator(
    ctx: Context,
    operator_id: str,
) -> QueryOperatorSummary:
    """Get a single query operator by id."""
    client = _client_from_context(ctx)
    safe_operator_id = _validate_required_query(operator_id, field_name="operator_id", max_length=100)
    return await _run_tool(client.get_query_operator(safe_operator_id))


@register_tool
async def get_query_sort_by(
    ctx: Context,
    sort_by_id: str,
) -> QuerySortBySummary:
    """Get a single query sort-by definition by id."""
    client = _client_from_context(ctx)
    safe_sort_by_id = _validate_required_query(sort_by_id, field_name="sort_by_id", max_length=100)
    return await _run_tool(client.get_query_sort_by(safe_sort_by_id))


@register_tool
async def list_query_filter_instance_schemas(
    ctx: Context,
    project: str | None = None,
) -> QueryFilterInstanceSchemaListResult:
    """List query filter instance schemas globally or for a project."""
    client = _client_from_context(ctx)
    safe_project = _validate_optional_project_ref(project)
    return await _run_tool(client.list_query_filter_instance_schemas(project=safe_project))


@register_tool
async def get_query_filter_instance_schema(
    ctx: Context,
    schema_id: str,
) -> QueryFilterInstanceSchemaSummary:
    """Get a single query filter instance schema by id."""
    client = _client_from_context(ctx)
    safe_schema_id = _validate_required_query(schema_id, field_name="schema_id", max_length=100)
    return await _run_tool(client.get_query_filter_instance_schema(safe_schema_id))
