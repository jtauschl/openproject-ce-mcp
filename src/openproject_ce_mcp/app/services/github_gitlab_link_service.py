"""Application Service for the GitHub/GitLab work-package linkage domain
(github_pull_requests + gitlab_issues + gitlab_merge_requests).

Entirely read-only -- see `app/ports/github_gitlab_link_api.py`'s module
docstring for the verified route/representer citations. Depends on
`GithubGitlabLinkApi` and `WorkPackageIdResolver` only (no
`project_id_to_identifier`/current-user dependency needed -- mirrors
`WikiPageLinkService`'s leaf, project-link-free shape, not
`CostService`'s, since none of this domain's three resources have their own
project-allowlist path -- see below).

Read scope reuses `"work_package"` (not a dedicated scope) -- matching
Costs'/Wiki Page Links' precedent for a work-package-scoped sub-resource.

Project-allowlist checks:
- `list_work_package_github_pull_requests` / `list_work_package_gitlab_issues`
  / `list_work_package_gitlab_merge_requests` all resolve `work_package_id`
  via `WorkPackageIdResolver(ref, write=False)`, which already confirms the
  anchor work package is allowed against `OPENPROJECT_READ_PROJECTS` before
  any linked-resource data is fetched -- matching `CostService.
  list_work_package_cost_entries`'s identical precedent. No additional
  per-item allowlist check is needed: the returned rows are inherently
  scoped to the (already allowed) work package's own project.
- `get_github_pull_request` (the global single-item lookup) runs ONLY
  `access.ensure_read_enabled("work_package", ...)` -- deliberately NOT
  `scope_policy.ensure_project_link_allowed`. Verified directly against
  source: `GithubPullRequestRepresenter` has no `project` link at all (no
  `associated_resource :project` anywhere in the file), so there is no
  project link on the payload for this MCP to check against, unlike
  `CostService.get_cost_entry`'s `_links.project` check. This mirrors
  `CostService.get_cost_type`'s classification exactly (project-agnostic
  lookup, no allowlist enforcement possible at this layer) -- the only
  authorization boundary for this specific tool is OpenProject's own
  upstream `@pull_request.visible?(current_user)` gate, not this MCP's
  OPENPROJECT_READ_PROJECTS allowlist. Document this explicitly in the tool
  docstring too.

No hidden_fields entity groups need special "clear associated metadata
together" handling -- each Summary gets one plain `apply_hidden_fields` call,
same as Costs.
"""

from __future__ import annotations

from ...config import Settings
from ...models import (
    GithubPullRequestListResult,
    GithubPullRequestSummary,
    GitlabIssueListResult,
    GitlabIssueSummary,
    GitlabMergeRequestListResult,
    GitlabMergeRequestSummary,
)
from ..policies import access, hidden_fields
from ..ports.github_gitlab_link_api import GithubGitlabLinkApi
from ..ports.work_package_ref import WorkPackageIdResolver


class GithubGitlabLinkService:
    def __init__(
        self,
        *,
        api: GithubGitlabLinkApi,
        settings: Settings,
        resolve_work_package_id: WorkPackageIdResolver,
    ) -> None:
        self._api = api
        self._settings = settings
        self._resolve_work_package_id = resolve_work_package_id

    def _stamp_pr(self, summary: GithubPullRequestSummary) -> GithubPullRequestSummary:
        return hidden_fields.apply_hidden_fields("github_pull_request", summary, settings=self._settings)

    def _stamp_issue(self, summary: GitlabIssueSummary) -> GitlabIssueSummary:
        return hidden_fields.apply_hidden_fields("gitlab_issue", summary, settings=self._settings)

    def _stamp_mr(self, summary: GitlabMergeRequestSummary) -> GitlabMergeRequestSummary:
        return hidden_fields.apply_hidden_fields("gitlab_merge_request", summary, settings=self._settings)

    async def get_github_pull_request(self, github_pull_request_id: int) -> GithubPullRequestSummary:
        access.ensure_read_enabled("work_package", settings=self._settings)
        raw = await self._api.get_github_pull_request_raw(github_pull_request_id)
        record = self._api.to_github_pull_request_record(raw)
        return self._stamp_pr(record.summary)

    async def list_work_package_github_pull_requests(self, work_package_id: int | str) -> GithubPullRequestListResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        resolved_id = await self._resolve_work_package_id(work_package_id, write=False)
        raw_elements = await self._api.fetch_github_pull_requests_for_work_package(resolved_id)
        results = [self._stamp_pr(self._api.to_github_pull_request_record(item).summary) for item in raw_elements]
        return GithubPullRequestListResult(count=len(results), results=results)

    async def list_work_package_gitlab_issues(self, work_package_id: int | str) -> GitlabIssueListResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        resolved_id = await self._resolve_work_package_id(work_package_id, write=False)
        raw_elements = await self._api.fetch_gitlab_issues_for_work_package(resolved_id)
        results = [self._stamp_issue(self._api.to_gitlab_issue_record(item).summary) for item in raw_elements]
        return GitlabIssueListResult(count=len(results), results=results)

    async def list_work_package_gitlab_merge_requests(self, work_package_id: int | str) -> GitlabMergeRequestListResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        resolved_id = await self._resolve_work_package_id(work_package_id, write=False)
        raw_elements = await self._api.fetch_gitlab_merge_requests_for_work_package(resolved_id)
        results = [self._stamp_mr(self._api.to_gitlab_merge_request_record(item).summary) for item in raw_elements]
        return GitlabMergeRequestListResult(count=len(results), results=results)
