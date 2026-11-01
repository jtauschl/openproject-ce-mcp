"""`update_work_package` and `bulk_update_work_packages` name the parent their `parent` reference resolved to.

The bare number `436` resolves to one work package, the display reference `PROJ-436` to another; the
work package being updated is a third one. `parent_target` must name the record each reference actually
resolved to, in the preview as well as in the result, next to `target` (the work package being updated).
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
from _client_test_helpers import _write_enabled_settings, started_client
from _tools_test_helpers import FakeContext
from _work_package_target_helpers import (
    EXPECTED_R1,
    EXPECTED_R2,
    RECORDS_BY_REFERENCE,
    REFERENCES,
    form_response,
    project_response,
    work_package_record,
)
from mcp import types
from mcp.client import Client

import openproject_ce_mcp.tools_runtime as tools_runtime
from openproject_ce_mcp import tools, tools_work_packages
from openproject_ce_mcp.client import OpenProjectClient
from openproject_ce_mcp.config import Settings
from openproject_ce_mcp.presentation import _to_payload
from openproject_ce_mcp.strict_mcpserver import StrictMCPServer
from openproject_ce_mcp.tools import bulk_update_work_packages, update_work_package

CHILD = work_package_record(500, "A-5", "The work package being moved", "New", 1, "Project A")
RECORDS = {**RECORDS_BY_REFERENCE, "500": CHILD}
EXPECTED_CHILD = {
    "id": 500,
    "display_id": "A-5",
    "project": "Project A",
    "subject": "The work package being moved",
    "status": "New",
}

_WP_PATH = re.compile(r"^/api/v3/work_packages/([^/]+)(/form)?$")


class _Server:
    def __init__(self) -> None:
        self.gets: list[str] = []
        self.forms: list[dict] = []
        self.writes: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        wp = _WP_PATH.match(path)
        if wp is not None:
            ref, suffix = wp.group(1), wp.group(2)
            if suffix == "/form" and method == "POST":
                self.forms.append(json.loads(request.content))
                return form_response(request)
            if suffix is None and method == "GET":
                self.gets.append(ref)
                return httpx.Response(200, json=RECORDS[ref], request=request)
            if suffix is None and method == "PATCH":
                self.writes.append(f"{method} {path}")
                return httpx.Response(200, json=RECORDS[ref], request=request)
        if path in {"/api/v3/projects/demo", "/api/v3/projects/1"}:
            return project_response(request, 1, "demo", "Project A")
        if path == "/api/v3/projects/2":
            return project_response(request, 2, "proj", "Project B")
        raise AssertionError(f"Unexpected request: {method} {request.url}")


def _client(server: _Server, settings: Settings | None = None) -> OpenProjectClient:
    return OpenProjectClient(settings or _write_enabled_settings(), transport=httpx.MockTransport(server.handler))


async def _update(ctx: Any, parent: str, confirm: bool) -> Any:
    return await update_work_package(ctx, "500", parent=parent, confirm=confirm)


async def _bulk_update(ctx: Any, parent: str, confirm: bool) -> Any:
    result = await bulk_update_work_packages(ctx, [{"work_package_id": "500", "parent": parent}], confirm=confirm)
    assert result.failed == 0, result.items[0].error
    return result.items[0].result


Call = Callable[[Any, str, bool], Awaitable[Any]]
TOOLS: dict[str, Call] = {"update_work_package": _update, "bulk_update_work_packages": _bulk_update}
tool_param = pytest.mark.parametrize("call", list(TOOLS.values()), ids=list(TOOLS))
reference_param = pytest.mark.parametrize(("ref", "expected"), REFERENCES, ids=["bare-number", "display-reference"])
confirm_param = pytest.mark.parametrize("confirm", [False, True], ids=["preview", "confirmed"])


async def _run(call: Call, parent: str, *, confirm: bool, settings: Settings | None = None) -> tuple[Any, _Server]:
    server = _Server()
    client = _client(server, settings)
    try:
        return await call(FakeContext(client), parent, confirm), server
    finally:
        await client.aclose()


@tool_param
@reference_param
@confirm_param
@pytest.mark.asyncio
async def test_the_parent_is_named_as_the_record_its_reference_resolved_to(
    call: Call, ref: str, expected: dict, confirm: bool
) -> None:
    result, server = await _run(call, ref, confirm=confirm)

    payload = _to_payload(result)
    assert payload["parent_target"] == expected
    assert payload["target"] == EXPECTED_CHILD
    assert server.gets.count(ref) == 1
    assert (len(server.writes) == 1) is confirm


@tool_param
@pytest.mark.parametrize("parent", ["none", None], ids=["clear", "unchanged"])
@pytest.mark.asyncio
async def test_no_parent_target_unless_a_parent_is_set(call: Call, parent: str | None) -> None:
    async def run(ctx: Any, _parent: str, confirm: bool) -> Any:
        if call is _update:
            return await update_work_package(ctx, "500", parent=parent, subject="Renamed", confirm=confirm)
        item = {"work_package_id": "500", "subject": "Renamed", **({} if parent is None else {"parent": parent})}
        return (await bulk_update_work_packages(ctx, [item], confirm=confirm)).items[0].result

    result, server = await _run(run, "", confirm=False)

    assert result.parent_target is None
    assert server.gets == ["500"]


@pytest.mark.asyncio
async def test_each_bulk_item_names_its_own_parent() -> None:
    server = _Server()
    client = _client(server)
    items = [
        {"work_package_id": "500", "parent": "436"},
        {"work_package_id": "500", "parent": "PROJ-436"},
    ]

    result = await bulk_update_work_packages(FakeContext(client), items, confirm=False)
    await client.aclose()

    assert [_to_payload(item.result)["parent_target"] for item in result.items] == [EXPECTED_R1, EXPECTED_R2]


@pytest.mark.asyncio
async def test_a_parent_target_can_be_selected_in_a_bulk_result() -> None:
    server = _Server()
    client = _client(server)

    result = await bulk_update_work_packages(
        FakeContext(client), [{"work_package_id": "500", "parent": "PROJ-436"}], select=["parent_target"], confirm=False
    )
    await client.aclose()

    assert _to_payload(result, select=frozenset({"parent_target"}))["items"][0]["result"] == {
        "parent_target": EXPECTED_R2
    }


@tool_param
@pytest.mark.asyncio
async def test_hidden_fields_are_absent_from_the_serialized_parent_target(call: Call) -> None:
    settings = dataclasses.replace(_write_enabled_settings(), hide_work_package_fields=("status", "subject"))

    result, _ = await _run(call, "PROJ-436", confirm=False, settings=settings)

    assert _to_payload(result)["parent_target"] == {"id": 9001, "display_id": "PROJ-436", "project": "Project B"}


@pytest.mark.asyncio
async def test_a_parent_outside_the_write_scope_is_refused_and_named_nowhere() -> None:
    settings = dataclasses.replace(_write_enabled_settings(), write_projects=("1",), read_projects=("*",))
    server = _Server()
    client = _client(server, settings)
    try:
        with pytest.raises(Exception, match="OPENPROJECT_WRITE_PROJECTS"):
            await update_work_package(FakeContext(client), "500", parent="PROJ-436", confirm=False)
    finally:
        await client.aclose()

    assert server.writes == []


@pytest.fixture
def mcp_call() -> Callable[[str, dict], Awaitable[types.CallToolResult]]:
    server_state = _Server()
    settings = dataclasses.replace(_write_enabled_settings())

    @asynccontextmanager
    async def lifespan(_):
        client = await started_client(settings, server_state.handler, [(1, "demo", "Demo")])
        try:
            yield SimpleNamespace(client=client)
        finally:
            await client.aclose()

    server = StrictMCPServer("test", lifespan=lifespan)
    tools_runtime.register_selected_tools(
        server,
        names=[
            tools_work_packages.update_work_package.__name__,
            tools_work_packages.bulk_update_work_packages.__name__,
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


@pytest.mark.parametrize(("ref", "expected"), REFERENCES, ids=["bare-number", "display-reference"])
@pytest.mark.asyncio
async def test_the_agent_sees_the_parent_in_the_update_preview(mcp_call, ref: str, expected: dict) -> None:
    result = await mcp_call("update_work_package", {"work_package_id": "500", "parent": ref, "confirm": False})

    assert result.is_error is False, _text(result)
    assert json.loads(_text(result))["parent_target"] == expected


@pytest.mark.parametrize(("ref", "expected"), REFERENCES, ids=["bare-number", "display-reference"])
@pytest.mark.asyncio
async def test_the_agent_sees_the_parent_in_the_bulk_preview(mcp_call, ref: str, expected: dict) -> None:
    result = await mcp_call(
        "bulk_update_work_packages", {"items": [{"work_package_id": "500", "parent": ref}], "confirm": False}
    )

    assert result.is_error is False, _text(result)
    assert json.loads(_text(result))["items"][0]["result"]["parent_target"] == expected
