"""HTTP-backed VersionApi adapter.

No `httpx` import (depends on the `Transport` Protocol only). `_trim_text`/
`_link_title`/`_delimit_user_content`/`SUBJECT_LIMIT`/`_trim_text_with_meta`/
`_extract_formattable_text_with_meta`/`FORMATTABLE_LIMIT`/`_has_usable_id`/
`_normalize_validation_errors` (as `_normalize_form_validation_errors`) are
shared via `app/adapters/_text.py`. This adapter's fields never need
`preserve_newlines=True`, so it relies on the shared helper's `False`
default.
"""

from __future__ import annotations

from typing import Any

from ...models import VersionDetail, VersionSummary
from ..ports.version_api import VersionFormResult, VersionPage, VersionRecord, summary_to_detail
from ..transport.protocol import Transport
from ._text import FORMATTABLE_LIMIT, SUBJECT_LIMIT
from ._text import delimit_user_content as _delimit_user_content
from ._text import extract_formattable_text_with_meta as _extract_formattable_text_with_meta
from ._text import has_usable_id as _has_usable_id
from ._text import link_title as _link_title
from ._text import normalize_form_validation_errors as _normalize_validation_errors
from ._text import trim_text as _trim_text


def normalize_version(payload: dict[str, Any], *, text_limit: int | None = FORMATTABLE_LIMIT) -> VersionSummary:
    """Pure HAL->model translation (ADR: "lives in the Domain API adapter").

    Excludes hidden-field masking -- that is a Policy decision the Service
    applies after this returns, not something the adapter does.

    ``text_limit=None`` returns the full description uncapped (single-version
    read); the FORMATTABLE_LIMIT default keeps list/write-preview callers
    capped (mirrors the work-package/project pattern).
    """
    links = payload.get("_links", {})
    description, description_truncated, description_length = _extract_formattable_text_with_meta(
        payload.get("description"), limit=text_limit
    )
    return VersionSummary(
        id=int(payload["id"]),
        name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or f"Version {payload['id']}",
        status=payload.get("status"),
        sharing=payload.get("sharing"),
        start_date=payload.get("startDate"),
        end_date=payload.get("endDate"),
        defining_project=_link_title(links.get("definingProject")),
        description=_delimit_user_content(description),
        description_truncated=description_truncated,
        description_length=description_length,
        created_at=payload.get("createdAt"),
        updated_at=payload.get("updatedAt"),
    )


def normalize_version_detail(payload: dict[str, Any], *, text_limit: int | None = FORMATTABLE_LIMIT) -> VersionDetail:
    return summary_to_detail(normalize_version(payload, text_limit=text_limit))


class HttpxVersionApi:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def _record(self, payload: dict[str, Any], *, text_limit: int | None = FORMATTABLE_LIMIT) -> VersionRecord:
        return VersionRecord(
            summary=normalize_version(payload, text_limit=text_limit),
            defining_project_link=payload.get("_links", {}).get("definingProject"),
            lookup_name=str(payload.get("name", "")),
        )

    async def list_for_project(
        self, project_id: int, *, offset: int, page_size: int, text_limit: int | None = FORMATTABLE_LIMIT
    ) -> VersionPage:
        payload = await self._transport.get_json(
            f"projects/{project_id}/versions", params={"offset": str(offset), "pageSize": str(page_size)}
        )
        records = [
            self._record(item, text_limit=text_limit)
            for item in payload.get("_embedded", {}).get("elements", [])
            if _has_usable_id(item)
        ]
        return VersionPage(records=records, server_total=int(payload.get("total", len(records))))

    async def list_global(
        self, *, offset: int, page_size: int, text_limit: int | None = FORMATTABLE_LIMIT
    ) -> VersionPage:
        payload = await self._transport.get_json("versions", params={"offset": str(offset), "pageSize": str(page_size)})
        records = [
            self._record(item, text_limit=text_limit)
            for item in payload.get("_embedded", {}).get("elements", [])
            if _has_usable_id(item)
        ]
        return VersionPage(records=records, server_total=None)

    async def get(self, version_id: int, *, text_limit: int | None = FORMATTABLE_LIMIT) -> VersionRecord:
        return self._record(await self._transport.get_json(f"versions/{version_id}"), text_limit=text_limit)

    async def create_form(self, payload: dict[str, Any]) -> VersionFormResult:
        return self._form_result(await self._transport.post_json("versions/form", json_body=payload))

    async def update_form(self, version_id: int, payload: dict[str, Any]) -> VersionFormResult:
        # POST, not PATCH -- the /form endpoint is always POST even for updates.
        return self._form_result(await self._transport.post_json(f"versions/{version_id}/form", json_body=payload))

    async def commit_create(self, payload: dict[str, Any]) -> VersionDetail:
        response = await self._transport.post_json("versions", json_body=payload)
        return normalize_version_detail(response)

    async def commit_update(self, version_id: int, payload: dict[str, Any]) -> VersionDetail:
        response = await self._transport.patch_json(f"versions/{version_id}", json_body=payload)
        return normalize_version_detail(response)

    async def delete(self, version_id: int) -> None:
        await self._transport.delete(f"versions/{version_id}")

    @staticmethod
    def _form_result(form: dict[str, Any]) -> VersionFormResult:
        embedded = form.get("_embedded", {})
        payload = embedded.get("payload", {})
        return VersionFormResult(
            payload=payload, validation_errors=_normalize_validation_errors(embedded.get("validationErrors"))
        )
