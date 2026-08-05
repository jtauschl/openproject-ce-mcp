"""HTTP-backed GridApi adapter.

No `httpx` import (depends on the `Transport` Protocol only).

`normalize_form_validation_errors` (from `_text.py`) is NOT the same as
HttpxMembershipApi's local validation-error normalizer -- the two genuinely
differ in behavior and are not interchangeable: `normalize_form_validation_errors`
tries formattable-text extraction first, then `entry.get("message")`, then a
raw trim fallback; Memberships' local copy skips the formattable-text branch
entirely. This adapter's `create`/`update` form-validation responses use the
three-branch shape.
"""

from __future__ import annotations

import json
from typing import Any

from ...models import GridSummary
from ..ports.grid_api import GridFormResult, GridRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import normalize_form_validation_errors as _normalize_validation_errors
from ._text import trim_text as _trim_text


def normalize_grid(payload: dict[str, Any]) -> GridSummary:
    """Pure HAL->model translation (ADR: 'lives in the Domain API adapter').

    `GridSummary` has no `name` field: this function never reads
    `payload.get("name")`, even though `create_grid`/`update_grid` accept and
    write one. That asymmetry is the existing contract, not a gap to fix here.
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
    )


class HttpxGridApi:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def _record(self, payload: dict[str, Any]) -> GridRecord:
        return GridRecord(
            summary=normalize_grid(payload),
            scope_link=payload.get("_links", {}).get("scope"),
        )

    async def list_page(self, *, offset: int, page_size: int, scope_filter: str | None) -> tuple[list[GridRecord], int]:
        params: dict[str, str] = {"offset": str(offset), "pageSize": str(page_size)}
        if scope_filter is not None:
            params["filters"] = json.dumps(
                [{"scope": {"operator": "=", "values": [scope_filter]}}], separators=(",", ":")
            )
        payload = await self._transport.get_json("grids", params=params)
        elements = payload.get("_embedded", {}).get("elements", [])
        records = [self._record(item) for item in elements if isinstance(item, dict)]
        total = int(payload.get("total", len(records)))
        return records, total

    async def get(self, grid_id: int) -> GridRecord:
        return self._record(await self._transport.get_json(f"grids/{grid_id}"))

    async def create_form(self, payload: dict[str, Any]) -> GridFormResult:
        return self._form_result(await self._transport.post_json("grids/form", json_body=payload))

    async def update_form(self, grid_id: int, payload: dict[str, Any]) -> GridFormResult:
        return self._form_result(await self._transport.post_json(f"grids/{grid_id}/form", json_body=payload))

    async def commit_create(self, payload: dict[str, Any]) -> GridSummary:
        response = await self._transport.post_json("grids", json_body=payload)
        return normalize_grid(response)

    async def commit_update(self, grid_id: int, payload: dict[str, Any]) -> GridSummary:
        response = await self._transport.patch_json(f"grids/{grid_id}", json_body=payload)
        return normalize_grid(response)

    async def delete(self, grid_id: int) -> None:
        await self._transport.delete(f"grids/{grid_id}")

    @staticmethod
    def _form_result(form: dict[str, Any]) -> GridFormResult:
        embedded = form.get("_embedded", {})
        payload = embedded.get("payload", {})
        return GridFormResult(
            payload=payload, validation_errors=_normalize_validation_errors(embedded.get("validationErrors"))
        )
