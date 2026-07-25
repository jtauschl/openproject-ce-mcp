"""HTTP-backed DocumentApi adapter (ADR 0001).

No `httpx` import (depends on the `Transport` Protocol only). Contains small,
deliberately duplicated private copies of `_trim_text`/`_id_from_href`/
`_link_title`/`_can_update_from_links`/`_delimit_user_content`/
`_link_to_web_url`/`_origin_from_url` (+ `SUBJECT_LIMIT`/`FORMATTABLE_LIMIT`),
after the established duplication pattern (see HttpxProjectApi's module
docstring) -- unify only once every domain has migrated.

`_extract_formattable_text` here keeps the `.get("raw") or .get("html")`
fallback that client.py's original has (and that HttpxProjectApi/
HttpxVersionApi also keep) -- verified against client.py directly rather
than copied from HttpxNewsApi's local copy, which is missing this fallback.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin, urlparse

from ...models import DocumentDetail, DocumentSummary
from ..ports.document_api import DocumentRecord
from ..transport.protocol import Transport

SUBJECT_LIMIT = 255
FORMATTABLE_LIMIT = 1_200


def _trim_text(value: Any, *, limit: int) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _id_from_href(href: str | None) -> int | None:
    if not href:
        return None
    parts = href.rstrip("/").split("/")
    try:
        return int(parts[-1])
    except (ValueError, IndexError):
        return None


def _link_title(link: Any) -> str | None:
    if not isinstance(link, dict):
        return None
    title = link.get("title")
    return _trim_text(title, limit=SUBJECT_LIMIT)


def _can_update_from_links(links: dict[str, Any]) -> bool:
    return "update" in links or "updateImmediately" in links


def _delimit_user_content(text: str | None) -> str | None:
    if text is None or not text.strip():
        return text
    return f"<user-content>{text}</user-content>"


def _extract_formattable_text(value: Any, *, limit: int) -> str | None:
    raw = value.get("raw") or value.get("html") if isinstance(value, dict) else value
    return _trim_text(raw, limit=limit)


def _origin_from_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def normalize_document(payload: dict[str, Any], *, base_url: str) -> DocumentSummary:
    """Pure HAL->model translation (ADR: 'lives in the Domain API adapter').

    Verbatim port of client.py's normalize_document, minus the
    _apply_hidden_fields call and the hidden-field-aware text extraction --
    hidden-field masking of the whole `description` value is a Policy/Service
    decision applied after this returns (same pattern as normalize_news's
    port: dropping the field_hidden check here changes nothing observable,
    since the Service masks the entire field afterwards regardless).
    """
    links = payload.get("_links", {})
    attachments = payload.get("_embedded", {}).get("attachments", {})
    attachment_count = 0
    if isinstance(attachments, dict):
        attachment_count = int(attachments.get("count") or attachments.get("total") or 0)
    description = _delimit_user_content(_extract_formattable_text(payload.get("description"), limit=SUBJECT_LIMIT))
    return DocumentSummary(
        id=int(payload["id"]),
        title=_trim_text(payload.get("title"), limit=SUBJECT_LIMIT) or f"Document {payload['id']}",
        project_id=_id_from_href(links.get("project", {}).get("href")),
        project=_link_title(links.get("project")),
        description=description,
        created_at=payload.get("createdAt"),
        attachment_count=attachment_count,
        can_update=_can_update_from_links(links),
        url=urljoin(f"{base_url.rstrip('/')}/", f"documents/{payload['id']}"),
    )


def normalize_document_detail(payload: dict[str, Any], *, base_url: str, origin: str) -> DocumentDetail:
    """Verbatim port of client.py's normalize_document_detail. Reuses every
    field from normalize_document() EXCEPT description, which is
    independently re-extracted from the same raw payload at the larger
    FORMATTABLE_LIMIT cap (not SUBJECT_LIMIT) -- the two normalizers apply
    different truncation limits to the same raw text, so this cannot be a
    simple copy of summary.
    """
    summary = normalize_document(payload, base_url=base_url)
    links = payload.get("_links", {})
    description = _delimit_user_content(_extract_formattable_text(payload.get("description"), limit=FORMATTABLE_LIMIT))
    return DocumentDetail(
        id=summary.id,
        title=summary.title,
        project_id=summary.project_id,
        project=summary.project,
        description=description,
        created_at=summary.created_at,
        attachment_count=summary.attachment_count,
        attachments_url=_link_to_web_url(links.get("attachments", {}).get("href"), base_url=base_url, origin=origin),
        can_update=summary.can_update,
        url=summary.url,
    )


def _link_to_web_url(href: str | None, *, base_url: str, origin: str) -> str | None:
    """Same-origin-checked href -> absolute web URL, or None for a foreign origin.

    Verbatim port of client.py's _link_to_web_url: a foreign-origin absolute
    href silently yields None rather than raising.
    """
    if not href:
        return None
    parsed = urlparse(href)
    if parsed.scheme:
        if _origin_from_url(href) != origin:
            return None
        return href
    if href.startswith("/"):
        return urljoin(f"{origin.rstrip('/')}/", href.lstrip("/"))
    return urljoin(f"{base_url.rstrip('/')}/", href)


class HttpxDocumentApi:
    def __init__(self, transport: Transport, *, base_url: str) -> None:
        self._transport = transport
        self._base_url = base_url
        self._origin = _origin_from_url(base_url)

    def _record(self, payload: dict[str, Any]) -> DocumentRecord:
        base_url = self._base_url
        origin = self._origin
        return DocumentRecord(
            summary=normalize_document(payload, base_url=base_url),
            # Lazy: only get()/update() (single-item paths) ever call this;
            # list_all()'s per-row records never do, so this avoids a second,
            # independent FORMATTABLE_LIMIT-capped re-extraction of every
            # record's description on every list call. The closure captures
            # only `payload`/`base_url`/`origin` (small, per-record), not
            # `self` -- it does not keep a whole adapter/transport alive.
            to_detail=lambda: normalize_document_detail(payload, base_url=base_url, origin=origin),
            project_link=payload.get("_links", {}).get("project"),
        )

    async def list_all(self, *, page_size: int) -> list[DocumentRecord]:
        payload = await self._transport.get_json("documents", params={"offset": "1", "pageSize": str(page_size)})
        elements = payload.get("_embedded", {}).get("elements", [])
        return [self._record(item) for item in elements if isinstance(item, dict)]

    async def get(self, document_id: int) -> DocumentRecord:
        return self._record(await self._transport.get_json(f"documents/{document_id}"))

    async def commit_update(self, document_id: int, payload: dict[str, Any]) -> DocumentDetail:
        response = await self._transport.patch_json(f"documents/{document_id}", json_body=payload)
        return normalize_document_detail(response, base_url=self._base_url, origin=self._origin)
