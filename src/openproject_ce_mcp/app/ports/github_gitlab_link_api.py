"""GitHub/GitLab work-package linkage Domain API port
(github_pull_requests + gitlab_issues + gitlab_merge_requests -- entirely read-only).

Verified directly against op-sources/17.7/modules/{github_integration,gitlab_integration}/
lib/api/v3/ -- no EnterpriseToken/enterprise gating anywhere in either module's
api/v3 tree (this is a Community Edition-compatible domain).

github_pull_requests has TWO read shapes:
- `get_github_pull_request_raw`: single pull request by its own id
  (`GET github_pull_requests/{id}`, `github_pull_requests_api.rb`, authorized via
  `@pull_request.visible?(current_user)`).
- `fetch_github_pull_requests_for_work_package`: ALL pull requests linked to a
  work package in one call (`GET work_packages/{id}/github_pull_requests`,
  `github_pull_requests_by_work_package_api.rb`, authorized via
  `authorize_in_work_package(:show_github_content, ...)`) -- UNPAGINATED
  upstream (`GithubPullRequestCollectionRepresenter` extends the plain
  `API::Decorators::Collection` base with no override; no offset/pageSize
  params are read anywhere in the route).

gitlab_issues and gitlab_merge_requests each have ONLY a work-package-scoped
list (`fetch_gitlab_issues_for_work_package` / `fetch_gitlab_merge_requests_for_work_package`,
both `GET work_packages/{id}/<resource>`, authorized via
`authorize_in_work_package(:show_gitlab_content, ...)`) -- no global
single-item GET route exists for either resource (verified: no such file in
either module's `lib/api/v3/gitlab_issues/` or `lib/api/v3/gitlab_merge_requests/`
directory). Both collections are unpaginated, same shape as github_pull_requests'.

`get_github_pull_request_raw` returns the raw HAL payload (not a record),
matching `CostApi.get_cost_entry_raw`'s precedent: `GithubPullRequestRepresenter`
has no `project` link at all (verified: full file read, no `associated_resource
:project`), so unlike `CostService.get_cost_entry` there is nothing for the
Service to extract from the raw payload for a project-allowlist check -- the
raw-payload return is kept for shape-consistency with the rest of this
project's `get_*_raw` convention, not because a project link needs
extracting.

`to_gitlab_issue_record`/`to_gitlab_merge_request_record` are declared as
separate Port methods (not inlined into the adapter's own fetch loop) to
match `CostApi.to_cost_entry_record`'s shape exactly, so the Service can call
them explicitly per element the same way `CostService.list_work_package_cost_entries`
does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ...models import GithubPullRequestSummary, GitlabIssueSummary, GitlabMergeRequestSummary


@dataclass(frozen=True)
class GithubPullRequestRecord:
    summary: GithubPullRequestSummary


@dataclass(frozen=True)
class GitlabIssueRecord:
    summary: GitlabIssueSummary


@dataclass(frozen=True)
class GitlabMergeRequestRecord:
    summary: GitlabMergeRequestSummary


class GithubGitlabLinkApi(Protocol):
    """Narrow, GitHub/GitLab-linkage-only Domain API port. GithubGitlabLinkService
    depends on this Protocol, never on HttpxGithubGitlabLinkApi concretely
    (enforced by the architecture-boundary test).
    """

    async def get_github_pull_request_raw(self, github_pull_request_id: int) -> dict[str, Any]: ...
    def to_github_pull_request_record(self, payload: dict[str, Any]) -> GithubPullRequestRecord: ...
    async def fetch_github_pull_requests_for_work_package(self, work_package_id: int) -> list[dict[str, Any]]: ...
    async def fetch_gitlab_issues_for_work_package(self, work_package_id: int) -> list[dict[str, Any]]: ...
    def to_gitlab_issue_record(self, payload: dict[str, Any]) -> GitlabIssueRecord: ...
    async def fetch_gitlab_merge_requests_for_work_package(self, work_package_id: int) -> list[dict[str, Any]]: ...
    def to_gitlab_merge_request_record(self, payload: dict[str, Any]) -> GitlabMergeRequestRecord: ...
