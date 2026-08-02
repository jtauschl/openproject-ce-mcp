"""Categories Domain API port -- narrow, no universal gateway."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ...models import CategorySummary


@dataclass(frozen=True)
class CategoryRecord:
    """One category as read from the API: the normalized `summary` plus the
    raw `project` HAL link.

    `project_link` is `None` for a record built via `list_for_project`
    (`GET /projects/{id}/categories` embeds no `_links.project` per element --
    the project is implicit in the request path, so `normalize_category`
    receives `project_id`/`project_name` as parameters instead), and a real
    raw dict for a record built via `get` (`GET /categories/{id}` DOES embed
    `_links.project` per OpenProject's own CategoryRepresenter; an earlier
    version of this port incorrectly claimed no single-category GET exists
    at all, and no per-record project link either). The Service
    uses `project_link` to cross-verify a caller-supplied `project_ref`
    against the category's REAL project, not just trust the caller's claim.

    No `to_detail`: `CategorySummary` IS the only normalized shape this
    domain has (no separate Detail model exists in models.py).
    """

    summary: CategorySummary
    project_link: dict[str, Any] | None


class CategoryApi(Protocol):
    """Narrow, Categories-only Domain API port. CategoryService depends on
    this Protocol, never on HttpxCategoryApi concretely (enforced by the
    architecture-boundary test).
    """

    async def list_for_project(self, project_id: int, *, project_name: str | None) -> list[CategoryRecord]: ...
    async def get(self, category_id: int) -> CategoryRecord: ...
