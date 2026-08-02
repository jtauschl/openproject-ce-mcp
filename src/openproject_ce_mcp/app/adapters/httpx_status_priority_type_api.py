"""HTTP-backed StatusPriorityTypeApi adapter.

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


def _lookup_name(payload: dict[str, Any]) -> str:
    """The raw, never-synthesized name used for exact-name resolution.

    Deliberately NOT `_trim_text(...) or f"X {id}"` -- that fallback is
    display-only behavior (see module docstring). A blank/missing raw name
    must never accidentally match a caller's literal-string search.
    """
    return str(payload.get("name", ""))


def _has_usable_id(item: Any) -> bool:
    """True for a dict element whose `id` can become a valid Record id.

    List endpoints skip an element failing this check rather than raising --
    an unrelated malformed row must not break resolution/listing of every
    other, well-formed row. Single-item `get_*` calls stay strict: a
    malformed response to a request for one specific id is a real error,
    not a row to silently skip.
    """
    if not isinstance(item, dict):
        return False
    raw_id = item.get("id")
    return isinstance(raw_id, int | str) and str(raw_id).isdigit()


class HttpxStatusPriorityTypeApi:
    def __init__(self, transport: Transport, *, base_url: str, api_prefix: str) -> None:
        self._transport = transport
        self._base_url = base_url
        self._api_prefix = api_prefix

    async def list_statuses(self) -> list[StatusRecord]:
        payload = await self._transport.get_json("statuses")
        elements = payload.get("_embedded", {}).get("elements", [])
        return [
            StatusRecord(summary=normalize_status(item, api_prefix=self._api_prefix), lookup_name=_lookup_name(item))
            for item in elements
            if _has_usable_id(item)
        ]

    async def get_status(self, status_id: int) -> StatusRecord:
        payload = await self._transport.get_json(f"statuses/{status_id}")
        return StatusRecord(
            summary=normalize_status(payload, api_prefix=self._api_prefix), lookup_name=_lookup_name(payload)
        )

    async def list_priorities(self) -> list[PriorityRecord]:
        payload = await self._transport.get_json("priorities")
        elements = payload.get("_embedded", {}).get("elements", [])
        return [
            PriorityRecord(summary=normalize_priority(item), lookup_name=_lookup_name(item))
            for item in elements
            if _has_usable_id(item)
        ]

    async def get_priority(self, priority_id: int) -> PriorityRecord:
        payload = await self._transport.get_json(f"priorities/{priority_id}")
        return PriorityRecord(summary=normalize_priority(payload), lookup_name=_lookup_name(payload))

    async def list_types(self, *, project_id: int | None) -> list[TypeRecord]:
        path = f"projects/{project_id}/types" if project_id is not None else "types"
        payload = await self._transport.get_json(path)
        elements = payload.get("_embedded", {}).get("elements", [])
        return [
            TypeRecord(summary=normalize_type(item, base_url=self._base_url), lookup_name=_lookup_name(item))
            for item in elements
            if _has_usable_id(item)
        ]

    async def get_type(self, type_id: int) -> TypeRecord:
        payload = await self._transport.get_json(f"types/{type_id}")
        return TypeRecord(summary=normalize_type(payload, base_url=self._base_url), lookup_name=_lookup_name(payload))
