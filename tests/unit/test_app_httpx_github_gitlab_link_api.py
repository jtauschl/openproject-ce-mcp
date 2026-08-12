from __future__ import annotations

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_github_gitlab_link_api import (
    HttpxGithubGitlabLinkApi,
    normalize_github_pull_request_raw,
    normalize_gitlab_issue_raw,
    normalize_gitlab_merge_request_raw,
)
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _github_pull_request_payload(pr_id: int = 9) -> dict:
    return {
        "id": pr_id,
        "number": 42,
        "htmlUrl": "https://github.com/acme/widget/pull/42",
        "state": "open",
        "repository": "acme/widget",
        "repositoryHtmlUrl": "https://github.com/acme/widget",
        "githubUpdatedAt": "2026-03-20T10:00:00Z",
        "title": "Fix the thing",
        "body": {"raw": "This PR fixes the thing.", "html": "<p>This PR fixes the thing.</p>"},
        "draft": False,
        "merged": True,
        "mergedAt": "2026-03-21T10:00:00Z",
        "commentsCount": 3,
        "reviewCommentsCount": 2,
        "additionsCount": 10,
        "deletionsCount": 4,
        "changedFilesCount": 2,
        "labels": ["bug", "priority:high"],
        "createdAt": "2026-03-19T10:00:00Z",
        "updatedAt": "2026-03-21T10:00:00Z",
        "_links": {
            "githubUser": {"href": "/api/v3/github_users/1", "title": "octocat"},
            "mergedBy": {"href": "/api/v3/github_users/2", "title": "hubot"},
        },
    }


def _gitlab_issue_payload(issue_id: int = 5) -> dict:
    return {
        "id": issue_id,
        "number": 7,
        "htmlUrl": "https://gitlab.com/acme/widget/-/issues/7",
        "state": "opened",
        "repository": "acme/widget",
        "gitlabUpdatedAt": "2026-03-20T10:00:00Z",
        "title": "Investigate the flaky test",
        "body": {"raw": "It fails intermittently.", "html": "<p>It fails intermittently.</p>"},
        "labels": ["flaky"],
        "createdAt": "2026-03-19T10:00:00Z",
        "updatedAt": "2026-03-21T10:00:00Z",
        "_links": {
            "gitlabUser": {"href": "/api/v3/gitlab_users/1", "title": "glbot"},
        },
    }


def _gitlab_merge_request_payload(mr_id: int = 6) -> dict:
    return {
        "id": mr_id,
        "number": 8,
        "htmlUrl": "https://gitlab.com/acme/widget/-/merge_requests/8",
        "state": "opened",
        "repository": "acme/widget",
        "gitlabUpdatedAt": "2026-03-20T10:00:00Z",
        "title": "Add the feature",
        "body": {"raw": "Adds the feature.", "html": "<p>Adds the feature.</p>"},
        "draft": True,
        "merged": False,
        "labels": ["feature"],
        "createdAt": "2026-03-19T10:00:00Z",
        "updatedAt": "2026-03-21T10:00:00Z",
        "_links": {
            "gitlabUser": {"href": "/api/v3/gitlab_users/1", "title": "glbot"},
            "mergedBy": {"href": "/api/v3/gitlab_users/2", "title": "glmerger"},
        },
    }


# --- GitHub pull requests --------------------------------------------------


@pytest.mark.asyncio
async def test_get_github_pull_request_raw_requests_single_pull_request() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/github_pull_requests/9"
        assert request.method == "GET"
        return httpx.Response(200, json=_github_pull_request_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxGithubGitlabLinkApi(HttpxTransport(http_client))
        raw = await api.get_github_pull_request_raw(9)

    assert raw["id"] == 9


@pytest.mark.asyncio
async def test_fetch_github_pull_requests_for_work_package_requests_the_sub_resource_and_extracts_elements() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/work_packages/42/github_pull_requests"
        assert request.method == "GET"
        assert not request.url.params
        return httpx.Response(
            200,
            json={"total": 1, "count": 1, "_embedded": {"elements": [_github_pull_request_payload()]}},
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxGithubGitlabLinkApi(HttpxTransport(http_client))
        elements = await api.fetch_github_pull_requests_for_work_package(42)

    assert len(elements) == 1
    assert elements[0]["id"] == 9


def test_normalize_github_pull_request_raw_extracts_all_fields() -> None:
    pr = normalize_github_pull_request_raw(_github_pull_request_payload(), text_limit=None)

    assert pr.id == 9
    assert pr.number == 42
    assert pr.html_url == "https://github.com/acme/widget/pull/42"
    assert pr.state == "open"
    assert pr.repository == "acme/widget"
    assert pr.repository_html_url == "https://github.com/acme/widget"
    assert pr.github_updated_at == "2026-03-20T10:00:00Z"
    assert pr.title == "Fix the thing"
    assert pr.body == "This PR fixes the thing."
    assert pr.body_truncated is False
    assert pr.body_length == len("This PR fixes the thing.")
    assert pr.draft is False
    assert pr.merged is True
    assert pr.merged_at == "2026-03-21T10:00:00Z"
    assert pr.comments_count == 3
    assert pr.review_comments_count == 2
    assert pr.additions_count == 10
    assert pr.deletions_count == 4
    assert pr.changed_files_count == 2
    assert pr.labels == ["bug", "priority:high"]
    assert pr.author == "octocat"
    assert pr.merged_by == "hubot"
    assert pr.created_at == "2026-03-19T10:00:00Z"
    assert pr.updated_at == "2026-03-21T10:00:00Z"


def test_normalize_github_pull_request_raw_handles_missing_optional_links() -> None:
    payload = _github_pull_request_payload()
    payload["_links"] = {}

    pr = normalize_github_pull_request_raw(payload, text_limit=None)

    assert pr.author is None
    assert pr.merged_by is None


def test_normalize_github_pull_request_raw_truncates_long_body() -> None:
    payload = _github_pull_request_payload()
    long_text = "x" * 50
    payload["body"] = {"raw": long_text}

    pr = normalize_github_pull_request_raw(payload, text_limit=10)

    assert pr.body_truncated is True
    assert pr.body_length == 50
    assert pr.body is not None
    assert len(pr.body) == 10


def test_normalize_github_pull_request_raw_defaults_booleans_when_absent() -> None:
    pr = normalize_github_pull_request_raw({"id": 1, "_links": {}}, text_limit=None)

    assert pr.draft is False
    assert pr.merged is False
    assert pr.labels == []


# --- GitLab issues ----------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_gitlab_issues_for_work_package_requests_the_sub_resource() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/work_packages/42/gitlab_issues"
        assert request.method == "GET"
        assert not request.url.params
        return httpx.Response(
            200,
            json={"total": 1, "count": 1, "_embedded": {"elements": [_gitlab_issue_payload()]}},
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxGithubGitlabLinkApi(HttpxTransport(http_client))
        elements = await api.fetch_gitlab_issues_for_work_package(42)

    assert len(elements) == 1
    assert elements[0]["id"] == 5


def test_normalize_gitlab_issue_raw_extracts_all_fields() -> None:
    issue = normalize_gitlab_issue_raw(_gitlab_issue_payload(), text_limit=None)

    assert issue.id == 5
    assert issue.number == 7
    assert issue.html_url == "https://gitlab.com/acme/widget/-/issues/7"
    assert issue.state == "opened"
    assert issue.repository == "acme/widget"
    assert issue.gitlab_updated_at == "2026-03-20T10:00:00Z"
    assert issue.title == "Investigate the flaky test"
    assert issue.body == "It fails intermittently."
    assert issue.body_truncated is False
    assert issue.body_length == len("It fails intermittently.")
    assert issue.labels == ["flaky"]
    assert issue.author == "glbot"
    assert issue.created_at == "2026-03-19T10:00:00Z"
    assert issue.updated_at == "2026-03-21T10:00:00Z"


def test_normalize_gitlab_issue_raw_handles_missing_optional_links() -> None:
    payload = _gitlab_issue_payload()
    payload["_links"] = {}

    issue = normalize_gitlab_issue_raw(payload, text_limit=None)

    assert issue.author is None


def test_normalize_gitlab_issue_raw_truncates_long_body() -> None:
    payload = _gitlab_issue_payload()
    long_text = "y" * 50
    payload["body"] = {"raw": long_text}

    issue = normalize_gitlab_issue_raw(payload, text_limit=10)

    assert issue.body_truncated is True
    assert issue.body_length == 50
    assert issue.body is not None
    assert len(issue.body) == 10


# --- GitLab merge requests ---------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_gitlab_merge_requests_for_work_package_requests_the_sub_resource() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/work_packages/42/gitlab_merge_requests"
        assert request.method == "GET"
        assert not request.url.params
        return httpx.Response(
            200,
            json={"total": 1, "count": 1, "_embedded": {"elements": [_gitlab_merge_request_payload()]}},
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxGithubGitlabLinkApi(HttpxTransport(http_client))
        elements = await api.fetch_gitlab_merge_requests_for_work_package(42)

    assert len(elements) == 1
    assert elements[0]["id"] == 6


def test_normalize_gitlab_merge_request_raw_extracts_all_fields() -> None:
    mr = normalize_gitlab_merge_request_raw(_gitlab_merge_request_payload(), text_limit=None)

    assert mr.id == 6
    assert mr.number == 8
    assert mr.html_url == "https://gitlab.com/acme/widget/-/merge_requests/8"
    assert mr.state == "opened"
    assert mr.repository == "acme/widget"
    assert mr.gitlab_updated_at == "2026-03-20T10:00:00Z"
    assert mr.title == "Add the feature"
    assert mr.body == "Adds the feature."
    assert mr.body_truncated is False
    assert mr.body_length == len("Adds the feature.")
    assert mr.draft is True
    assert mr.merged is False
    assert mr.labels == ["feature"]
    assert mr.author == "glbot"
    assert mr.merged_by == "glmerger"
    assert mr.created_at == "2026-03-19T10:00:00Z"
    assert mr.updated_at == "2026-03-21T10:00:00Z"


def test_normalize_gitlab_merge_request_raw_handles_missing_optional_links() -> None:
    payload = _gitlab_merge_request_payload()
    payload["_links"] = {}

    mr = normalize_gitlab_merge_request_raw(payload, text_limit=None)

    assert mr.author is None
    assert mr.merged_by is None


def test_normalize_gitlab_merge_request_raw_truncates_long_body() -> None:
    payload = _gitlab_merge_request_payload()
    long_text = "z" * 50
    payload["body"] = {"raw": long_text}

    mr = normalize_gitlab_merge_request_raw(payload, text_limit=10)

    assert mr.body_truncated is True
    assert mr.body_length == 50
    assert mr.body is not None
    assert len(mr.body) == 10
