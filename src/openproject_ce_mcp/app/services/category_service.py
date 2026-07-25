"""Application Service for the Categories domain (ADR 0001).

Depends on the CategoryApi Protocol, never HttpxCategoryApi concretely
(enforced by the architecture-boundary test). No dedicated CategoryResolver:
a `category_id` is always a numeric value already validated by tools.py --
there is no semantic-reference resolution for this domain to warrant a
Resolver in the ADR sense.

Categories shares the "project" read scope with Projects/News/Documents --
there is no dedicated OPENPROJECT_ENABLE_CATEGORY_* flag, so
access.ensure_read_enabled here uses scope="project" (verbatim behavior of
client.py's original _ensure_read_enabled("project") call).

Read-only, list-only API: the OpenProject v3 API exposes no single-category
GET, and no create/update/delete for categories. get() re-lists and filters
by id in Python, mirroring client.py's original get_category exactly --
this is NOT Documents'/Memberships' per-record `ensure_project_link_allowed`
pattern, since an individual category payload carries no own `project` HAL
link; the read allowlist check happens once, inside resolve_project_ref
itself, before the list fetch.
"""

from __future__ import annotations

from ...config import Settings
from ...models import CategoryListResult, CategorySummary
from ..errors import NotFoundError
from ..policies import access, hidden_fields
from ..ports.category_api import CategoryApi
from ..ports.project_ref import ProjectRefResolver


class CategoryService:
    def __init__(
        self,
        *,
        api: CategoryApi,
        settings: Settings,
        resolve_project_ref: ProjectRefResolver,
    ) -> None:
        self._api = api
        self._settings = settings
        self._resolve_project_ref = resolve_project_ref

    def _stamp(self, value: CategorySummary) -> CategorySummary:
        return hidden_fields.apply_hidden_fields("category", value, settings=self._settings)

    async def list(self, project_ref: str) -> CategoryListResult:
        access.ensure_read_enabled("project", settings=self._settings)
        project_payload = await self._resolve_project_ref(project_ref, write=False)
        project_id = int(project_payload["id"])
        # Raw (untrimmed) name passed through -- trimming to SUBJECT_LIMIT is
        # text normalization, done by the adapter's list_for_project, not here.
        project_name = project_payload.get("name")
        records = await self._api.list_for_project(project_id, project_name=project_name)
        results = [self._stamp(record.summary) for record in records]
        return CategoryListResult(count=len(results), results=results)

    async def get(self, *, project_ref: str, category_id: int) -> CategorySummary:
        categories = await self.list(project_ref)
        for category in categories.results:
            if category.id == category_id:
                return category
        raise NotFoundError("OpenProject category not found in this project.")
