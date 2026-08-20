"""HTTP-backed WikiPageApi adapter.

No `httpx` import (depends on the `Transport` Protocol only). `_trim_text`/
`_id_from_href`/`_link_title` are shared via `app/adapters/_text.py`.

No web `url`/`attachments_url` fields: `wiki_pages/{numeric_id}` never
resolves to a real page -- OpenProject's real wiki route is project-scoped
and keyed by the page's title-derived slug, not its numeric id, and the API
doesn't expose that slug at all, only `id`/`title`. `attachments_url` would
be a pure API sub-collection href with no dedicated MCP tool to justify
keeping it.

No `content` field either: `WikiPageRepresenter` (lib/api/v3/wiki_pages/
wiki_page_representer.rb, verified against 16.1 and 17.7) renders only
`id`, `title`, and the project link -- no `text`/`content` property, and
`WikiPagesAPI`'s single `GET /wiki_pages/{id}` route (the only one that
exists; no list/create/update/delete either) mounts nothing else that would
expose the page body. OpenProject's REST API v3 simply has no route that
returns wiki page body text at all.
"""

from __future__ import annotations

from typing import Any

from ...models import WikiPageDetail
from ..ports.wiki_page_api import WikiPageRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import id_from_href as _id_from_href
from ._text import link_title as _link_title
from ._text import trim_text as _trim_text


def normalize_wiki_page(payload: dict[str, Any]) -> WikiPageDetail:
    """Pure HAL->model translation (ADR: 'lives in the Domain API adapter').

    Excludes hidden-field masking -- hidden-field masking of the whole
    WikiPageDetail is a Policy/Service decision applied after this returns
    (same pattern as normalize_document/normalize_news).
    """
    links = payload.get("_links", {})
    return WikiPageDetail(
        id=int(payload["id"]),
        title=_trim_text(payload.get("title"), limit=SUBJECT_LIMIT) or f"Wiki page {payload['id']}",
        project_id=_id_from_href(links.get("project", {}).get("href")),
        project=_link_title(links.get("project")),
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
