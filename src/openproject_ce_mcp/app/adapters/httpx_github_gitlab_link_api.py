"""HTTP-backed GithubGitlabLinkApi adapter.

No `httpx` import (depends on the `Transport` Protocol only, matching every
other adapter).

Route verification (`modules/{github_integration,gitlab_integration}/lib/api/v3/` in OpenProject):
- `GET github_pull_requests/{id}`                -- github_pull_requests/github_pull_requests_api.rb
- `GET work_packages/{id}/github_pull_requests`   -- github_pull_requests/github_pull_requests_by_work_package_api.rb
- `GET work_packages/{id}/gitlab_issues`          -- gitlab_issues/gitlab_issues_by_work_package_api.rb
- `GET work_packages/{id}/gitlab_merge_requests`  -- gitlab_merge_requests/gitlab_merge_requests_by_work_package_api.rb

All three collection routes are unpaginated (`*CollectionRepresenter <
API::Decorators::Collection`, no override; no offset/pageSize read
anywhere) -- `fetch_*_for_work_package` reads `_embedded.elements` directly
and returns the raw list, no query params sent, matching
`HttpxCostApi.fetch_cost_entries_for_work_package`'s precedent.

`body` is a `formattable_property` on all three single-item representers
(verified: `github_pull_request_representer.rb`, `gitlab_issue_representer.rb`,
`gitlab_merge_request_representer.rb`), extracted via
`extract_formattable_text_with_meta` with `limit=self._text_limit`, fixed at
construction time from `settings.text_limit` -- same as
`HttpxMeetingOutcomeApi`'s `notes` field, no per-call override exposed.

Plain (non-link) properties camelize automatically with no explicit `as:`
override except `github_html_url`/`gitlab_html_url` -> `htmlUrl` (verified:
representers declare `property :github_html_url, as: :htmlUrl` /
`property :gitlab_html_url, as: :htmlUrl`); every other plain property
(`repository_html_url`, `comments_count`, `review_comments_count`,
`additions_count`, `deletions_count`, `changed_files_count`, `merged_at`,
`github_updated_at`/`gitlab_updated_at`) camelizes without an explicit `as:`,
matching `spent_units` -> `spentUnits` in `httpx_cost_api.py`'s established
convention.

`author`/`merged_by` HAL link keys -- verified directly against
`lib/api/decorators/linked_resource.rb`'s `associated_resource` macro: the
rendered `_links` key is `name.to_s.camelize(:lower)` (see `link_attr`), so
`associated_resource :github_user` / `:gitlab_user` renders under
`_links.githubUser` / `_links.gitlabUser`, and `associated_resource
:merged_by` renders under `_links.mergedBy` for both GitHub PR and GitLab MR.
GitLab issues have no `merged_by` link at all (issues have no merge concept).

`checkRuns`/`latest_check_runs` (GitHub PR) and `pipelines`/`latest_pipelines`
(GitLab MR) are real fields (verified in both representers) but are NOT
extracted here -- each is a nested collection-of-objects (id/htmlUrl/name/
status/... per check run or pipeline), not a scalar/link like `author`. No
existing Summary in this codebase models a nested list-of-objects field
(`labels` is a list of plain strings, the only list-field precedent).
Building a `GithubCheckRunSummary`/`GitlabPipelineSummary` pair would
meaningfully expand this domain's surface beyond "linkage discovery" -- a
deliberate scope decision, not an oversight. The PR's own review/CI *counts*
(`comments_count`, `review_comments_count`, etc.) are still surfaced.
"""

from __future__ import annotations

from typing import Any

from ...models import GithubPullRequestSummary, GitlabIssueSummary, GitlabMergeRequestSummary
from ..ports.github_gitlab_link_api import GithubPullRequestRecord, GitlabIssueRecord, GitlabMergeRequestRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import extract_formattable_text_with_meta as _extract_formattable_text_with_meta
from ._text import link_title as _link_title
from ._text import trim_text as _trim_text


def normalize_github_pull_request_raw(payload: dict[str, Any], *, text_limit: int | None) -> GithubPullRequestSummary:
    links = payload.get("_links", {})
    body, body_truncated, body_length = _extract_formattable_text_with_meta(payload.get("body"), limit=text_limit)
    return GithubPullRequestSummary(
        id=int(payload["id"]),
        number=payload.get("number"),
        html_url=_trim_text(payload.get("htmlUrl"), limit=SUBJECT_LIMIT),
        state=_trim_text(payload.get("state"), limit=SUBJECT_LIMIT),
        repository=_trim_text(payload.get("repository"), limit=SUBJECT_LIMIT),
        repository_html_url=_trim_text(payload.get("repositoryHtmlUrl"), limit=SUBJECT_LIMIT),
        github_updated_at=payload.get("githubUpdatedAt"),
        title=_trim_text(payload.get("title"), limit=SUBJECT_LIMIT),
        body=body,
        body_truncated=body_truncated,
        body_length=body_length,
        draft=bool(payload.get("draft")),
        merged=bool(payload.get("merged")),
        merged_at=payload.get("mergedAt"),
        comments_count=payload.get("commentsCount"),
        review_comments_count=payload.get("reviewCommentsCount"),
        additions_count=payload.get("additionsCount"),
        deletions_count=payload.get("deletionsCount"),
        changed_files_count=payload.get("changedFilesCount"),
        labels=[str(label) for label in payload.get("labels") or []],
        author=_link_title(links.get("githubUser")),
        merged_by=_link_title(links.get("mergedBy")),
        created_at=payload.get("createdAt"),
        updated_at=payload.get("updatedAt"),
    )


def normalize_gitlab_issue_raw(payload: dict[str, Any], *, text_limit: int | None) -> GitlabIssueSummary:
    links = payload.get("_links", {})
    body, body_truncated, body_length = _extract_formattable_text_with_meta(payload.get("body"), limit=text_limit)
    return GitlabIssueSummary(
        id=int(payload["id"]),
        number=payload.get("number"),
        html_url=_trim_text(payload.get("htmlUrl"), limit=SUBJECT_LIMIT),
        state=_trim_text(payload.get("state"), limit=SUBJECT_LIMIT),
        repository=_trim_text(payload.get("repository"), limit=SUBJECT_LIMIT),
        gitlab_updated_at=payload.get("gitlabUpdatedAt"),
        title=_trim_text(payload.get("title"), limit=SUBJECT_LIMIT),
        body=body,
        body_truncated=body_truncated,
        body_length=body_length,
        labels=[str(label) for label in payload.get("labels") or []],
        author=_link_title(links.get("gitlabUser")),
        created_at=payload.get("createdAt"),
        updated_at=payload.get("updatedAt"),
    )


def normalize_gitlab_merge_request_raw(payload: dict[str, Any], *, text_limit: int | None) -> GitlabMergeRequestSummary:
    links = payload.get("_links", {})
    body, body_truncated, body_length = _extract_formattable_text_with_meta(payload.get("body"), limit=text_limit)
    return GitlabMergeRequestSummary(
        id=int(payload["id"]),
        number=payload.get("number"),
        html_url=_trim_text(payload.get("htmlUrl"), limit=SUBJECT_LIMIT),
        state=_trim_text(payload.get("state"), limit=SUBJECT_LIMIT),
        repository=_trim_text(payload.get("repository"), limit=SUBJECT_LIMIT),
        gitlab_updated_at=payload.get("gitlabUpdatedAt"),
        title=_trim_text(payload.get("title"), limit=SUBJECT_LIMIT),
        body=body,
        body_truncated=body_truncated,
        body_length=body_length,
        draft=bool(payload.get("draft")),
        merged=bool(payload.get("merged")),
        labels=[str(label) for label in payload.get("labels") or []],
        author=_link_title(links.get("gitlabUser")),
        merged_by=_link_title(links.get("mergedBy")),
        created_at=payload.get("createdAt"),
        updated_at=payload.get("updatedAt"),
    )


class HttpxGithubGitlabLinkApi:
    def __init__(self, transport: Transport, *, text_limit: int | None = None) -> None:
        self._transport = transport
        self._text_limit = text_limit

    def to_github_pull_request_record(self, payload: dict[str, Any]) -> GithubPullRequestRecord:
        return GithubPullRequestRecord(summary=normalize_github_pull_request_raw(payload, text_limit=self._text_limit))

    def to_gitlab_issue_record(self, payload: dict[str, Any]) -> GitlabIssueRecord:
        return GitlabIssueRecord(summary=normalize_gitlab_issue_raw(payload, text_limit=self._text_limit))

    def to_gitlab_merge_request_record(self, payload: dict[str, Any]) -> GitlabMergeRequestRecord:
        return GitlabMergeRequestRecord(
            summary=normalize_gitlab_merge_request_raw(payload, text_limit=self._text_limit)
        )

    async def get_github_pull_request_raw(self, github_pull_request_id: int) -> dict[str, Any]:
        return await self._transport.get_json(f"github_pull_requests/{github_pull_request_id}")

    async def fetch_github_pull_requests_for_work_package(self, work_package_id: int) -> list[dict[str, Any]]:
        payload = await self._transport.get_json(f"work_packages/{work_package_id}/github_pull_requests")
        return [item for item in payload.get("_embedded", {}).get("elements", []) if isinstance(item, dict)]

    async def fetch_gitlab_issues_for_work_package(self, work_package_id: int) -> list[dict[str, Any]]:
        payload = await self._transport.get_json(f"work_packages/{work_package_id}/gitlab_issues")
        return [item for item in payload.get("_embedded", {}).get("elements", []) if isinstance(item, dict)]

    async def fetch_gitlab_merge_requests_for_work_package(self, work_package_id: int) -> list[dict[str, Any]]:
        payload = await self._transport.get_json(f"work_packages/{work_package_id}/gitlab_merge_requests")
        return [item for item in payload.get("_embedded", {}).get("elements", []) if isinstance(item, dict)]
