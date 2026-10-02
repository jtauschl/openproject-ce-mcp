"""Application Service for the Budgets domain.

Depends on the `BudgetApi` Protocol (never `HttpxBudgetApi` concretely --
enforced by the architecture-boundary test) and on `ProjectRefResolver`,
which authorizes the project against OPENPROJECT_READ_PROJECTS before its
budgets are listed.

Read scope uses `"project"`: a budget belongs to a project, not to any one
work package.
"""

from __future__ import annotations

from ...config import Settings
from ...models import BudgetListResult
from ..policies import access, hidden_fields
from ..ports.budget_api import BudgetApi
from ..ports.project_ref import ProjectRefResolver


class BudgetService:
    def __init__(self, *, api: BudgetApi, settings: Settings, resolve_project_ref: ProjectRefResolver) -> None:
        self._api = api
        self._settings = settings
        self._resolve_project_ref = resolve_project_ref

    async def list_for_project(self, project_ref: str) -> BudgetListResult:
        access.ensure_read_enabled("project", settings=self._settings)
        project_payload = await self._resolve_project_ref(project_ref, write=False)
        budgets = await self._api.list_for_project(int(project_payload["id"]))
        results = [hidden_fields.apply_hidden_fields("budget", budget, settings=self._settings) for budget in budgets]
        return BudgetListResult(count=len(results), results=results)
