"""HTTP-backed FileLinkApi adapter (ADR 0001, OPM-318 first consumer).

No `httpx` import (depends on the `Transport` Protocol only, matching every
other adapter). `trim_text`/`id_from_href`/`link_title`/`SUBJECT_LIMIT` come
from `app/adapters/_text.py` -- verified against client.py's real
`normalize_file_link` (client.py:4444-4462): this normalizer needs exactly
`trim_text` (title truncation), `id_from_href` (storage id from the storage
link's href), and `link_title` (storage name from the storage link's title)
-- no formattable-text extraction, no delimit_user_content (file link titles
are plain filenames, not user-content-marked rich text in the original
either). Only `api_prefix` is needed for URL construction (the emitted `url`
is an API href, like `HttpxGridApi`, not a web link) -- no `base_url`.
"""

from __future__ import annotations

from typing import Any

from ...models import FileLinkSummary
from ..api_href import api_href as _api_href
from ..ports.file_link_api import FileLinkRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import id_from_href as _id_from_href
from ._text import link_title as _link_title
from ._text import trim_text as _trim_text


def normalize_file_link(payload: dict[str, Any], *, api_prefix: str) -> FileLinkSummary:
    """Pure HAL->model translation (ADR: 'lives in the Domain API adapter').

    Verbatim port of client.py's normalize_file_link, minus the
    _apply_hidden_fields call -- masking is a Service-layer concern applied
    after this returns (same pattern as every other migrated normalize_*).
    """
    file_link_id = int(payload["id"])
    links = payload.get("_links", {})
    storage_link = links.get("storage")
    storage_id = _id_from_href(storage_link.get("href")) if isinstance(storage_link, dict) else None
    storage_name = _link_title(storage_link)
    return FileLinkSummary(
        id=file_link_id,
        title=_trim_text(payload.get("title") or payload.get("originData", {}).get("name"), limit=SUBJECT_LIMIT)
        or f"File link {file_link_id}",
        storage_id=storage_id,
        storage_name=storage_name,
        created_at=payload.get("createdAt"),
        updated_at=payload.get("updatedAt"),
        url=_api_href(f"file_links/{file_link_id}", api_prefix=api_prefix),
    )


class HttpxFileLinkApi:
    def __init__(self, transport: Transport, *, api_prefix: str = "/api/v3/") -> None:
        self._transport = transport
        self._api_prefix = api_prefix

    def _record(self, payload: dict[str, Any]) -> FileLinkRecord:
        return FileLinkRecord(
            summary=normalize_file_link(payload, api_prefix=self._api_prefix),
            container_link=payload.get("_links", {}).get("container"),
        )

    async def list_for_work_package(self, work_package_id: int) -> list[FileLinkRecord]:
        payload = await self._transport.get_json(f"work_packages/{work_package_id}/file_links")
        elements = payload.get("_embedded", {}).get("elements", [])
        return [self._record(item) for item in elements if isinstance(item, dict)]

    async def get(self, file_link_id: int) -> FileLinkRecord:
        return self._record(await self._transport.get_json(f"file_links/{file_link_id}"))

    async def delete(self, file_link_id: int) -> None:
        await self._transport.delete(f"file_links/{file_link_id}")
