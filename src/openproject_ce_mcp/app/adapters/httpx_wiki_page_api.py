"""HTTP-backed WikiPageApi adapter (ADR 0001).

No `httpx` import (depends on the `Transport` Protocol only). `_trim_text`/
`_id_from_href`/`_link_title`/`_delimit_user_content`/`_link_to_web_url`/
`_origin_from_url`/`SUBJECT_LIMIT` are shared via `app/adapters/_text.py`.

`_web_url` has no shared equivalent (Documents builds its `url` field
inline with a raw urljoin call in normalize_document, not through a
helper) -- this is a small Wiki-Pages-local free function verified against
client.py's bound-method original (client.py:4512-4513: `_web_url(self,
relative_path)` -> `urljoin(f"{self.settings.base_url.rstrip('/')}/",
relative_path.lstrip('/'))`).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

from ...models import WikiPageDetail
from ..ports.wiki_page_api import WikiPageRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import delimit_user_content as _delimit_user_content
from ._text import id_from_href as _id_from_href
from ._text import link_title as _link_title
from ._text import link_to_web_url as _link_to_web_url
from ._text import origin_from_url as _origin_from_url
from ._text import trim_text as _trim_text

CONTENT_LIMIT = 50_000


def _web_url(relative_path: str, *, base_url: str) -> str:
    """Verbatim port of client.py's _web_url (a relative-path -> absolute
    web URL join, no same-origin check needed since the input is always a
    same-server relative path, not a foreign href)."""
    return urljoin(f"{base_url.rstrip('/')}/", relative_path.lstrip("/"))


def normalize_wiki_page(payload: dict[str, Any], *, base_url: str, origin: str) -> WikiPageDetail:
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
        attachments_url=_link_to_web_url(links.get("attachments", {}).get("href"), base_url=base_url, origin=origin),
        url=_web_url(f"wiki_pages/{payload['id']}", base_url=base_url),
    )


class HttpxWikiPageApi:
    def __init__(self, transport: Transport, *, base_url: str) -> None:
        self._transport = transport
        self._base_url = base_url
        self._origin = _origin_from_url(base_url)

    async def get(self, wiki_page_id: int) -> WikiPageRecord:
        payload = await self._transport.get_json(f"wiki_pages/{wiki_page_id}")
        return WikiPageRecord(
            detail=normalize_wiki_page(payload, base_url=self._base_url, origin=self._origin),
            project_link=payload.get("_links", {}).get("project"),
        )
