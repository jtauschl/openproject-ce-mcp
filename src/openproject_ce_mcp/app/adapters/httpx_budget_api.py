"""HTTP-backed BudgetApi adapter.

No `httpx` import (depends on the `Transport` Protocol only, matching every
other adapter).
"""

from __future__ import annotations

from typing import Any

from ...models import BudgetSummary
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import trim_text as _trim_text


def normalize_budget(payload: dict[str, Any]) -> BudgetSummary:
    """Pure HAL->model translation. Excludes hidden-field masking."""
    budget_id = int(payload["id"])
    return BudgetSummary(
        id=budget_id,
        subject=_trim_text(payload.get("subject"), limit=SUBJECT_LIMIT) or f"Budget {budget_id}",
    )


class HttpxBudgetApi:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    async def list_for_project(self, project_id: int) -> list[BudgetSummary]:
        payload = await self._transport.get_json(f"projects/{project_id}/budgets")
        elements = payload.get("_embedded", {}).get("elements", [])
        return [normalize_budget(item) for item in elements if isinstance(item, dict)]
