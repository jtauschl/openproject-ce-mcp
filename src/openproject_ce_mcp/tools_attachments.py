"""Attachments/file-links domain MCP tool handlers: list_work_package_attachments,
get_attachment, create_work_package_attachment, delete_attachment,
list_work_package_file_links, delete_file_link.

Attachments and Nextcloud file links share a domain because both are file
artifacts attached to a work package and neither requires a separate boundary.

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

import base64

from mcp.server.mcpserver import Context
from mcp.types import ImageContent, TextContent

from .models import (
    AttachmentContentOutcome,
    AttachmentListResult,
    AttachmentSummary,
    AttachmentWriteResult,
    FileLinkListResult,
    FileLinkSummary,
    FileLinkWriteResult,
)
from .presentation import ContentBundle
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


def _content_blocks(outcome: AttachmentContentOutcome) -> tuple[ImageContent | TextContent, ...]:
    """The native MCP block(s) for one AttachmentContentOutcome, or none.

    An image becomes an ImageContent block — base64 is how the MCP wire format
    carries image bytes, and the client turns it back into something the model
    can actually look at, which a base64 string in a JSON field would not be.
    Text goes back as text, never re-encoded.
    """
    if outcome.image_bytes is not None:
        return (
            ImageContent(
                type="image",
                data=base64.b64encode(outcome.image_bytes).decode("ascii"),
                # Guaranteed to be one of the four inlineable image types:
                # the Service only populates image_bytes after classifying it
                # as one of them.
                mime_type=outcome.metadata.content_type or "application/octet-stream",
            ),
        )
    if outcome.text is not None:
        # Same <user-content> delimiting every long-form user-authored field
        # (descriptions, comments, wiki text) gets: an attached .md or .json
        # is user-authored text handed straight to the model, so it is the
        # prompt-injection surface SECURITY.md describes. Inlined here rather
        # than via app/adapters/_text.delimit_user_content because the tool
        # layer may not import from app/.
        return (TextContent(type="text", text=f"<user-content>{outcome.text}</user-content>"),)
    return ()


@register_tool
async def get_attachment_content(
    ctx: Context,
    attachment_id: int,
    max_bytes: int | None = None,
) -> ContentBundle:
    """Read an attachment's actual content, not just its metadata.

    Returns a JSON block describing the outcome, followed by the content
    itself as a native block when it can be inlined:

    - PNG/JPEG/GIF/WebP come back as an image the model can see
    - text-like content (text/*, JSON, XML) comes back as text, cut at the
      byte limit if it is long (outcome "text", truncated=true)
    - an image over the byte limit is refused whole rather than returned
      partially (outcome "too_large")
    - anything else returns metadata only (outcome "not_inline_supported") —
      no bytes, since no MCP client could display them; content_type there is
      the attachment's stored type, which names the file where the served
      header only says "not inlineable"

    max_bytes may only LOWER the server's configured limit
    (OPENPROJECT_ATTACHMENT_CONTENT_MAX_BYTES, 5 MB by default), never raise it.

    size_bytes is the size of the returned content block, and is null if
    file_size_bytes is hidden by server configuration, rather than leaking it
    indirectly under another name.

    Nothing is written to disk. Use get_attachment for metadata alone.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(attachment_id, field_name="attachment_id")
    safe_max_bytes = None if max_bytes is None else _validate_positive_int(max_bytes, field_name="max_bytes")
    outcome = await _run_tool(client.attachment.get_content(safe_id, max_bytes=safe_max_bytes))
    return ContentBundle(body=outcome.metadata, blocks=_content_blocks(outcome))


@register_tool
async def list_work_package_attachments(
    ctx: Context,
    work_package_id: int | str,
    offset: int = 1,
    limit: int | None = None,
    select: list[str] | None = None,
    include_total_size: bool = False,
    include_images: bool = False,
) -> AttachmentListResult | ContentBundle:
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

    include_images=true also reads the listed PNG/JPEG/GIF/WebP attachments
    and returns them as images the model can see, appended after the list.
    One shared byte budget covers the whole call
    (OPENPROJECT_ATTACHMENT_CONTENT_MAX_BYTES, 5 MB by default), taken in
    listing order; every attachment that was not inlined is reported in
    `images` with its reason. Use get_attachment_content for one specific
    attachment, or for text content.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    _validate_select(select, row_type=AttachmentSummary)
    if not include_images:
        return await _run_tool(
            client.attachment.list_for_work_package(
                safe_id, offset=safe_offset, limit=safe_limit, include_total_size=include_total_size
            )
        )
    listing = await _run_tool(
        client.attachment.list_for_work_package_with_images(
            safe_id, offset=safe_offset, limit=safe_limit, include_total_size=include_total_size
        )
    )
    blocks = tuple(block for outcome in listing.included for block in _content_blocks(outcome))
    return ContentBundle(body=listing.list_result, blocks=blocks)


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
