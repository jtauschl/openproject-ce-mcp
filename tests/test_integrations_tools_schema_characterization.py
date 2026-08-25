"""Characterization test: freezes the 4 GitHub/GitLab Integrations MCP tool schemas.

Proves that where these tool functions live (tools.py vs. their own per-domain
file) has zero effect on what an MCP client actually sees -- parameter names/
order/types, descriptions, required fields, and whether the tool carries an
output_schema (trimmed tools register with structured_output=False and have
none, see test_trimming.py). A future relocation of any of these functions to
a different module must leave this file completely unmodified; a diff to it
would mean the move changed the public tool contract, not just its location.
"""

from __future__ import annotations

from openproject_ce_mcp.config import Settings
from openproject_ce_mcp.server import create_app


def _make_settings(**overrides) -> Settings:
    defaults = {
        "base_url": "https://op.example.com",
        "api_token": "token",
        "timeout": 12,
        "verify_ssl": True,
        "default_page_size": 20,
        "max_page_size": 50,
        "max_results": 100,
        "log_level": "WARNING",
        "enable_work_package_write": True,
        "enable_project_write": True,
        "enable_membership_write": True,
        "enable_version_write": True,
        "enable_board_write": True,
        "enable_admin_write": True,
        "read_projects": ("*",),
        "write_projects": ("*",),
        "enable_metadata_tools": True,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _tools(mcp) -> dict:
    return {t.name: t for t in mcp._tool_manager.list_tools()}


def test_get_github_pull_request_schema() -> None:
    tool = _tools(create_app(_make_settings()))["get_github_pull_request"]
    assert (
        tool.description
        == "Get a single GitHub pull request by its own id.\n\nGitHub pull requests are read-only mirror rows synced by OpenProject's own\nGitHub App integration -- never creatable via this API. An empty or 404\nresult can mean either the pull request doesn't exist, or the GitHub App\nintegration isn't configured on this instance; OpenProject's API does not\ndistinguish these cases.\n\nUnlike work-package-scoped lookups in this domain, this global lookup\nrelies on OpenProject's own visibility check (whether the linked work\npackage is visible to the API token), not on this MCP's\nOPENPROJECT_READ_PROJECTS allowlist -- the pull request payload carries no\nproject link for this MCP to check against.\n"
    )
    assert tool.output_schema == {
        "properties": {
            "id": {
                "title": "Id",
                "type": "integer",
            },
            "number": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Number",
            },
            "html_url": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Html Url",
            },
            "state": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "State",
            },
            "repository": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Repository",
            },
            "repository_html_url": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Repository Html Url",
            },
            "github_updated_at": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Github Updated At",
            },
            "title": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Title",
            },
            "body": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Body",
            },
            "body_truncated": {
                "title": "Body Truncated",
                "type": "boolean",
            },
            "body_length": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Body Length",
            },
            "draft": {
                "title": "Draft",
                "type": "boolean",
            },
            "merged": {
                "title": "Merged",
                "type": "boolean",
            },
            "merged_at": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Merged At",
            },
            "comments_count": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Comments Count",
            },
            "review_comments_count": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Review Comments Count",
            },
            "additions_count": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Additions Count",
            },
            "deletions_count": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Deletions Count",
            },
            "changed_files_count": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Changed Files Count",
            },
            "labels": {
                "items": {
                    "type": "string",
                },
                "title": "Labels",
                "type": "array",
            },
            "author": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Author",
            },
            "merged_by": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Merged By",
            },
            "created_at": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Created At",
            },
            "updated_at": {
                "anyOf": [
                    {
                        "type": "string",
                    },
                    {
                        "type": "null",
                    },
                ],
                "title": "Updated At",
            },
        },
        "required": [
            "id",
            "number",
            "html_url",
            "state",
            "repository",
            "repository_html_url",
            "github_updated_at",
            "title",
            "body",
            "body_truncated",
            "body_length",
            "draft",
            "merged",
            "merged_at",
            "comments_count",
            "review_comments_count",
            "additions_count",
            "deletions_count",
            "changed_files_count",
            "labels",
            "author",
            "merged_by",
            "created_at",
            "updated_at",
        ],
        "title": "GithubPullRequestSummary",
        "type": "object",
    }
    assert tool.parameters == {
        "properties": {
            "github_pull_request_id": {
                "title": "Github Pull Request Id",
                "type": "integer",
            },
        },
        "required": ["github_pull_request_id"],
        "title": "get_github_pull_requestArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["github_pull_request_id"]


def test_list_work_package_github_pull_requests_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_work_package_github_pull_requests"]
    assert (
        tool.description
        == "List all GitHub pull requests linked to a work package.\n\nwork_package_id: internal id (e.g., 952) or display_id (e.g., \"PROJ-51\"), not UI display number.\n\nReturns every linked pull request in one call -- this endpoint is\nunpaginated on OpenProject's side (no offset/limit parameters exist). An\nempty result can mean either no pull requests are linked, or the GitHub\nApp integration isn't configured on this instance; OpenProject's API does\nnot distinguish these cases.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "work_package_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "string",
                    },
                ],
                "title": "Work Package Id",
            },
        },
        "required": ["work_package_id"],
        "title": "list_work_package_github_pull_requestsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["work_package_id"]


def test_list_work_package_gitlab_issues_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_work_package_gitlab_issues"]
    assert (
        tool.description
        == "List all GitLab issues linked to a work package.\n\nwork_package_id: internal id (e.g., 952) or display_id (e.g., \"PROJ-51\"), not UI display number.\n\nReturns every linked issue in one call -- this endpoint is unpaginated on\nOpenProject's side (no offset/limit parameters exist). An empty result can\nmean either no issues are linked, or the GitLab integration isn't\nconfigured on this instance; OpenProject's API does not distinguish these\ncases. No single-item get_gitlab_issue tool exists because no such\nendpoint exists upstream -- only this work-package-scoped list.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "work_package_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "string",
                    },
                ],
                "title": "Work Package Id",
            },
        },
        "required": ["work_package_id"],
        "title": "list_work_package_gitlab_issuesArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["work_package_id"]


def test_list_work_package_gitlab_merge_requests_schema() -> None:
    tool = _tools(create_app(_make_settings()))["list_work_package_gitlab_merge_requests"]
    assert (
        tool.description
        == "List all GitLab merge requests linked to a work package.\n\nwork_package_id: internal id (e.g., 952) or display_id (e.g., \"PROJ-51\"), not UI display number.\n\nReturns every linked merge request in one call -- this endpoint is\nunpaginated on OpenProject's side (no offset/limit parameters exist). An\nempty result can mean either no merge requests are linked, or the GitLab\nintegration isn't configured on this instance; OpenProject's API does not\ndistinguish these cases. No single-item get_gitlab_merge_request tool\nexists because no such endpoint exists upstream -- only this\nwork-package-scoped list.\n"
    )
    assert tool.output_schema is None
    assert tool.parameters == {
        "properties": {
            "work_package_id": {
                "anyOf": [
                    {
                        "type": "integer",
                    },
                    {
                        "type": "string",
                    },
                ],
                "title": "Work Package Id",
            },
        },
        "required": ["work_package_id"],
        "title": "list_work_package_gitlab_merge_requestsArguments",
        "type": "object",
        "additionalProperties": False,
    }
    # Dict equality above doesn't check key order -- assert it separately.
    assert list(tool.parameters["properties"]) == ["work_package_id"]
