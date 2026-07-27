"""HTTP-backed StatusPriorityTypeApi adapter (16th migrated domain, OPM-1627).

No `httpx` import (depends on the `Transport` Protocol only). `trim_text` is
shared via `app/adapters/_text.py` (verified against client.py's real
module-level `_trim_text` -- unchanged, safe to reuse).

`normalize_status`/`normalize_priority`/`normalize_type` are pure HAL->model
translation, no hidden-field awareness (masking is a Service-layer concern,
applied after these return -- see `status_priority_type_service.py`).
Verbatim ports of client.py's originals, minus each one's own
`_apply_hidden_fields` call.

Two different URL-building shapes are preserved deliberately, not unified --
verified as a genuine, non-accidental difference in client.py, not a
copy-paste drift to fix: `normalize_status`'s `url` used `self._api_href(...)`
(a relative `/api/v3/...` href, via the shared `app/api_href.py` helper here),
while `normalize_type`'s `url` used `self._web_url(...)` (an absolute web URL
joined against `base_url`, matching Category's adapter's `urljoin` pattern).
`PrioritySummary` has no `url` field at all -- client.py's original
`normalize_priority` never built one.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

from ...app.api_href import api_href
from ...models import PrioritySummary, StatusSummary, TypeSummary
from ..ports.status_priority_type_api import PriorityRecord, StatusRecord, TypeRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import trim_text as _trim_text


def normalize_status(payload: dict[str, Any], *, api_prefix: str) -> StatusSummary:
    status_id = int(payload["id"])
    return StatusSummary(
        id=status_id,
        name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or f"Status {status_id}",
        is_default=bool(payload.get("isDefault")),
        is_closed=bool(payload.get("isClosed")),
        color=_trim_text(payload.get("color"), limit=SUBJECT_LIMIT),
        position=payload.get("position"),
        url=api_href(f"statuses/{status_id}", api_prefix=api_prefix),
        is_readonly=payload.get("isReadonly"),
        default_done_ratio=payload.get("defaultDoneRatio"),
        excluded_from_totals=payload.get("excludedFromTotals"),
    )


def normalize_priority(payload: dict[str, Any]) -> PrioritySummary:
    priority_id = int(payload["id"])
    return PrioritySummary(
        id=priority_id,
        name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or f"Priority {priority_id}",
        is_default=bool(payload.get("isDefault")),
        is_active=bool(payload.get("isActive")),
        color=_trim_text(payload.get("color"), limit=SUBJECT_LIMIT),
        position=payload.get("position"),
    )


def normalize_type(payload: dict[str, Any], *, base_url: str) -> TypeSummary:
    type_id = int(payload["id"])
    return TypeSummary(
        id=type_id,
        name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or f"Type {type_id}",
        color=_trim_text(payload.get("color"), limit=SUBJECT_LIMIT),
        position=payload.get("position"),
        is_default=bool(payload.get("isDefault")),
        is_milestone=bool(payload.get("isMilestone")),
        url=urljoin(f"{base_url.rstrip('/')}/", f"types/{type_id}"),
        created_at=payload.get("createdAt"),
        updated_at=payload.get("updatedAt"),
    )


class HttpxStatusPriorityTypeApi:
    def __init__(self, transport: Transport, *, base_url: str, api_prefix: str) -> None:
        self._transport = transport
        self._base_url = base_url
        self._api_prefix = api_prefix

    async def list_statuses(self) -> list[StatusRecord]:
        payload = await self._transport.get_json("statuses")
        elements = payload.get("_embedded", {}).get("elements", [])
        return [
            StatusRecord(summary=normalize_status(item, api_prefix=self._api_prefix))
            for item in elements
            if isinstance(item, dict)
        ]

    async def get_status(self, status_id: int) -> StatusRecord:
        payload = await self._transport.get_json(f"statuses/{status_id}")
        return StatusRecord(summary=normalize_status(payload, api_prefix=self._api_prefix))

    async def list_priorities(self) -> list[PriorityRecord]:
        payload = await self._transport.get_json("priorities")
        elements = payload.get("_embedded", {}).get("elements", [])
        return [PriorityRecord(summary=normalize_priority(item)) for item in elements if isinstance(item, dict)]

    async def get_priority(self, priority_id: int) -> PriorityRecord:
        payload = await self._transport.get_json(f"priorities/{priority_id}")
        return PriorityRecord(summary=normalize_priority(payload))

    async def list_types(self, *, project_id: int | None) -> list[TypeRecord]:
        path = f"projects/{project_id}/types" if project_id is not None else "types"
        payload = await self._transport.get_json(path)
        elements = payload.get("_embedded", {}).get("elements", [])
        return [
            TypeRecord(summary=normalize_type(item, base_url=self._base_url))
            for item in elements
            if isinstance(item, dict)
        ]

    async def get_type(self, type_id: int) -> TypeRecord:
        payload = await self._transport.get_json(f"types/{type_id}")
        return TypeRecord(summary=normalize_type(payload, base_url=self._base_url))
