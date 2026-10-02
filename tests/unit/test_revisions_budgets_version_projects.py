"""Revisions, project budgets and the projects of a version.

Each is read-only. Revisions are filtered by their own project link even when
the anchor work package is readable (a commit message can reference a work
package of another project); a version's projects are filtered one by one,
since a shared version reaches beyond its defining project.
"""

from __future__ import annotations

import httpx
import pytest
from _client_test_helpers import _base_settings, _make_project_response

from openproject_ce_mcp.app.errors import ProjectScopeDeniedError
from openproject_ce_mcp.client import OpenProjectClient


def _revision(revision_id: int, project_href: str, title: str) -> dict:
    return {
        "id": revision_id,
        "identifier": "0123456789abcdef",
        "formattedIdentifier": "0123456",
        "authorName": "alice",
        "message": {"format": "plain", "raw": "Fix login, refs #42"},
        "createdAt": "2026-03-20T11:00:00Z",
        "_links": {"project": {"href": project_href, "title": title}, "author": {"title": "Alice"}},
    }


def _client(routes: dict[str, dict], seen: list[httpx.Request], **settings) -> OpenProjectClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/api/v3/projects/1":
            return _make_project_response(request, 1)
        body = routes.get(request.url.path)
        if body is None:
            raise AssertionError(f"Unexpected request: {request.method} {request.url}")
        return httpx.Response(200, json=body, request=request)

    return OpenProjectClient(_base_settings(**settings), transport=httpx.MockTransport(handler))


_WP = {"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}}


@pytest.mark.asyncio
async def test_work_package_revisions_are_normalized_and_filtered_by_their_own_project() -> None:
    seen: list[httpx.Request] = []
    revisions = {
        "_embedded": {
            "elements": [_revision(3, "/api/v3/projects/1", "Demo"), _revision(4, "/api/v3/projects/7", "Other")]
        }
    }
    client = _client(
        {"/api/v3/work_packages/42": _WP, "/api/v3/work_packages/42/revisions": revisions},
        seen,
        read_projects=("demo",),
    )
    result = await client.revision.list_for_work_package(42)
    assert result.count == 1
    revision = result.results[0]
    assert (revision.id, revision.formatted_identifier, revision.author_name, revision.author, revision.project) == (
        3,
        "0123456",
        "alice",
        "Alice",
        "Demo",
    )
    assert revision.message == "<user-content>Fix login, refs #42</user-content>"
    await client.aclose()


@pytest.mark.asyncio
async def test_get_revision_checks_its_project() -> None:
    seen: list[httpx.Request] = []
    client = _client(
        {"/api/v3/revisions/4": _revision(4, "/api/v3/projects/7", "Other")}, seen, read_projects=("demo",)
    )
    with pytest.raises(ProjectScopeDeniedError):
        await client.revision.get(4)
    await client.aclose()


@pytest.mark.asyncio
async def test_get_revision_without_a_project_link_fails_closed() -> None:
    seen: list[httpx.Request] = []
    payload = _revision(4, "/api/v3/projects/1", "Demo")
    del payload["_links"]["project"]
    client = _client({"/api/v3/revisions/4": payload}, seen)
    with pytest.raises(ProjectScopeDeniedError):
        await client.revision.get(4)
    await client.aclose()


@pytest.mark.asyncio
async def test_project_budgets_are_listed_for_a_readable_project() -> None:
    seen: list[httpx.Request] = []
    budgets = {"_embedded": {"elements": [{"_type": "Budget", "id": 1, "subject": "Q3 2026"}]}}
    client = _client({"/api/v3/projects/1/budgets": budgets}, seen, read_projects=("demo",))
    result = await client.budget.list_for_project("1")
    assert [(b.id, b.subject) for b in result.results] == [(1, "Q3 2026")]
    await client.aclose()


@pytest.mark.asyncio
async def test_project_budgets_of_an_unreadable_project_are_refused() -> None:
    seen: list[httpx.Request] = []
    client = _client({}, seen, read_projects=("other",))
    with pytest.raises(ProjectScopeDeniedError):
        await client.budget.list_for_project("1")
    assert all("budgets" not in r.url.path for r in seen)
    await client.aclose()


def _version(project_href: str, title: str) -> dict:
    return {
        "_type": "Version",
        "id": 5,
        "name": "1.0",
        "status": "open",
        "sharing": "system",
        "_links": {"definingProject": {"href": project_href, "title": title}},
    }


@pytest.mark.asyncio
async def test_version_projects_are_filtered_one_by_one() -> None:
    seen: list[httpx.Request] = []
    projects = {
        "_embedded": {
            "elements": [
                {"_type": "Project", "id": 1, "name": "Demo", "identifier": "demo"},
                {"_type": "Project", "id": 7, "name": "Other", "identifier": "other"},
            ]
        }
    }
    client = _client(
        {"/api/v3/versions/5": _version("/api/v3/projects/1", "Demo"), "/api/v3/versions/5/projects": projects},
        seen,
        read_projects=("demo",),
    )
    result = await client.version.list_projects(5)
    assert [p.identifier for p in result.results] == ["demo"]
    await client.aclose()


@pytest.mark.asyncio
async def test_version_projects_need_the_version_itself_to_be_readable() -> None:
    seen: list[httpx.Request] = []
    client = _client({"/api/v3/versions/5": _version("/api/v3/projects/7", "Other")}, seen, read_projects=("demo",))
    with pytest.raises(ProjectScopeDeniedError):
        await client.version.list_projects(5)
    assert all(not r.url.path.endswith("/projects") for r in seen)
    await client.aclose()
