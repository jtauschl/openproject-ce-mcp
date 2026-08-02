"""HTTP-backed NewsApi adapter.

No `httpx` import (depends on the `Transport` Protocol only), no
`api_prefix` parameter (unlike HttpxMembershipApi/HttpxProjectApi): News
builds no raw absolute hrefs from server responses, every path is a fixed
string (`news`, `news/{id}`). `_trim_text`/`_link_title`/`_id_from_href`/
`_delimit_user_content`/`_can_update_from_links`/`SUBJECT_LIMIT` are shared
via `app/adapters/_text.py` (unified once every domain migrated;
`_can_update_from_links` joined the shared module once Boards made it a 3rd
byte-identical copy).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

from ...models import NewsDetail, NewsSummary
from ..pagination import paginate_all
from ..ports.news_api import NewsRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import can_update_from_links as _can_update_from_links
from ._text import delimit_user_content as _delimit_user_content
from ._text import id_from_href as _id_from_href
from ._text import link_title as _link_title
from ._text import trim_text as _trim_text

FORMATTABLE_LIMIT = 1_200


def _extract_formattable_text(value: Any, *, limit: int) -> str | None:
    raw = value.get("raw") or value.get("html") if isinstance(value, dict) else value
    return _trim_text(raw, limit=limit)


def normalize_news(payload: dict[str, Any], *, base_url: str) -> NewsSummary:
    """Pure HAL->model translation (ADR: 'lives in the Domain API adapter').

    Verbatim port of client.py's normalize_news, minus the
    _apply_hidden_fields call and the hidden-field-aware text extraction --
    hidden-field masking of the whole `description` value is a Policy/Service
    decision applied after this returns (client.py's entity="news"
    hide-check only ever affected whether the raw
    text was extracted at all; since the Service masks the entire field
    afterwards regardless, dropping that check here changes nothing
    observable -- same pattern as normalize_project's port).
    """
    links = payload.get("_links", {})
    description = _delimit_user_content(_extract_formattable_text(payload.get("description"), limit=SUBJECT_LIMIT))
    return NewsSummary(
        id=int(payload["id"]),
        title=_trim_text(payload.get("title"), limit=SUBJECT_LIMIT) or f"News {payload['id']}",
        summary=_trim_text(payload.get("summary"), limit=SUBJECT_LIMIT),
        description=description,
        project_id=_id_from_href(links.get("project", {}).get("href")),
        project=_link_title(links.get("project")),
        author=_link_title(links.get("author")),
        created_at=payload.get("createdAt"),
        can_update=_can_update_from_links(links),
        can_delete=bool(links.get("delete")),
        url=urljoin(f"{base_url.rstrip('/')}/", f"news/{payload['id']}"),
    )


def normalize_news_detail(payload: dict[str, Any], *, base_url: str, summary: NewsSummary | None = None) -> NewsDetail:
    """Verbatim port of client.py's normalize_news_detail. Reuses every field
    from normalize_news() EXCEPT description, which is independently
    re-extracted from the same raw payload at the larger FORMATTABLE_LIMIT
    cap (not SUBJECT_LIMIT) -- the two normalizers apply different truncation
    limits to the same raw text, so this cannot be a simple copy of summary.

    `summary` lets a caller that already built a `NewsSummary` for the same
    payload (see `_record()`) pass it in directly instead of paying for a
    second `normalize_news()` call -- callers with only the raw payload
    (`commit_create`/`commit_update`) omit it and get the summary computed
    here.
    """
    if summary is None:
        summary = normalize_news(payload, base_url=base_url)
    description = _delimit_user_content(_extract_formattable_text(payload.get("description"), limit=FORMATTABLE_LIMIT))
    return NewsDetail(
        id=summary.id,
        title=summary.title,
        summary=summary.summary,
        description=description,
        project_id=summary.project_id,
        project=summary.project,
        author=summary.author,
        created_at=summary.created_at,
        can_update=summary.can_update,
        can_delete=summary.can_delete,
        url=summary.url,
    )


class HttpxNewsApi:
    def __init__(self, transport: Transport, *, base_url: str) -> None:
        self._transport = transport
        self._base_url = base_url

    def _record(self, payload: dict[str, Any]) -> NewsRecord:
        base_url = self._base_url
        summary = normalize_news(payload, base_url=base_url)
        return NewsRecord(
            summary=summary,
            # Lazy: only get()/update()/delete() (single-item paths) ever call
            # this; list_all()'s per-row records never do, so this avoids a
            # second, independent FORMATTABLE_LIMIT-capped re-extraction of
            # every record's description on every list call. The closure
            # captures only `payload`/`base_url`/`summary` (small, per-record),
            # not `self` -- it does not keep a whole adapter/transport alive.
            # Passing `summary` through avoids re-deriving every OTHER field
            # (id, title, project, author, url, ...) a second time.
            to_detail=lambda: normalize_news_detail(payload, base_url=base_url, summary=summary),
            project_link=payload.get("_links", {}).get("project"),
        )

    async def _list_page(self, offset: int, page_size: int) -> tuple[list[NewsRecord], int]:
        payload = await self._transport.get_json("news", params={"offset": str(offset), "pageSize": str(page_size)})
        elements = payload.get("_embedded", {}).get("elements", [])
        records = [self._record(item) for item in elements if isinstance(item, dict)]
        total = int(payload.get("total", len(records)))
        return records, total

    async def list_all(self, *, page_size: int) -> list[NewsRecord]:
        # Walk every server page -- results are filtered client-side against
        # the read allowlist, so a single bounded fetch capped at page_size
        # (this method's prior behavior) would silently hide any news item
        # beyond that cap once the real news count exceeded it. News is
        # genuinely OffsetPaginatedCollection server-side (verified against
        # op-sources), same bug class as list_users/list_groups' search
        # branches (found via a full-diff Codex review on release/0.3.4,
        # ported here).
        return await paginate_all(self._list_page, page_size=page_size, key=lambda r: r.summary.id)

    async def get(self, news_id: int) -> NewsRecord:
        return self._record(await self._transport.get_json(f"news/{news_id}"))

    async def commit_create(self, payload: dict[str, Any]) -> NewsDetail:
        response = await self._transport.post_json("news", json_body=payload)
        return normalize_news_detail(response, base_url=self._base_url)

    async def commit_update(self, news_id: int, payload: dict[str, Any]) -> NewsDetail:
        response = await self._transport.patch_json(f"news/{news_id}", json_body=payload)
        return normalize_news_detail(response, base_url=self._base_url)

    async def delete(self, news_id: int) -> None:
        await self._transport.delete(f"news/{news_id}")
