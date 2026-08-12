from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import PermissionDeniedError
from openproject_ce_mcp.app.ports.github_gitlab_link_api import (
    GithubPullRequestRecord,
    GitlabIssueRecord,
    GitlabMergeRequestRecord,
)
from openproject_ce_mcp.app.services.github_gitlab_link_service import GithubGitlabLinkService
from openproject_ce_mcp.models import GithubPullRequestSummary, GitlabIssueSummary, GitlabMergeRequestSummary


def _pr_summary(pr_id: int = 9) -> GithubPullRequestSummary:
    return GithubPullRequestSummary(
        id=pr_id,
        number=42,
        html_url="https://github.com/acme/widget/pull/42",
        state="open",
        repository="acme/widget",
        repository_html_url="https://github.com/acme/widget",
        github_updated_at=None,
        title="Fix the thing",
        body="This PR fixes the thing.",
        body_truncated=False,
        body_length=25,
        draft=False,
        merged=True,
        merged_at=None,
        comments_count=3,
        review_comments_count=2,
        additions_count=10,
        deletions_count=4,
        changed_files_count=2,
        labels=["bug"],
        author="octocat",
        merged_by="hubot",
        created_at=None,
        updated_at=None,
    )


def _issue_summary(issue_id: int = 5) -> GitlabIssueSummary:
    return GitlabIssueSummary(
        id=issue_id,
        number=7,
        html_url="https://gitlab.com/acme/widget/-/issues/7",
        state="opened",
        repository="acme/widget",
        gitlab_updated_at=None,
        title="Investigate the flaky test",
        body="It fails intermittently.",
        body_truncated=False,
        body_length=25,
        labels=["flaky"],
        author="glbot",
        created_at=None,
        updated_at=None,
    )


def _mr_summary(mr_id: int = 6) -> GitlabMergeRequestSummary:
    return GitlabMergeRequestSummary(
        id=mr_id,
        number=8,
        html_url="https://gitlab.com/acme/widget/-/merge_requests/8",
        state="opened",
        repository="acme/widget",
        gitlab_updated_at=None,
        title="Add the feature",
        body="Adds the feature.",
        body_truncated=False,
        body_length=18,
        draft=True,
        merged=False,
        labels=["feature"],
        author="glbot",
        merged_by="glmerger",
        created_at=None,
        updated_at=None,
    )


class _FakeGithubGitlabLinkApi:
    def __init__(
        self,
        *,
        pull_request_id: int = 9,
        pull_requests_for_work_package: list[GithubPullRequestSummary] | None = None,
        issues_for_work_package: list[GitlabIssueSummary] | None = None,
        merge_requests_for_work_package: list[GitlabMergeRequestSummary] | None = None,
    ) -> None:
        self._pull_request_id = pull_request_id
        self._pull_requests_for_work_package = (
            pull_requests_for_work_package if pull_requests_for_work_package is not None else [_pr_summary()]
        )
        self._issues_for_work_package = (
            issues_for_work_package if issues_for_work_package is not None else [_issue_summary()]
        )
        self._merge_requests_for_work_package = (
            merge_requests_for_work_package if merge_requests_for_work_package is not None else [_mr_summary()]
        )
        self.get_github_pull_request_raw_calls: list[int] = []
        self.fetch_github_pull_requests_for_work_package_calls: list[int] = []
        self.fetch_gitlab_issues_for_work_package_calls: list[int] = []
        self.fetch_gitlab_merge_requests_for_work_package_calls: list[int] = []

    async def get_github_pull_request_raw(self, github_pull_request_id: int) -> dict:
        self.get_github_pull_request_raw_calls.append(github_pull_request_id)
        return {"__summary__": _pr_summary(github_pull_request_id)}

    def to_github_pull_request_record(self, payload: dict) -> GithubPullRequestRecord:
        return GithubPullRequestRecord(summary=payload["__summary__"])

    async def fetch_github_pull_requests_for_work_package(self, work_package_id: int) -> list[dict]:
        self.fetch_github_pull_requests_for_work_package_calls.append(work_package_id)
        return [{"__summary__": s} for s in self._pull_requests_for_work_package]

    async def fetch_gitlab_issues_for_work_package(self, work_package_id: int) -> list[dict]:
        self.fetch_gitlab_issues_for_work_package_calls.append(work_package_id)
        return [{"__summary__": s} for s in self._issues_for_work_package]

    def to_gitlab_issue_record(self, payload: dict) -> GitlabIssueRecord:
        return GitlabIssueRecord(summary=payload["__summary__"])

    async def fetch_gitlab_merge_requests_for_work_package(self, work_package_id: int) -> list[dict]:
        self.fetch_gitlab_merge_requests_for_work_package_calls.append(work_package_id)
        return [{"__summary__": s} for s in self._merge_requests_for_work_package]

    def to_gitlab_merge_request_record(self, payload: dict) -> GitlabMergeRequestRecord:
        return GitlabMergeRequestRecord(summary=payload["__summary__"])


def _resolve_work_package_id_ok(resolved_id: int = 42):
    calls: list[tuple[int | str, bool]] = []

    async def resolve(work_package_ref, *, write: bool = False) -> int:
        calls.append((work_package_ref, write))
        return resolved_id

    resolve.calls = calls  # type: ignore[attr-defined]
    return resolve


def _service(
    *,
    api: _FakeGithubGitlabLinkApi | None = None,
    settings=None,
    resolve_work_package_id=None,
) -> GithubGitlabLinkService:
    return GithubGitlabLinkService(
        api=api or _FakeGithubGitlabLinkApi(),
        settings=settings or make_settings(),
        resolve_work_package_id=resolve_work_package_id or _resolve_work_package_id_ok(),
    )


# --- get_github_pull_request --------------------------------------------------


@pytest.mark.asyncio
async def test_get_github_pull_request_returns_summary() -> None:
    api = _FakeGithubGitlabLinkApi(pull_request_id=9)
    service = _service(api=api)

    result = await service.get_github_pull_request(9)

    assert result.id == 9
    assert api.get_github_pull_request_raw_calls == [9]


@pytest.mark.asyncio
async def test_get_github_pull_request_denies_when_work_package_read_disabled() -> None:
    api = _FakeGithubGitlabLinkApi()
    settings = dataclasses.replace(make_settings(), enable_work_package_read=False)
    service = _service(api=api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get_github_pull_request(9)

    assert api.get_github_pull_request_raw_calls == []


@pytest.mark.asyncio
async def test_get_github_pull_request_masks_hidden_fields() -> None:
    api = _FakeGithubGitlabLinkApi()
    settings = dataclasses.replace(make_settings(), hidden_fields={"github_pull_request": ("body",)})
    service = _service(api=api, settings=settings)

    result = await service.get_github_pull_request(9)

    assert result._hidden_keys == frozenset({"body"})  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_get_github_pull_request_ignores_a_restrictive_read_allowlist() -> None:
    """No project-allowlist check runs for GitHub pull requests at all --
    proves the 'no project link on the payload' design decision (see
    app/services/github_gitlab_link_service.py's module docstring), not just
    documents it."""
    api = _FakeGithubGitlabLinkApi(pull_request_id=9)
    settings = dataclasses.replace(make_settings(), read_projects=())
    service = _service(api=api, settings=settings)

    result = await service.get_github_pull_request(9)

    assert result.id == 9


@pytest.mark.asyncio
async def test_get_github_pull_request_never_calls_work_package_resolver() -> None:
    api = _FakeGithubGitlabLinkApi(pull_request_id=9)
    resolve = _resolve_work_package_id_ok(42)
    service = _service(api=api, resolve_work_package_id=resolve)

    await service.get_github_pull_request(9)

    assert resolve.calls == []


# --- list_work_package_github_pull_requests -----------------------------------


@pytest.mark.asyncio
async def test_list_work_package_github_pull_requests_resolves_work_package_and_returns_all() -> None:
    prs = [_pr_summary(9), _pr_summary(10)]
    api = _FakeGithubGitlabLinkApi(pull_requests_for_work_package=prs)
    resolve = _resolve_work_package_id_ok(42)
    service = _service(api=api, resolve_work_package_id=resolve)

    result = await service.list_work_package_github_pull_requests("PROJ-51")

    assert result.count == 2
    assert len(result.results) == 2
    assert not hasattr(result, "offset")
    assert not hasattr(result, "limit")
    assert not hasattr(result, "truncated")
    assert resolve.calls == [("PROJ-51", False)]
    assert api.fetch_github_pull_requests_for_work_package_calls == [42]


@pytest.mark.asyncio
async def test_list_work_package_github_pull_requests_denies_when_work_package_read_disabled() -> None:
    api = _FakeGithubGitlabLinkApi()
    settings = dataclasses.replace(make_settings(), enable_work_package_read=False)
    service = _service(api=api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.list_work_package_github_pull_requests(42)


@pytest.mark.asyncio
async def test_list_work_package_github_pull_requests_masks_hidden_fields() -> None:
    api = _FakeGithubGitlabLinkApi(pull_requests_for_work_package=[_pr_summary(9)])
    settings = dataclasses.replace(make_settings(), hidden_fields={"github_pull_request": ("author",)})
    service = _service(api=api, settings=settings)

    result = await service.list_work_package_github_pull_requests(42)

    assert result.results[0]._hidden_keys == frozenset({"author"})  # type: ignore[attr-defined]


# --- list_work_package_gitlab_issues --------------------------------------------


@pytest.mark.asyncio
async def test_list_work_package_gitlab_issues_resolves_work_package_and_returns_all() -> None:
    issues = [_issue_summary(5), _issue_summary(6)]
    api = _FakeGithubGitlabLinkApi(issues_for_work_package=issues)
    resolve = _resolve_work_package_id_ok(42)
    service = _service(api=api, resolve_work_package_id=resolve)

    result = await service.list_work_package_gitlab_issues("PROJ-51")

    assert result.count == 2
    assert len(result.results) == 2
    assert resolve.calls == [("PROJ-51", False)]
    assert api.fetch_gitlab_issues_for_work_package_calls == [42]


@pytest.mark.asyncio
async def test_list_work_package_gitlab_issues_denies_when_work_package_read_disabled() -> None:
    api = _FakeGithubGitlabLinkApi()
    settings = dataclasses.replace(make_settings(), enable_work_package_read=False)
    service = _service(api=api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.list_work_package_gitlab_issues(42)


@pytest.mark.asyncio
async def test_list_work_package_gitlab_issues_masks_hidden_fields() -> None:
    api = _FakeGithubGitlabLinkApi(issues_for_work_package=[_issue_summary(5)])
    settings = dataclasses.replace(make_settings(), hidden_fields={"gitlab_issue": ("body",)})
    service = _service(api=api, settings=settings)

    result = await service.list_work_package_gitlab_issues(42)

    assert result.results[0]._hidden_keys == frozenset({"body"})  # type: ignore[attr-defined]


# --- list_work_package_gitlab_merge_requests ------------------------------------


@pytest.mark.asyncio
async def test_list_work_package_gitlab_merge_requests_resolves_work_package_and_returns_all() -> None:
    mrs = [_mr_summary(6), _mr_summary(7)]
    api = _FakeGithubGitlabLinkApi(merge_requests_for_work_package=mrs)
    resolve = _resolve_work_package_id_ok(42)
    service = _service(api=api, resolve_work_package_id=resolve)

    result = await service.list_work_package_gitlab_merge_requests("PROJ-51")

    assert result.count == 2
    assert len(result.results) == 2
    assert resolve.calls == [("PROJ-51", False)]
    assert api.fetch_gitlab_merge_requests_for_work_package_calls == [42]


@pytest.mark.asyncio
async def test_list_work_package_gitlab_merge_requests_denies_when_work_package_read_disabled() -> None:
    api = _FakeGithubGitlabLinkApi()
    settings = dataclasses.replace(make_settings(), enable_work_package_read=False)
    service = _service(api=api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.list_work_package_gitlab_merge_requests(42)


@pytest.mark.asyncio
async def test_list_work_package_gitlab_merge_requests_masks_hidden_fields() -> None:
    api = _FakeGithubGitlabLinkApi(merge_requests_for_work_package=[_mr_summary(6)])
    settings = dataclasses.replace(make_settings(), hidden_fields={"gitlab_merge_request": ("author",)})
    service = _service(api=api, settings=settings)

    result = await service.list_work_package_gitlab_merge_requests(42)

    assert result.results[0]._hidden_keys == frozenset({"author"})  # type: ignore[attr-defined]
