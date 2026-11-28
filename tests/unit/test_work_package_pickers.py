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

from openproject_ce_mcp.app.errors import InvalidInputError, PermissionDeniedError, ProjectScopeDeniedError
from openproject_ce_mcp.client import OpenProjectClient
from openproject_ce_mcp.presentation import _to_payload, dump_payload
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
async def test_relation_candidates_carry_the_hidden_keys_of_the_work_package_setting() -> None:
    """The matrix of every hidden entity cannot call this tool (the default relation type selects by the relation
    fields), so the masking of its rows is proved here with a setting that leaves the filter open."""
    seen: list[httpx.Request] = []
    candidates = {
        "_embedded": {
            "elements": [
                {
                    "id": 43,
                    "subject": "Login fails",
                    "_links": {
                        "type": {"title": "Bug"},
                        "status": {"title": "New"},
                        "project": {"href": "/api/v3/projects/1", "title": "Demo"},
                    },
                }
            ]
        }
    }
    client = await _client(
        {"/api/v3/work_packages/42": _wp(), "/api/v3/work_packages/42/available_relation_candidates": candidates},
        seen,
        hidden_fields={"work_package": ("subject", "status")},
    )
    result = await client.work_package_picker.relation_candidates(42)
    text = dump_payload(_to_payload(result, select=None, elide_none=False))
    assert "Login fails" not in text and '"New"' not in text
    assert "Bug" in text
    await client.aclose()


@pytest.mark.asyncio
async def test_relation_candidates_are_refused_before_any_request_while_a_relation_field_is_hidden() -> None:
    seen: list[httpx.Request] = []
    client = await _client({}, seen, hidden_fields={"relation": ("type",)})
    seen.clear()
    with pytest.raises(InvalidInputError, match="relation field 'type' is hidden"):
        await client.work_package_picker.relation_candidates(42)
    assert seen == []
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


def _watchers(*ids: int, total: int | None = None) -> dict:
    return {
        "total": len(ids) if total is None else total,
        "_embedded": {"elements": [{"_type": "User", "id": i, "name": f"User {i}", "login": f"user{i}"} for i in ids]},
    }


def _project_row(project_id: int, identifier: str) -> dict:
    return {"_type": "Project", "id": project_id, "identifier": identifier, "name": identifier.title(), "_links": {}}


@pytest.mark.asyncio
async def test_available_watchers_send_the_page_and_report_the_next_one() -> None:
    seen: list[httpx.Request] = []
    client = await _client(
        {"/api/v3/work_packages/42": _wp(), "/api/v3/work_packages/42/available_watchers": _watchers(5, 6, total=5)},
        seen,
    )
    result = await client.work_package_picker.available_watchers(42, offset=2, limit=2)
    request = seen[-1]
    assert (request.url.params["offset"], request.url.params["pageSize"]) == ("2", "2")
    assert [(w.id, w.name, w.login) for w in result.results] == [(5, "User 5", "user5"), (6, "User 6", "user6")]
    assert (result.total, result.count, result.next_offset, result.truncated) == (5, 2, 3, True)
    await client.aclose()


@pytest.mark.asyncio
async def test_the_last_page_of_available_watchers_has_no_next_offset() -> None:
    seen: list[httpx.Request] = []
    client = await _client(
        {"/api/v3/work_packages/42": _wp(), "/api/v3/work_packages/42/available_watchers": _watchers(8, total=5)},
        seen,
    )
    result = await client.work_package_picker.available_watchers(42, offset=3, limit=2)
    assert (result.next_offset, result.truncated) == (None, False)
    await client.aclose()


@pytest.mark.asyncio
async def test_available_watchers_honour_the_watcher_hide_setting() -> None:
    seen: list[httpx.Request] = []
    client = await _client(
        {"/api/v3/work_packages/42": _wp(), "/api/v3/work_packages/42/available_watchers": _watchers(5)},
        seen,
        hidden_fields={"watcher": ("login",)},
    )
    result = await client.work_package_picker.available_watchers(42)
    assert result.results[0]._hidden_keys == frozenset({"login"})
    await client.aclose()


@pytest.mark.asyncio
async def test_available_watchers_for_a_work_package_outside_the_read_allowlist_are_refused_before_listing() -> None:
    seen: list[httpx.Request] = []
    client = await _client(
        {
            "/api/v3/work_packages/42": _wp("/api/v3/projects/7", "Other"),
            "/api/v3/work_packages/42/available_watchers": _watchers(5),
        },
        seen,
        read_projects=("demo",),
    )
    with pytest.raises(ProjectScopeDeniedError):
        await client.work_package_picker.available_watchers(42)
    assert all("available_watchers" not in r.url.path for r in seen)
    await client.aclose()


@pytest.mark.asyncio
async def test_available_projects_drop_rows_outside_the_read_scope_and_hide_the_server_total() -> None:
    seen: list[httpx.Request] = []
    payload = {
        "total": 2,
        "_embedded": {"elements": [_project_row(1, "demo"), _project_row(7, "other")]},
    }
    client = await _client(
        {"/api/v3/work_packages/42": _wp(), "/api/v3/work_packages/42/available_projects": payload},
        seen,
        read_projects=("demo",),
    )
    result = await client.work_package_picker.available_projects(42)
    assert seen[-1].url.path == "/api/v3/work_packages/42/available_projects"
    assert [p.identifier for p in result.results] == ["demo"]
    assert (result.count, result.total) == (1, 1)
    await client.aclose()


@pytest.mark.asyncio
async def test_available_projects_for_a_work_package_outside_the_read_allowlist_are_refused_before_listing() -> None:
    seen: list[httpx.Request] = []
    client = await _client(
        {
            "/api/v3/work_packages/42": _wp("/api/v3/projects/7", "Other"),
            "/api/v3/work_packages/42/available_projects": {"total": 0, "_embedded": {"elements": []}},
        },
        seen,
        read_projects=("demo",),
    )
    with pytest.raises(ProjectScopeDeniedError):
        await client.work_package_picker.available_projects(42)
    assert all("available_projects" not in r.url.path for r in seen)
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("switch", "method"),
    [
        ("enable_project_read", "available_projects"),
        ("enable_work_package_read", "available_projects"),
        ("enable_work_package_read", "available_watchers"),
    ],
)
async def test_the_read_switches_of_the_listed_domains_are_required(switch: str, method: str) -> None:
    seen: list[httpx.Request] = []
    client = await _client({}, seen, **{switch: False})
    with pytest.raises(PermissionDeniedError):
        await getattr(client.work_package_picker, method)(42)
    assert seen == []
    await client.aclose()
