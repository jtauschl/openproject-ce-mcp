"""Relations domain MCP tool handlers: create_work_package_relation, delete_relation,
get_work_package_relations, list_relations, update_relation.

These wrap the RELATIONS resource (an edge between two work packages, with a
type such as blocks/relates/precedes/follows), not work-package CRUD itself
-- they live in their own module rather than alongside work-package CRUD.

Their `@register_tool` decorators come from `tools_runtime`, never from
`tools.py` -- see that module's own docstring for why. `tools.py` imports
this module for the decorator's registration side effect and re-exports all
five names: `create_work_package_relation`, `delete_relation`, and
`update_relation` because existing tests (`tests/test_trimming.py`,
`tests/unit/test_work_package_tools.py`, `tests/unit/test_tool_validation.py`)
import them directly from `openproject_ce_mcp.tools`; `get_work_package_relations`
and `list_relations` are re-exported alongside for consistency, matching
`tools_projects.py`'s and `tools_admin.py`'s precedent of re-exporting the
full moved set rather than only the names a test happens to import today.
"""

from __future__ import annotations

from mcp.server.mcpserver import Context

from .models import (
    RelationListResult,
    RelationSummary,
    RelationUpdateResult,
    RelationWriteResult,
)
from .tools_runtime import _client_from_context, _run_tool, register_tool
from .tools_validation import (
    _validate_limit,
    _validate_offset,
    _validate_optional_non_negative_int,
    _validate_optional_text,
    _validate_optional_update_text,
    _validate_positive_int,
    _validate_relation_type,
    _validate_select,
    _validate_work_package_ref,
)


@register_tool
async def create_work_package_relation(
    ctx: Context,
    work_package_id: int | str,
    related_to_work_package_id: int | str,
    relation_type: str,
    description: str | None = None,
    lag: int | None = None,
    confirm: bool = False,
) -> RelationWriteResult:
    """Prepare or create a relation between work packages.

    Both work_package_id and related_to_work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.
    relation_type: relates, duplicates, duplicated, blocks, blocked, precedes, follows, includes, partof, requires, required.
    work_package_id becomes from_id and related_to_work_package_id becomes to_id — but OpenProject stores
    only one canonical type per pair and silently rewrites the other: creating with relation_type='precedes'
    (or 'blocked', 'duplicated', 'partof', 'required') is stored as the paired canonical type ('follows',
    'blocks', 'duplicates', 'includes', 'requires' respectively) with from_id/to_id SWAPPED relative to
    work_package_id/related_to_work_package_id. The canonical types themselves ('follows', 'blocks',
    'duplicates', 'includes', 'requires', and non-directional 'relates') are stored exactly as given, with
    from_id/to_id unswapped. This happens once at creation and does not depend on which work package's
    relations you later query — always read the actual type/from_id/to_id from the response rather than
    assuming they match what you requested.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    safe_related_id = _validate_work_package_ref(related_to_work_package_id, field_name="related_to_work_package_id")
    safe_relation_type = _validate_relation_type(relation_type)
    safe_description = _validate_optional_text(description, field_name="description", max_length=255)
    safe_lag = _validate_optional_non_negative_int(lag, field_name="lag")
    return await _run_tool(
        client.relation.create(
            work_package_id=safe_id,
            related_to_work_package_id=safe_related_id,
            relation_type=safe_relation_type,
            description=safe_description,
            lag=safe_lag,
            confirm=confirm,
        )
    )


@register_tool
async def delete_relation(
    ctx: Context,
    relation_id: int,
    confirm: bool = False,
) -> RelationWriteResult:
    """Prepare or delete a relation between work packages."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(relation_id, field_name="relation_id")
    return await _run_tool(client.relation.delete(relation_id=safe_id, confirm=confirm))


@register_tool
async def get_work_package_relations(
    ctx: Context,
    work_package_id: int | str,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
) -> RelationListResult:
    """Get all relations for a work package (blocks, relates to, duplicates, etc.).

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.
    type/from_id/to_id reflect how OpenProject actually stored the relation, which does not depend on
    which work package's relations you query — but can differ from how it was originally requested, since
    OpenProject canonicalizes some relation types at creation time (e.g. a relation requested as 'precedes'
    is stored as 'follows' with from_id/to_id swapped; see create_work_package_relation). Use from_id/to_id
    together with type, not the request you expect to have made, to determine the actual direction.

    Each result additionally carries queried_perspective, a caller-relative reading of the same relation
    from work_package_id's own side — never a replacement for type/from_id/to_id, which stay unchanged.
    queried_perspective.direction is "from" or "to" (which raw id equals work_package_id);
    queried_perspective.effective_type is the type as read FROM work_package_id's side (e.g. a stored
    "blocks" relation reads as effective_type="blocked" when work_package_id is the to_id side, "blocks"
    when it's the from_id side). queried_perspective.predecessor_id/successor_id are populated only for
    the precedes/follows type pair (OpenProject's own scheduling-relevant relation types); both stay null
    for every other type, since no other type has an equivalent first/second concept.

    select fields: id, type, to_id (see server instructions for select's general semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap. total is only
    the count of allowed relations returned on THIS page, not a full count
    of all matches — the search stops as soon as it has enough, so an exact
    total would need an extra full walk. Page until next_offset is null.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    _validate_select(select, row_type=RelationSummary)
    return await _run_tool(client.relation.list_for_work_package(safe_id, offset=safe_offset, limit=safe_limit))


@register_tool
async def list_relations(
    ctx: Context,
    relation_type: str | None = None,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
) -> RelationListResult:
    """List all relations across the instance, optionally filtered by type (e.g. 'blocks', 'follows').

    type/from_id/to_id reflect how OpenProject actually stored the relation (it does not change depending
    on which work package's relations you're viewing), which can differ from how it was originally
    requested — OpenProject canonicalizes some relation types at creation time (e.g. a relation requested
    as 'precedes' is stored as 'follows' with from_id/to_id swapped; see create_work_package_relation).
    Filtering by relation_type matches the stored (canonical) type, not necessarily the type a caller
    originally requested when creating it.

    Each result's queried_perspective field is always null here — a caller-relative reading needs one
    anchor work package to read the relation FROM, and this instance-wide listing has none. Use
    get_work_package_relations instead when you need queried_perspective populated.

    select fields: id, type, to_id (see server instructions for select's general semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap. total is only
    the count of allowed relations returned on THIS page, not a full count
    of all matches — the search stops as soon as it has enough, so an exact
    total would need an extra full walk. Page until next_offset is null.
    """
    client = _client_from_context(ctx)
    safe_type = _validate_relation_type(relation_type) if relation_type else None
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    _validate_select(select, row_type=RelationSummary)
    return await _run_tool(client.relation.list_all(relation_type=safe_type, offset=safe_offset, limit=safe_limit))


@register_tool
async def update_relation(
    ctx: Context,
    relation_id: int,
    relation_type: str | None = None,
    description: str | None = None,
    confirm: bool = False,
) -> RelationUpdateResult:
    """Prepare or update the type or description of a relation. Set confirm=true to write.

    relation_type is subject to the same write-time canonicalization as create_work_package_relation:
    setting it to a "reverse" pair member (precedes, blocked, duplicated, partof, required) rewrites the
    stored relation to the paired canonical type (follows, blocks, duplicates, includes, requires) with
    from_id/to_id swapped relative to the relation's existing from/to. Read the actual type/from_id/to_id
    back afterward rather than assuming they match what was requested.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(relation_id, field_name="relation_id")
    safe_type = _validate_relation_type(relation_type) if relation_type else None
    safe_desc = _validate_optional_update_text(description, field_name="description", max_length=500)
    return await _run_tool(
        client.relation.update(
            relation_id=safe_id,
            relation_type=safe_type,
            description=safe_desc,
            confirm=confirm,
        )
    )
