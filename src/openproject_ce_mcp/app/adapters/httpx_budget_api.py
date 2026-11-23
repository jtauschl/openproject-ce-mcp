"""HTTP-backed BudgetApi adapter."""

from __future__ import annotations

from typing import Any

from ...models import BudgetSummary
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT, unnamed
from ._text import trim_text as _trim_text


def normalize_budget(payload: dict[str, Any], *, project_id: int, project_name: str | None) -> BudgetSummary:
    budget_id = int(payload["id"])
    return BudgetSummary(
        id=budget_id,
        subject=_trim_text(payload.get("subject"), limit=SUBJECT_LIMIT) or unnamed("budget"),
        project_id=project_id,
        project=project_name,
    )


class HttpxBudgetApi:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    async def list_for_project(self, project_id: int, *, project_name: str | None) -> list[BudgetSummary]:
        trimmed_project_name = _trim_text(project_name, limit=SUBJECT_LIMIT)
        payload = await self._transport.get_json(f"projects/{project_id}/budgets")
        elements = payload.get("_embedded", {}).get("elements", [])
        return [
            normalize_budget(item, project_id=project_id, project_name=trimmed_project_name)
            for item in elements
            if isinstance(item, dict)
        ]
