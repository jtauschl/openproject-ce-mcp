"""Attachments/file-links domain MCP tool handlers: list_work_package_attachments,
get_attachment, create_work_package_attachment, delete_attachment,
list_container_attachments, create_container_attachment,
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

`list_container_attachments`/`create_container_attachment` cover the other
containers OpenProject attaches files to (wiki pages, forum posts, meetings,
comments). Listing belongs to the work-package read group; each call also
checks the container's own scope flag and project allowlist.

Upload registration stays in `tools.py`: `WORK_PACKAGE_UPLOAD_TOOLS` requires
work-package writes, while `CONTAINER_UPLOAD_TOOLS` requires any of
`CONTAINER_UPLOAD_WRITE_SCOPES`. Both require `OPENPROJECT_ATTACHMENT_ROOT`
and usable project read/write allowlists. A container upload also checks its
own write scope at execution time.

"""

from __future__ import annotations

import base64
from typing import Annotated

from mcp.server.mcpserver import Context
from mcp.types import ImageContent, TextContent
from pydantic import Field

from .models import (
    AttachmentContentOutcome,
    AttachmentListResult,
    AttachmentSummary,
    AttachmentWriteResult,
    ContainerAttachmentWriteResult,
    FileLinkListResult,
    FileLinkSummary,
    FileLinkWriteResult,
)
from .presentation import ContentBundle
from .tool_params import Confirm, ExpectDisplayId, Limit, Offset, WorkPackageRef, select_field
from .tools_runtime import _client_from_context, _run_tool, register_tool
from .tools_validation import (
    _validate_choice,
    _validate_expect_display_id,
    _validate_limit,
    _validate_offset,
    _validate_optional_text,
    _validate_positive_int,
    _validate_required_text,
    _validate_select,
    _validate_work_package_ref,
)
from .user_content import delimit_user_content

#: container_type values of list_container_attachments/create_container_attachment.
ATTACHMENT_CONTAINER_TYPES = {"wiki_page", "post", "meeting", "activity"}
_CONTAINER_TYPE = (
    "wiki_page, post (forum message), meeting, or activity (a work package comment, by its activity id from "
    "get_work_package_activities)."
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
        # An attached .md or .json is user-authored text handed straight to the model, so it is
        # the prompt-injection surface SECURITY.md describes and gets the same delimiter as a
        # description or comment.
        return (TextContent(type="text", text=delimit_user_content(outcome.text)),)
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
    - anything else returns metadata only (outcome "not_inline_supported");
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
    work_package_id: WorkPackageRef,
    offset: Offset = 1,
    limit: Limit = None,
    select: Annotated[list[str] | None, select_field(AttachmentSummary)] = None,
    include_total_size: bool = False,
    include_images: bool = False,
) -> AttachmentListResult | ContentBundle:
    """List attachments on a work package.

    include_total_size=true sums file_size_bytes across every attachment
    (independent of limit/offset); OpenProject's attachments endpoint
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
    work_package_id: WorkPackageRef,
    file_path: Annotated[
        str,
        Field(
            description="Path on the MCP server's machine, inside OPENPROJECT_ATTACHMENT_ROOT; uploaded under its file name."
        ),
    ],
    description: Annotated[str | None, Field(description="Markdown text stored with the attachment.")] = None,
    expect_display_id: ExpectDisplayId = None,
    confirm: Confirm = False,
) -> AttachmentWriteResult:
    """Upload a local file as an attachment to a work package.

    The preview checks that the file exists inside OPENPROJECT_ATTACHMENT_ROOT, is not a credential or
    configuration file, and fits OpenProject's maximum attachment size. For wiki pages, forum posts, meetings
    or comments use create_container_attachment.
    expect_display_id names the ticket you mean and makes a mismatch an error; see the server instructions.
    The result names the work package the reference resolved to in `target`.
    """
    client = _client_from_context(ctx)
    safe_work_package_id = _validate_work_package_ref(work_package_id)
    safe_expect = _validate_expect_display_id(expect_display_id)
    safe_file_path = _validate_required_text(file_path, field_name="file_path", max_length=4096)
    safe_description = _validate_optional_text(
        description, field_name="description", max_length=None, wrapped_on_read=True
    )
    return await _run_tool(
        client.attachment.create(
            work_package_id=safe_work_package_id,
            file_path=safe_file_path,
            description=safe_description,
            expect_display_id=safe_expect,
            confirm=confirm,
        )
    )


@register_tool
async def delete_attachment(
    ctx: Context,
    attachment_id: Annotated[int, Field(description="Attachment id, from list_work_package_attachments.")],
    confirm: Confirm = False,
) -> AttachmentWriteResult:
    """Delete an attachment; this cannot be undone."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(attachment_id, field_name="attachment_id")
    return await _run_tool(client.attachment.delete(attachment_id=safe_id, confirm=confirm))


@register_tool
async def list_work_package_file_links(
    ctx: Context,
    work_package_id: WorkPackageRef,
    offset: Offset = 1,
    limit: Limit = None,
    select: Annotated[list[str] | None, select_field(FileLinkSummary)] = None,
) -> FileLinkListResult:
    """List Nextcloud file links attached to a work package (Community Edition).

    For files uploaded to OpenProject itself, use list_work_package_attachments."""
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    _validate_select(select, row_type=FileLinkSummary)
    return await _run_tool(client.file_link.list_for_work_package(safe_id, offset=safe_offset, limit=safe_limit))


@register_tool
async def delete_file_link(
    ctx: Context,
    file_link_id: Annotated[int, Field(description="File link id, from list_work_package_file_links.")],
    confirm: Confirm = False,
) -> FileLinkWriteResult:
    """Delete a file link; this cannot be undone, but the file itself stays in the external storage."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(file_link_id, field_name="file_link_id")
    return await _run_tool(client.file_link.delete(safe_id, confirm=confirm))


@register_tool
async def list_container_attachments(
    ctx: Context,
    container_type: Annotated[str, Field(description=_CONTAINER_TYPE)],
    container_id: Annotated[int, Field(description="Numeric id of that wiki page, post, meeting or activity.")],
    offset: Offset = 1,
    limit: Limit = None,
    select: Annotated[list[str] | None, select_field(AttachmentSummary)] = None,
) -> AttachmentListResult:
    """List attachments on a wiki page, forum post, meeting or comment.

    For work packages themselves use list_work_package_attachments. The
    container's project must be inside OPENPROJECT_READ_PROJECTS (a comment's
    is its work package's). get_attachment/get_attachment_content/delete_attachment
    stay limited to work package attachments; download_url opens any of these
    in a browser.
    """
    client = _client_from_context(ctx)
    safe_type = _validate_choice(container_type, field_name="container_type", allowed_values=ATTACHMENT_CONTAINER_TYPES)
    safe_id = _validate_positive_int(container_id, field_name="container_id")
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    _validate_select(select, row_type=AttachmentSummary)
    return await _run_tool(
        client.attachment.list_for_container(safe_type, safe_id, offset=safe_offset, limit=safe_limit)
    )


@register_tool
async def create_container_attachment(
    ctx: Context,
    container_type: Annotated[str, Field(description=_CONTAINER_TYPE)],
    container_id: Annotated[int, Field(description="Numeric id of that wiki page, post, meeting or activity.")],
    file_path: Annotated[
        str,
        Field(
            description="Path on the MCP server's machine, inside OPENPROJECT_ATTACHMENT_ROOT; uploaded under its file name."
        ),
    ],
    description: Annotated[str | None, Field(description="Markdown text stored with the attachment.")] = None,
    confirm: Confirm = False,
) -> ContainerAttachmentWriteResult:
    """Upload an attachment to a wiki page, forum post, meeting or comment.

    For work packages themselves use create_work_package_attachment. The
    container's project must be inside OPENPROJECT_WRITE_PROJECTS; the write
    flag checked is the container's own (project for wiki pages and posts,
    meeting for meetings, work package for comments).
    """
    client = _client_from_context(ctx)
    safe_type = _validate_choice(container_type, field_name="container_type", allowed_values=ATTACHMENT_CONTAINER_TYPES)
    safe_id = _validate_positive_int(container_id, field_name="container_id")
    safe_file_path = _validate_required_text(file_path, field_name="file_path", max_length=4096)
    safe_description = _validate_optional_text(
        description, field_name="description", max_length=None, wrapped_on_read=True
    )
    return await _run_tool(
        client.attachment.create_for_container(
            container_type=safe_type,
            container_id=safe_id,
            file_path=safe_file_path,
            description=safe_description,
            confirm=confirm,
        )
    )
