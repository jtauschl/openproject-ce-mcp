"""Application Service for the News domain.

Depends on the NewsApi Protocol, never HttpxNewsApi concretely (enforced by
the architecture-boundary test). No dedicated NewsResolver: like Memberships,
a `news_id` is always a numeric value already validated by the tool layer --
there is no semantic-reference resolution for this domain to warrant a
Resolver in the ADR sense.

News shares the "project" read/write scope with Projects/Documents/Grids --
there is no dedicated OPENPROJECT_ENABLE_NEWS_* flag, so every
access.ensure_read_enabled/ensure_write_enabled call here uses scope="project".

Unlike MembershipService, News has no /form endpoint: create_news/update_news
are hand-rolled POST/PATCH with no server-side validation round-trip -- wired
onto the shared `_write_outcome._finalize_write` with `validation_errors={}`
throughout (OPM-2705), the same no-form shape Group/Storage already use; a
previous News-local `_WriteOutcome`/`_preview`/`_committed`/`_to_write_result`
duplicate has been removed now that the shared helper covers this shape too.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...config import Settings
from ...models import NewsDetail, NewsListResult, NewsWriteResult
from ..pagination import clamp_limit, scan_records_and_paginate
from ..policies import access, hidden_fields
from ..policies import scope as scope_policy
from ..policies.news_policy import news_payload_allowed
from ..ports.news_api import NewsApi
from ..ports.project_ref import ProjectRefResolver
from ._write_outcome import _finalize_write, _WriteOutcome
from .project_scoped_list import SUBJECT_LIMIT, resolve_project_filter_candidates, summary_matches_project_candidates
from .project_scoped_list import trim_text as _trim_text


class NewsService:
    def __init__(
        self,
        *,
        api: NewsApi,
        settings: Settings,
        project_id_to_identifier: Mapping[int, str],
        resolve_project_ref: ProjectRefResolver,
    ) -> None:
        self._api = api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier
        self._resolve_project_ref = resolve_project_ref

    def _stamp(self, value: Any) -> Any:
        return hidden_fields.apply_hidden_fields("news", value, settings=self._settings)

    async def list(
        self,
        *,
        project: str | None = None,
        search: str | None = None,
        offset: int = 1,
        limit: int | None = None,
        text_limit: int | None = None,
    ) -> NewsListResult:
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
        search_key = search.casefold() if search is not None else None

        def _record_allowed(record: Any) -> bool:
            if not news_payload_allowed(
                {"_links": {"project": record.project_link}},
                settings=self._settings,
                project_id_to_identifier=self._project_id_to_identifier,
            ):
                return False
            if project_candidates is not None and not summary_matches_project_candidates(
                record.summary, project_candidates
            ):
                return False
            if search_key is not None:
                return (
                    search_key in (record.summary.title or "").casefold()
                    or search_key in (record.summary.summary or "").casefold()
                )
            return True

        # Scan server pages rather than a single fetch capped at
        # settings.max_results, which would silently hide any news item
        # beyond that cap once the endpoint's real result count exceeds it.
        effective_text_limit = text_limit if text_limit is not None else self._settings.text_limit
        raw_items, truncated = await scan_records_and_paginate(
            lambda o, ps: self._api.list_page(offset=o, page_size=ps, text_limit=effective_text_limit),
            item_allowed=_record_allowed,
            server_page_size=self._settings.max_page_size,
            offset=offset,
            limit=effective_limit,
            key=lambda r: r.summary.id,
        )
        results = [self._stamp(record.summary) for record in raw_items]
        total = len(results)
        return NewsListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=total,
            next_offset=offset + 1 if truncated else None,
            truncated=truncated,
            results=results,
        )

    async def get(self, news_id: int, *, text_limit: int | None = None) -> NewsDetail:
        access.ensure_read_enabled("project", settings=self._settings)
        record = await self._api.get(news_id, text_limit=text_limit)
        scope_policy.ensure_project_link_allowed(
            record.project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        return self._stamp(record.to_detail())

    async def create(
        self,
        *,
        project: str,
        title: str,
        summary: str | None = None,
        description: str | None = None,
        confirm: bool = False,
    ) -> NewsWriteResult:
        project_payload = await self._resolve_project_ref(project, write=True)
        project_id = str(project_payload["id"])
        hidden_fields.ensure_field_writable("news", "title", settings=self._settings)
        payload: dict[str, Any] = {
            "title": title,
            "_links": {"project": {"href": f"/api/v3/projects/{project_id}"}},
        }
        if summary is not None:
            hidden_fields.ensure_field_writable("news", "summary", settings=self._settings)
            payload["summary"] = summary
        if description is not None:
            hidden_fields.ensure_field_writable("news", "description", settings=self._settings)
            payload["description"] = {"format": "markdown", "raw": description}

        async def _commit(p: dict[str, Any]) -> NewsDetail:
            return self._stamp(await self._api.commit_create(p))  # type: ignore[no-any-return]

        outcome = await _finalize_write(
            confirm=confirm,
            payload=payload,
            validation_errors={},
            identity={"news_id": None, "project": _trim_text(project_payload.get("name"), limit=SUBJECT_LIMIT)},
            ensure_write_enabled=lambda: access.ensure_write_enabled("project", settings=self._settings),
            commit=_commit,
            committed_identity=lambda d: {"news_id": d.id, "project": d.project},
            rejected_message="",
            preview_message="OpenProject is ready to create this news entry. Ask for confirmation, then call again with confirm=true.",
            success_message="News created successfully.",
        )
        return self._to_write_result("create", outcome)

    async def update(
        self,
        *,
        news_id: int,
        title: str | None = None,
        summary: str | None = None,
        description: str | None = None,
        confirm: bool = False,
    ) -> NewsWriteResult:
        current = await self._api.get(news_id)
        scope_policy.ensure_project_write_link_allowed(
            current.project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        detail = current.to_detail()
        payload: dict[str, Any] = {}
        if title is not None:
            hidden_fields.ensure_field_writable("news", "title", settings=self._settings)
            payload["title"] = title
        if summary is not None:
            hidden_fields.ensure_field_writable("news", "summary", settings=self._settings)
            payload["summary"] = summary
        if description is not None:
            hidden_fields.ensure_field_writable("news", "description", settings=self._settings)
            payload["description"] = {"format": "markdown", "raw": description}

        async def _commit(p: dict[str, Any]) -> NewsDetail:
            return self._stamp(await self._api.commit_update(news_id, p))  # type: ignore[no-any-return]

        outcome = await _finalize_write(
            confirm=confirm,
            payload=payload,
            validation_errors={},
            identity={"news_id": detail.id, "project": detail.project},
            ensure_write_enabled=lambda: access.ensure_write_enabled("project", settings=self._settings),
            commit=_commit,
            committed_identity=lambda d: {"news_id": d.id, "project": d.project},
            rejected_message="",
            preview_message="OpenProject is ready to update this news entry. Ask for confirmation, then call again with confirm=true.",
            success_message="News updated successfully.",
        )
        return self._to_write_result("update", outcome)

    async def delete(self, *, news_id: int, confirm: bool = False) -> NewsWriteResult:
        current = await self._api.get(news_id)
        scope_policy.ensure_project_write_link_allowed(
            current.project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        detail = self._stamp(current.to_detail())
        payload = {"id": detail.id, "title": detail.title}

        async def _commit(p: dict[str, Any]) -> NewsDetail:
            await self._api.delete(news_id)
            return detail

        outcome = await _finalize_write(
            confirm=confirm,
            payload=payload,
            validation_errors={},
            identity={"news_id": detail.id, "project": detail.project},
            ensure_write_enabled=lambda: access.ensure_write_enabled("project", settings=self._settings),
            commit=_commit,
            committed_identity=lambda d: {"news_id": d.id, "project": d.project},
            rejected_message="",
            preview_message="OpenProject found the news entry. Ask for confirmation, then call again with confirm=true to delete it.",
            success_message="News deleted successfully.",
            preview_detail=detail,
        )
        return self._to_write_result("delete", outcome)

    def _to_write_result(self, action: str, outcome: _WriteOutcome[NewsDetail | None]) -> NewsWriteResult:
        return NewsWriteResult(
            action=action,
            state=outcome.state,
            ready=outcome.ready,
            message=outcome.message,
            payload=outcome.payload,
            validation_errors=outcome.validation_errors,
            result=outcome.detail,
            **outcome.identity,
        )
