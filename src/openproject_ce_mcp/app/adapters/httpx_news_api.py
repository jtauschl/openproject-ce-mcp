"""HTTP-backed NewsApi adapter.

No `httpx` import (depends on the `Transport` Protocol only), no
`api_prefix` parameter (unlike HttpxMembershipApi/HttpxProjectApi): News
builds no raw absolute hrefs from server responses, every path is a fixed
string (`news`, `news/{id}`). `_trim_text`/`_link_title`/`_id_from_href`/
`_delimit_user_content`/`_can_update_from_links`/`SUBJECT_LIMIT` are shared
via `app/adapters/_text.py`.
"""

from __future__ import annotations

from typing import Any

from ...models import NewsDetail, NewsSummary
from ..ports.news_api import NewsRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import can_update_from_links as _can_update_from_links
from ._text import delimit_user_content as _delimit_user_content
from ._text import extract_formattable_text_with_meta as _extract_formattable_text_with_meta
from ._text import id_from_href as _id_from_href
from ._text import link_title as _link_title
from ._text import trim_text as _trim_text

FORMATTABLE_LIMIT = 1_200


def normalize_news(payload: dict[str, Any], *, text_limit: int | None = SUBJECT_LIMIT) -> NewsSummary:
    """Pure HAL->model translation (ADR: 'lives in the Domain API adapter').

    Excludes hidden-field masking and the hidden-field-aware text
    extraction -- hidden-field masking of the whole `description` value is a
    Policy/Service decision applied after this returns: the Service masks
    the entire field regardless, so omitting an extraction-time hide-check
    here changes nothing observable (same pattern as normalize_project).

    ``text_limit`` defaults to SUBJECT_LIMIT (this normalizer's historical
    cap) so every existing caller keeps its current truncation point; the
    Service passes `settings.text_limit` through for list results, matching
    `normalize_work_package_summary`'s equivalent parameter.
    """
    links = payload.get("_links", {})
    description, truncated, length = _extract_formattable_text_with_meta(payload.get("description"), limit=text_limit)
    return NewsSummary(
        id=int(payload["id"]),
        title=_trim_text(payload.get("title"), limit=SUBJECT_LIMIT) or f"News {payload['id']}",
        summary=_trim_text(payload.get("summary"), limit=SUBJECT_LIMIT),
        description=_delimit_user_content(description),
        project_id=_id_from_href(links.get("project", {}).get("href")),
        project=_link_title(links.get("project")),
        author=_link_title(links.get("author")),
        created_at=payload.get("createdAt"),
        can_update=_can_update_from_links(links),
        can_delete=bool(links.get("delete")),
        description_truncated=truncated,
        description_length=length,
    )


def normalize_news_detail(
    payload: dict[str, Any], *, summary: NewsSummary | None = None, text_limit: int | None = FORMATTABLE_LIMIT
) -> NewsDetail:
    """Reuses every field from normalize_news() EXCEPT description, which is
    independently
    re-extracted from the same raw payload at the larger FORMATTABLE_LIMIT
    cap (not SUBJECT_LIMIT) -- the two normalizers apply different truncation
    limits to the same raw text, so this cannot be a simple copy of summary.

    `summary` lets a caller that already built a `NewsSummary` for the same
    payload (see `_record()`) pass it in directly instead of paying for a
    second `normalize_news()` call -- callers with only the raw payload
    (`commit_create`/`commit_update`) omit it and get the summary computed
    here.

    ``text_limit`` lets a caller (get_news's `text_limit` tool parameter)
    override the FORMATTABLE_LIMIT default, matching get_work_package's
    equivalent parameter.
    """
    if summary is None:
        summary = normalize_news(payload)
    description, truncated, length = _extract_formattable_text_with_meta(payload.get("description"), limit=text_limit)
    return NewsDetail(
        id=summary.id,
        title=summary.title,
        summary=summary.summary,
        description=_delimit_user_content(description),
        project_id=summary.project_id,
        project=summary.project,
        author=summary.author,
        created_at=summary.created_at,
        can_update=summary.can_update,
        can_delete=summary.can_delete,
        description_truncated=truncated,
        description_length=length,
    )


class HttpxNewsApi:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def _record(
        self,
        payload: dict[str, Any],
        *,
        text_limit: int | None = SUBJECT_LIMIT,
        detail_text_limit: int | None = None,
    ) -> NewsRecord:
        summary = normalize_news(payload, text_limit=text_limit)
        return NewsRecord(
            summary=summary,
            # Lazy: only get()/update()/delete() (single-item paths) ever call
            # this; list_all()'s per-row records never do, so this avoids a
            # second, independent FORMATTABLE_LIMIT-capped re-extraction of
            # every record's description on every list call. The closure
            # captures only `payload`/`summary`/`detail_text_limit` (small,
            # per-record), not `self` -- it does not keep a whole
            # adapter/transport alive. Passing `summary` through avoids
            # re-deriving every OTHER field (id, title, project, author, ...)
            # a second time.
            to_detail=lambda: normalize_news_detail(payload, summary=summary, text_limit=detail_text_limit),
            project_link=payload.get("_links", {}).get("project"),
        )

    async def list_page(
        self, *, offset: int, page_size: int, text_limit: int | None = None
    ) -> tuple[list[NewsRecord], int]:
        payload = await self._transport.get_json("news", params={"offset": str(offset), "pageSize": str(page_size)})
        elements = payload.get("_embedded", {}).get("elements", [])
        records = [self._record(item, text_limit=text_limit) for item in elements if isinstance(item, dict)]
        total = int(payload.get("total", len(records)))
        return records, total

    async def get(self, news_id: int, *, text_limit: int | None = None) -> NewsRecord:
        return self._record(
            await self._transport.get_json(f"news/{news_id}"),
            detail_text_limit=text_limit,
        )

    async def commit_create(self, payload: dict[str, Any]) -> NewsDetail:
        response = await self._transport.post_json("news", json_body=payload)
        return normalize_news_detail(response)

    async def commit_update(self, news_id: int, payload: dict[str, Any]) -> NewsDetail:
        response = await self._transport.patch_json(f"news/{news_id}", json_body=payload)
        return normalize_news_detail(response)

    async def delete(self, news_id: int) -> None:
        await self._transport.delete(f"news/{news_id}")
