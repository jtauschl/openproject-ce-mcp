"""Application Service for the Views domain.

Depends on the ViewApi Protocol, never HttpxViewApi concretely (enforced by
the architecture-boundary test). No dedicated ViewResolver: a `view_id` is
always a numeric value already validated by tools.py -- there is no
semantic-reference resolution for this domain to warrant a Resolver.

Views shares the "project" read scope with Projects/News/Documents/
Categories -- there is no dedicated OPENPROJECT_ENABLE_VIEW_* flag, so
access.ensure_read_enabled here uses scope="project" (verbatim behavior of
client.py's original _ensure_read_enabled("project") call).

Read-only, no dedicated policy file: unlike Documents/News/Versions, Views
needs no <domain>_payload_allowed wrapper around scope.project_link_payload_allowed
-- there is only ever one link key ("project") to check, and that link is
NULLABLE (a view need not belong to any project; OpenProject's own
QueryRepresenter emits an explicit empty link for a global/unbound view).
Uses `scope.ensure_project_link_allowed_if_present` (the OPTIONAL-project-
link contract), not the required one: a missing/explicitly-empty link is a
documented, legitimate server state here, allowed under a wide-open scope
and denied under a restrictive one, while a structurally malformed link is
always rejected regardless of scope.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...models import ViewDetail, ViewListResult
from ..pagination import clamp_limit, paginate_all, paginate_client
from ..policies import access, hidden_fields
from ..policies import scope as scope_policy
from ..ports.project_ref import ProjectRefResolver
from ..ports.view_api import ViewApi
from .project_scoped_list import resolve_project_filter_candidates, summary_matches_project_candidates


class ViewService:
    def __init__(
        self,
        *,
        api: ViewApi,
        settings: Settings,
        project_id_to_identifier: dict[int, str],
        resolve_project_ref: ProjectRefResolver,
    ) -> None:
        self._api = api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier
        self._resolve_project_ref = resolve_project_ref

    def _stamp(self, value: Any) -> Any:
        return hidden_fields.apply_hidden_fields("view", value, settings=self._settings)

    def _allowed(self, project_link: dict | None) -> bool:
        return scope_policy.payload_allowed(
            lambda: scope_policy.ensure_project_link_allowed_if_present(
                project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
            )
        )

    async def list(
        self,
        *,
        project: str | None = None,
        view_type: str | None = None,
        search: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> ViewListResult:
        access.ensure_read_enabled("project", settings=self._settings)
        effective_limit = clamp_limit(
            limit,
            default_page_size=self._settings.default_page_size,
            max_page_size=self._settings.max_page_size,
            max_results=self._settings.max_results,
        )
        project_candidates = await resolve_project_filter_candidates(
            project, resolve_project_ref=self._resolve_project_ref
        )

        # A single fetch capped at settings.max_results silently hid any view
        # beyond that cap once the endpoint's real result count exceeded it --
        # walk every server page instead.
        records = await paginate_all(
            lambda offset, page_size: self._api.list_all(offset=offset, page_size=page_size),
            page_size=self._settings.max_page_size,
            key=lambda r: r.summary.id,
        )
        results = [self._stamp(record.summary) for record in records if self._allowed(record.project_link)]
        if project_candidates is not None:
            results = [item for item in results if summary_matches_project_candidates(item, project_candidates)]
        if view_type is not None:
            results = [item for item in results if (item.type or "").casefold() == view_type.casefold()]
        if search is not None:
            search_key = search.casefold()
            results = [item for item in results if search_key in (item.name or "").casefold()]

        page, total, next_offset, truncated = paginate_client(offset=offset, limit=effective_limit, results=results)
        return ViewListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(page),
            next_offset=next_offset,
            truncated=truncated,
            results=page,
        )

    async def get(self, view_id: int) -> ViewDetail:
        access.ensure_read_enabled("project", settings=self._settings)
        record = await self._api.get(view_id)
        scope_policy.ensure_project_link_allowed_if_present(
            record.project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        return self._stamp(record.detail)
