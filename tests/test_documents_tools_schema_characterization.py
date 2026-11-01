"""Characterization test: freezes the 13 Documents/News/Wiki MCP tool schemas.

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
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _tools(mcp) -> dict:
    return {t.name: t for t in mcp._tool_manager.list_tools()}


def test_list_documents_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_documents"]
    assert (
        tool.description
        == "List documents, optionally filtered to a single project or by title search.\n\ntotal is only the count of allowed documents returned on THIS page, not a full count of all matches; the search\nstops as soon as it has enough, so an exact total would need an extra full walk. Page until next_offset is null.\n\ntext_limit caps each document's description at that many characters\n(default: the server's configured OPENPROJECT_TEXT_LIMIT, NOT unlimited --\nunlike get_document's single-item default). When text is cut,\ndescription_truncated is true and description_length reports the real\nlength.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Project identifier, id, or name; a unique part of a name or identifier also matches.",
                "title": "Project",
            },
            "search": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Search"},
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
                "description": "Fields to return; a requested unset field comes back as null. Allowed: attachment_count, can_update, created_at, description, description_length, description_truncated, id, project, project_id, title.",
                "title": "Select",
            },
            "text_limit": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": None, "title": "Text Limit"},
        },
        "title": "list_documentsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["project", "search", "offset", "limit", "select", "text_limit"]


def test_get_document_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_document"]
    assert (
        tool.description
        == "Get a single document by id.\n\nThe description is returned in full by default (single documents are not\ntruncated). Pass ``text_limit`` to cap it at that many characters; when the\ntext is cut, ``description_truncated`` is true and ``description_length``\nreports the real length.\n"
    )
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
            "project_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Project Id",
            },
            "project": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Project",
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
            "attachment_count": {
                "title": "Attachment Count",
                "type": "integer",
            },
            "can_update": {
                "title": "Can Update",
                "type": "boolean",
            },
            "description_truncated": {
                "default": False,
                "title": "Description Truncated",
                "type": "boolean",
            },
            "description_length": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Description Length",
            },
        },
        "required": [
            "id",
            "title",
            "project_id",
            "project",
            "description",
            "created_at",
            "attachment_count",
            "can_update",
        ],
        "title": "DocumentDetail",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {
            "document_id": {
                "title": "Document Id",
                "type": "integer",
            },
            "text_limit": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Text Limit",
            },
        },
        "required": ["document_id"],
        "title": "get_documentArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["document_id", "text_limit"]


def test_update_document_schema() -> None:
    tool = _tools(create_app(_make_settings()))["update_document"]
    assert tool.description == "Update a document. Omitted fields stay unchanged."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "document_id": {
                "description": "Numeric document id, as returned by list_documents.",
                "title": "Document Id",
                "type": "integer",
            },
            "title": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "At most 255 characters.",
                "title": "Title",
            },
            "description": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": 'Document text; "" clears it.',
                "title": "Description",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["document_id"],
        "title": "update_documentArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["document_id", "title", "description", "confirm"]


def test_list_news_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_news"]
    assert (
        tool.description
        == "List news entries, optionally filtered by project or title/summary search.\n\ntotal is only the count of allowed news entries returned on THIS page, not a full count of all matches; the\nsearch stops as soon as it has enough, so an exact total would need an extra full walk. Page until next_offset\nis null.\n\ntext_limit caps each entry's summary/description at that many characters\n(default: the server's configured OPENPROJECT_TEXT_LIMIT, NOT unlimited --\nunlike get_news's single-item default). When text is cut,\ndescription_truncated is true and description_length reports the real\nlength.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {
                "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Project identifier, id, or name; a unique part of a name or identifier also matches.",
                "title": "Project",
            },
            "search": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Search"},
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
                "description": "Fields to return; a requested unset field comes back as null. Allowed: author, can_delete, can_update, created_at, description, description_length, description_truncated, id, project, project_id, summary, title.",
                "title": "Select",
            },
            "text_limit": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": None, "title": "Text Limit"},
        },
        "title": "list_newsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["project", "search", "offset", "limit", "select", "text_limit"]


def test_get_news_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_news"]
    assert (
        tool.description
        == "Get a single news entry by id.\n\nThe description is returned in full by default (single news entries are\nnot truncated). Pass ``text_limit`` to cap it at that many characters;\nwhen the text is cut, ``description_truncated`` is true and\n``description_length`` reports the real length.\n"
    )
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
            "summary": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Summary",
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
            "project_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Project Id",
            },
            "project": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Project",
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
            "can_update": {
                "title": "Can Update",
                "type": "boolean",
            },
            "can_delete": {
                "title": "Can Delete",
                "type": "boolean",
            },
            "description_truncated": {
                "default": False,
                "title": "Description Truncated",
                "type": "boolean",
            },
            "description_length": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Description Length",
            },
        },
        "required": [
            "id",
            "title",
            "summary",
            "description",
            "project_id",
            "project",
            "author",
            "created_at",
            "can_update",
            "can_delete",
        ],
        "title": "NewsDetail",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {
            "news_id": {
                "title": "News Id",
                "type": "integer",
            },
            "text_limit": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Text Limit",
            },
        },
        "required": ["news_id"],
        "title": "get_newsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["news_id", "text_limit"]


def test_create_news_schema() -> None:
    tool = _tools(create_app(_make_settings()))["create_news"]
    assert tool.description == "Create a news entry inside a project."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {
                "anyOf": [{"type": "integer"}, {"type": "string"}],
                "description": "Project identifier, id, or name; a unique part of a name or identifier also matches.",
                "title": "Project",
            },
            "title": {"description": "At most 255 characters.", "title": "Title", "type": "string"},
            "summary": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Short plain text, at most 500 characters.",
                "title": "Summary",
            },
            "description": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "Full text in Markdown.",
                "title": "Description",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["project", "title"],
        "title": "create_newsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["project", "title", "summary", "description", "confirm"]


def test_update_news_schema() -> None:
    tool = _tools(create_app(_make_settings()))["update_news"]
    assert tool.description == "Update a news entry. Omitted fields stay unchanged."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "news_id": {
                "description": "Numeric news id, as returned by list_news.",
                "title": "News Id",
                "type": "integer",
            },
            "title": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "At most 255 characters.",
                "title": "Title",
            },
            "summary": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": 'Short plain text, at most 500 characters; "" clears it.',
                "title": "Summary",
            },
            "description": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": 'Full text in Markdown; "" clears it.',
                "title": "Description",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["news_id"],
        "title": "update_newsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["news_id", "title", "summary", "description", "confirm"]


def test_delete_news_schema() -> None:
    tool = _tools(create_app(_make_settings()))["delete_news"]
    assert tool.description == "Delete a news entry with its comments and attachments; this cannot be undone."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "news_id": {
                "description": "Numeric news id, as returned by list_news.",
                "title": "News Id",
                "type": "integer",
            },
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["news_id"],
        "title": "delete_newsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["news_id", "confirm"]


def test_get_wiki_page_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_wiki_page"]
    assert (
        tool.description
        == "Get a single wiki page's metadata (id, title, project) by id.\n\nOpenProject's REST API v3 does not expose a wiki page's body text at\nall -- GET /api/v3/wiki_pages/{id} returns only id/title/project, and\nthere is no other route that returns the page content. This tool\ntherefore cannot return wiki page text; use the OpenProject web UI to\nread a page's content.\n"
    )
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
            "project_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Project Id",
            },
            "project": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Project",
            },
        },
        "required": ["id", "title", "project_id", "project"],
        "title": "WikiPageDetail",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {
            "wiki_page_id": {
                "title": "Wiki Page Id",
                "type": "integer",
            },
        },
        "required": ["wiki_page_id"],
        "title": "get_wiki_pageArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["wiki_page_id"]


def test_get_post_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_post"]
    assert (
        tool.description
        == "Get a single forum post by id.\n\nOpenProject's API exposes exactly one route for posts:\nGET /api/v3/posts/{id}. There is no collection/list endpoint for posts or\nforums at all in OpenProject's REST API -- a post's id must therefore\ncome from elsewhere (e.g. a work package's activity/journal referencing\na forum post, or a link copied from the OpenProject web UI). This MCP\ndoes not and cannot provide a list_posts or list_forums tool.\n"
    )
    assert tool.output_schema == {
        "properties": {
            "id": {
                "title": "Id",
                "type": "integer",
            },
            "subject": {
                "title": "Subject",
                "type": "string",
            },
            "project_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Project Id",
            },
            "project": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Project",
            },
        },
        "required": ["id", "subject", "project_id", "project"],
        "title": "PostDetail",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {
            "post_id": {
                "title": "Post Id",
                "type": "integer",
            },
        },
        "required": ["post_id"],
        "title": "get_postArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["post_id"]


def test_list_work_package_wiki_links_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_work_package_wiki_links"]
    assert (
        tool.description
        == "List wiki pages linked to a work package.\n\nRequires OpenProject 17.5+; on an older server this returns a [not_found]\nnaming the required version.\n\nKnown OpenProject server bug (17.5 to at least 17.9.1): this call returns\na [server_error] when none of the work package's links\nresolves to a wiki page the user can see, and on 17.5/17.6 also when the\nwork package has no links. A link to the internal wiki resolves when its\nidentifier is the page's numeric id.\n\nOnly the work package is checked against OPENPROJECT_READ_PROJECTS: a link\ncarries no project, so a link to a page in another project is listed. It\nshows the identifier, provider and author, never the page's title or text.\n"
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
        },
        "required": ["work_package_id"],
        "title": "list_work_package_wiki_linksArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["work_package_id", "offset", "limit"]


def test_create_work_package_wiki_link_schema() -> None:
    tool = _tools(create_app(_make_settings()))["create_work_package_wiki_link"]
    assert (
        tool.description
        == "Create a link from a work package to a wiki page.\n\nRequires OpenProject 17.7+; on an older server this returns a [not_found]\nnaming the required version.\n\nidentifier: the target wiki page's identifier at its provider; for the\ninternal wiki, the page's numeric id (the wiki_page_id of get_wiki_page).\nOpenProject accepts any string, but list_work_package_wiki_links fails\nwhile none of a work package's links resolves to a page.\nprovider: the wiki provider's universal identifier (e.g. \"internal\" for\nOpenProject's built-in wiki).\nThe result names the work package the reference resolved to in `target`.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "work_package_id": {
                "anyOf": [{"type": "integer"}, {"type": "string"}],
                "description": 'Work package id (e.g. 952) or display id (e.g. "PROJ-51"), not the bare number 51.',
                "title": "Work Package Id",
            },
            "identifier": {"title": "Identifier", "type": "string"},
            "provider": {"title": "Provider", "type": "string"},
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["work_package_id", "identifier", "provider"],
        "title": "create_work_package_wiki_linkArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["work_package_id", "identifier", "provider", "confirm"]


def test_delete_work_package_wiki_link_schema() -> None:
    tool = _tools(create_app(_make_settings()))["delete_work_package_wiki_link"]
    assert (
        tool.description
        == "Delete a work package's wiki page link; this cannot be undone.\n\nRequires OpenProject 17.6+. On 17.4 or older this returns a [not_found]\nnaming 17.6; on 17.5 the link check below usually fails first with a\n[server_error].\n\nThis tool lists the work package's links first to verify that link_id\nbelongs to work_package_id (an authorization check), so it fails with a\n[server_error] whenever list_work_package_wiki_links does (see there).\n\nOnly relation links (link_type \"relation\") can be deleted. An inline\nlink comes from a wiki link in the work package's description or from a\nwiki page that mentions the work package; this tool rejects it with a\n[validation_error], and the link goes away only when that text changes.\nDeleting needs the \"Manage wiki page links\" permission in the work\npackage's project; without it OpenProject answers 404, which the tool\nreports as a [not_found] naming 17.6, not as [permission_denied].\n\nwork_package_id must be the work package the link belongs to; OpenProject has no single GET for a link,\nso the delete is authorized against that work package's project.\nlink_id: the wiki page link's own id, from list_work_package_wiki_links.\nThe result names the work package the reference resolved to in `target`.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "work_package_id": {
                "anyOf": [{"type": "integer"}, {"type": "string"}],
                "description": 'Work package id (e.g. 952) or display id (e.g. "PROJ-51"), not the bare number 51.',
                "title": "Work Package Id",
            },
            "link_id": {"title": "Link Id", "type": "integer"},
            "confirm": {
                "default": False,
                "description": "false: preview only, nothing changes. true: applies it; get the user's approval of the preview first.",
                "title": "Confirm",
                "type": "boolean",
            },
        },
        "required": ["work_package_id", "link_id"],
        "title": "delete_work_package_wiki_linkArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["work_package_id", "link_id", "confirm"]
