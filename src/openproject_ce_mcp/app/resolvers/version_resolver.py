"""Version-reference resolver (ADR 0001).

Resolves a version reference (numeric id, or exact case-insensitive name) to a
concrete numeric-id string. Verbatim behavioral port of the pre-existing
`_resolve_version_id`. Depends on `VersionApi` + `fetch_visible_version_records`
(both at or below its own layer) -- never on `VersionService`.

Name comparison uses `VersionRecord.lookup_name` (the raw, never-synthesized
name), not `summary.name`: `normalize_version` falls back to a synthetic
display name (`f"Version {id}"`) when the raw name is blank/missing, which
could otherwise make a caller's literal search for "Version 7" accidentally
match a version whose real name was blank. See `app/ports/version_api.py`'s
`VersionRecord` docstring for the full rationale. This resolver depends on
`fetch_visible_version_records` (not the summary-projecting `fetch_version_page`
`VersionService.list()` uses) specifically because it needs each record's
`lookup_name`, which a `VersionSummary` doesn't carry -- and, as a side
effect, scans the full visible-record list once per resolve_id call instead
of re-fetching the same server pages once per client-side page the way the
previous `fetch_version_page`-based implementation did.
"""

from __future__ import annotations

from ...config import Settings
from ..errors import InvalidInputError
from ..policies import scope as scope_policy
from ..ports.project_ref import ProjectRefResolver
from ..ports.project_resolution import ProjectResolutionContext
from ..ports.version_api import VersionApi, VersionRecord
from .version_query import fetch_visible_version_records


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
            records = await fetch_visible_version_records(
                api=self._api,
                resolve_project_ref=self._resolve_project_ref,
                settings=self._settings,
                project_id_to_identifier=self._project_id_to_identifier,
                project=project_ref,
                context=context,
            )

            if wanted_id is not None:
                if any(r.summary.id == wanted_id for r in records):
                    return version_ref
                raise InvalidInputError(f"OpenProject version '{version_ref}' is not available in project '{project}'.")

            name_matches: list[VersionRecord] = [
                r for r in records if r.lookup_name.casefold() == version_ref.casefold()
            ]
            if not name_matches:
                raise InvalidInputError(f"OpenProject version '{version_ref}' was not found in project '{project}'.")
            if len(name_matches) > 1:
                raise InvalidInputError(
                    f"OpenProject version '{version_ref}' is ambiguous without a more specific filter. Pass a numeric version id."
                )
            return str(name_matches[0].summary.id)

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
            # exactly) -- calling the port directly here (bypassing
            # fetch_visible_version_records, which is the only place that check
            # lives) naturally reproduces that asymmetry rather than requiring a
            # special case.
            record = await self._api.get(int(version_ref))
            scope_policy.ensure_project_link_allowed(
                record.defining_project_link,
                settings=self._settings,
                project_id_to_identifier=self._project_id_to_identifier,
            )
            return version_ref

        # No project + name ref: scan every visible record's raw lookup_name.
        records = await fetch_visible_version_records(
            api=self._api,
            resolve_project_ref=self._resolve_project_ref,
            settings=self._settings,
            project_id_to_identifier=self._project_id_to_identifier,
            project=None,
            context=None,
        )
        name_matches = [r for r in records if r.lookup_name.casefold() == version_ref.casefold()]

        if not name_matches:
            raise InvalidInputError(f"OpenProject version '{version_ref}' was not found.")
        if len(name_matches) > 1:
            raise InvalidInputError(
                f"OpenProject version '{version_ref}' is ambiguous without a more specific filter. Pass a numeric version id."
            )
        return str(name_matches[0].summary.id)
