"""Attachments/file-links domain MCP tool handlers: list_work_package_attachments,
get_attachment, create_work_package_attachment, delete_attachment,
list_work_package_file_links, delete_file_link.

Attachments and Nextcloud file links share a domain -- both are file-ish
artifacts hung off a work package -- per OPM-395's own suggested domain
boundary ("attachments_file_links"); one file, since nothing in either half
argues for a split.

Their `@register_tool` decorators come from `tools_runtime`, never from
`tools.py` -- see that module's own docstring for why. `tools.py` imports
this module for the decorator's registration side effect and re-exports all
six names: `create_work_package_attachment`, `delete_attachment`,
`delete_file_link`, `get_attachment`, `list_work_package_attachments`, and
`list_work_package_file_links` because an existing test
(`tests/unit/test_project_and_domain_tools.py`) imports all six directly
from `openproject_ce_mcp.tools`, matching `tools_relations.py`'s and
`tools_projects.py`'s precedent of re-exporting the full moved set.

`create_work_package_attachment`'s registration gate (`ATTACHMENT_UPLOAD_TOOLS`,
requiring work-package write scope, a configured `OPENPROJECT_ATTACHMENT_ROOT`,
AND a usable project read/write allowlist) stays in `tools.py`'s own
`register_tools()`/`enabled_tool_names()` -- only the function body moved
here, not the gating metadata.
"""

from __future__ import annotations

from mcp.server.mcpserver import Context

from .models import (
    AttachmentListResult,
    AttachmentSummary,
    AttachmentWriteResult,
    FileLinkListResult,
    FileLinkSummary,
    FileLinkWriteResult,
)
from .tools_runtime import _client_from_context, _run_tool, register_tool
from .tools_validation import (
    _validate_limit,
    _validate_offset,
    _validate_optional_text,
    _validate_positive_int,
    _validate_required_text,
    _validate_select,
    _validate_work_package_ref,
)


@register_tool
async def list_work_package_attachments(
    ctx: Context,
    work_package_id: int | str,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
    include_total_size: bool = False,
) -> AttachmentListResult:
    """List attachments on a work package.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.

    select fields: id, title, file_name, description (see server instructions
    for select's general semantics).

    limit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned
    next_offset as the next call's offset to page past the cap.

    include_total_size=true sums file_size_bytes across every attachment
    (independent of limit/offset) — OpenProject's attachments endpoint
    always returns the full list in one response, so this costs no extra
    request in the common case. Null if file_size_bytes is hidden by
    server configuration, rather than leaking it indirectly through a sum.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    _validate_select(select, row_type=AttachmentSummary)
    return await _run_tool(
        client.attachment.list_for_work_package(
            safe_id, offset=safe_offset, limit=safe_limit, include_total_size=include_total_size
        )
    )


@register_tool
async def get_attachment(
    ctx: Context,
    attachment_id: int,
) -> AttachmentSummary:
    """Get a single attachment by id."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(attachment_id, field_name="attachment_id")
    return await _run_tool(client.attachment.get(safe_id))


@register_tool
async def create_work_package_attachment(
    ctx: Context,
    work_package_id: int | str,
    file_path: str,
    description: str | None = None,
    confirm: bool = False,
) -> AttachmentWriteResult:
    """Prepare or upload an attachment to a work package.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.
    """
    client = _client_from_context(ctx)
    safe_work_package_id = _validate_work_package_ref(work_package_id)
    safe_file_path = _validate_required_text(file_path, field_name="file_path", max_length=4096)
    safe_description = _validate_optional_text(description, field_name="description", max_length=10_000)
    return await _run_tool(
        client.attachment.create(
            work_package_id=safe_work_package_id,
            file_path=safe_file_path,
            description=safe_description,
            confirm=confirm,
        )
    )


@register_tool
async def delete_attachment(
    ctx: Context,
    attachment_id: int,
    confirm: bool = False,
) -> AttachmentWriteResult:
    """Prepare or delete an attachment."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(attachment_id, field_name="attachment_id")
    return await _run_tool(client.attachment.delete(attachment_id=safe_id, confirm=confirm))


@register_tool
async def list_work_package_file_links(
    ctx: Context,
    work_package_id: int | str,
    select: list[str] | None = None,
) -> FileLinkListResult:
    """List Nextcloud file links attached to a work package (Community Edition).

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.

    select fields: id, title (see server instructions for select's general semantics).
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    _validate_select(select, row_type=FileLinkSummary)
    return await _run_tool(client.file_link.list_for_work_package(safe_id))


@register_tool
async def delete_file_link(
    ctx: Context,
    file_link_id: int,
    confirm: bool = False,
) -> FileLinkWriteResult:
    """Prepare or delete a Nextcloud file link."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(file_link_id, field_name="file_link_id")
    return await _run_tool(client.file_link.delete(safe_id, confirm=confirm))
