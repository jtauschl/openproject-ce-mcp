"""HTTP-backed WikiPageApi adapter.

No `httpx` import (depends on the `Transport` Protocol only). `_trim_text`/
`_id_from_href`/`_link_title`/`_delimit_user_content`/`SUBJECT_LIMIT` are
shared via `app/adapters/_text.py`.

No web `url`/`attachments_url` fields: `wiki_pages/{numeric_id}` never
resolves to a real page -- OpenProject's real wiki route is project-scoped
and keyed by the page's title-derived slug, not its numeric id, and the API
doesn't expose that slug at all, only `id`/`title`. `attachments_url` would
be a pure API sub-collection href with no dedicated MCP tool to justify
keeping it.
"""

from __future__ import annotations

from typing import Any

from ...models import WikiPageDetail
from ..ports.wiki_page_api import WikiPageRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import delimit_user_content as _delimit_user_content
from ._text import id_from_href as _id_from_href
from ._text import link_title as _link_title
from ._text import trim_text as _trim_text
from ._text import trim_text_with_meta as _trim_text_with_meta

CONTENT_LIMIT = 50_000


def normalize_wiki_page(payload: dict[str, Any], *, text_limit: int | None = CONTENT_LIMIT) -> WikiPageDetail:
    """Pure HAL->model translation (ADR: 'lives in the Domain API adapter').

    Excludes hidden-field masking -- hidden-field masking of the whole
    WikiPageDetail is a Policy/Service decision applied after this returns
    (same pattern as normalize_document/normalize_news).

    ``text_limit`` defaults to CONTENT_LIMIT (this normalizer's historical
    cap) so an existing caller that omits it keeps the current truncation
    point; get_wiki_page's ``text_limit`` tool parameter overrides it,
    matching get_work_package's equivalent parameter -- pass ``None`` for
    uncapped content.
    """
    links = payload.get("_links", {})
    text_block = payload.get("text") or payload.get("content")
    raw_content = text_block.get("raw") if isinstance(text_block, dict) else None
    content, truncated, length = _trim_text_with_meta(raw_content, limit=text_limit)
    content = _delimit_user_content(content)
    return WikiPageDetail(
        id=int(payload["id"]),
        title=_trim_text(payload.get("title"), limit=SUBJECT_LIMIT) or f"Wiki page {payload['id']}",
        project_id=_id_from_href(links.get("project", {}).get("href")),
        project=_link_title(links.get("project")),
        content=content,
        content_truncated=truncated,
        content_length=length,
    )


class HttpxWikiPageApi:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    async def get(self, wiki_page_id: int, *, text_limit: int | None = CONTENT_LIMIT) -> WikiPageRecord:
        payload = await self._transport.get_json(f"wiki_pages/{wiki_page_id}")
        return WikiPageRecord(
            detail=normalize_wiki_page(payload, text_limit=text_limit),
            project_link=payload.get("_links", {}).get("project"),
        )
