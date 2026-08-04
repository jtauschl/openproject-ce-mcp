"""HTTP-backed WikiPageApi adapter.

No `httpx` import (depends on the `Transport` Protocol only). `_trim_text`/
`_id_from_href`/`_link_title`/`_delimit_user_content`/`SUBJECT_LIMIT` are
shared via `app/adapters/_text.py`.

No web `url`/`attachments_url` fields: the adapter previously built
`wiki_pages/{numeric_id}`, which never resolved (OpenProject's real wiki
route is project-scoped and keyed by the page's title-derived slug, not its
numeric id -- and the API doesn't expose that slug at all, only `id`/
`title`), and `attachments_url` was a pure API sub-collection href with no
dedicated MCP tool to justify keeping it.
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

CONTENT_LIMIT = 50_000


def normalize_wiki_page(payload: dict[str, Any]) -> WikiPageDetail:
    """Pure HAL->model translation (ADR: 'lives in the Domain API adapter').

    Verbatim port of client.py's normalize_wiki_page, minus the
    _apply_hidden_fields call -- hidden-field masking of the whole
    WikiPageDetail is a Policy/Service decision applied after this returns
    (same pattern as normalize_document/normalize_news's port).
    """
    links = payload.get("_links", {})
    text_block = payload.get("text") or payload.get("content")
    content: str | None = None
    if isinstance(text_block, dict):
        content = _trim_text(text_block.get("raw"), limit=CONTENT_LIMIT)
    content = _delimit_user_content(content)
    return WikiPageDetail(
        id=int(payload["id"]),
        title=_trim_text(payload.get("title"), limit=SUBJECT_LIMIT) or f"Wiki page {payload['id']}",
        project_id=_id_from_href(links.get("project", {}).get("href")),
        project=_link_title(links.get("project")),
        content=content,
    )


class HttpxWikiPageApi:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    async def get(self, wiki_page_id: int) -> WikiPageRecord:
        payload = await self._transport.get_json(f"wiki_pages/{wiki_page_id}")
        return WikiPageRecord(
            detail=normalize_wiki_page(payload),
            project_link=payload.get("_links", {}).get("project"),
        )
