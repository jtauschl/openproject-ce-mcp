"""Application Service for the Budgets domain.

Budgets share the "project" read scope. A budget row carries no project link,
so the project the caller names, checked against the read allowlist by the
resolver, is the whole scope decision.
"""

from __future__ import annotations

from ...config import Settings
from ...models import BudgetListResult, BudgetSummary
from ..policies import access, hidden_fields
from ..ports.budget_api import BudgetApi
from ..ports.project_ref import ProjectRefResolver
from ._error_masking import redacted_server_errors


@redacted_server_errors("budget")
class BudgetService:
    def __init__(
        self,
        *,
        api: BudgetApi,
        settings: Settings,
        resolve_project_ref: ProjectRefResolver,
    ) -> None:
        self._api = api
        self._settings = settings
        self._resolve_project_ref = resolve_project_ref

    def _stamp(self, value: BudgetSummary) -> BudgetSummary:
        return hidden_fields.apply_hidden_fields("budget", value, settings=self._settings)

    async def list(self, project_ref: str) -> BudgetListResult:
        access.ensure_read_enabled("project", settings=self._settings)
        project_payload = await self._resolve_project_ref(project_ref, write=False)
        budgets = await self._api.list_for_project(int(project_payload["id"]), project_name=project_payload.get("name"))
        results = [self._stamp(budget) for budget in budgets]
        return BudgetListResult(count=len(results), results=results)
