"""`create_project`, `update_project` and `copy_project` name the parent project their `parent` reference resolved to.

The identifier `platform` belongs to one project while another project is named `platform`; the identifier wins,
so a caller who meant the second one is moved under the first without noticing. `parent_target` must name the
project the reference actually resolved to, in the preview and in the confirmed result, and it must be the same
project the request to OpenProject links.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from _client_test_helpers import _base_settings, started_client
from _tools_test_helpers import FakeContext
from mcp import types
from mcp.client import Client

import openproject_ce_mcp.tools_runtime as tools_runtime
from openproject_ce_mcp import tools, tools_projects
from openproject_ce_mcp.app.policies import hidden_fields
from openproject_ce_mcp.client import OpenProjectClient
from openproject_ce_mcp.config import Settings
from openproject_ce_mcp.models import ProjectCopyResult, ProjectWriteResult, ResolvedParentProject
from openproject_ce_mcp.presentation import _to_payload
from openproject_ce_mcp.strict_mcpserver import StrictMCPServer
from openproject_ce_mcp.tool_errors import ToolCallError

CHILD = (3, "child", "Child")
PLATFORM = (5, "platform", "Core")
BETA = (6, "beta", "platform")
PROJECTS = [CHILD, PLATFORM, BETA]
RECORDS = {str(pid): (pid, identifier, name) for pid, identifier, name in PROJECTS}
RECORDS.update({identifier: (pid, identifier, name) for pid, identifier, name in PROJECTS})

EXPECTED_PLATFORM = {"id": 5, "identifier": "platform", "name": "Core"}
EXPECTED_BETA = {"id": 6, "identifier": "beta", "name": "platform"}
REFERENCES = [("platform", EXPECTED_PLATFORM), ("beta", EXPECTED_BETA), ("6", EXPECTED_BETA)]

_JOB_ID = "32ac4e5e-1e49-4cbd-b70e-bc1c781d8af2"
_PROJECT_PATH = re.compile(r"^/api/v3/projects/([^/]+)$")
_NOT_FOUND = {"_type": "Error", "errorIdentifier": "urn:openproject-org:api:v3:errors:NotFound", "message": "Not found"}


def _project(pid: int, identifier: str, name: str) -> dict:
    return {"_type": "Project", "id": pid, "identifier": identifier, "name": name, "_links": {}}


class _Server:
    def __init__(self, *, reject: bool = False) -> None:
        self.reject = reject
        self.gets: list[str] = []
        self.forms: list[dict] = []
        self.commits: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        if method == "POST" and path.endswith("/form"):
            body = json.loads(request.content)
            self.forms.append(body)
            errors = {"name": {"message": "rejected"}} if self.reject else {}
            return httpx.Response(
                200,
                json={"_type": "Form", "_embedded": {"schema": {}, "payload": body, "validationErrors": errors}},
                request=request,
            )
        if method == "GET" and path == f"/api/v3/job_statuses/{_JOB_ID}":
            return httpx.Response(200, json={"_type": "JobStatus", "id": _JOB_ID}, request=request)
        if method == "POST" and path == "/api/v3/projects/3/copy":
            self.commits.append(json.loads(request.content))
            return httpx.Response(302, headers={"Location": f"/api/v3/job_statuses/{_JOB_ID}"}, request=request)
        if method == "POST" and path == "/api/v3/projects":
            self.commits.append(json.loads(request.content))
            return httpx.Response(201, json=_project(9, "created", "Created"), request=request)
        match = _PROJECT_PATH.match(path)
        if match is not None:
            ref = match.group(1)
            if method == "GET":
                self.gets.append(ref)
                if ref not in RECORDS:
                    return httpx.Response(404, json=_NOT_FOUND, request=request)
                return httpx.Response(200, json=_project(*RECORDS[ref]), request=request)
            if method == "PATCH":
                self.commits.append(json.loads(request.content))
                return httpx.Response(200, json=_project(*CHILD), request=request)
        raise AssertionError(f"Unexpected request: {method} {request.url}")


def _settings(**overrides: Any) -> Settings:
    return _base_settings(enable_project_write=True, **overrides)


async def _client(server: _Server, settings: Settings | None = None) -> OpenProjectClient:
    return await started_client(settings or _settings(), server.handler, PROJECTS)


async def _create(ctx: Any, parent: str | None, confirm: bool) -> Any:
    return await tools.create_project(ctx, "New", "new", parent=parent, confirm=confirm)


async def _update(ctx: Any, parent: str | None, confirm: bool) -> Any:
    return await tools.update_project(ctx, "child", name="Renamed", parent=parent, confirm=confirm)


async def _copy(ctx: Any, parent: str | None, confirm: bool) -> Any:
    return await tools.copy_project(ctx, "child", "Copy", "copy", parent=parent, confirm=confirm)


Call = Callable[[Any, str | None, bool], Awaitable[Any]]
TOOLS: dict[str, Call] = {"create_project": _create, "update_project": _update, "copy_project": _copy}
tool_param = pytest.mark.parametrize("call", list(TOOLS.values()), ids=list(TOOLS))
reference_param = pytest.mark.parametrize(
    ("ref", "expected"), REFERENCES, ids=["identifier-over-name", "identifier", "id"]
)
confirm_param = pytest.mark.parametrize("confirm", [False, True], ids=["preview", "confirmed"])


async def _run(
    call: Call, parent: str | None, *, confirm: bool, settings: Settings | None = None, reject: bool = False
) -> tuple[Any, _Server]:
    server = _Server(reject=reject)
    client = await _client(server, settings)
    try:
        return await call(FakeContext(client), parent, confirm), server
    finally:
        await client.aclose()


@tool_param
@reference_param
@confirm_param
@pytest.mark.asyncio
async def test_the_parent_is_named_as_the_project_its_reference_resolved_to(
    call: Call, ref: str, expected: dict, confirm: bool
) -> None:
    result, server = await _run(call, ref, confirm=confirm)

    assert _to_payload(result)["parent_target"] == expected
    assert server.gets.count(ref) == 1


@tool_param
@reference_param
@confirm_param
@pytest.mark.asyncio
async def test_the_parent_shown_is_the_parent_written(call: Call, ref: str, expected: dict, confirm: bool) -> None:
    result, server = await _run(call, ref, confirm=confirm)

    sent = server.commits[-1] if confirm else server.forms[-1]
    assert sent["_links"]["parent"]["href"] == f"/api/v3/projects/{_to_payload(result)['parent_target']['id']}"
    assert _to_payload(result)["parent_target"]["id"] == expected["id"]


@tool_param
@pytest.mark.parametrize("parent", ["none", None], ids=["clear", "unchanged"])
@pytest.mark.asyncio
async def test_no_parent_target_unless_a_parent_is_set(call: Call, parent: str | None) -> None:
    if call is not _update and parent == "none":
        pytest.skip("only update_project clears a parent")

    result, _ = await _run(call, parent, confirm=False)

    assert result.parent_target is None


@pytest.mark.asyncio
async def test_a_delete_names_no_parent() -> None:
    server = _Server()
    client = await _client(server)
    try:
        result = await tools.delete_project(FakeContext(client), "child", confirm=False)
    finally:
        await client.aclose()

    assert result.parent_target is None


@pytest.mark.asyncio
async def test_an_all_digit_reference_that_is_no_project_is_not_found() -> None:
    server = _Server()
    client = await _client(server)
    try:
        with pytest.raises(ToolCallError, match="(?i)not_found"):
            await _update(FakeContext(client), "7", False)
    finally:
        await client.aclose()


@pytest.mark.parametrize("hidden", ["name", "identifier"])
@pytest.mark.asyncio
async def test_a_hidden_project_field_is_absent_from_the_serialized_parent_target(hidden: str) -> None:
    settings = dataclasses.replace(_settings(), hide_project_fields=(hidden,))

    async def update(ctx: Any, parent: str | None, confirm: bool) -> Any:
        return await tools.update_project(ctx, "child", public=True, parent=parent, confirm=confirm)

    result, _ = await _run(update, "platform", confirm=False, settings=settings)

    expected = {key: value for key, value in EXPECTED_PLATFORM.items() if key != hidden}
    assert _to_payload(result)["parent_target"] == expected


@pytest.mark.parametrize("hidden", ["name", "identifier"])
@pytest.mark.parametrize("result_type", [ProjectWriteResult, ProjectCopyResult])
def test_a_hidden_field_is_dropped_from_the_nested_parent_of_either_result_type(hidden: str, result_type: type) -> None:
    settings = dataclasses.replace(_settings(), hide_project_fields=(hidden,))
    parent = hidden_fields.apply_hidden_fields(
        "project", ResolvedParentProject(5, "platform", "Core"), settings=settings
    )
    if result_type is ProjectWriteResult:
        result = ProjectWriteResult("update", "preview", True, "m", 3, "Child", {}, {}, None, parent_target=parent)
    else:
        result = ProjectCopyResult("copy", "preview", True, "m", 3, "Child", {}, {}, None, parent_target=parent)

    expected = {key: value for key, value in EXPECTED_PLATFORM.items() if key != hidden}
    assert _to_payload(result)["parent_target"] == expected


@tool_param
@pytest.mark.asyncio
async def test_a_parent_outside_the_write_scope_is_refused_and_named_nowhere(call: Call) -> None:
    settings = _settings(read_projects=("*",), write_projects=("child", "new", "copy"))
    server = _Server()
    client = await _client(server, settings)
    try:
        with pytest.raises(ToolCallError, match="OPENPROJECT_WRITE_PROJECTS"):
            await call(FakeContext(client), "platform", False)
    finally:
        await client.aclose()

    assert server.commits == []


@tool_param
@pytest.mark.asyncio
async def test_a_rejected_form_still_names_the_parent(call: Call) -> None:
    result, server = await _run(call, "platform", confirm=False, reject=True)

    assert result.ready is False
    assert _to_payload(result)["parent_target"] == EXPECTED_PLATFORM
    assert server.commits == []


@pytest.fixture
def mcp_call() -> Callable[[str, dict], Awaitable[types.CallToolResult]]:
    server_state = _Server()

    @asynccontextmanager
    async def lifespan(_):
        client = await started_client(_settings(), server_state.handler, PROJECTS)
        try:
            yield SimpleNamespace(client=client)
        finally:
            await client.aclose()

    server = StrictMCPServer("test", lifespan=lifespan)
    tools_runtime.register_selected_tools(
        server,
        names=[
            tools_projects.create_project.__name__,
            tools_projects.update_project.__name__,
            tools_projects.copy_project.__name__,
        ],
        hide_active=False,
        annotations=tools.TOOL_ANNOTATIONS,
    )

    async def call(name: str, arguments: dict) -> types.CallToolResult:
        async with Client(server, mode="legacy") as client:
            return await client.call_tool(name, arguments)

    return call


def _text(result: types.CallToolResult) -> str:
    return "".join(getattr(block, "text", "") for block in result.content)


AGENT_CALLS = {
    "create_project": {"name": "New", "identifier": "new"},
    "update_project": {"project": "child", "name": "Renamed"},
    "copy_project": {"source_project": "child", "name": "Copy", "identifier": "copy"},
}


@pytest.mark.parametrize("tool", list(AGENT_CALLS))
@reference_param
@pytest.mark.asyncio
async def test_the_agent_sees_the_parent_in_the_preview(mcp_call, tool: str, ref: str, expected: dict) -> None:
    result = await mcp_call(tool, {**AGENT_CALLS[tool], "parent": ref, "confirm": False})

    assert result.is_error is False, _text(result)
    assert json.loads(_text(result))["parent_target"] == expected
