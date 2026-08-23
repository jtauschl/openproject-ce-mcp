"""Cost tool handlers: get_cost_entry, list_work_package_cost_entries,
get_work_package_costs_by_type, get_cost_type.

A small, entirely read-only domain -- cost entries and cost types have no
create/update/delete endpoint in OpenProject's API (Community Edition), and
cost types have no collection GET either (no list_cost_types tool exists
because the endpoint does not exist upstream). Not one of the ticket's
original 15 suggested domain boundaries (OPM-395) -- costs is a newer
OpenProject Costs-module surface with its own service/port/adapter
(app/services/cost_service.py, app/ports/cost_api.py), and forms a clean
standalone domain distinct from Time Entries despite sharing the
"work_package" read scope, matching tools_categories.py's precedent of a
small standalone file for a small read-only group.

Their `@register_tool` decorators come from `tools_runtime`, never from
`tools.py` -- see that module's own docstring for why. `tools.py` imports
this module for the decorator's registration side effect and re-exports all
four public names for consistency with every other domain module, even
though no existing test currently imports them directly from
`openproject_ce_mcp.tools`.
"""

from __future__ import annotations

from mcp.server.mcpserver import Context

from .models import (
    CostEntryListResult,
    CostEntrySummary,
    CostTypeSummary,
    WorkPackageCostsByTypeResult,
)
from .tools_runtime import _client_from_context, _run_tool, register_tool
from .tools_validation import _validate_positive_int, _validate_work_package_ref


@register_tool
async def get_cost_entry(
    ctx: Context,
    cost_entry_id: int,
) -> CostEntrySummary:
    """Get a single cost entry by id.

    Cost entries are entirely read-only in OpenProject's API (Community
    Edition) -- there is no create/update/delete endpoint for this resource.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(cost_entry_id, field_name="cost_entry_id")
    return await _run_tool(client.get_cost_entry(safe_id))


@register_tool
async def list_work_package_cost_entries(
    ctx: Context,
    work_package_id: int | str,
) -> CostEntryListResult:
    """List all cost entries recorded against a work package.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.

    Returns every cost entry for the work package in one call -- this endpoint
    is unpaginated on OpenProject's side (no offset/limit parameters exist).
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    return await _run_tool(client.list_work_package_cost_entries(safe_id))


@register_tool
async def get_work_package_costs_by_type(
    ctx: Context,
    work_package_id: int | str,
) -> WorkPackageCostsByTypeResult:
    """Get a work package's costs aggregated by cost type.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.

    count is the number of distinct cost types with recorded spend on this
    work package, not a monetary total. Each result's spent_units is a
    quantity in that cost type's own unit (see get_cost_type for the unit
    name) -- there is no currency conversion or grand total computed here or
    by OpenProject's own API.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    return await _run_tool(client.get_work_package_costs_by_type(safe_id))


@register_tool
async def get_cost_type(
    ctx: Context,
    cost_type_id: int,
) -> CostTypeSummary:
    """Get a cost type by id.

    Cost types are entirely read-only in OpenProject's API (Community
    Edition) -- there is no create/update/delete endpoint, and no collection
    GET either (no list_cost_types tool exists because the endpoint does not
    exist upstream).
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(cost_type_id, field_name="cost_type_id")
    return await _run_tool(client.get_cost_type(safe_id))
