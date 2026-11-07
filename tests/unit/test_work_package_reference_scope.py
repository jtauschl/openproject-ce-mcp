"""A version or sprint defined outside the read scope is named by no work package result.

The work package of a covered project carries a version shared into it from a project the scope does
not cover, in its links, in a custom field and as a group label. Each path that returns work packages
runs through the real adapters here, once with a restricted scope and once under `*`.
"""

from __future__ import annotations

import ast
import dataclasses
import json
from collections import Counter

import httpx
import pytest
from _client_test_helpers import _project_index_response, make_settings
from _source_scan import SERVICES, matching_nodes

from openproject_ce_mcp.app.services._work_package_references import HIDDEN_GROUP_LABEL
from openproject_ce_mcp.client import OpenProjectClient

SECRET_VERSION = "Secret release 7"
SECRET_SPRINT = "Secret sprint 3"
OWN_VERSION = "Own release 8"
ALL = ("list", "search", "get", "get_batch", "execute_query", "update", "update_preview", "delete_preview")
# A preview echoes what the form proposed and never names a version, whatever the scope.
PREVIEWS = ("update_preview",)


def _version_link(version_id: int, title: str) -> dict:
    return {"href": f"/api/v3/versions/{version_id}", "title": title}


def _work_package(wp_id: int = 10) -> dict:
    payload = {
        "id": wp_id,
        "subject": "Subject",
        "lockVersion": 1,
        "_links": {
            "self": {"href": f"/api/v3/work_packages/{wp_id}"},
            "project": {"href": "/api/v3/projects/1", "title": "Demo"},
            "version": _version_link(7, SECRET_VERSION),
            "targetVersions": [_version_link(7, SECRET_VERSION), _version_link(8, OWN_VERSION)],
            "sprint": {"href": "/api/v3/sprints/3", "title": SECRET_SPRINT},
            "customField5": [_version_link(7, SECRET_VERSION)],
            "customField6": _version_link(8, OWN_VERSION),
            "customField7": {"href": "/api/v3/custom_options/4", "title": "High"},
        },
    }
    return payload


def _version_resource(version_id: int, name: str, *, project_id: int) -> dict:
    return {
        "id": version_id,
        "name": name,
        "_links": {
            "self": {"href": f"/api/v3/versions/{version_id}"},
            "definingProject": {"href": f"/api/v3/projects/{project_id}"},
        },
    }


class _Server:
    def __init__(self) -> None:
        self.requests: Counter[str] = Counter()
        self.group_link = "/api/v3/versions/7"

    def handler(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        self.requests[f"{method} {path}"] += 1
        if path in {"/api/v3/projects/demo", "/api/v3/projects/1"}:
            body = {"_type": "Project", "id": 1, "name": "Demo", "identifier": "demo", "_links": {}}
        elif path == "/api/v3/projects":
            # The scan finds nothing; a read of named ids (the directory checking a recorded identifier) finds them.
            named = '"id"' in request.url.params.get("filters", "")
            return _project_index_response(request, [(1, "demo", "Demo"), (9, "secret", "Secret")] if named else [])
        elif path == "/api/v3/projects/9":
            body = {"_type": "Project", "id": 9, "name": "Secret", "identifier": "secret", "_links": {}}
        elif path == "/api/v3/versions/7":
            body = _version_resource(7, SECRET_VERSION, project_id=9)
        elif path == "/api/v3/versions/8":
            body = _version_resource(8, OWN_VERSION, project_id=1)
        elif path == "/api/v3/backlog_buckets/6":
            body = {
                "id": 6,
                "name": SECRET_VERSION,
                "_links": {
                    "self": {"href": "/api/v3/backlog_buckets/6"},
                    "definingWorkspace": {"href": "/api/v3/projects/9"},
                },
            }
        elif path == "/api/v3/sprints/3":
            body = {
                "id": 3,
                "name": SECRET_SPRINT,
                "_links": {"self": {"href": "/api/v3/sprints/3"}, "definingWorkspace": {"href": "/api/v3/projects/9"}},
            }
        elif path == "/api/v3/work_packages" and method == "GET":
            body = {
                "total": 1,
                "_embedded": {"elements": [_work_package()]},
                "groups": [
                    {
                        "value": SECRET_VERSION,
                        "count": 1,
                        "sums": {"estimatedTime": "P1D"},
                        "_links": {"valueLink": [{"href": self.group_link}]},
                    }
                ],
                "totalSums": {"estimatedTime": "P1D"},
            }
        elif path == "/api/v3/work_packages/10" and method == "GET":
            body = _work_package()
        elif path == "/api/v3/work_packages/10/form":
            payload = {
                "subject": "New",
                "_links": {
                    "version": _version_link(7, SECRET_VERSION),
                    "targetVersions": [_version_link(7, SECRET_VERSION), _version_link(8, OWN_VERSION)],
                },
            }
            body = {"_embedded": {"payload": payload, "validationErrors": {}, "schema": {}}}
        elif path == "/api/v3/work_packages/10" and method == "PATCH":
            body = _work_package()
        elif path == "/api/v3/queries/5":
            body = {"_embedded": {"results": {"total": 1, "_embedded": {"elements": [_work_package()]}}}}
        else:
            raise AssertionError(f"Unexpected request: {method} {request.url}")
        return httpx.Response(200, json=body, request=request)


def _client(server: _Server, *, read_projects: tuple[str, ...]) -> OpenProjectClient:
    settings = dataclasses.replace(
        make_settings(), read_projects=read_projects, write_projects=read_projects, enable_work_package_write=True
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(server.handler))
    client._project_id_to_identifier[1] = "demo"
    return client


async def _read(client: OpenProjectClient, server: _Server, path: str):
    work_package = client.work_package
    if path == "list":
        return await work_package.list(project="demo")
    if path == "search":
        return await work_package.search(project="demo", search="Subject")
    if path == "get":
        return await work_package.get(10)
    if path == "get_batch":
        return await work_package.get_batch(ids=[10])
    if path == "execute_query":
        return await client.query_execution.execute(5)
    if path == "update":
        return await work_package.update(work_package_id=10, subject="New", confirm=True)
    if path == "update_preview":
        return await work_package.update(work_package_id=10, subject="New", confirm=False)
    return await work_package.delete(work_package_id=10, confirm=False)


def _text(result: object) -> str:
    return json.dumps(dataclasses.asdict(result), default=str)  # type: ignore[call-overload]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ALL)
async def test_no_result_names_a_version_or_sprint_defined_outside_the_read_scope(path: str) -> None:
    server = _Server()
    client = _client(server, read_projects=("demo",))

    text = _text(await _read(client, server, path))

    assert SECRET_VERSION not in text
    assert SECRET_SPRINT not in text
    if path in PREVIEWS:
        assert OWN_VERSION not in text
    else:
        assert OWN_VERSION in text
        assert '"High"' in text
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [path for path in ALL if path not in PREVIEWS])
async def test_under_a_wildcard_scope_every_title_is_kept_and_nothing_is_looked_up(path: str) -> None:
    server = _Server()
    client = _client(server, read_projects=("*",))

    text = _text(await _read(client, server, path))

    assert SECRET_VERSION in text and SECRET_SPRINT in text and OWN_VERSION in text
    assert not [request for request in server.requests if "/versions/" in request or "/sprints/" in request]
    await client.aclose()


@pytest.mark.asyncio
async def test_a_version_is_looked_up_once_per_call_however_many_rows_and_fields_name_it() -> None:
    server = _Server()
    client = _client(server, read_projects=("demo",))

    await _read(client, server, "list")

    assert {key: count for key, count in server.requests.items() if "/versions/" in key or "/sprints/" in key} == {
        "GET /api/v3/versions/7": 1,
        "GET /api/v3/versions/8": 1,
        "GET /api/v3/sprints/3": 1,
    }
    await client.aclose()


@pytest.mark.asyncio
async def test_a_second_read_judges_the_remembered_projects_without_a_request() -> None:
    server = _Server()
    client = _client(server, read_projects=("demo",))

    await _read(client, server, "get")
    await _read(client, server, "list")

    assert {key: count for key, count in server.requests.items() if "/versions/" in key or "/sprints/" in key} == {
        "GET /api/v3/versions/7": 1,
        "GET /api/v3/versions/8": 1,
        "GET /api/v3/sprints/3": 1,
    }
    await client.aclose()


@pytest.mark.asyncio
async def test_the_version_shown_as_the_alias_is_none_when_the_assignment_has_a_hidden_version() -> None:
    server = _Server()
    client = _client(server, read_projects=("demo",))

    detail = await _read(client, server, "get")

    assert (detail.version, detail.target_versions, detail.sprint) == (None, [OWN_VERSION], None)
    assert detail.custom_fields == {"customField5": [], "customField6": OWN_VERSION, "customField7": "High"}
    await client.aclose()


@pytest.mark.asyncio
async def test_a_group_named_after_a_hidden_version_keeps_its_totals_under_a_neutral_label() -> None:
    server = _Server()
    client = _client(server, read_projects=("demo",))

    result = await client.work_package.list(project="demo", group_by="version", include_sums=True)

    assert [(g.value, g.count, g.sums) for g in result.groups or []] == [
        (HIDDEN_GROUP_LABEL, 1, {"estimatedTime": "P1D"})
    ]
    assert result.total_sums == {"estimatedTime": "P1D"}
    assert SECRET_VERSION not in _text(result)
    await client.aclose()


@pytest.mark.asyncio
async def test_a_group_named_after_a_hidden_backlog_bucket_is_judged_like_a_version() -> None:
    server = _Server()
    server.group_link = "/api/v3/backlog_buckets/6"
    client = _client(server, read_projects=("demo",))

    result = await client.work_package.list(project="demo", group_by="backlog_bucket", include_sums=True)

    assert [g.value for g in result.groups or []] == [HIDDEN_GROUP_LABEL]
    await client.aclose()


@pytest.mark.asyncio
async def test_groups_are_kept_under_a_wildcard_scope() -> None:
    server = _Server()
    client = _client(server, read_projects=("*",))

    result = await client.work_package.list(project="demo", group_by="version", include_sums=True)

    assert [g.value for g in result.groups or []] == [SECRET_VERSION]
    await client.aclose()


@pytest.mark.asyncio
async def test_a_failing_lookup_fails_the_read_instead_of_showing_an_unchecked_title() -> None:
    server = _Server()
    client = _client(server, read_projects=("demo",))
    original = server.handler

    def failing(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/versions/7":
            return httpx.Response(500, json={"message": "boom"}, request=request)
        return original(request)

    client = OpenProjectClient(client.settings, transport=httpx.MockTransport(failing))
    client._project_id_to_identifier[1] = "demo"

    with pytest.raises(Exception, match="boom|500|server"):
        await client.work_package.get(10)
    await client.aclose()


@pytest.mark.asyncio
async def test_a_version_the_token_cannot_see_is_not_named() -> None:
    server = _Server()
    original = server.handler

    def not_found(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/versions/7":
            return httpx.Response(404, json={"message": "not found"}, request=request)
        return original(request)

    client = _client(server, read_projects=("demo",))
    client = OpenProjectClient(client.settings, transport=httpx.MockTransport(not_found))
    client._project_id_to_identifier[1] = "demo"

    detail = await client.work_package.get(10)

    assert SECRET_VERSION not in _text(detail)
    await client.aclose()


# service function -> the read above that runs it
PRESENTING_FUNCTIONS = {
    "query_execution_service.py:execute": "execute_query",
    "work_package_service.py:_list_collection_fast_path": "list",
    "work_package_service.py:_list_collection_scanned": "search",
    "work_package_service.py:_to_write_result": "update",
    "work_package_service.py:delete": "delete_preview",
    "work_package_service.py:get": "get",
}
_PRESENTERS = {"present_summaries", "present_detail", "_present", "_detail_of"}


def _presenting_functions(source: str | None = None) -> set[str]:
    def calls_presenter(node: ast.AST) -> bool:
        if not isinstance(node, ast.Call):
            return False
        func = node.func
        return (isinstance(func, ast.Name) and func.id in _PRESENTERS) or (
            isinstance(func, ast.Attribute) and func.attr in _PRESENTERS
        )

    found = matching_nodes(calls_presenter, directories=(SERVICES,), source=source)
    return {
        name for name in found if not name.startswith(("_work_package_presentation.py:", "project_service.py:"))
    } - {
        "work_package_service.py:_present",
        "work_package_service.py:_detail_of",
    }


def test_every_service_function_that_presents_work_packages_is_run_by_a_read_above() -> None:
    assert _presenting_functions() == set(PRESENTING_FUNCTIONS)
    assert set(PRESENTING_FUNCTIONS.values()) <= set(ALL)


def test_a_new_presenting_function_is_found() -> None:
    planted = "async def export(self, records):\n    return await present_summaries(records)\n"

    assert _presenting_functions(planted) == {"planted.py:export"}
