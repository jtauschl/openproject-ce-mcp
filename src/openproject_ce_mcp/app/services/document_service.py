"""Application Service for the Documents domain (ADR 0001).

Depends on the DocumentApi Protocol, never HttpxDocumentApi concretely
(enforced by the architecture-boundary test). No dedicated DocumentResolver:
like Memberships/News, a `document_id` is always a numeric value already
validated by tools.py -- there is no semantic-reference resolution for this
domain to warrant a Resolver in the ADR sense.

Documents shares the "project" read/write scope with Projects/News/Grids --
there is no dedicated OPENPROJECT_ENABLE_DOCUMENT_* flag, so every
access.ensure_read_enabled/ensure_write_enabled call here uses scope="project"
(verbatim behavior of client.py's original _ensure_read_enabled("project")/
_ensure_write_enabled("project") calls).

PATCH-only, no dedicated create/delete: the OpenProject v3 API exposes no
create/delete endpoint for documents. update() is therefore a single flat
preview/commit method with no shared private _WriteOutcome/_finalize_write
state machine -- unlike every full-CRUD domain migrated so far (Versions,
Projects, Memberships, News), a shared state-machine type would have exactly
one call site here and add indirection with no reuse benefit. This is the
first migrated domain with this (simpler) shape.

update() does NOT call resolve_project_ref (unlike News' create/update):
it takes no `project` parameter at all -- the project scope is derived
entirely from the ALREADY-FETCHED document's own `_links.project`, checked
via scope_policy.ensure_project_write_link_allowed directly.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...models import DocumentDetail, DocumentListResult, DocumentWriteResult
from ..pagination import clamp_limit, paginate_client
from ..policies import access, hidden_fields
from ..policies import scope as scope_policy
from ..policies.document_policy import document_payload_allowed
from ..ports.document_api import DocumentApi
from ..ports.project_ref import ProjectRefResolver
from .project_scoped_list import resolve_project_filter_candidates, summary_matches_project_candidates


class DocumentService:
    def __init__(
        self,
        *,
        api: DocumentApi,
        settings: Settings,
        project_id_to_identifier: dict[int, str],
        resolve_project_ref: ProjectRefResolver,
    ) -> None:
        self._api = api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier
        self._resolve_project_ref = resolve_project_ref

    def _stamp(self, value: Any) -> Any:
        return hidden_fields.apply_hidden_fields("document", value, settings=self._settings)

    async def list(
        self,
        *,
        project: str | None = None,
        search: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> DocumentListResult:
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

        records = await self._api.list_all(page_size=self._settings.max_results)
        results = [
            self._stamp(record.summary)
            for record in records
            if document_payload_allowed(
                {"_links": {"project": record.project_link}},
                settings=self._settings,
                project_id_to_identifier=self._project_id_to_identifier,
            )
        ]
        if project_candidates is not None:
            results = [item for item in results if summary_matches_project_candidates(item, project_candidates)]
        if search is not None:
            search_key = search.casefold()
            results = [item for item in results if search_key in (item.title or "").casefold()]

        page, total, next_offset, truncated = paginate_client(offset=offset, limit=effective_limit, results=results)
        return DocumentListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(page),
            next_offset=next_offset,
            truncated=truncated,
            results=page,
        )

    async def get(self, document_id: int) -> DocumentDetail:
        access.ensure_read_enabled("project", settings=self._settings)
        record = await self._api.get(document_id)
        scope_policy.ensure_project_link_allowed(
            record.project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        return self._stamp(record.to_detail())

    async def update(
        self,
        *,
        document_id: int,
        title: str | None = None,
        description: str | None = None,
        confirm: bool = False,
    ) -> DocumentWriteResult:
        current = await self._api.get(document_id)
        scope_policy.ensure_project_write_link_allowed(
            current.project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        detail = current.to_detail()
        payload: dict[str, Any] = {}
        if title is not None:
            hidden_fields.ensure_field_writable("document", "title", settings=self._settings)
            payload["title"] = title
        if description is not None:
            hidden_fields.ensure_field_writable("document", "description", settings=self._settings)
            payload["description"] = {"format": "markdown", "raw": description}

        if not confirm:
            return DocumentWriteResult(
                action="update",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject is ready to update this document. Ask for confirmation, then call again with confirm=true.",
                document_id=detail.id,
                project=detail.project,
                payload=payload,
                validation_errors={},
                result=None,
            )

        access.ensure_write_enabled("project", settings=self._settings)
        result = self._stamp(await self._api.commit_update(document_id, payload))
        return DocumentWriteResult(
            action="update",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Document updated successfully.",
            document_id=result.id,
            project=result.project,
            payload=payload,
            validation_errors={},
            result=result,
        )
