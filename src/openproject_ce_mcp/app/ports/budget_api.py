"""Budgets Domain API port.

Read-only, project-anchored: the budgets of one project. The project is
authorized before its budgets are fetched, and a budget's own representation
carries no project link, so there is nothing further to filter -- and no
single-budget lookup, which would have nothing to authorize against.
"""

from __future__ import annotations

from typing import Protocol

from ...models import BudgetSummary


class BudgetApi(Protocol):
    """Narrow, Budgets-only Domain API port. BudgetService depends on this
    Protocol, never on HttpxBudgetApi concretely (enforced by the
    architecture-boundary test).
    """

    async def list_for_project(self, project_id: int) -> list[BudgetSummary]: ...
