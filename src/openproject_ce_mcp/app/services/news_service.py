"""Application Service for the News domain (ADR 0001).

Depends on the NewsApi Protocol, never HttpxNewsApi concretely (enforced by
the architecture-boundary test). No dedicated NewsResolver: like Memberships,
a `news_id` is always a numeric value already validated by tools.py -- there
is no semantic-reference resolution for this domain to warrant a Resolver in
the ADR sense.

News shares the "project" read/write scope with Projects/Documents/Grids --
there is no dedicated OPENPROJECT_ENABLE_NEWS_* flag, so every
access.ensure_read_enabled/ensure_write_enabled call here uses scope="project"
(verbatim behavior of client.py's original _ensure_read_enabled("project")/
_ensure_write_enabled("project") calls in list_news/get_news/create_news/
update_news/delete_news).

Unlike MembershipService, News has no /form endpoint: create_news/update_news
are hand-rolled POST/PATCH with no server-side validation round-trip, so the
private _WriteOutcome/_preview/_committed/_to_write_result helpers below (a
trimmed, News-local counterpart to membership_service.py's
_finalize_write/_WriteOutcome) have no validation_errors branch -- kept
separate rather than shared/generalized since that branch genuinely doesn't
apply here, and every migrated domain's write-state-machine helper is
intentionally private/domain-local per ADR 0001, unified only once every
domain has migrated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...config import Settings
from ...models import NewsDetail, NewsListResult, NewsSummary, NewsWriteResult
from ..pagination import paginate_client
from ..policies import access, hidden_fields
from ..policies import scope as scope_policy
from ..policies.news_policy import news_payload_allowed
from ..ports.news_api import NewsApi
from ..ports.project_ref import ProjectRefResolver

SUBJECT_LIMIT = 255


@dataclass(frozen=True)
class _WriteOutcome:
    action: str
    confirmed: bool
    requires_confirmation: bool
    news_id: int | None
    project: str | None
    payload: dict[str, Any]
    result: NewsDetail | None


def _preview(*, action: str, news_id: int | None, project: str | None, payload: dict[str, Any]) -> _WriteOutcome:
    return _WriteOutcome(
        action=action,
        confirmed=False,
        requires_confirmation=True,
        news_id=news_id,
        project=project,
        payload=payload,
        result=None,
    )


def _committed(*, action: str, payload: dict[str, Any], result: NewsDetail) -> _WriteOutcome:
    return _WriteOutcome(
        action=action,
        confirmed=True,
        requires_confirmation=False,
        news_id=result.id,
        project=result.project,
        payload=payload,
        result=result,
    )


def _delete_outcome(*, confirmed: bool, payload: dict[str, Any], detail: NewsDetail) -> _WriteOutcome:
    """delete()'s preview AND commit both carry the SAME (already-fetched,
    already-stamped) `detail` as `result` -- unlike create()/update(), whose
    preview has no committed value yet. Verified against the original
    client.py delete_news's _finalize_delete call, which passed
    preview_result=detail (not None, unlike delete_membership's None)."""
    return _WriteOutcome(
        action="delete",
        confirmed=confirmed,
        requires_confirmation=not confirmed,
        news_id=detail.id,
        project=detail.project,
        payload=payload,
        result=detail,
    )


_MESSAGES: dict[str, tuple[str, str]] = {
    "create": (
        "OpenProject is ready to create this news entry. Ask for confirmation, then call again with confirm=true.",
        "News created successfully.",
    ),
    "update": (
        "OpenProject is ready to update this news entry. Ask for confirmation, then call again with confirm=true.",
        "News updated successfully.",
    ),
    "delete": (
        "OpenProject found the news entry. Ask for confirmation, then call again with confirm=true to delete it.",
        "News deleted successfully.",
    ),
}


def _to_write_result(outcome: _WriteOutcome) -> NewsWriteResult:
    preview_message, success_message = _MESSAGES[outcome.action]
    return NewsWriteResult(
        action=outcome.action,
        confirmed=outcome.confirmed,
        requires_confirmation=outcome.requires_confirmation,
        ready=True,
        message=success_message if outcome.confirmed else preview_message,
        news_id=outcome.news_id,
        project=outcome.project,
        payload=outcome.payload,
        validation_errors={},
        result=outcome.result,
    )


def _trim_text(value: Any, *, limit: int) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


class NewsService:
    def __init__(
        self,
        *,
        api: NewsApi,
        settings: Settings,
        project_id_to_identifier: dict[int, str],
        resolve_project_ref: ProjectRefResolver,
    ) -> None:
        self._api = api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier
        self._resolve_project_ref = resolve_project_ref

    def _stamp(self, value: Any) -> Any:
        return hidden_fields.apply_hidden_fields("news", value, settings=self._settings)

    async def _resolve_project_filter_candidates(self, project: str | None) -> set[str] | None:
        if project is None:
            return None
        project_payload = await self._resolve_project_ref(project, write=False)
        return {
            str(project_payload["id"]).casefold(),
            (_trim_text(project_payload.get("identifier"), limit=SUBJECT_LIMIT) or "").casefold(),
            (_trim_text(project_payload.get("name"), limit=SUBJECT_LIMIT) or "").casefold(),
        }

    @staticmethod
    def _summary_matches_project_candidates(item: NewsSummary, project_candidates: set[str]) -> bool:
        return not project_candidates.isdisjoint(
            {
                str(item.project_id).casefold() if item.project_id is not None else "",
                (item.project or "").casefold(),
            }
        )

    async def list(
        self,
        *,
        project: str | None = None,
        search: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> NewsListResult:
        access.ensure_read_enabled("project", settings=self._settings)
        effective_limit = min(
            limit or self._settings.default_page_size, self._settings.max_page_size, self._settings.max_results
        )
        project_candidates = await self._resolve_project_filter_candidates(project)

        records = await self._api.list_all(page_size=self._settings.max_results)
        results = [
            self._stamp(record.summary)
            for record in records
            if news_payload_allowed(
                {"_links": {"project": record.project_link}},
                settings=self._settings,
                project_id_to_identifier=self._project_id_to_identifier,
            )
        ]
        if project_candidates is not None:
            results = [item for item in results if self._summary_matches_project_candidates(item, project_candidates)]
        if search is not None:
            search_key = search.casefold()
            results = [
                item
                for item in results
                if search_key in (item.title or "").casefold() or search_key in (item.summary or "").casefold()
            ]

        page, total, next_offset, truncated = paginate_client(offset=offset, limit=effective_limit, results=results)
        return NewsListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(page),
            next_offset=next_offset,
            truncated=truncated,
            results=page,
        )

    async def get(self, news_id: int) -> NewsDetail:
        access.ensure_read_enabled("project", settings=self._settings)
        record = await self._api.get(news_id)
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

        if not confirm:
            return _to_write_result(
                _preview(
                    action="create",
                    news_id=None,
                    project=_trim_text(project_payload.get("name"), limit=SUBJECT_LIMIT),
                    payload=payload,
                )
            )

        access.ensure_write_enabled("project", settings=self._settings)
        result = self._stamp(await self._api.commit_create(payload))
        return _to_write_result(_committed(action="create", payload=payload, result=result))

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

        if not confirm:
            return _to_write_result(
                _preview(action="update", news_id=detail.id, project=detail.project, payload=payload)
            )

        access.ensure_write_enabled("project", settings=self._settings)
        result = self._stamp(await self._api.commit_update(news_id, payload))
        return _to_write_result(_committed(action="update", payload=payload, result=result))

    async def delete(self, *, news_id: int, confirm: bool = False) -> NewsWriteResult:
        current = await self._api.get(news_id)
        scope_policy.ensure_project_write_link_allowed(
            current.project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        detail = self._stamp(current.to_detail())
        payload = {"id": detail.id, "title": detail.title}

        if not confirm:
            return _to_write_result(_delete_outcome(confirmed=False, payload=payload, detail=detail))

        access.ensure_write_enabled("project", settings=self._settings)
        await self._api.delete(news_id)
        return _to_write_result(_delete_outcome(confirmed=True, payload=payload, detail=detail))
