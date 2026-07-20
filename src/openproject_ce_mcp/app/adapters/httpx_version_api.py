"""HTTP-backed VersionApi adapter (ADR 0001).

No `httpx` import (depends on the `Transport` Protocol only). Contains small,
deliberately duplicated private copies of `_trim_text`/`_extract_formattable_text`/
`_trim_text_with_meta`/`_extract_formattable_text_with_meta`/`_link_title`/
`_normalize_validation_errors`/`_delimit_user_content`
(+ `SUBJECT_LIMIT`/`FORMATTABLE_LIMIT`) -- duplicated rather than imported from
client.py to avoid `app/` importing from `client.py` (still used by ~50 other
normalize_* methods and 6 other `_finalize_*_write` variants there). Unify only
once every domain has migrated and client.py's copies become truly dead.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

from ...models import VersionDetail, VersionSummary
from ..ports.version_api import VersionFormResult, VersionPage, VersionRecord, summary_to_detail
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


def _extract_formattable_text(value: Any, *, limit: int = FORMATTABLE_LIMIT) -> str | None:
    if isinstance(value, dict):
        return _trim_text(value.get("raw") or value.get("html"), limit=limit)
    return _trim_text(value, limit=limit)


def _trim_text_with_meta(value: Any, *, limit: int | None) -> tuple[str | None, bool, int | None]:
    """Like ``_trim_text`` but reports truncation metadata. ``limit=None`` means
    no cap. Duplicated from client.py's helper of the same name (see module
    docstring) -- this copy deliberately skips the ``preserve_newlines`` option,
    which client.py's version needs and this adapter's fields don't.
    """
    if value is None:
        return None, False, None
    text = " ".join(str(value).split())
    if not text:
        return None, False, None
    full_length = len(text)
    if limit is None or full_length <= limit:
        return text, False, full_length
    return text[: limit - 1].rstrip() + "…", True, full_length


def _extract_formattable_text_with_meta(
    value: Any, *, limit: int | None = FORMATTABLE_LIMIT
) -> tuple[str | None, bool, int | None]:
    raw = value.get("raw") or value.get("html") if isinstance(value, dict) else value
    return _trim_text_with_meta(raw, limit=limit)


def _link_title(link: Any) -> str | None:
    if not isinstance(link, dict):
        return None
    title = link.get("title")
    return _trim_text(title, limit=SUBJECT_LIMIT)


def _delimit_user_content(text: str | None) -> str | None:
    """Wrap user-provided text in boundary markers for prompt injection safety.

    Duplicated from client.py's helper of the same name, for the same reason
    the other helpers in this module are duplicated (see module docstring).
    """
    if text is None or not text.strip():
        return text
    return f"<user-content>{text}</user-content>"


def _normalize_validation_errors(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, str] = {}
    for key, entry in value.items():
        message = _extract_formattable_text(entry, limit=SUBJECT_LIMIT)
        if message is None and isinstance(entry, dict):
            message = _trim_text(entry.get("message"), limit=SUBJECT_LIMIT)
        if message is None:
            message = _trim_text(entry, limit=SUBJECT_LIMIT)
        if message:
            normalized[str(key)] = message
    return normalized


def normalize_version(
    payload: dict[str, Any], *, base_url: str, text_limit: int | None = FORMATTABLE_LIMIT
) -> VersionSummary:
    """Pure HAL->model translation (ADR: "lives in the Domain API adapter").

    Verbatim port of client.py's normalize_version, minus the _apply_hidden_fields
    call -- hidden-field masking is a Policy decision the Service applies after
    the port returns, not something the adapter does.

    ``text_limit=None`` returns the full description uncapped (single-version
    read); the FORMATTABLE_LIMIT default keeps list/write-preview callers capped
    (OPM-1457, mirrors client.py's work-package/project pattern).
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
        url=urljoin(f"{base_url.rstrip('/')}/", f"versions/{payload['id']}"),
        created_at=payload.get("createdAt"),
        updated_at=payload.get("updatedAt"),
    )


def normalize_version_detail(
    payload: dict[str, Any], *, base_url: str, text_limit: int | None = FORMATTABLE_LIMIT
) -> VersionDetail:
    return summary_to_detail(normalize_version(payload, base_url=base_url, text_limit=text_limit))


class HttpxVersionApi:
    def __init__(self, transport: Transport, *, base_url: str) -> None:
        self._transport = transport
        self._base_url = base_url

    def _record(self, payload: dict[str, Any], *, text_limit: int | None = FORMATTABLE_LIMIT) -> VersionRecord:
        return VersionRecord(
            summary=normalize_version(payload, base_url=self._base_url, text_limit=text_limit),
            defining_project_link=payload.get("_links", {}).get("definingProject"),
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
            if isinstance(item, dict)
        ]
        return VersionPage(records=records, server_total=int(payload.get("total", len(records))))

    async def list_global(
        self, *, offset: int, page_size: int, text_limit: int | None = FORMATTABLE_LIMIT
    ) -> VersionPage:
        payload = await self._transport.get_json("versions", params={"offset": str(offset), "pageSize": str(page_size)})
        records = [
            self._record(item, text_limit=text_limit)
            for item in payload.get("_embedded", {}).get("elements", [])
            if isinstance(item, dict)
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
        return normalize_version_detail(response, base_url=self._base_url)

    async def commit_update(self, version_id: int, payload: dict[str, Any]) -> VersionDetail:
        response = await self._transport.patch_json(f"versions/{version_id}", json_body=payload)
        return normalize_version_detail(response, base_url=self._base_url)

    async def delete(self, version_id: int) -> None:
        await self._transport.delete(f"versions/{version_id}")

    @staticmethod
    def _form_result(form: dict[str, Any]) -> VersionFormResult:
        embedded = form.get("_embedded", {})
        payload = embedded.get("payload", {})
        return VersionFormResult(
            payload=payload, validation_errors=_normalize_validation_errors(embedded.get("validationErrors"))
        )
