"""GitHub/GitLab integration MCP tool handlers: get_github_pull_request,
list_work_package_github_pull_requests, list_work_package_gitlab_issues,
list_work_package_gitlab_merge_requests.

Read-only linkage tools for both providers, kept in one module rather than
split by provider (tools_github.py / tools_gitlab.py) -- they share a single
`GithubGitlabLinkService`, one `GithubGitlabLinkApi` port, and one
`HttpxGithubGitlabLinkApi` adapter underneath; a presentation-layer split
here would cut against that shared shape for no real decoupling benefit.

Their `@register_tool` decorators come from `tools_runtime`, never from
`tools.py` -- see that module's own docstring for why. `tools.py` imports
this module for the decorator's registration side effect and re-exports all
four names for consistency with sibling modules, even though no existing
test imports any of them directly from `openproject_ce_mcp.tools`.
"""

from __future__ import annotations

from mcp.server.mcpserver import Context

from .models import (
    GithubPullRequestListResult,
    GithubPullRequestSummary,
    GitlabIssueListResult,
    GitlabMergeRequestListResult,
)
from .tools_runtime import _client_from_context, _run_tool, register_tool
from .tools_validation import _validate_positive_int, _validate_work_package_ref


@register_tool
async def get_github_pull_request(
    ctx: Context,
    github_pull_request_id: int,
) -> GithubPullRequestSummary:
    """Get a single GitHub pull request by its own id.

    GitHub pull requests are read-only mirror rows synced by OpenProject's own
    GitHub App integration -- never creatable via this API. An empty or 404
    result can mean either the pull request doesn't exist, or the GitHub App
    integration isn't configured on this instance; OpenProject's API does not
    distinguish these cases.

    Unlike work-package-scoped lookups in this domain, this global lookup
    relies on OpenProject's own visibility check (whether the linked work
    package is visible to the API token), not on this MCP's
    OPENPROJECT_READ_PROJECTS allowlist -- the pull request payload carries no
    project link for this MCP to check against.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_positive_int(github_pull_request_id, field_name="github_pull_request_id")
    return await _run_tool(client.get_github_pull_request(safe_id))


@register_tool
async def list_work_package_github_pull_requests(
    ctx: Context,
    work_package_id: int | str,
) -> GithubPullRequestListResult:
    """List all GitHub pull requests linked to a work package.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.

    Returns every linked pull request in one call -- this endpoint is
    unpaginated on OpenProject's side (no offset/limit parameters exist). An
    empty result can mean either no pull requests are linked, or the GitHub
    App integration isn't configured on this instance; OpenProject's API does
    not distinguish these cases.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    return await _run_tool(client.list_work_package_github_pull_requests(safe_id))


@register_tool
async def list_work_package_gitlab_issues(
    ctx: Context,
    work_package_id: int | str,
) -> GitlabIssueListResult:
    """List all GitLab issues linked to a work package.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.

    Returns every linked issue in one call -- this endpoint is unpaginated on
    OpenProject's side (no offset/limit parameters exist). An empty result can
    mean either no issues are linked, or the GitLab integration isn't
    configured on this instance; OpenProject's API does not distinguish these
    cases. No single-item get_gitlab_issue tool exists because no such
    endpoint exists upstream -- only this work-package-scoped list.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    return await _run_tool(client.list_work_package_gitlab_issues(safe_id))


@register_tool
async def list_work_package_gitlab_merge_requests(
    ctx: Context,
    work_package_id: int | str,
) -> GitlabMergeRequestListResult:
    """List all GitLab merge requests linked to a work package.

    work_package_id: internal id (e.g., 952) or display_id (e.g., "PROJ-51"), not UI display number.

    Returns every linked merge request in one call -- this endpoint is
    unpaginated on OpenProject's side (no offset/limit parameters exist). An
    empty result can mean either no merge requests are linked, or the GitLab
    integration isn't configured on this instance; OpenProject's API does not
    distinguish these cases. No single-item get_gitlab_merge_request tool
    exists because no such endpoint exists upstream -- only this
    work-package-scoped list.
    """
    client = _client_from_context(ctx)
    safe_id = _validate_work_package_ref(work_package_id)
    return await _run_tool(client.list_work_package_gitlab_merge_requests(safe_id))
