"""Characterization test: freezes the 7 Attachments/File Links MCP tool schemas.

Proves that where these tool functions live (tools.py vs. their own per-domain
file) has zero effect on what an MCP client actually sees -- parameter names/
order/types, descriptions, required fields, and whether the tool carries an
output_schema (trimmed tools register with structured_output=False and have
none, see test_trimming.py). A future relocation of any of these functions to
a different module must leave this file completely unmodified; a diff to it
would mean the move changed the public tool contract, not just its location.
"""

from __future__ import annotations

from openproject_ce_mcp.config import Settings
from openproject_ce_mcp.server import create_app


def _make_settings(**overrides) -> Settings:
    defaults = {
        "base_url": "https://op.example.com",
        "api_token": "token",
        "timeout": 12,
        "verify_ssl": True,
        "default_page_size": 20,
        "max_page_size": 50,
        "max_results": 100,
        "log_level": "WARNING",
        "enable_work_package_write": True,
        "enable_project_write": True,
        "enable_membership_write": True,
        "enable_version_write": True,
        "enable_board_write": True,
        "enable_admin_write": True,
        "read_projects": ("*",),
        "write_projects": ("*",),
        "enable_metadata_tools": True,
        "attachment_root": "/tmp/op-attachments",
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _tools(mcp) -> dict:
    return {t.name: t for t in mcp._tool_manager.list_tools()}


def test_list_work_package_attachments_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_work_package_attachments"]
    assert (
        tool.description
        == "List attachments on a work package.\n\ninclude_total_size=true sums file_size_bytes across every attachment\n(independent of limit/offset); OpenProject's attachments endpoint\nalways returns the full list in one response, so this costs no extra\nrequest in the common case. Null if file_size_bytes is hidden by\nserver configuration, rather than leaking it indirectly through a sum.\n\ninclude_images=true also reads the listed PNG/JPEG/GIF/WebP attachments\nand returns them as images the model can see, appended after the list.\nOne shared byte budget covers the whole call\n(OPENPROJECT_ATTACHMENT_CONTENT_MAX_BYTES, 5 MB by default), taken in\nlisting order; every attachment that was not inlined is reported in\n`images` with its reason. Use get_attachment_content for one specific\nattachment, or for text content.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "work_package_id": {
                "anyOf": [{"type": "integer"}, {"type": "string"}],
                "description": 'Work package id (e.g. 952) or display id (e.g. "PROJ-51"), not the bare number 51.',
                "title": "Work Package Id",
            },
            "offset": {
                "default": 1,
                "description": "1-based page number; pass the previous result's next_offset.",
                "title": "Offset",
                "type": "integer",
            },
            "limit": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "description": "Page size, capped at OPENPROJECT_MAX_PAGE_SIZE.",
                "title": "Limit",
            },
            "select": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "description": "Fields to return; a requested unset field comes back as null. Allowed: author, container_id, container_type, content_type, created_at, description, download_url, file_name, file_size_bytes, id, status, title.",
                "title": "Select",
            },
            "include_total_size": {"default": False, "title": "Include Total Size", "type": "boolean"},
            "include_images": {"default": False, "title": "Include Images", "type": "boolean"},
        },
        "required": ["work_package_id"],
        "title": "list_work_package_attachmentsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "work_package_id",
        "offset",
        "limit",
        "select",
        "include_total_size",
        "include_images",
    ]


def test_get_attachment_content_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_attachment_content"]
    assert (
        tool.description
        == 'Read an attachment\'s actual content, not just its metadata.\n\nReturns a JSON block describing the outcome, followed by the content\nitself as a native block when it can be inlined:\n\n- PNG/JPEG/GIF/WebP come back as an image the model can see\n- text-like content (text/*, JSON, XML) comes back as text, cut at the\n  byte limit if it is long (outcome "text", truncated=true)\n- an image over the byte limit is refused whole rather than returned\n  partially (outcome "too_large")\n- anything else returns metadata only (outcome "not_inline_supported");\n  no bytes, since no MCP client could display them; content_type there is\n  the attachment\'s stored type, which names the file where the served\n  header only says "not inlineable"\n\nmax_bytes may only LOWER the server\'s configured limit\n(OPENPROJECT_ATTACHMENT_CONTENT_MAX_BYTES, 5 MB by default), never raise it.\n\nsize_bytes is the size of the returned content block, and is null if\nfile_size_bytes is hidden by server configuration, rather than leaking it\nindirectly under another name.\n\nNothing is written to disk. Use get_attachment for metadata alone.\n'
    )
    # Returns a ContentBundle (native content blocks after a JSON block), so it
    # is registered through the trimming wrapper with structured_output=False
    # and carries no output schema -- see presentation.ContentBundle.
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "attachment_id": {"title": "Attachment Id", "type": "integer"},
            "max_bytes": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": None, "title": "Max Bytes"},
        },
        "required": ["attachment_id"],
        "title": "get_attachment_contentArguments",
        "type": "object",
        "additionalProperties": False,
    }
    assert list(tool.parameters["properties"]) == ["attachment_id", "max_bytes"]


def test_get_attachment_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_attachment"]
    assert tool.description == "Get a single attachment by id."
    assert tool.output_schema == {
        "properties": {
            "id": {
                "title": "Id",
                "type": "integer",
            },
            "title": {
                "title": "Title",
                "type": "string",
            },
            "file_name": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "File Name",
            },
            "file_size_bytes": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "File Size Bytes",
            },
            "description": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Description",
            },
            "content_type": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Content Type",
            },
            "status": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Status",
            },
            "author": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Author",
            },
            "container_type": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Container Type",
            },
            "container_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Container Id",
            },
            "created_at": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Created At",
            },
            "download_url": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Download Url",
            },
        },
        "required": [
            "id",
            "title",
            "file_name",
            "file_size_bytes",
            "description",
            "content_type",
            "status",
            "author",
            "container_type",
            "container_id",
            "created_at",
            "download_url",
        ],
        "title": "AttachmentSummary",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {
            "attachment_id": {
                "title": "Attachment Id",
                "type": "integer",
            },
        },
        "required": ["attachment_id"],
        "title": "get_attachmentArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["attachment_id"]


def test_create_work_package_attachment_schema() -> None:
    tool = _tools(create_app(_make_settings()))["create_work_package_attachment"]
    assert (
        tool.description
        == "Upload a local file as an attachment to a work package.\n\nThe preview checks that the file exists inside OPENPROJECT_ATTACHMENT_ROOT, is not a credential or\nconfiguration file, and fits OpenProject's maximum attachment size. For wiki pages, forum posts, meetings\nor comments use create_container_attachment.\nexpect_display_id names the ticket you mean and makes a mismatch an error; see the server instructions.\nThe result names the work package the reference resolved to in `target`.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "work_package_id": {
                "anyOf": [{"type": "integer"}, {"type": "string"}],
                "description": 'Work package id (e.g. 952) or display id (e.g. "PROJ-51"), not the bare number 51.',
                "title": "Work Package Id",
            },
            "file_path": {
                "description": "Path on the MCP server's machine, inside OPENPROJECT_ATTACHMENT_ROOT; uploaded under its file name.",
                "title": "File Path",
                "type": "string",
            },
            "description": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Markdown text stored with the attachment.",
                "title": "Description",
            },
            "expect_display_id": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": 'Display id of the work package you mean, e.g. "PROJ-51"; see the server instructions.',
                "title": "Expect Display Id",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["work_package_id", "file_path"],
        "title": "create_work_package_attachmentArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "work_package_id",
        "file_path",
        "description",
        "expect_display_id",
        "confirm",
    ]


def test_delete_attachment_schema() -> None:
    tool = _tools(create_app(_make_settings()))["delete_attachment"]
    assert tool.description == "Delete an attachment; this cannot be undone."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "attachment_id": {
                "description": "Attachment id, from list_work_package_attachments.",
                "title": "Attachment Id",
                "type": "integer",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["attachment_id"],
        "title": "delete_attachmentArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["attachment_id", "confirm"]


def test_list_container_attachments_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_container_attachments"]
    assert (
        tool.description
        == "List attachments on a wiki page, forum post, meeting or comment.\n\nFor work packages themselves use list_work_package_attachments. The\ncontainer's project must be inside OPENPROJECT_READ_PROJECTS (a comment's\nis its work package's). get_attachment/get_attachment_content/delete_attachment\nstay limited to work package attachments; download_url opens any of these\nin a browser.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "container_type": {
                "description": "wiki_page, post (forum message), meeting, or activity (a work package comment, by its activity id from get_work_package_activities).",
                "title": "Container Type",
                "type": "string",
            },
            "container_id": {
                "description": "Numeric id of that wiki page, post, meeting or activity.",
                "title": "Container Id",
                "type": "integer",
            },
            "offset": {
                "default": 1,
                "description": "1-based page number; pass the previous result's next_offset.",
                "title": "Offset",
                "type": "integer",
            },
            "limit": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "description": "Page size, capped at OPENPROJECT_MAX_PAGE_SIZE.",
                "title": "Limit",
            },
            "select": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "description": "Fields to return; a requested unset field comes back as null. Allowed: author, container_id, container_type, content_type, created_at, description, download_url, file_name, file_size_bytes, id, status, title.",
                "title": "Select",
            },
        },
        "required": ["container_type", "container_id"],
        "title": "list_container_attachmentsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["container_type", "container_id", "offset", "limit", "select"]


def test_create_container_attachment_schema() -> None:
    tool = _tools(create_app(_make_settings()))["create_container_attachment"]
    assert (
        tool.description
        == "Upload an attachment to a wiki page, forum post, meeting or comment.\n\nFor work packages themselves use create_work_package_attachment. The\ncontainer's project must be inside OPENPROJECT_WRITE_PROJECTS; the write\nflag checked is the container's own (project for wiki pages and posts,\nmeeting for meetings, work package for comments).\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "container_type": {
                "description": "wiki_page, post (forum message), meeting, or activity (a work package comment, by its activity id from get_work_package_activities).",
                "title": "Container Type",
                "type": "string",
            },
            "container_id": {
                "description": "Numeric id of that wiki page, post, meeting or activity.",
                "title": "Container Id",
                "type": "integer",
            },
            "file_path": {
                "description": "Path on the MCP server's machine, inside OPENPROJECT_ATTACHMENT_ROOT; uploaded under its file name.",
                "title": "File Path",
                "type": "string",
            },
            "description": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Markdown text stored with the attachment.",
                "title": "Description",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["container_type", "container_id", "file_path"],
        "title": "create_container_attachmentArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == [
        "container_type",
        "container_id",
        "file_path",
        "description",
        "confirm",
    ]


def test_list_work_package_file_links_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_work_package_file_links"]
    assert (
        tool.description
        == "List Nextcloud file links attached to a work package (Community Edition).\n\nFor files uploaded to OpenProject itself, use list_work_package_attachments."
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "work_package_id": {
                "anyOf": [{"type": "integer"}, {"type": "string"}],
                "description": 'Work package id (e.g. 952) or display id (e.g. "PROJ-51"), not the bare number 51.',
                "title": "Work Package Id",
            },
            "offset": {
                "default": 1,
                "description": "1-based page number; pass the previous result's next_offset.",
                "title": "Offset",
                "type": "integer",
            },
            "limit": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "description": "Page size, capped at OPENPROJECT_MAX_PAGE_SIZE.",
                "title": "Limit",
            },
            "select": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "description": "Fields to return; a requested unset field comes back as null. Allowed: created_at, id, storage_id, storage_name, title, updated_at.",
                "title": "Select",
            },
        },
        "required": ["work_package_id"],
        "title": "list_work_package_file_linksArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["work_package_id", "offset", "limit", "select"]


def test_delete_file_link_schema() -> None:
    tool = _tools(create_app(_make_settings()))["delete_file_link"]
    assert (
        tool.description
        == "Delete a file link; this cannot be undone, but the file itself stays in the external storage."
    )
    assert tool.output_schema == {
        "$defs": {
            "FileLinkSummary": {
                "properties": {
                    "id": {
                        "title": "Id",
                        "type": "integer",
                    },
                    "title": {
                        "title": "Title",
                        "type": "string",
                    },
                    "storage_id": {
                        "anyOf": [
                            {
                                "type": "integer",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "title": "Storage Id",
                    },
                    "storage_name": {
                        "anyOf": [
                            {
                                "type": "string",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "title": "Storage Name",
                    },
                    "created_at": {
                        "anyOf": [
                            {
                                "type": "string",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "title": "Created At",
                    },
                    "updated_at": {
                        "anyOf": [
                            {
                                "type": "string",
                            },
                            {
                                "type": "null",
                            },
                        ],
                        "title": "Updated At",
                    },
                },
                "required": ["id", "title", "storage_id", "storage_name", "created_at", "updated_at"],
                "title": "FileLinkSummary",
                "type": "object",
            },
        },
        "properties": {
            "action": {
                "title": "Action",
                "type": "string",
            },
            "state": {
                "enum": ["rejected", "invalid", "preview", "confirmed"],
                "title": "State",
                "type": "string",
            },
            "ready": {
                "title": "Ready",
                "type": "boolean",
            },
            "message": {
                "title": "Message",
                "type": "string",
            },
            "file_link_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "File Link Id",
            },
            "work_package_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Work Package Id",
            },
            "validation_errors": {
                "additionalProperties": True,
                "title": "Validation Errors",
                "type": "object",
            },
            "result": {
                "anyOf": [
                    {
                        "$ref": "#/$defs/FileLinkSummary",
                    },
                    {
                        "type": "null",
                    },
                ],
            },
        },
        "required": [
            "action",
            "state",
            "ready",
            "message",
            "file_link_id",
            "work_package_id",
            "validation_errors",
            "result",
        ],
        "title": "FileLinkWriteResult",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {
            "file_link_id": {
                "description": "File link id, from list_work_package_file_links.",
                "title": "File Link Id",
                "type": "integer",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["file_link_id"],
        "title": "delete_file_linkArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["file_link_id", "confirm"]
