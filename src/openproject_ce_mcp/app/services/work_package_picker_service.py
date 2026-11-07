"""Application Service for the Work Package Pickers domain.

Depends on the `WorkPackagePickerApi` Protocol (never
`HttpxWorkPackagePickerApi` concretely -- enforced by the
architecture-boundary test), on `WorkPackageIdResolver` and on
`ProjectRefResolver`.

The anchor (a work package, or a project for `available_assignees`) is
resolved through the same resolvers every read uses, so it must itself be
readable under OPENPROJECT_READ_PROJECTS before anything is listed. What
comes back is then filtered where it carries a project: a relation candidate outside the read allowlist is dropped, so the
listing never names a project this server may not show. Principals carry no
project, so they are returned as OpenProject lists them.

Read scope reuses `"work_package"` (not a dedicated scope): every one of
these lookups exists to fill a work package field.
"""

from __future__ import annotations

from collections.abc import Mapping

from ...config import Settings
from ...models import (
    AvailableWatcherListResult,
    PrincipalCollectionResult,
    ProjectListResult,
    RelationCandidateListResult,
)
from ..errors import InvalidInputError
from ..pagination import effective_limit, paginate_server
from ..policies import access, hidden_fields
from ..policies import scope as scope_policy
from ..ports.project_api import ProjectApi
from ..ports.project_ref import ProjectRefResolver
from ..ports.work_package_picker_api import WorkPackagePickerApi
from ..ports.work_package_ref import WorkPackageIdResolver
from ..resolvers.project_query import fetch_allowed_project_page
from .project_service import _stamp_project


class WorkPackagePickerService:
    def __init__(
        self,
        *,
        api: WorkPackagePickerApi,
        settings: Settings,
        project_id_to_identifier: Mapping[int, str],
        resolve_work_package_id: WorkPackageIdResolver,
        resolve_project_ref: ProjectRefResolver,
        project_api: ProjectApi,
    ) -> None:
        self._api = api
        self._project_api = project_api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier
        self._resolve_work_package_id = resolve_work_package_id
        self._resolve_project_ref = resolve_project_ref

    async def available_assignees(
        self, *, work_package_id: int | str | None = None, project_ref: str | None = None
    ) -> PrincipalCollectionResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        if (work_package_id is None) == (project_ref is None):
            raise InvalidInputError("Pass exactly one of work_package_id or project.")
        if work_package_id is not None:
            resolved_id = await self._resolve_work_package_id(work_package_id, write=False)
            principals = await self._api.available_assignees(work_package_id=resolved_id, project_id=None)
        else:
            assert project_ref is not None
            project_payload = await self._resolve_project_ref(project_ref, write=False)
            principals = await self._api.available_assignees(
                work_package_id=None, project_id=int(project_payload["id"])
            )
        results = [hidden_fields.apply_hidden_fields("principal", p, settings=self._settings) for p in principals]
        return PrincipalCollectionResult(count=len(results), results=results)

    async def relation_candidates(
        self,
        work_package_id: int | str,
        *,
        query: str | None = None,
        relation_type: str | None = None,
        limit: int | None = None,
    ) -> RelationCandidateListResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        resolved_id = await self._resolve_work_package_id(work_package_id, write=False)
        pairs = await self._api.relation_candidates(
            resolved_id,
            query=query,
            relation_type=relation_type,
            page_size=effective_limit(limit, settings=self._settings),
        )
        results = [
            hidden_fields.apply_hidden_fields("work_package", summary, settings=self._settings)
            for summary, raw in pairs
            if scope_policy.project_link_payload_allowed(
                raw,
                link_key="project",
                settings=self._settings,
                project_id_to_identifier=self._project_id_to_identifier,
            )
        ]
        return RelationCandidateListResult(count=len(results), results=results)

    async def available_watchers(
        self, work_package_id: int | str, *, offset: int = 1, limit: int | None = None
    ) -> AvailableWatcherListResult:
        """The users that may be added as watchers. OpenProject answers only a caller who may add watchers."""
        access.ensure_read_enabled("work_package", settings=self._settings)
        resolved_id = await self._resolve_work_package_id(work_package_id, write=False)
        page_limit = effective_limit(limit, settings=self._settings)
        watchers, total = await self._api.available_watchers(resolved_id, offset=offset, page_size=page_limit)
        results = [hidden_fields.apply_hidden_fields("watcher", w, settings=self._settings) for w in watchers]
        next_offset, truncated = paginate_server(offset=offset, limit=page_limit, total=total)
        return AvailableWatcherListResult(
            offset=offset,
            limit=page_limit,
            total=total,
            count=len(results),
            next_offset=next_offset,
            truncated=truncated,
            results=results,
        )

    async def available_projects(
        self, work_package_id: int | str, *, offset: int = 1, limit: int | None = None
    ) -> ProjectListResult:
        """The projects the work package may be moved to, kept to those the read scope covers.

        The server `total` counts projects outside the scope too, so it is not passed on.
        """
        access.ensure_read_enabled("work_package", settings=self._settings)
        access.ensure_read_enabled("project", settings=self._settings)
        resolved_id = await self._resolve_work_package_id(work_package_id, write=False)
        page_limit = effective_limit(limit, settings=self._settings)
        page_results, total, next_offset, truncated = await fetch_allowed_project_page(
            fetch_page=lambda server_offset, server_page_size: self._project_api.list_available_for_work_package(
                resolved_id,
                server_offset=server_offset,
                server_page_size=server_page_size,
                text_limit=self._settings.text_limit,
            ),
            settings=self._settings,
            offset=offset,
            limit=page_limit,
        )
        stamped = [
            _stamp_project(
                record.summary, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
            )
            for record in page_results
        ]
        return ProjectListResult(
            offset=offset,
            limit=page_limit,
            total=total,
            count=len(stamped),
            next_offset=next_offset,
            truncated=truncated,
            results=stamped,
        )
