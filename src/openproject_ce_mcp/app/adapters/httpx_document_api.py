"""HTTP-backed DocumentApi adapter.

No `httpx` import (depends on the `Transport` Protocol only). `_trim_text`/
`_id_from_href`/`_link_title`/`_delimit_user_content`/`_can_update_from_links`/
`SUBJECT_LIMIT` are shared via `app/adapters/_text.py`.
`_extract_formattable_text`/`FORMATTABLE_LIMIT` stay local -- not shared
across every adapter.

`_extract_formattable_text` here keeps the `.get("raw") or .get("html")`
fallback (also kept by HttpxProjectApi/HttpxVersionApi) -- HttpxNewsApi's
local copy is missing this fallback, a genuine behavioral difference, not
an oversight to "fix" by unifying the two.

No `attachments_url`: a pure API sub-collection href with no dedicated MCP
tool to justify keeping it (unlike work packages, which have
`list_work_package_attachments`).
"""

from __future__ import annotations

from typing import Any

from ...models import DocumentDetail, DocumentSummary
from ..ports.document_api import DocumentRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import can_update_from_links as _can_update_from_links
from ._text import delimit_user_content as _delimit_user_content
from ._text import extract_formattable_text_with_meta as _extract_formattable_text_with_meta
from ._text import id_from_href as _id_from_href
from ._text import link_title as _link_title
from ._text import trim_text as _trim_text

FORMATTABLE_LIMIT = 1_200


def normalize_document(payload: dict[str, Any], *, text_limit: int | None = SUBJECT_LIMIT) -> DocumentSummary:
    """Pure HAL->model translation (ADR: 'lives in the Domain API adapter').

    Excludes hidden-field masking and the hidden-field-aware text
    extraction -- hidden-field masking of the whole `description` value is a
    Policy/Service decision applied after this returns (same pattern as
    normalize_news: omitting the field_hidden check here changes nothing
    observable, since the Service masks the entire field afterwards
    regardless).

    ``text_limit`` defaults to SUBJECT_LIMIT (this normalizer's historical
    cap) so every existing caller keeps its current truncation point; the
    Service passes `settings.text_limit` through for list results, matching
    `normalize_work_package_summary`'s equivalent parameter.
    """
    links = payload.get("_links", {})
    attachments = payload.get("_embedded", {}).get("attachments", {})
    attachment_count = 0
    if isinstance(attachments, dict):
        attachment_count = int(attachments.get("count") or attachments.get("total") or 0)
    description, truncated, length = _extract_formattable_text_with_meta(payload.get("description"), limit=text_limit)
    return DocumentSummary(
        id=int(payload["id"]),
        title=_trim_text(payload.get("title"), limit=SUBJECT_LIMIT) or f"Document {payload['id']}",
        project_id=_id_from_href(links.get("project", {}).get("href")),
        project=_link_title(links.get("project")),
        description=_delimit_user_content(description),
        created_at=payload.get("createdAt"),
        attachment_count=attachment_count,
        can_update=_can_update_from_links(links),
        description_truncated=truncated,
        description_length=length,
    )


def normalize_document_detail(
    payload: dict[str, Any], *, summary: DocumentSummary | None = None, text_limit: int | None = FORMATTABLE_LIMIT
) -> DocumentDetail:
    """Reuses every field from normalize_document() EXCEPT description,
    which is independently re-extracted from the same raw payload at the larger
    FORMATTABLE_LIMIT cap (not SUBJECT_LIMIT) -- the two normalizers apply
    different truncation limits to the same raw text, so this cannot be a
    simple copy of summary.

    `summary` lets a caller that already built a `DocumentSummary` for the
    same payload (see `_record()`) pass it in directly instead of paying for
    a second `normalize_document()` call -- callers with only the raw
    payload (`commit_update`) omit it and get the summary computed here.

    ``text_limit`` lets a caller (get_document's `text_limit` tool parameter)
    override the FORMATTABLE_LIMIT default, matching get_work_package's
    equivalent parameter.
    """
    if summary is None:
        summary = normalize_document(payload)
    description, truncated, length = _extract_formattable_text_with_meta(payload.get("description"), limit=text_limit)
    return DocumentDetail(
        id=summary.id,
        title=summary.title,
        project_id=summary.project_id,
        project=summary.project,
        description=_delimit_user_content(description),
        created_at=summary.created_at,
        attachment_count=summary.attachment_count,
        can_update=summary.can_update,
        description_truncated=truncated,
        description_length=length,
    )


class HttpxDocumentApi:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def _record(
        self,
        payload: dict[str, Any],
        *,
        text_limit: int | None = SUBJECT_LIMIT,
        detail_text_limit: int | None = None,
    ) -> DocumentRecord:
        summary = normalize_document(payload, text_limit=text_limit)
        return DocumentRecord(
            summary=summary,
            # Lazy: only get()/update() (single-item paths) ever call this;
            # list_all()'s per-row records never do, so this avoids a second,
            # independent FORMATTABLE_LIMIT-capped re-extraction of every
            # record's description on every list call. The closure captures
            # only `payload`/`summary`/`detail_text_limit` (small, per-record),
            # not `self` -- it does not keep a whole adapter/transport alive.
            # Passing `summary` through avoids re-deriving every OTHER field
            # (id, title, project, ...) a second time inside the thunk.
            to_detail=lambda: normalize_document_detail(payload, summary=summary, text_limit=detail_text_limit),
            project_link=payload.get("_links", {}).get("project"),
        )

    async def list_all(
        self, *, offset: int, page_size: int, text_limit: int | None = None
    ) -> tuple[list[DocumentRecord], int]:
        payload = await self._transport.get_json(
            "documents", params={"offset": str(offset), "pageSize": str(page_size)}
        )
        elements = payload.get("_embedded", {}).get("elements", [])
        records = [self._record(item, text_limit=text_limit) for item in elements if isinstance(item, dict)]
        total = int(payload.get("total", len(records)))
        return records, total

    async def get(self, document_id: int, *, text_limit: int | None = None) -> DocumentRecord:
        return self._record(
            await self._transport.get_json(f"documents/{document_id}"),
            detail_text_limit=text_limit,
        )

    async def commit_update(self, document_id: int, payload: dict[str, Any]) -> DocumentDetail:
        response = await self._transport.patch_json(f"documents/{document_id}", json_body=payload)
        return normalize_document_detail(response)
