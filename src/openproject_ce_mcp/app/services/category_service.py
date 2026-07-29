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

get() uses OpenProject's real single-category GET (found via an independent
Codex review verifying against
op-sources/17.2/lib/api/v3/categories/categories_api.rb -- an earlier
version of this Service re-listed the project's full category list and
Python-filtered by id, on the mistaken assumption no single-category GET
existed). `project_ref` is now OPTIONAL: the category's own real
`project_link` (returned by the GET) is what's actually checked against the
read allowlist via `ensure_project_link_allowed`, matching Documents'/
Memberships' per-record pattern -- a caller-supplied `project_ref`, when
given, is an ADDITIONAL cross-check that the category actually belongs to
the claimed project (raises NotFoundError on mismatch, not silently ignored),
not the sole source of authorization the way it was before this fix.
"""

from __future__ import annotations

from ...config import Settings
from ...models import CategoryListResult, CategorySummary
from ..errors import NotFoundError
from ..policies import access, hidden_fields
from ..policies import scope as scope_policy
from ..ports.category_api import CategoryApi
from ..ports.project_ref import ProjectRefResolver


class CategoryService:
    def __init__(
        self,
        *,
        api: CategoryApi,
        settings: Settings,
        project_id_to_identifier: dict[int, str],
        resolve_project_ref: ProjectRefResolver,
    ) -> None:
        self._api = api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier
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

    async def get(self, *, category_id: int, project_ref: str | None = None) -> CategorySummary:
        access.ensure_read_enabled("project", settings=self._settings)
        record = await self._api.get(category_id)
        scope_policy.ensure_project_link_allowed(
            record.project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        if project_ref is not None:
            expected_project = await self._resolve_project_ref(project_ref, write=False)
            expected_id = int(expected_project["id"])
            if record.summary.project_id != expected_id:
                raise NotFoundError("OpenProject category not found in this project.")
        return self._stamp(record.summary)
