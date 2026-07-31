"""HTTP-backed AttachmentApi adapter (ADR 0001).

No `httpx` import (depends on the `Transport` Protocol only, matching every
other adapter). `trim_text`/`id_from_href`/`link_title`/`delimit_user_content`/
`link_to_web_url`/`web_url`/`slug_from_href`/`SUBJECT_LIMIT` come from
`app/adapters/_text.py` -- verified against client.py's real
`normalize_attachment` (client.py:3517-3548), which needs all seven:
`trim_text` (title/file_name/content_type/status truncation),
`delimit_user_content` + `_extract_formattable_text` (description --
`_extract_formattable_text` stays local, per the documented per-adapter
exception), `link_title` (author), `id_from_href` (container_id from the
container link), `slug_from_href` (container_type fallback for a non-work-
-package container), `link_to_web_url` (same-origin-checked download_url),
`web_url` (the attachment's own API url).

`list_for_work_package` hand-rolls its own page-walk (offset/pageSize with a
`seen_ids`/first-page guard against a server that ignores both params and
always returns the same full page) rather than using `app/pagination.
paginate_all`: `paginate_all` requires a `(items, total)` return contract, and
client.py's original `list_work_package_attachments` never read a `total`
field from this endpoint's response -- only `_embedded.elements`. Reusing
`paginate_all` here would be an unverified, speculative behavior change, not
a structural port.
"""

from __future__ import annotations

from typing import Any

from ...models import AttachmentSummary
from ..ports.attachment_api import AttachmentRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import delimit_user_content as _delimit_user_content
from ._text import id_from_href as _id_from_href
from ._text import link_title as _link_title
from ._text import link_to_web_url as _link_to_web_url
from ._text import slug_from_href as _slug_from_href
from ._text import trim_text as _trim_text
from ._text import web_url as _web_url


def _extract_formattable_text(value: Any) -> str | None:
    """Local, deliberately not `_text.py`-shared (per the documented
    per-adapter exception) -- verbatim of client.py's own
    `_extract_formattable_text`, minus the truncation-limit parameter this
    call site never used (description has no text_limit in
    normalize_attachment)."""
    if not isinstance(value, dict):
        return None
    return value.get("raw") or value.get("html")


def normalize_attachment(payload: dict[str, Any], *, base_url: str, origin: str) -> AttachmentSummary:
    """Pure HAL->model translation (ADR: 'lives in the Domain API adapter').

    Verbatim port of client.py's normalize_attachment, minus the
    _apply_hidden_fields call -- masking is a Service-layer concern applied
    after this returns (same pattern as every other migrated normalize_*).
    """
    links = payload.get("_links", {})
    container_link = links.get("container")
    container_href = container_link.get("href") if isinstance(container_link, dict) else None
    container_type = None
    if isinstance(container_href, str):
        if "work_packages/" in container_href:
            container_type = "WorkPackage"
        else:
            container_type = _slug_from_href(container_href)
    download_href = None
    if isinstance(links.get("downloadLocation"), dict):
        download_href = links["downloadLocation"].get("href")
    if not download_href and isinstance(links.get("staticDownloadLocation"), dict):
        download_href = links["staticDownloadLocation"].get("href")
    return AttachmentSummary(
        id=int(payload["id"]),
        title=_trim_text(payload.get("title") or payload.get("fileName"), limit=SUBJECT_LIMIT)
        or f"Attachment {payload['id']}",
        file_name=_trim_text(payload.get("fileName"), limit=SUBJECT_LIMIT),
        file_size=payload.get("fileSize"),
        description=_delimit_user_content(_extract_formattable_text(payload.get("description"))),
        content_type=_trim_text(payload.get("contentType"), limit=SUBJECT_LIMIT),
        status=_trim_text(payload.get("status"), limit=SUBJECT_LIMIT),
        author=_link_title(links.get("author")),
        container_type=container_type,
        container_id=_id_from_href(container_href),
        created_at=payload.get("createdAt"),
        download_url=_link_to_web_url(download_href, base_url=base_url, origin=origin),
        url=_web_url(f"api/v3/attachments/{payload['id']}", base_url=base_url),
    )


class HttpxAttachmentApi:
    def __init__(self, transport: Transport, *, base_url: str, origin: str) -> None:
        self._transport = transport
        self._base_url = base_url
        self._origin = origin

    def _record(self, payload: dict[str, Any]) -> AttachmentRecord:
        return AttachmentRecord(
            summary=normalize_attachment(payload, base_url=self._base_url, origin=self._origin),
            container_link=payload.get("_links", {}).get("container"),
        )

    async def list_for_work_package(self, work_package_id: int, *, page_size: int) -> list[AttachmentRecord]:
        # No pageSize was ever sent by the original code, silently relying on
        # OpenProject's own server-side default page size -- any attachment
        # beyond that default was permanently unreachable. Walk every server
        # page instead, verbatim of client.py's original guard-loop shape.
        # page_size comes from the Service (settings.max_page_size), not
        # hardcoded here -- Adapters hold no Settings dependency.
        offset = 1
        results: list[AttachmentRecord] = []
        seen_ids: set[Any] = set()
        is_first_page = True
        while True:
            payload = await self._transport.get_json(
                f"work_packages/{work_package_id}/attachments",
                params={"offset": str(offset), "pageSize": str(page_size)},
            )
            elements = [item for item in payload.get("_embedded", {}).get("elements", []) if isinstance(item, dict)]
            # Some work-package-scoped sub-collection endpoints may silently
            # ignore offset/pageSize and always return every element --
            # without this check, `len(elements) < page_size` never becomes
            # true and this loops forever, re-fetching the same full page.
            page_ids = {item.get("id") for item in elements}
            if not is_first_page and page_ids and page_ids <= seen_ids:
                break
            is_first_page = False
            seen_ids.update(page_ids)
            results.extend(self._record(item) for item in elements)
            if len(elements) < page_size:
                break
            offset += 1
        return results

    async def get(self, attachment_id: int) -> AttachmentRecord:
        return self._record(await self._transport.get_json(f"attachments/{attachment_id}"))

    async def create(
        self,
        work_package_id: int,
        *,
        metadata: dict[str, Any],
        file_name: str,
        file_bytes: bytes,
        content_type: str,
    ) -> AttachmentRecord:
        response = await self._transport.post_multipart(
            f"work_packages/{work_package_id}/attachments",
            metadata=metadata,
            file_name=file_name,
            file_bytes=file_bytes,
            content_type=content_type,
        )
        return self._record(response)

    async def delete(self, attachment_id: int) -> None:
        await self._transport.delete(f"attachments/{attachment_id}")

    async def get_max_attachment_size(self) -> int | None:
        payload = await self._transport.get_json("configuration")
        maximum = payload.get("maximumAttachmentFileSize")
        return int(maximum) if isinstance(maximum, int | float) else None
