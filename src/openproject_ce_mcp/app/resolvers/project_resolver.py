"""Project-reference resolver (ADR 0001).

Resolves a project reference (numeric id, exact identifier, or -- as a fallback --
display name) to a resolved raw HAL payload. Verbatim behavioral port of the
pre-existing `_resolve_project_ref`/`_resolve_project_by_name`/
`_project_ambiguous_error`. Depends on `ProjectApi` + `fetch_project_page` (both at
or below its own layer) -- never on `ProjectService`.

Unlike VersionResolver, this resolver does not consume a `ProjectRefResolver` port
seam -- it IS the concrete implementation the seam is bound to (client.py's
`_get_project_payload`/`_resolve_project_ref` delegate to it after the rebind).
`resolve()` implements the full `ProjectRefResolver` Protocol contract itself,
including the `context` parameter.

`resolve_record()` is the typed counterpart: same exact algorithm, but returns
the full `ProjectRecord` (summary + detail + payload) the adapter already
normalized, instead of discarding it down to `.payload`. It deliberately takes
no `context` parameter -- `ProjectResolutionContext`
(`..ports.project_resolution`) caches `dict[str, Any]` payloads only, and
`resolvers` may not import `adapters` to re-derive a summary/detail from a
cache-hit payload without a second HTTP call. A `context`-aware
`resolve_record()` that silently re-fetched on every call would be a
misleading cache contract, so it isn't offered; `resolve()` keeps its
existing `context`-aware, payload-caching behavior unchanged, calling
`resolve_record()` only when `context is None`.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...models import ProjectSummary
from ..errors import InvalidInputError, NotFoundError
from ..policies import project_policy
from ..ports.project_api import FORMATTABLE_LIMIT, ProjectApi, ProjectRecord
from ..ports.project_resolution import ProjectResolutionContext
from .project_query import fetch_project_page

_PROJECT_NAME_SEARCH_MAX_PAGES = 5


class ProjectResolver:
    def __init__(self, *, api: ProjectApi, settings: Settings, project_id_to_identifier: dict[int, str]) -> None:
        self._api = api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier

    async def resolve(
        self, project_ref: str, *, write: bool = False, context: ProjectResolutionContext | None = None
    ) -> dict[str, Any]:
        if context is not None:
            return await context.resolve(project_ref, write=write)
        record = await self.resolve_record(project_ref, write=write)
        return record.payload

    async def resolve_record(
        self, project_ref: str, *, write: bool = False, text_limit: int | None = FORMATTABLE_LIMIT
    ) -> ProjectRecord:
        """Typed counterpart to resolve(); see module docstring for why this
        takes no `context` parameter."""
        return await self._resolve_record_uncached(project_ref, write=write, text_limit=text_limit)

    async def resolve_id(self, project_ref: str, *, write: bool = False) -> str:
        payload = await self.resolve(project_ref, write=write)
        return str(payload["id"])

    async def _resolve_record_uncached(self, project_ref: str, *, write: bool, text_limit: int | None) -> ProjectRecord:
        """Resolve a project by numeric id, exact identifier, or (as a fallback) display name.

        Numeric id / identifier is tried first via a direct GET (cheap, unchanged from before this
        fallback existed). Only when that 404s do we fall back to a name search via list_projects.
        Identifiers are unique in OpenProject by construction; display names are not, so an exact-name
        match is only trusted once the search has confirmed there is no second project with that same
        name (see _resolve_by_name_record for the exact algorithm).
        """
        try:
            record: ProjectRecord | None = await self._api.get(project_ref, text_limit=text_limit)
        except NotFoundError:
            record = None
        if record is not None and record.payload.get("_type") != "Project":
            record = None
        if record is not None:
            if write:
                project_policy.ensure_project_write_allowed(
                    record.payload,
                    project_ref=project_ref,
                    settings=self._settings,
                    project_id_to_identifier=self._project_id_to_identifier,
                )
            else:
                project_policy.ensure_project_read_allowed(
                    record.payload,
                    project_ref=project_ref,
                    settings=self._settings,
                    project_id_to_identifier=self._project_id_to_identifier,
                )
            return record
        return await self._resolve_by_name_record(project_ref, write=write, text_limit=text_limit)

    async def _resolve_by_name_record(self, project_ref: str, *, write: bool, text_limit: int | None) -> ProjectRecord:
        normalized = " ".join(project_ref.split())
        normalized_cf = normalized.casefold()
        page_size = self._settings.max_results
        exact_name_matches: list[ProjectSummary] = []
        substring_matches: list[ProjectSummary] = []
        exhausted = False
        offset = 1
        for _ in range(_PROJECT_NAME_SEARCH_MAX_PAGES):
            page_results, _total, next_offset, truncated = await fetch_project_page(
                api=self._api,
                settings=self._settings,
                project_id_to_identifier=self._project_id_to_identifier,
                search=normalized,
                offset=offset,
                limit=page_size,
            )
            for project in page_results:
                identifier_cf = (project.identifier or "").casefold()
                if identifier_cf == normalized_cf:
                    # Identifiers are unique — an exact identifier match, wherever it turns up in the
                    # search results, always wins immediately over any name/substring match.
                    return await self._resolve_record_uncached(str(project.id), write=write, text_limit=text_limit)
                name_cf = (project.name or "").casefold()
                if name_cf == normalized_cf:
                    exact_name_matches.append(project)
                else:
                    substring_matches.append(project)
            if len(exact_name_matches) >= 2:
                break
            if not truncated:
                exhausted = True
                break
            offset = next_offset if next_offset is not None else offset + 1

        if len(exact_name_matches) >= 2:
            raise self._ambiguous_error(project_ref, exact_name_matches, exhausted=True)
        if not exhausted:
            # The page cap was hit before the search could confirm a unique match — never fabricate
            # uniqueness here, since a later (unscanned) page could still contain a second exact-name
            # match or an exact-identifier match that would change the outcome.
            pending = exact_name_matches or substring_matches
            raise self._ambiguous_error(project_ref, pending, exhausted=False)
        if len(exact_name_matches) == 1:
            return await self._resolve_record_uncached(
                str(exact_name_matches[0].id), write=write, text_limit=text_limit
            )
        if len(substring_matches) == 1:
            return await self._resolve_record_uncached(str(substring_matches[0].id), write=write, text_limit=text_limit)
        if len(substring_matches) > 1:
            raise self._ambiguous_error(project_ref, substring_matches, exhausted=True)
        raise NotFoundError(f"OpenProject project '{project_ref}' was not found. Call list_projects.")

    def _ambiguous_error(
        self, project_ref: str, candidates: list[ProjectSummary], *, exhausted: bool
    ) -> InvalidInputError:
        shown = candidates[:10]
        formatted = ", ".join(f"'{c.identifier or c.id}' (id {c.id}, name '{c.name}')" for c in shown)
        if exhausted:
            remainder = len(candidates) - len(shown)
            suffix = f" (+{remainder} more)" if remainder > 0 else ""
        else:
            suffix = " (additional matches may exist)"
        return InvalidInputError(
            f"OpenProject project '{project_ref}' is ambiguous: {formatted}{suffix}. "
            f"Use a numeric id or exact identifier, or call list_projects(search='{project_ref}')."
        )
