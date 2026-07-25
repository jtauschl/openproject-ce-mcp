"""Categories Domain API port (ADR 0001) -- narrow, no universal gateway."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ...models import CategorySummary


@dataclass(frozen=True)
class CategoryRecord:
    """One category as read from the API: just the normalized `summary`.

    No `to_detail` (client.py has no normalize_category_detail -- this
    domain's normalizer produces one shape only, unlike Documents/News/
    Versions). No `project_link` either: an individual category payload
    carries no own `project` HAL link (only `defaultAssignee`) -- the
    project scope comes entirely from the caller-supplied `project_ref`,
    already allowlist-checked by ProjectRefResolver before the fetch, so
    there is no per-record link for a Policy check to inspect.
    """

    summary: CategorySummary


class CategoryApi(Protocol):
    """Narrow, Categories-only Domain API port. CategoryService depends on
    this Protocol, never on HttpxCategoryApi concretely (enforced by the
    architecture-boundary test).

    List-only: the OpenProject v3 API exposes no single-category GET --
    client.py's own get_category re-lists and filters by id in Python, so
    there is no commit_create/commit_update/delete/get method here either.
    """

    async def list_for_project(self, project_id: int, *, project_name: str | None) -> list[CategoryRecord]: ...
