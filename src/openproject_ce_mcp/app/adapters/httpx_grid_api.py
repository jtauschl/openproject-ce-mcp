"""HTTP-backed GridApi adapter (ADR 0001).

No `httpx` import (depends on the `Transport` Protocol only).

`_normalize_validation_errors`/`_extract_formattable_text` here are ported
from client.py's MODULE-LEVEL versions (client.py:6986-6998, 7071-7074), NOT
copied from HttpxMembershipApi's local copy -- the two genuinely differ:
client.py's module-level version tries `_extract_formattable_text` first,
then `entry.get("message")`, then a raw trim fallback; Memberships' local
copy skips the `_extract_formattable_text` branch entirely. client.py's
original create_grid/update_grid used the module-level version (grids never
had their own local copy in the flat code), so this adapter ports that exact
three-branch shape to stay behaviorally equivalent.
"""

from __future__ import annotations

import json
from typing import Any

from ...models import GridSummary
from ..api_href import api_href as _api_href
from ..ports.grid_api import GridFormResult, GridRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import trim_text as _trim_text


def _extract_formattable_text(value: Any, *, limit: int) -> str | None:
    if isinstance(value, dict):
        return _trim_text(value.get("raw") or value.get("html"), limit=limit)
    return _trim_text(value, limit=limit)


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


def normalize_grid(payload: dict[str, Any], *, api_prefix: str) -> GridSummary:
    """Pure HAL->model translation (ADR: 'lives in the Domain API adapter').

    Verbatim port of client.py's normalize_grid, minus the
    _apply_hidden_fields call. Note GridSummary has no `name` field --
    client.py's original never reads payload.get("name") either, even
    though create_grid/update_grid accept and write one; this is the
    existing contract, not a gap to fix here.
    """
    grid_id = int(payload["id"])
    links = payload.get("_links", {})
    scope_link = links.get("scope")
    scope_href = scope_link.get("href") if isinstance(scope_link, dict) else None
    scope = _trim_text(scope_href, limit=SUBJECT_LIMIT)
    return GridSummary(
        id=grid_id,
        row_count=payload.get("rowCount"),
        column_count=payload.get("columnCount"),
        scope=scope,
        created_at=payload.get("createdAt"),
        updated_at=payload.get("updatedAt"),
        url=_api_href(f"grids/{grid_id}", api_prefix=api_prefix),
    )


class HttpxGridApi:
    def __init__(self, transport: Transport, *, api_prefix: str = "/api/v3/") -> None:
        self._transport = transport
        self._api_prefix = api_prefix

    def _record(self, payload: dict[str, Any]) -> GridRecord:
        return GridRecord(
            summary=normalize_grid(payload, api_prefix=self._api_prefix),
            scope_link=payload.get("_links", {}).get("scope"),
        )

    async def list_all(self, *, scope_filter: str | None, page_size: int) -> list[GridRecord]:
        params: dict[str, str] = {"offset": "1", "pageSize": str(page_size)}
        if scope_filter is not None:
            params["filters"] = json.dumps(
                [{"scope": {"operator": "=", "values": [scope_filter]}}], separators=(",", ":")
            )
        payload = await self._transport.get_json("grids", params=params)
        elements = payload.get("_embedded", {}).get("elements", [])
        return [self._record(item) for item in elements if isinstance(item, dict)]

    async def get(self, grid_id: int) -> GridRecord:
        return self._record(await self._transport.get_json(f"grids/{grid_id}"))

    async def create_form(self, payload: dict[str, Any]) -> GridFormResult:
        return self._form_result(await self._transport.post_json("grids/form", json_body=payload))

    async def update_form(self, grid_id: int, payload: dict[str, Any]) -> GridFormResult:
        return self._form_result(await self._transport.post_json(f"grids/{grid_id}/form", json_body=payload))

    async def commit_create(self, payload: dict[str, Any]) -> GridSummary:
        response = await self._transport.post_json("grids", json_body=payload)
        return normalize_grid(response, api_prefix=self._api_prefix)

    async def commit_update(self, grid_id: int, payload: dict[str, Any]) -> GridSummary:
        response = await self._transport.patch_json(f"grids/{grid_id}", json_body=payload)
        return normalize_grid(response, api_prefix=self._api_prefix)

    async def delete(self, grid_id: int) -> None:
        await self._transport.delete(f"grids/{grid_id}")

    @staticmethod
    def _form_result(form: dict[str, Any]) -> GridFormResult:
        embedded = form.get("_embedded", {})
        payload = embedded.get("payload", {})
        return GridFormResult(
            payload=payload, validation_errors=_normalize_validation_errors(embedded.get("validationErrors"))
        )
