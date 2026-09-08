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
        == "List documents, optionally filtered to a single project or by title search.\n\nselect fields: id, title (see server instructions for select's general semantics).\n\nlimit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned\nnext_offset as the next call's offset to page past the cap. total is only\nthe count of allowed documents returned on THIS page, not a full count of\nall matches — the search stops as soon as it has enough, so an exact\ntotal would need an extra full walk. Page until next_offset is null.\n\ntext_limit caps each document's description at that many characters\n(default: the server's configured OPENPROJECT_TEXT_LIMIT, NOT unlimited --\nunlike get_document's single-item default). When text is cut,\ndescription_truncated is true and description_length reports the real\nlength.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Project",
            },
            "search": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Search",
            },
            "offset": {
                "default": 1,
                "title": "Offset",
                "type": "integer",
            },
            "limit": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Limit",
            },
            "select": {
                "anyOf": [
                    {
                        "items": {
                            "type": "string",
                        },
                        "type": "array",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Select",
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
    assert tool.description == (
        "Prepare or update a document.\n\n"
        "WARNING -- known OpenProject server bug (reported upstream, not fixed as\n"
        "of this writing: community.openproject.org/wp/19876,\n"
        "github.com/opf/openproject/pull/24769): setting description corrupts the\n"
        "stored value into a literal, unusable string on every currently\n"
        "supported OpenProject version. The description you see echoed back\n"
        "immediately after a confirmed update looks correct, but the value\n"
        "actually persisted server-side is broken -- this is a server-side\n"
        "parsing defect, not something this client can work around. Avoid using\n"
        "description here until the upstream fix ships; title alone is\n"
        "unaffected.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "document_id": {
                "title": "Document Id",
                "type": "integer",
            },
            "title": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Title",
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
                "default": None,
                "title": "Description",
            },
            "confirm": {
                "default": False,
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
        == "List news entries, optionally filtered by project or title/summary search.\n\nselect fields: id, title (see server instructions for select's general semantics).\n\nlimit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned\nnext_offset as the next call's offset to page past the cap. total is only\nthe count of allowed news entries returned on THIS page, not a full\ncount of all matches — the search stops as soon as it has enough, so an\nexact total would need an extra full walk. Page until next_offset is\nnull.\n\ntext_limit caps each entry's summary/description at that many characters\n(default: the server's configured OPENPROJECT_TEXT_LIMIT, NOT unlimited --\nunlike get_news's single-item default). When text is cut,\ndescription_truncated is true and description_length reports the real\nlength.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Project",
            },
            "search": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Search",
            },
            "offset": {
                "default": 1,
                "title": "Offset",
                "type": "integer",
            },
            "limit": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Limit",
            },
            "select": {
                "anyOf": [
                    {
                        "items": {
                            "type": "string",
                        },
                        "type": "array",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Select",
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
    assert tool.description == "Prepare or create a news entry inside a project."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "project": {
                "title": "Project",
                "type": "string",
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
                "default": None,
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
                "default": None,
                "title": "Description",
            },
            "confirm": {
                "default": False,
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
    assert tool.description == "Prepare or update a news entry."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "news_id": {
                "title": "News Id",
                "type": "integer",
            },
            "title": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
                "title": "Title",
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
                "default": None,
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
                "default": None,
                "title": "Description",
            },
            "confirm": {
                "default": False,
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
    assert tool.description == "Prepare or delete a news entry."
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "news_id": {
                "title": "News Id",
                "type": "integer",
            },
            "confirm": {
                "default": False,
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
        == 'List wiki pages linked to a work package.\n\nRequires OpenProject 17.6+ — the wiki_page_links endpoint does not exist\non earlier versions and returns a [server_error].\n\nKnown OpenProject server bug (confirmed on 16.6/17.6/17.7.1): this call\nreturns a [server_error] whenever the work package\nactually has one or more wiki page links — only the empty-list case\nreliably works. create_work_package_wiki_link/delete_work_package_wiki_link\nare unaffected and fully functional.\n\nwork_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.\n\nlimit is capped at OPENPROJECT_MAX_PAGE_SIZE (default 50); pass the returned\nnext_offset as the next call\'s offset to page past the cap.\n'
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "work_package_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "string",
                    },
                ],
                "title": "Work Package Id",
            },
            "offset": {
                "default": 1,
                "title": "Offset",
                "type": "integer",
            },
            "limit": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "default": None,
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
        == "Prepare or create a link from a work package to a wiki page; only\nwrites when called again with confirm=true.\n\nRequires OpenProject 17.6+ — the wiki_page_links endpoint does not exist\non earlier versions and returns a [server_error].\n\nwork_package_id: internal id (e.g., 952) or display_id (e.g., \"PROJ-51\"), not UI display number.\nidentifier: the target wiki page's provider-specific identifier (not this\nMCP's own wiki_page_id — OpenProject's wiki-provider abstraction uses its\nown opaque page identifiers).\nprovider: the wiki provider's universal identifier (e.g. \"internal\" for\nOpenProject's built-in wiki).\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "work_package_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "string",
                    },
                ],
                "title": "Work Package Id",
            },
            "identifier": {
                "title": "Identifier",
                "type": "string",
            },
            "provider": {
                "title": "Provider",
                "type": "string",
            },
            "confirm": {
                "default": False,
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
        == "Prepare or delete a work package's wiki page link; only deletes when\ncalled again with confirm=true.\n\nKnown OpenProject server bug (confirmed on 16.6/17.6/17.7.1): this call\ncurrently fails with a [server_error] whenever the\ngiven link actually exists — the same bug that breaks\nlist_work_package_wiki_links, since this tool verifies link_id actually\nbelongs to work_package_id before deleting (a real authorization check,\nnot optional) by internally listing the work package's links first.\n\nwork_package_id: internal id (e.g., 952) or display_id (e.g., \"PROJ-51\"), not UI display number\n— used to authorize the delete against that work package's project, since\nOpenProject has no single-resource GET for a wiki page link to discover\nits parent work package from link_id alone.\nlink_id: the wiki page link's own id, from list_work_package_wiki_links.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "work_package_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "string",
                    },
                ],
                "title": "Work Package Id",
            },
            "link_id": {
                "title": "Link Id",
                "type": "integer",
            },
            "confirm": {
                "default": False,
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
