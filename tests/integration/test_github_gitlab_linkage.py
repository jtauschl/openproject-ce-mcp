"""Integration tests for the GitHub/GitLab work-package linkage domain
(github_pull_requests + gitlab_issues + gitlab_merge_requests).

Entirely read-only mirror rows populated only by an actual configured GitHub
App / GitLab webhook integration -- never creatable via any API (see
`app/ports/github_gitlab_link_api.py`'s module docstring). The configured
test OpenProject instance has neither integration
configured, so the live test suite cannot exercise the "has linked
PRs/issues/MRs" case at all -- a structural coverage gap, not an oversight.
Tests below verify only the empty-collection shape (a work package with
nothing linked returns count=0/results=[], not an error) and the 404 shape
for get_github_pull_request, following the same documented-gap pattern as
tests/integration/test_wiki_page_links.py.
"""

from __future__ import annotations

import pytest

from openproject_ce_mcp.client import NotFoundError, OpenProjectClient

pytestmark = pytest.mark.integration


async def _new_wp_id(client: OpenProjectClient, test_project: str, wp_ids: list[int]) -> int:
    wp_result = await client.work_package.create(
        project=test_project, type="Task", subject="Integration test WP for GitHub/GitLab linkage", confirm=True
    )
    assert wp_result.ready, wp_result.validation_errors
    wp_id = wp_result.work_package_id
    assert wp_id is not None
    wp_ids.append(wp_id)
    return wp_id


async def test_get_github_pull_request_not_found_raises(client: OpenProjectClient) -> None:
    with pytest.raises(NotFoundError):
        await client.github_gitlab_link.get_github_pull_request(999999999)


async def test_list_github_pull_requests_for_work_package_without_any_returns_empty(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    wp_id = await _new_wp_id(client, test_project, wp_ids)

    result = await client.github_gitlab_link.list_work_package_github_pull_requests(wp_id)

    assert result.count == len(result.results) == 0


async def test_list_github_pull_requests_accepts_a_semantic_work_package_ref(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    wp_id = await _new_wp_id(client, test_project, wp_ids)
    wp = await client.work_package.get(wp_id)
    display_id = wp.display_id or ""
    # Semantic identifiers (project-prefixed, e.g. "TST-105") only exist on
    # 17.5+ in semantic mode. On 16.x display_id is absent (added in 17.4);
    # on classic 17.x it's the numeric id as a string. Same detection as
    # test_semantic_identifiers.py::test_reference_resolution_matches_instance_mode.
    is_semantic = "-" in display_id and not display_id.isdigit()
    if not is_semantic:
        pytest.skip("instance is not in semantic identifier mode; nothing to resolve")

    result = await client.github_gitlab_link.list_work_package_github_pull_requests(display_id)

    assert result.count == 0


async def test_list_gitlab_issues_for_work_package_without_any_returns_empty(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    wp_id = await _new_wp_id(client, test_project, wp_ids)

    result = await client.github_gitlab_link.list_work_package_gitlab_issues(wp_id)

    assert result.count == len(result.results) == 0


async def test_list_gitlab_merge_requests_for_work_package_without_any_returns_empty(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    wp_id = await _new_wp_id(client, test_project, wp_ids)

    result = await client.github_gitlab_link.list_work_package_gitlab_merge_requests(wp_id)

    assert result.count == len(result.results) == 0
