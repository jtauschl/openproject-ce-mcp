"""Application Service for the Sprints (Backlogs) domain (ADR 0001).

Depends on the SprintApi Protocol, never HttpxSprintApi concretely (enforced
by the architecture-boundary test). No dedicated SprintResolver: a
`sprint_id` is always a numeric value already validated by tools.py -- there
is no semantic-reference resolution for this domain to warrant a Resolver
(mirrors Views/Categories/Wiki Pages).

Sprints shares the "project" read scope with Projects/News/Documents/
Categories/Views/Grids -- no dedicated OPENPROJECT_ENABLE_SPRINT_* flag
exists, so access.ensure_read_enabled here uses scope="project" (verbatim
behavior of client.py's original _ensure_read_enabled("project") call in all
three of its methods).

Unlike Views, Sprints DOES need a dedicated Policy module (sprint_policy.py):
the allowlist check has two branches (embedded-object vs. link), not one.

Two list methods, not one: `list()` hits the global `sprints` endpoint (no
project filter argument at all in the legacy code -- `list_sprints` never
took a `project` kwarg); `list_for_project()` hits the project-scoped
`projects/{id}/sprints` endpoint via a resolved project id, but STILL filters
client-side afterward -- a sprint shared into a project via Backlogs sharing
can be *defined* by a different, possibly disallowed project (verified by
client.py's existing `list_project_sprints` behavior and its own test
coverage in test_versions_and_sprints.py). Because `SprintSummary`'s
project-ish fields are named `defining_workspace_id`/`defining_workspace`
(not `project_id`/`project`), `project_scoped_list.py`'s
`summary_matches_project_candidates` (whose Protocol requires the latter
names) is not usable here -- and is not needed anyway, since neither list
method does client-side project-*candidate* matching (list_for_project
scopes via the request URL, not by matching a resolved candidate set against
each row).

NotFoundError rewrap (three distinct "Backlogs module" messages, matching
client.py's originals exactly) happens here, not in the adapter -- mirrors
the existing ProjectService NotFoundError-rewrap precedent.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...models import SprintDetail, SprintListResult
from ..errors import NotFoundError
from ..pagination import clamp_limit, paginate_all, paginate_client
from ..policies import access, hidden_fields
from ..policies.sprint_policy import ensure_sprint_workspace_allowed, sprint_payload_allowed
from ..ports.project_ref import ProjectRefResolver
from ..ports.project_resolution import ProjectResolutionContext
from ..ports.sprint_api import SprintApi, SprintRecord


class SprintService:
    def __init__(
        self,
        *,
        api: SprintApi,
        settings: Settings,
        project_id_to_identifier: dict[int, str],
        resolve_project_ref: ProjectRefResolver,
    ) -> None:
        self._api = api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier
        self._resolve_project_ref = resolve_project_ref

    def _stamp(self, value: Any) -> Any:
        return hidden_fields.apply_hidden_fields("sprint", value, settings=self._settings)

    def _allowed(self, record: SprintRecord) -> bool:
        return sprint_payload_allowed(
            defining_workspace_payload=record.defining_workspace_payload,
            defining_workspace_link=record.defining_workspace_link,
            settings=self._settings,
            project_id_to_identifier=self._project_id_to_identifier,
        )

    def _paginate(
        self, records: list[SprintRecord], *, search: str | None, offset: int, limit: int
    ) -> SprintListResult:
        results = [self._stamp(record.summary) for record in records if self._allowed(record)]
        if search is not None:
            search_key = search.casefold()
            results = [item for item in results if search_key in (item.name or "").casefold()]
        page, total, next_offset, truncated = paginate_client(offset=offset, limit=limit, results=results)
        return SprintListResult(
            offset=offset,
            limit=limit,
            total=total,
            count=len(page),
            next_offset=next_offset,
            truncated=truncated,
            results=page,
        )

    async def list(
        self,
        *,
        search: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> SprintListResult:
        access.ensure_read_enabled("project", settings=self._settings)
        effective_limit = clamp_limit(
            limit,
            default_page_size=self._settings.default_page_size,
            max_page_size=self._settings.max_page_size,
            max_results=self._settings.max_results,
        )
        try:
            # A single fetch capped at settings.max_results silently hid any
            # sprint beyond that cap once the endpoint's real result count
            # exceeded it -- walk every server page instead.
            records = await paginate_all(
                lambda offset, page_size: self._api.list_all(offset=offset, page_size=page_size),
                page_size=self._settings.max_page_size,
                key=lambda r: r.summary.id,
            )
        except NotFoundError as exc:
            raise NotFoundError(
                "OpenProject sprints require the Backlogs module and OpenProject 17.3 or newer."
            ) from exc
        return self._paginate(records, search=search, offset=offset, limit=effective_limit)

    async def list_for_project(
        self,
        project: str,
        *,
        search: str | None = None,
        offset: int = 1,
        limit: int | None = None,
        context: ProjectResolutionContext | None = None,
    ) -> SprintListResult:
        access.ensure_read_enabled("project", settings=self._settings)
        effective_limit = clamp_limit(
            limit,
            default_page_size=self._settings.default_page_size,
            max_page_size=self._settings.max_page_size,
            max_results=self._settings.max_results,
        )
        project_payload = await self._resolve_project_ref(project, write=False, context=context)
        project_id = int(project_payload["id"])
        try:
            # Even though this is project-scoped, results are still filtered
            # client-side (a sprint shared into this project can be *defined*
            # by a different, possibly disallowed project), so a full walk of
            # every server page is required -- a single bounded fetch would
            # silently hide any sprint beyond that cap.
            records = await paginate_all(
                lambda offset, page_size: self._api.list_for_project(project_id, offset=offset, page_size=page_size),
                page_size=self._settings.max_page_size,
                key=lambda r: r.summary.id,
            )
        except NotFoundError as exc:
            raise NotFoundError(
                "OpenProject project sprints require the Backlogs module and OpenProject 17.3 or newer."
            ) from exc
        return self._paginate(records, search=search, offset=offset, limit=effective_limit)

    async def get(self, sprint_id: int) -> SprintDetail:
        access.ensure_read_enabled("project", settings=self._settings)
        try:
            record = await self._api.get(sprint_id)
        except NotFoundError as exc:
            raise NotFoundError(
                "OpenProject sprint not found, or the Backlogs module / sprint API is unavailable."
            ) from exc
        ensure_sprint_workspace_allowed(
            defining_workspace_payload=record.defining_workspace_payload,
            defining_workspace_link=record.defining_workspace_link,
            settings=self._settings,
            project_id_to_identifier=self._project_id_to_identifier,
        )
        return self._stamp(record.detail)
