"""Sprint-reference resolver.

The most behaviorally sensitive of the five work-package field resolvers (a
server-paginated page-walk with two distinct lookup paths). Raises on more
than one case-insensitive name match -- same as `TypeResolver`, unlike
`StatusPriorityTypeResolver`'s status/priority methods. Depends on the
`SprintApi` Port and `app/policies/sprint_policy.py`'s pure functions, plus
the `ProjectRefResolver` seam for resolving `project` to a numeric id.

The repeated-page-ids termination safeguard (`page_ids <= seen_ids`) is
security/correctness-relevant, not a style choice: some project-scoped
sub-collection endpoints (verified live) silently ignore offset/page-size and
always return every element -- without this check, `next_offset` never
becomes `None` and the loop never terminates.

Name comparison uses `SprintRecord.lookup_name` (the raw, never-synthesized
name), not `summary.name`: `normalize_sprint` falls back to a synthetic
display name (`f"Sprint {id}"`) when the raw name is blank/missing, which
could otherwise make a caller's literal search for "Sprint 7" accidentally
match a sprint whose real name was blank. See `app/ports/sprint_api.py`'s
`SprintRecord` docstring for the full rationale.
"""

from __future__ import annotations

from collections.abc import Mapping

from ...config import Settings
from ...work_package_reference import is_numeric_ref
from ..errors import InvalidInputError, NotFoundError
from ..offered_values import candidates_clause, offered_clause
from ..pagination import collection_exhausted
from ..policies import sprint_policy
from ..ports.project_ref import ProjectRefResolver
from ..ports.project_resolution import ProjectResolutionContext
from ..ports.sprint_api import SprintApi


class SprintResolver:
    def __init__(
        self,
        *,
        api: SprintApi,
        resolve_project_ref: ProjectRefResolver,
        settings: Settings,
        project_id_to_identifier: Mapping[int, str],
    ) -> None:
        self._api = api
        self._resolve_project_ref = resolve_project_ref
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier

    async def resolve_id(
        self, sprint_ref: str, *, project: str, context: ProjectResolutionContext | None = None
    ) -> str:
        if is_numeric_ref(sprint_ref):
            try:
                record = await self._api.get(int(sprint_ref))
            except NotFoundError as exc:
                raise NotFoundError(
                    "OpenProject sprint not found, or the sprint API is unavailable "
                    "(it requires the Backlogs module and OpenProject 17.3 or newer)."
                ) from exc
            sprint_policy.ensure_sprint_workspace_allowed(
                defining_workspace_payload=record.defining_workspace_payload,
                defining_workspace_link=record.defining_workspace_link,
                settings=self._settings,
                project_id_to_identifier=self._project_id_to_identifier,
            )
            return sprint_ref

        # Page-walk real server pages via list_for_project directly, trusting
        # its reported `total` (mirrors VersionResolver.resolve_id's genuine
        # server-paginated project path).
        project_payload = await self._resolve_project_ref(project, context=context)
        project_id = int(project_payload["id"])
        page_size = self._settings.max_page_size
        visible: list[tuple[int, str]] = []
        matches: list[tuple[int, str]] = []
        seen_ids: set[int] = set()
        offset = 1
        is_first_page = True
        fetched = 0
        while True:
            try:
                records, total = await self._api.list_for_project(project_id, offset=offset, page_size=page_size)
            except NotFoundError as exc:
                raise NotFoundError(
                    "OpenProject project sprints require the Backlogs module and OpenProject 17.3 or newer."
                ) from exc
            # Some project-scoped sub-collection endpoints (verified live: a
            # project's versions endpoint) silently ignore offset/page size
            # and always return every element -- without this check,
            # `next_offset` never becomes None and this loops forever,
            # re-fetching the same full page.
            page_ids = {record.summary.id for record in records}
            if not is_first_page and page_ids and page_ids <= seen_ids:
                break
            is_first_page = False
            seen_ids.update(page_ids)
            for record in records:
                if not sprint_policy.sprint_payload_allowed(
                    defining_workspace_payload=record.defining_workspace_payload,
                    defining_workspace_link=record.defining_workspace_link,
                    settings=self._settings,
                    project_id_to_identifier=self._project_id_to_identifier,
                ):
                    continue
                visible.append((record.summary.id, record.lookup_name))
                if record.lookup_name.casefold() == sprint_ref.casefold():
                    matches.append((record.summary.id, record.lookup_name))
            fetched += len(records)
            if not records or collection_exhausted(total, fetched):
                break
            offset += 1
        if not matches:
            raise InvalidInputError(
                f"OpenProject sprint '{sprint_ref}' was not found in project '{project}'."
                + offered_clause((name for _id, name in visible), plural="sprints")
            )
        if len(matches) > 1:
            raise InvalidInputError(
                f"OpenProject sprint '{sprint_ref}' is ambiguous without a more specific filter. Pass a numeric sprint id."
                + candidates_clause(matches)
            )
        return str(matches[0][0])
