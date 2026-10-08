"""Work package pickers: available assignees and relation candidates.

The anchor must be readable before anything is listed, and whatever carries a
project (a relation candidate) is filtered against
OPENPROJECT_READ_PROJECTS so the listing never names a project the server may
not show.
"""

from __future__ import annotations

import httpx
import pytest
from _client_test_helpers import _base_settings, _make_project_response, started_client
from _tools_test_helpers import FakeContext

from openproject_ce_mcp.app.errors import InvalidInputError, ProjectScopeDeniedError
from openproject_ce_mcp.client import OpenProjectClient
from openproject_ce_mcp.tools_work_package_pickers import list_work_package_available_relation_candidates

_PRINCIPALS = {
    "_embedded": {
        "elements": [
            {"_type": "User", "id": 5, "name": "Alice", "email": "alice@example.com"},
            {"_type": "Group", "id": 9, "name": "Developers"},
        ]
    }
}


def _wp(project_href: str = "/api/v3/projects/1", title: str = "Demo") -> dict:
    return {"id": 42, "_links": {"project": {"href": project_href, "title": title}}}


def _handler(routes: dict[str, dict], seen: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/api/v3/projects/1":
            return _make_project_response(request, 1)
        body = routes.get(request.url.path)
        if body is None:
            raise AssertionError(f"Unexpected request: {request.method} {request.url}")
        return httpx.Response(200, json=body, request=request)

    return handler


_PROJECTS = [(1, "demo", "Demo"), (7, "other", "Other")]


async def _client(routes: dict[str, dict], seen: list[httpx.Request], **settings) -> OpenProjectClient:
    return await started_client(_base_settings(**settings), _handler(routes, seen), _PROJECTS)


@pytest.mark.asyncio
async def test_available_assignees_for_a_work_package() -> None:
    seen: list[httpx.Request] = []
    client = await _client(
        {"/api/v3/work_packages/42": _wp(), "/api/v3/work_packages/42/available_assignees": _PRINCIPALS}, seen
    )
    result = await client.work_package_picker.available_assignees(work_package_id=42)
    assert result.count == 2
    assert [(p.id, p.type, p.name) for p in result.results] == [(5, "User", "Alice"), (9, "Group", "Developers")]
    await client.aclose()


@pytest.mark.asyncio
async def test_available_assignees_for_a_project() -> None:
    seen: list[httpx.Request] = []
    client = await _client({"/api/v3/projects/1/available_assignees": _PRINCIPALS}, seen)
    result = await client.work_package_picker.available_assignees(project_ref="1")
    assert result.count == 2
    assert seen[-1].url.path == "/api/v3/projects/1/available_assignees"
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [{}, {"work_package_id": 42, "project_ref": "1"}])
async def test_available_assignees_needs_exactly_one_anchor(kwargs: dict) -> None:
    seen: list[httpx.Request] = []
    client = await _client({}, seen)
    with pytest.raises(InvalidInputError, match="exactly one"):
        await client.work_package_picker.available_assignees(**kwargs)
    assert seen == []
    await client.aclose()


@pytest.mark.asyncio
async def test_an_anchor_outside_the_read_allowlist_is_refused_before_listing() -> None:
    seen: list[httpx.Request] = []
    client = await _client(
        {
            "/api/v3/work_packages/42": _wp("/api/v3/projects/7", "Other"),
            "/api/v3/work_packages/42/available_assignees": _PRINCIPALS,
        },
        seen,
        read_projects=("demo",),
    )
    with pytest.raises(ProjectScopeDeniedError):
        await client.work_package_picker.available_assignees(work_package_id=42)
    assert all("available_assignees" not in r.url.path for r in seen)
    await client.aclose()


@pytest.mark.asyncio
async def test_relation_candidates_pass_query_type_and_limit_and_drop_foreign_projects() -> None:
    seen: list[httpx.Request] = []
    candidates = {
        "_embedded": {
            "elements": [
                {
                    "id": 43,
                    "displayId": "DEMO-43",
                    "subject": "Login fails",
                    "_links": {
                        "type": {"title": "Bug"},
                        "status": {"title": "New"},
                        "project": {"href": "/api/v3/projects/1", "title": "Demo"},
                    },
                },
                {
                    "id": 44,
                    "subject": "Secret",
                    "_links": {"project": {"href": "/api/v3/projects/7", "title": "Other"}},
                },
            ]
        }
    }
    client = await _client(
        {"/api/v3/work_packages/42": _wp(), "/api/v3/work_packages/42/available_relation_candidates": candidates},
        seen,
        read_projects=("demo",),
    )
    result = await client.work_package_picker.relation_candidates(42, query="login", relation_type="blocks", limit=5)
    request = seen[-1]
    assert request.url.params["query"] == "login"
    assert request.url.params["type"] == "blocks"
    assert request.url.params["pageSize"] == "5"
    assert [(c.id, c.display_id, c.subject, c.type, c.status, c.project) for c in result.results] == [
        (43, "DEMO-43", "Login fails", "Bug", "New", "Demo")
    ]
    await client.aclose()


@pytest.mark.asyncio
async def test_relation_candidates_omit_unset_filters() -> None:
    seen: list[httpx.Request] = []
    client = await _client(
        {
            "/api/v3/work_packages/42": _wp(),
            "/api/v3/work_packages/42/available_relation_candidates": {"_embedded": {"elements": []}},
        },
        seen,
    )
    await client.work_package_picker.relation_candidates(42)
    assert "query" not in seen[-1].url.params and "type" not in seen[-1].url.params
    await client.aclose()


@pytest.mark.asyncio
async def test_project_anchor_outside_the_read_allowlist_is_refused_before_listing() -> None:
    seen: list[httpx.Request] = []
    client = await _client({}, seen, read_projects=("other",))
    with pytest.raises(ProjectScopeDeniedError):
        await client.work_package_picker.available_assignees(project_ref="1")
    assert all("available_assignees" not in r.url.path for r in seen)
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("relation_type", ["parent", "child"])
async def test_tool_forwards_hierarchy_relation_types(relation_type: str) -> None:
    seen: list[httpx.Request] = []
    client = await _client(
        {
            "/api/v3/work_packages/42": _wp(),
            "/api/v3/work_packages/42/available_relation_candidates": {"_embedded": {"elements": []}},
        },
        seen,
    )
    await list_work_package_available_relation_candidates(
        FakeContext(client), work_package_id=42, relation_type=relation_type
    )
    assert seen[-1].url.path == "/api/v3/work_packages/42/available_relation_candidates"
    assert seen[-1].url.params["type"] == relation_type
    await client.aclose()
