"""Version-reference resolver (ADR 0001).

Resolves a version reference (numeric id, or exact case-insensitive name) to a
concrete numeric-id string. Verbatim behavioral port of the pre-existing
`_resolve_version_id`. Depends on `VersionApi` + `fetch_version_page` (both at or
below its own layer) -- never on `VersionService`.
"""

from __future__ import annotations

from ...config import Settings
from ...models import VersionSummary
from ..errors import InvalidInputError
from ..policies import scope as scope_policy
from ..ports.project_ref import ProjectRefResolver
from ..ports.project_resolution import ProjectResolutionContext
from ..ports.version_api import VersionApi
from .version_query import fetch_version_page


class VersionResolver:
    def __init__(
        self,
        *,
        api: VersionApi,
        resolve_project_ref: ProjectRefResolver,
        settings: Settings,
        project_id_to_identifier: dict[int, str],
    ) -> None:
        self._api = api
        self._resolve_project_ref = resolve_project_ref
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier

    async def resolve_id(
        self, version_ref: str, *, project: str | None, context: ProjectResolutionContext | None = None
    ) -> str:
        if project is not None:
            project_ref = project
            if project_ref.isdigit():
                # Must use resolve_project_ref, not a raw port call. The project
                # fetch itself is unavoidable either way (the payload's id/identifier/
                # name are what the allowlist check matches against) — the point is
                # that resolve_project_ref fetches AND checks together, so a denied
                # project raises immediately and no FURTHER request (e.g. listing
                # that project's versions) ever fires afterward.
                project_payload = await self._resolve_project_ref(project_ref, write=False, context=context)
                project_ref = project_payload.get("identifier") or project_ref

            wanted_id = int(version_ref) if version_ref.isdigit() else None
            name_matches: list[VersionSummary] = []
            offset = 1
            while True:
                page_results, _total, next_offset, _truncated = await fetch_version_page(
                    api=self._api,
                    resolve_project_ref=self._resolve_project_ref,
                    settings=self._settings,
                    project_id_to_identifier=self._project_id_to_identifier,
                    project=project_ref,
                    search=None,
                    offset=offset,
                    limit=self._settings.max_page_size,
                    context=context,
                )
                if wanted_id is not None:
                    if any(v.id == wanted_id for v in page_results):
                        return version_ref
                else:
                    name_matches.extend(v for v in page_results if (v.name or "").casefold() == version_ref.casefold())
                if next_offset is None:
                    break
                offset = next_offset

            if wanted_id is not None:
                raise InvalidInputError(f"OpenProject version '{version_ref}' is not available in project '{project}'.")
            if not name_matches:
                raise InvalidInputError(f"OpenProject version '{version_ref}' was not found in project '{project}'.")
            if len(name_matches) > 1:
                raise InvalidInputError(
                    f"OpenProject version '{version_ref}' is ambiguous without a more specific filter. Pass a numeric version id."
                )
            return str(name_matches[0].id)

        if version_ref.isdigit():
            # No target project to check availability against — reached via a global,
            # unscoped `version` filter on list_work_packages/search_work_packages
            # (project is optional there). Deliberately conservative: falls back to a
            # direct definingProject check, which can reject a version shared *into*
            # an allowed project when that project isn't specified as the check
            # target (no way to know which sharing context applies without one) — an
            # accepted fail-closed trade-off for the project-less path, not a bug.
            #
            # Deliberately does NOT call ensure_read_enabled (existing quirk, preserved
            # exactly) -- calling the port directly here (bypassing fetch_version_page,
            # which is the only place that check lives) naturally reproduces that
            # asymmetry rather than requiring a special case.
            record = await self._api.get(int(version_ref))
            scope_policy.ensure_project_link_allowed(
                record.defining_project_link,
                settings=self._settings,
                project_id_to_identifier=self._project_id_to_identifier,
            )
            return version_ref

        # No project + name ref: pass search=version_ref rather than relying on our
        # own post-hoc filtering, AND page-walk the search-filtered results.
        name_matches = []
        offset = 1
        while True:
            page_results, _total, next_offset, _truncated = await fetch_version_page(
                api=self._api,
                resolve_project_ref=self._resolve_project_ref,
                settings=self._settings,
                project_id_to_identifier=self._project_id_to_identifier,
                project=None,
                search=version_ref,
                offset=offset,
                limit=self._settings.max_page_size,
                context=None,
            )
            name_matches.extend(v for v in page_results if (v.name or "").casefold() == version_ref.casefold())
            if next_offset is None:
                break
            offset = next_offset

        if not name_matches:
            raise InvalidInputError(f"OpenProject version '{version_ref}' was not found.")
        if len(name_matches) > 1:
            raise InvalidInputError(
                f"OpenProject version '{version_ref}' is ambiguous without a more specific filter. Pass a numeric version id."
            )
        return str(name_matches[0].id)
