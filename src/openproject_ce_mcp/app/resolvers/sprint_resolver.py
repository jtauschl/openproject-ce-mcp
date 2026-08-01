"""Sprint-reference resolver (ADR 0001, OPM-371).

Verbatim behavioral port of the flat `_resolve_sprint_id` -- the most
behaviorally sensitive of the five work-package field resolvers (a
server-paginated page-walk with two distinct lookup paths). Preserves its
ambiguity check exactly (raises on more than one case-insensitive name match
-- same as `TypeResolver`, unlike `StatusPriorityTypeResolver`'s status/
priority methods). Depends on the pre-existing `SprintApi` instance
(`self._sprint_api`) and `app/policies/sprint_policy.py`'s existing pure
functions (unchanged, no relocation needed), plus the `ProjectRefResolver`
seam for resolving `project` to a numeric id.

The repeated-page-ids termination safeguard (`page_ids <= seen_ids`) is
security/correctness-relevant, not a style choice: some project-scoped
sub-collection endpoints (verified live) silently ignore offset/page-size and
always return every element -- without this check, `next_offset` never
becomes `None` and the loop never terminates. Ported byte-for-byte, not
"cleaned up."
"""

from __future__ import annotations

from ...config import Settings
from ..errors import InvalidInputError, NotFoundError
from ..pagination import paginate_server
from ..policies import access, sprint_policy
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
        project_id_to_identifier: dict[int, str],
    ) -> None:
        self._api = api
        self._resolve_project_ref = resolve_project_ref
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier

    async def resolve_id(
        self, sprint_ref: str, *, project: str, context: ProjectResolutionContext | None = None
    ) -> str:
        if sprint_ref.isdigit():
            try:
                record = await self._api.get(int(sprint_ref))
            except NotFoundError as exc:
                raise NotFoundError(
                    "OpenProject sprint not found, or the Backlogs module / sprint API is unavailable."
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
        access.ensure_read_enabled("project", settings=self._settings)
        project_payload = await self._resolve_project_ref(project, context=context)
        project_id = int(project_payload["id"])
        page_size = self._settings.max_page_size
        matches: list[str] = []
        seen_ids: set[int] = set()
        offset = 1
        is_first_page = True
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
                if (record.summary.name or "").casefold() == sprint_ref.casefold():
                    matches.append(str(record.summary.id))
            next_offset, _truncated = paginate_server(offset=offset, limit=page_size, total=total)
            if next_offset is None:
                break
            offset = next_offset
        if not matches:
            raise InvalidInputError(f"OpenProject sprint '{sprint_ref}' was not found in project '{project}'.")
        if len(matches) > 1:
            raise InvalidInputError(
                f"OpenProject sprint '{sprint_ref}' is ambiguous without a more specific filter. Pass a numeric sprint id."
            )
        return matches[0]
