"""Revisions tool handlers: list_work_package_revisions, get_revision.

Read-only repository commits linked to work packages, delegating to
`app/services/revision_service.py`'s `RevisionService`.

Their `@register_tool` decorators come from `tools_runtime`, never from
`tools.py` -- see that module's own docstring for why. `tools.py` imports
this module for the decorator's registration side effect and re-exports both
public names for consistency with every other domain module.
"""

from __future__ import annotations

from mcp.server.mcpserver import Context

from .models import RevisionListResult, RevisionSummary
from .tools_runtime import _client_from_context, _run_tool, register_tool
from .tools_validation import _validate_positive_int, _validate_select, _validate_work_package_ref


@register_tool
async def list_work_package_revisions(
    ctx: Context,
    work_package_id: int | str,
    select: list[str] | None = None,
) -> RevisionListResult:
    """List the repository revisions (commits) linked to a work package.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.
    OpenProject links a commit when its message references the work package.
    Empty when the project has no repository configured.

    select fields: id, formatted_identifier, author_name, message, created_at
    (see server instructions for select's general semantics).
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    _validate_select(select, row_type=RevisionSummary)
    return await _run_tool(client.revision.list_for_work_package(safe_id))


@register_tool
async def get_revision(ctx: Context, revision_id: int) -> RevisionSummary:
    """Return one repository revision (commit) by its OpenProject id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(revision_id, field_name="revision_id")
    return await _run_tool(client.revision.get(safe_id))
