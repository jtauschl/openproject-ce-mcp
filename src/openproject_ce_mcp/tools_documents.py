"""Documents/News/Wiki Pages/Posts/Wiki-Page-Links tool handlers: list_documents,
get_document, update_document, list_news, get_news, create_news, update_news,
delete_news, get_wiki_page, get_post, list_work_package_wiki_links,
create_work_package_wiki_link, delete_work_package_wiki_link.

One file for five sub-domains (Documents, News, Wiki Pages, Posts, Wiki-Page
Links): none of these 13 functions calls another of them, and none is called
by any other domain's tool function -- every body only validates its own
arguments (via tools_validation.py) and delegates to exactly one
`client.<method>(...)` call. A finer per-domain split is possible but not
warranted for a group this size; keeping them together avoids triplicating
the module docstring/import boilerplate for what are otherwise five small,
uncoupled content-resource domains.

Their `@register_tool` decorators come from `tools_runtime`, never from
`tools.py` -- see that module's own docstring for why. `tools.py` imports
this module for the decorator's registration side effect and re-exports all
thirteen public names: nine of them because existing tests
(`tests/unit/test_project_and_domain_tools.py`) import them directly from
`openproject_ce_mcp.tools` (create_news, delete_news, get_document, get_news,
get_wiki_page, list_documents, list_news, update_document, update_news); the
remaining four (get_post, list_work_package_wiki_links,
create_work_package_wiki_link, delete_work_package_wiki_link) are re-exported
alongside for a consistent public surface, matching `tools_admin.py`'s and
`tools_projects.py`'s precedent.
"""

from __future__ import annotations

from typing import Annotated

from mcp.server.mcpserver import Context
from pydantic import Field

from .models import (
    DocumentDetail,
    DocumentListResult,
    DocumentSummary,
    DocumentWriteResult,
    NewsDetail,
    NewsListResult,
    NewsSummary,
    NewsWriteResult,
    PostDetail,
    WikiPageDetail,
    WikiPageLinkListResult,
    WikiPageLinkWriteResult,
)
from .tool_params import (
    Confirm,
    ExpectDisplayId,
    Limit,
    Offset,
    OptionalProjectRef,
    ProjectRef,
    WorkPackageRef,
    select_field,
)
from .tools_runtime import _client_from_context, _run_tool, register_tool
from .tools_validation import (
    _require_at_least_one,
    _validate_expect_display_id,
    _validate_limit,
    _validate_list_query_params,
    _validate_offset,
    _validate_optional_project_ref,
    _validate_optional_query,
    _validate_optional_text,
    _validate_optional_text_limit,
    _validate_optional_update_text,
    _validate_positive_int,
    _validate_project_ref,
    _validate_required_query,
    _validate_select,
    _validate_work_package_ref,
)

_NEWS_ID = "Numeric news id, as returned by list_news."
_TITLE = "At most 255 characters."


@register_tool
async def list_documents(
    ctx: Context,
    project: OptionalProjectRef = None,
    search: str | None = None,
    offset: Offset = 1,
    limit: Limit = None,
    select: Annotated[list[str] | None, select_field(DocumentSummary)] = None,
    text_limit: int | None = None,
) -> DocumentListResult:
    """List documents, optionally filtered to a single project or by title search.

    total is only the count of allowed documents returned on THIS page, not a full count of all matches; the search
    stops as soon as it has enough, so an exact total would need an extra full walk. Page until next_offset is null.

    text_limit caps each document's description at that many characters
    (default: the server's configured OPENPROJECT_TEXT_LIMIT, NOT unlimited --
    unlike get_document's single-item default). When text is cut,
    description_truncated is true and description_length reports the real
    length.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_optional_project_ref(project)
    safe_search, safe_offset, safe_limit = _validate_list_query_params(search, offset, limit)
    _validate_select(select, row_type=DocumentSummary)
    safe_text_limit = _validate_optional_text_limit(text_limit)
    return await _run_tool(
        client.document.list(
            project=safe_project, search=safe_search, offset=safe_offset, limit=safe_limit, text_limit=safe_text_limit
        )
    )


@register_tool
async def get_document(
    ctx: Context,
    document_id: int,
    text_limit: int | None = None,
) -> DocumentDetail:
    """Get a single document by id.

    The description is returned in full by default (single documents are not
    truncated). Pass ``text_limit`` to cap it at that many characters; when the
    text is cut, ``description_truncated`` is true and ``description_length``
    reports the real length.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(document_id, field_name="document_id")
    safe_text_limit = _validate_optional_text_limit(text_limit)
    return await _run_tool(client.document.get(safe_id, text_limit=safe_text_limit))


@register_tool
async def update_document(
    ctx: Context,
    document_id: Annotated[int, Field(description="Numeric document id, as returned by list_documents.")],
    title: Annotated[str | None, Field(description=_TITLE)] = None,
    description: Annotated[str | None, Field(description='Document text; "" clears it.')] = None,
    confirm: Confirm = False,
) -> DocumentWriteResult:
    """Update a document. Omitted fields stay unchanged."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(document_id, field_name="document_id")
    safe_title = _validate_optional_query(title, field_name="title", max_length=255)
    safe_description = _validate_optional_update_text(description, field_name="description", max_length=None)
    _require_at_least_one(safe_title, safe_description, message="At least one field to update is required.")
    return await _run_tool(
        client.document.update(
            document_id=safe_id,
            title=safe_title,
            description=safe_description,
            confirm=confirm,
        )
    )


@register_tool
async def list_news(
    ctx: Context,
    project: OptionalProjectRef = None,
    search: str | None = None,
    offset: Offset = 1,
    limit: Limit = None,
    select: Annotated[list[str] | None, select_field(NewsSummary)] = None,
    text_limit: int | None = None,
) -> NewsListResult:
    """List news entries, optionally filtered by project or title/summary search.

    total is only the count of allowed news entries returned on THIS page, not a full count of all matches; the
    search stops as soon as it has enough, so an exact total would need an extra full walk. Page until next_offset
    is null.

    text_limit caps each entry's summary/description at that many characters
    (default: the server's configured OPENPROJECT_TEXT_LIMIT, NOT unlimited --
    unlike get_news's single-item default). When text is cut,
    description_truncated is true and description_length reports the real
    length.
    """
    client = _client_from_context(ctx)
    safe_project = _validate_optional_project_ref(project)
    safe_search, safe_offset, safe_limit = _validate_list_query_params(search, offset, limit)
    _validate_select(select, row_type=NewsSummary)
    safe_text_limit = _validate_optional_text_limit(text_limit)
    return await _run_tool(
        client.news.list(
            project=safe_project,
            search=safe_search,
            offset=safe_offset,
            limit=safe_limit,
            text_limit=safe_text_limit,
        )
    )


@register_tool
async def get_news(
    ctx: Context,
    news_id: int,
    text_limit: int | None = None,
) -> NewsDetail:
    """Get a single news entry by id.

    The description is returned in full by default (single news entries are
    not truncated). Pass ``text_limit`` to cap it at that many characters;
    when the text is cut, ``description_truncated`` is true and
    ``description_length`` reports the real length.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(news_id, field_name="news_id")
    safe_text_limit = _validate_optional_text_limit(text_limit)
    return await _run_tool(client.news.get(safe_id, text_limit=safe_text_limit))


@register_tool
async def create_news(
    ctx: Context,
    project: ProjectRef,
    title: Annotated[str, Field(description=_TITLE)],
    summary: Annotated[str | None, Field(description="Short plain text, at most 500 characters.")] = None,
    description: Annotated[str | None, Field(description="Full text in Markdown.")] = None,
    confirm: Confirm = False,
) -> NewsWriteResult:
    """Create a news entry inside a project."""
    client = _client_from_context(ctx)
    safe_project = _validate_project_ref(project)
    safe_title = _validate_required_query(title, field_name="title", max_length=255)
    safe_summary = _validate_optional_text(summary, field_name="summary", max_length=500)
    safe_description = _validate_optional_text(description, field_name="description", max_length=None)
    return await _run_tool(
        client.news.create(
            project=safe_project,
            title=safe_title,
            summary=safe_summary,
            description=safe_description,
            confirm=confirm,
        )
    )


@register_tool
async def update_news(
    ctx: Context,
    news_id: Annotated[int, Field(description=_NEWS_ID)],
    title: Annotated[str | None, Field(description=_TITLE)] = None,
    summary: Annotated[str | None, Field(description='Short plain text, at most 500 characters; "" clears it.')] = None,
    description: Annotated[str | None, Field(description='Full text in Markdown; "" clears it.')] = None,
    confirm: Confirm = False,
) -> NewsWriteResult:
    """Update a news entry. Omitted fields stay unchanged."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(news_id, field_name="news_id")
    safe_title = _validate_optional_query(title, field_name="title", max_length=255)
    safe_summary = _validate_optional_update_text(summary, field_name="summary", max_length=500)
    safe_description = _validate_optional_update_text(description, field_name="description", max_length=None)
    _require_at_least_one(
        safe_title, safe_summary, safe_description, message="At least one field to update is required."
    )
    return await _run_tool(
        client.news.update(
            news_id=safe_id,
            title=safe_title,
            summary=safe_summary,
            description=safe_description,
            confirm=confirm,
        )
    )


@register_tool
async def delete_news(
    ctx: Context,
    news_id: Annotated[int, Field(description=_NEWS_ID)],
    confirm: Confirm = False,
) -> NewsWriteResult:
    """Delete a news entry with its comments and attachments; this cannot be undone."""
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(news_id, field_name="news_id")
    return await _run_tool(client.news.delete(news_id=safe_id, confirm=confirm))


@register_tool
async def get_wiki_page(
    ctx: Context,
    wiki_page_id: int,
) -> WikiPageDetail:
    """Get a single wiki page's metadata (id, title, project) by id.

    OpenProject's REST API v3 does not expose a wiki page's body text at
    all -- GET /api/v3/wiki_pages/{id} returns only id/title/project, and
    there is no other route that returns the page content. This tool
    therefore cannot return wiki page text; use the OpenProject web UI to
    read a page's content.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(wiki_page_id, field_name="wiki_page_id")
    return await _run_tool(client.wiki_page.get(safe_id))


@register_tool
async def get_post(
    ctx: Context,
    post_id: int,
) -> PostDetail:
    """Get a single forum post by id.

    OpenProject's API exposes exactly one route for posts:
    GET /api/v3/posts/{id}. There is no collection/list endpoint for posts or
    forums at all in OpenProject's REST API -- a post's id must therefore
    come from elsewhere (e.g. a work package's activity/journal referencing
    a forum post, or a link copied from the OpenProject web UI). This MCP
    does not and cannot provide a list_posts or list_forums tool.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(post_id, field_name="post_id")
    return await _run_tool(client.post.get(safe_id))


@register_tool
async def list_work_package_wiki_links(
    ctx: Context,
    work_package_id: WorkPackageRef,
    offset: Offset = 1,
    limit: Limit = None,
) -> WikiPageLinkListResult:
    """List wiki pages linked to a work package.

    Requires OpenProject 17.5+; on an older server this returns a
    [RESOURCE_NOT_FOUND] naming the required version.

    Known OpenProject server bug (17.5 to at least 17.9.1): this call returns
    an [OPENPROJECT_UNAVAILABLE] when none of the work package's links
    resolves to a wiki page the user can see, and on 17.5/17.6 also when the
    work package has no links. A link to the internal wiki resolves when its
    identifier is the page's numeric id.

    Only the work package is checked against OPENPROJECT_READ_PROJECTS: a link
    carries no project, so a link to a page in another project is listed. It
    shows the identifier, provider and author, never the page's title or text.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    safe_offset = _validate_offset(offset)
    safe_limit = _validate_limit(limit)
    return await _run_tool(client.wiki_page_link.list_for_work_package(safe_id, offset=safe_offset, limit=safe_limit))


@register_tool
async def create_work_package_wiki_link(
    ctx: Context,
    work_package_id: WorkPackageRef,
    identifier: str,
    provider: str,
    expect_display_id: ExpectDisplayId = None,
    confirm: Confirm = False,
) -> WikiPageLinkWriteResult:
    """Create a link from a work package to a wiki page.

    Requires OpenProject 17.7+; on an older server this returns a
    [RESOURCE_NOT_FOUND] naming the required version.

    identifier: the target wiki page's identifier at its provider; for the
    internal wiki, the page's numeric id (the wiki_page_id of get_wiki_page).
    OpenProject accepts any string, but list_work_package_wiki_links fails
    while none of a work package's links resolves to a page.
    provider: the wiki provider's universal identifier (e.g. "internal" for
    OpenProject's built-in wiki).
    expect_display_id names the ticket you mean and makes a mismatch an error; see the server instructions.
    The result names the work package the reference resolved to in `target`.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    safe_expect = _validate_expect_display_id(expect_display_id)
    safe_identifier = _validate_required_query(identifier, field_name="identifier", max_length=255)
    safe_provider = _validate_required_query(provider, field_name="provider", max_length=255)
    return await _run_tool(
        client.wiki_page_link.create(
            safe_id,
            identifier=safe_identifier,
            provider=safe_provider,
            expect_display_id=safe_expect,
            confirm=confirm,
        )
    )


@register_tool
async def delete_work_package_wiki_link(
    ctx: Context,
    work_package_id: WorkPackageRef,
    link_id: int,
    expect_display_id: ExpectDisplayId = None,
    confirm: Confirm = False,
) -> WikiPageLinkWriteResult:
    """Delete a work package's wiki page link; this cannot be undone.

    Requires OpenProject 17.6+. On 17.4 or older this returns a
    [RESOURCE_NOT_FOUND] naming 17.6; on 17.5 the link check below usually
    fails first with an [OPENPROJECT_UNAVAILABLE].

    This tool lists the work package's links first to verify that link_id
    belongs to work_package_id (an authorization check), so it fails with an
    [OPENPROJECT_UNAVAILABLE] whenever list_work_package_wiki_links does (see
    there).

    Only relation links (link_type "relation") can be deleted. An inline
    link comes from a wiki link in the work package's description or from a
    wiki page that mentions the work package; this tool rejects it with a
    [VALIDATION_FAILED], and the link goes away only when that text changes.
    Deleting needs the "Manage wiki page links" permission in the work
    package's project; without it OpenProject answers 404, which the tool
    reports as a [RESOURCE_NOT_FOUND] naming 17.6, not as
    [OPENPROJECT_PERMISSION_DENIED].

    work_package_id must be the work package the link belongs to; OpenProject has no single GET for a link,
    so the delete is authorized against that work package's project.
    link_id: the wiki page link's own id, from list_work_package_wiki_links.
    expect_display_id names the ticket you mean and makes a mismatch an error; see the server instructions.
    The result names the work package the reference resolved to in `target`.
    """
    client = _client_from_context(ctx)
    safe_wp_id = _validate_work_package_ref(work_package_id)
    safe_link_id = _validate_positive_int(link_id, field_name="link_id")
    safe_expect = _validate_expect_display_id(expect_display_id)
    return await _run_tool(
        client.wiki_page_link.delete(safe_wp_id, safe_link_id, expect_display_id=safe_expect, confirm=confirm)
    )
