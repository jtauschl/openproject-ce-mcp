"""HTTP-backed PostApi adapter.

No `httpx` import (depends on the `Transport` Protocol only). `_trim_text`/
`_id_from_href`/`_link_title`/`SUBJECT_LIMIT` are shared via
`app/adapters/_text.py`.

No `content`/description field: post_representer.rb (17.7) exposes only
`id`/`subject`/`associated_project`/`self_link` -- unlike WikiPageDetail
there is no body-text field to extract at all, so no
`_delimit_user_content`/`_trim_text_with_meta` call is needed here (subject
is a short plain string, not formattable/HAL-wrapped text).

No `attachments_url`/`url`: same reasoning as HttpxDocumentApi/
HttpxWikiPageApi -- a pure API sub-collection href with no dedicated MCP
tool to justify keeping it (the AttachmentsByPostAPI mount is explicitly out
of scope for OPM-178).
"""

from __future__ import annotations

from typing import Any

from ...models import PostDetail
from ..ports.post_api import PostRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import id_from_href as _id_from_href
from ._text import link_title as _link_title
from ._text import trim_text as _trim_text


def normalize_post(payload: dict[str, Any]) -> PostDetail:
    """Pure HAL->model translation (ADR: 'lives in the Domain API adapter').

    Excludes hidden-field masking -- hidden-field masking of the whole
    PostDetail is a Policy/Service decision applied after this returns (same
    pattern as normalize_document/normalize_wiki_page).
    """
    links = payload.get("_links", {})
    return PostDetail(
        id=int(payload["id"]),
        subject=_trim_text(payload.get("subject"), limit=SUBJECT_LIMIT) or f"Post {payload['id']}",
        project_id=_id_from_href(links.get("project", {}).get("href")),
        project=_link_title(links.get("project")),
    )


class HttpxPostApi:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    async def get(self, post_id: int) -> PostRecord:
        payload = await self._transport.get_json(f"posts/{post_id}")
        return PostRecord(
            detail=normalize_post(payload),
            project_link=payload.get("_links", {}).get("project"),
        )
