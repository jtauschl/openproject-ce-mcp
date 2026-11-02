"""A write that names a parent work package by a bare number says which ticket it means.

Same rules as `test_work_package_display_id_guard.py`, applied to the parent: `create_work_package`, `create_subtask`,
`update_work_package` and the items of `bulk_create_work_packages` and `bulk_update_work_packages` refuse a bare
number on a record with a semantic display id, in preview and in confirm, unless `expect_parent_display_id` names the
ticket it resolves to. The requests go through the real client, resolver, adapter and service behind a recording
server; every refusal is asserted to have sent no write request.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
from _client_test_helpers import _write_enabled_settings
from _tools_test_helpers import FakeContext
from _work_package_target_helpers import (
    R1,
    RECORDS_BY_REFERENCE,
    form_response,
    project_response,
    work_package_record,
)

from openproject_ce_mcp.client import InvalidInputError, OpenProjectClient
from openproject_ce_mcp.config import Settings
from openproject_ce_mcp.presentation import _to_payload
from openproject_ce_mcp.tool_errors import ToolCallError, ToolInputError
from openproject_ce_mcp.tools import (
    bulk_create_work_packages,
    bulk_update_work_packages,
    create_subtask,
    create_work_package,
    update_work_package,
)

CHILD = work_package_record(500, "A-5", "The work package being moved", "New", 1, "Project A")
RECORDS = {**RECORDS_BY_REFERENCE, "A-5": CHILD}

_WP_PATH = re.compile(r"^/api/v3/work_packages/([^/]+)(/form)?$")
_PROJECT_FORM_PATH = re.compile(r"^/api/v3/projects/(\d+)/work_packages/form$")


class _Server:
    def __init__(self, records: dict[str, dict] | None = None) -> None:
        self.records = RECORDS if records is None else records
        self.gets: list[str] = []
        self.writes: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        wp = _WP_PATH.match(path)
        if wp is not None:
            ref, suffix = wp.group(1), wp.group(2)
            if suffix == "/form" and method == "POST":
                return form_response(request)
            if suffix is None and method == "GET":
                self.gets.append(ref)
                if ref not in self.records:
                    return httpx.Response(404, json={"message": "not found"}, request=request)
                return httpx.Response(200, json=self.records[ref], request=request)
            if suffix is None and method == "PATCH":
                self.writes.append(f"{method} {path}")
                return httpx.Response(200, json=self.records[ref], request=request)
        if path == "/api/v3/work_packages" and method == "POST":
            self.writes.append(f"{method} {path}")
            body = json.loads(request.content)
            created = work_package_record(777, "A-777", body["subject"], "New", 1, "Project A")
            return httpx.Response(201, json=created, request=request)
        if _PROJECT_FORM_PATH.match(path) and method == "POST":
            return form_response(request)
        if path in {"/api/v3/projects/demo", "/api/v3/projects/1"}:
            return project_response(request, 1, "demo", "Project A")
        if path == "/api/v3/projects/2":
            return project_response(request, 2, "proj", "Project B")
        if re.match(r"^/api/v3/projects/\d+/types$", path):
            return httpx.Response(200, json={"_embedded": {"elements": [{"id": 8, "name": "Task"}]}}, request=request)
        raise AssertionError(f"Unexpected request: {method} {request.url}")


async def _item_result(result: Any) -> Any:
    item = result.items[0]
    if not item.success:
        raise ToolCallError(item.error)
    return item.result


async def _create(ctx: Any, ref: str, expect: str | None, confirm: bool) -> Any:
    return await create_work_package(
        ctx, "demo", "Task", "Child", parent=ref, expect_parent_display_id=expect, confirm=confirm
    )


async def _subtask(ctx: Any, ref: str, expect: str | None, confirm: bool) -> Any:
    return await create_subtask(ctx, ref, "Task", "Child", expect_parent_display_id=expect, confirm=confirm)


async def _update(ctx: Any, ref: str, expect: str | None, confirm: bool) -> Any:
    return await update_work_package(ctx, "A-5", parent=ref, expect_parent_display_id=expect, confirm=confirm)


async def _bulk_create(ctx: Any, ref: str, expect: str | None, confirm: bool) -> Any:
    item = {"project": "demo", "type": "Task", "subject": "Child", "parent": ref, "expect_parent_display_id": expect}
    return await _item_result(await bulk_create_work_packages(ctx, [item], confirm=confirm))


async def _bulk_update(ctx: Any, ref: str, expect: str | None, confirm: bool) -> Any:
    item = {"work_package_id": "A-5", "parent": ref, "expect_parent_display_id": expect}
    return await _item_result(await bulk_update_work_packages(ctx, [item], confirm=confirm))


Call = Callable[[Any, str, str | None, bool], Awaitable[Any]]
TOOLS: dict[str, Call] = {
    "create_work_package": _create,
    "create_subtask": _subtask,
    "update_work_package": _update,
    "bulk_create_work_packages": _bulk_create,
    "bulk_update_work_packages": _bulk_update,
}
tool_param = pytest.mark.parametrize("call", list(TOOLS.values()), ids=list(TOOLS))
confirm_param = pytest.mark.parametrize("confirm", [False, True], ids=["preview", "confirm"])


async def _run(
    call: Call,
    ref: str,
    expect: str | None = None,
    *,
    confirm: bool = False,
    records: dict[str, dict] | None = None,
    settings: Settings | None = None,
) -> tuple[Any, _Server]:
    server = _Server(records)
    client = OpenProjectClient(settings or _write_enabled_settings(), transport=httpx.MockTransport(server.handler))
    try:
        return await call(FakeContext(client), ref, expect, confirm), server
    finally:
        await client.aclose()


async def _refused(
    call: Call,
    ref: str,
    expect: str | None = None,
    *,
    confirm: bool = False,
    records: dict[str, dict] | None = None,
    settings: Settings | None = None,
) -> tuple[str, _Server]:
    server = _Server(records)
    client = OpenProjectClient(settings or _write_enabled_settings(), transport=httpx.MockTransport(server.handler))
    try:
        with pytest.raises((ToolCallError, ToolInputError)) as caught:
            await call(FakeContext(client), ref, expect, confirm)
    finally:
        await client.aclose()
    assert server.writes == [], "a refused write must send no write request"
    return str(caught.value), server


@tool_param
@confirm_param
@pytest.mark.asyncio
async def test_a_bare_number_alone_is_refused_and_the_message_names_the_ticket_and_the_parameter(
    call: Call, confirm: bool
) -> None:
    message, server = await _refused(call, "436", confirm=confirm)

    assert "436 is A-1 (Project A). If you mean A-1, repeat with expect_parent_display_id 'A-1'" in message
    assert server.gets.count("436") == 1


@tool_param
@confirm_param
@pytest.mark.asyncio
async def test_an_expectation_naming_another_ticket_is_refused(call: Call, confirm: bool) -> None:
    message, _ = await _refused(call, "436", "PROJ-436", confirm=confirm)

    assert (
        "expect_parent_display_id 'PROJ-436' does not name the work package that 436 resolved to (A-1 (Project A))"
        in message
    )


@tool_param
@confirm_param
@pytest.mark.asyncio
async def test_an_expectation_naming_the_resolved_ticket_passes_without_a_second_lookup(
    call: Call, confirm: bool
) -> None:
    result, server = await _run(call, "436", "A-1", confirm=confirm)

    assert result is not None
    assert server.gets.count("436") == 1
    assert "A-1" not in server.gets
    assert bool(server.writes) is confirm


@tool_param
@pytest.mark.asyncio
async def test_a_display_reference_needs_no_expectation(call: Call) -> None:
    _, server = await _run(call, "PROJ-436", confirm=True)

    assert server.gets.count("PROJ-436") == 1


@tool_param
@pytest.mark.asyncio
async def test_an_expectation_is_checked_against_a_display_reference_too(call: Call) -> None:
    message, server = await _refused(call, "PROJ-436", "A-1", records={**RECORDS, "A-1": R1})

    assert "does not name the work package that PROJ-436 resolved to (PROJ-436 (Project B))" in message
    assert server.gets.count("A-1") == 1


@tool_param
@pytest.mark.asyncio
async def test_a_former_identifier_that_resolves_to_the_same_work_package_passes(call: Call) -> None:
    _, server = await _run(call, "436", "OLD-1", confirm=True, records={**RECORDS, "OLD-1": R1})

    assert server.gets.count("OLD-1") == 1


@tool_param
@pytest.mark.asyncio
async def test_an_expectation_that_does_not_exist_is_refused_with_the_resolver_hint(call: Call) -> None:
    message, _ = await _refused(call, "436", "NOPE-1")

    assert "expect_parent_display_id 'NOPE-1' does not name the work package that 436 resolved to" in message
    assert "'NOPE-1' was not found" in message


NUMERIC_DISPLAY_ID = work_package_record(436, "436", "Classic mode", "New", 1, "Project A")
NO_DISPLAY_ID = {key: value for key, value in R1.items() if key != "displayId"}
RECORD_WITHOUT_SEMANTIC_ID = pytest.mark.parametrize(
    "record", [NUMERIC_DISPLAY_ID, NO_DISPLAY_ID], ids=["numeric-display-id", "no-display-id-before-17.4"]
)


@tool_param
@RECORD_WITHOUT_SEMANTIC_ID
@pytest.mark.asyncio
async def test_a_parent_without_a_semantic_display_id_takes_a_bare_number_unchanged(call: Call, record: dict) -> None:
    _, server = await _run(call, "436", confirm=True, records={**RECORDS, "436": record})

    assert server.writes


@tool_param
@RECORD_WITHOUT_SEMANTIC_ID
@pytest.mark.asyncio
async def test_an_expectation_on_a_parent_without_a_semantic_display_id_is_refused(call: Call, record: dict) -> None:
    message, _ = await _refused(call, "436", "A-1", records={**RECORDS, "436": record})

    assert "Work package 436 has no semantic display id" in message
    assert "omit expect_parent_display_id" in message


@tool_param
@pytest.mark.asyncio
async def test_a_parent_outside_the_write_scope_gives_the_scope_denial_and_no_guard_text(call: Call) -> None:
    settings = dataclasses.replace(_write_enabled_settings(), write_projects=("1",), read_projects=("*",))

    message, _ = await _refused(call, "PROJ-436", settings=settings)

    assert "OPENPROJECT_WRITE_PROJECTS" in message
    assert "expect_parent_display_id" not in message
    assert "Project B" not in message


@tool_param
@pytest.mark.asyncio
async def test_a_hidden_project_and_subject_are_not_named_in_a_guard_message(call: Call) -> None:
    settings = dataclasses.replace(_write_enabled_settings(), hide_work_package_fields=("project", "subject"))

    required, _ = await _refused(call, "436", settings=settings)
    mismatch, _ = await _refused(call, "436", "PROJ-436", settings=settings)

    assert "436 is A-1." in required
    for message in (required, mismatch):
        assert "Project A" not in message
        assert R1["subject"] not in message


@tool_param
@pytest.mark.asyncio
async def test_a_hidden_display_id_drops_the_requirement_and_refuses_an_expectation_before_any_fetch(
    call: Call,
) -> None:
    settings = dataclasses.replace(_write_enabled_settings(), hide_work_package_fields=("display_id",))

    _, server = await _run(call, "436", confirm=True, settings=settings)
    message, refused = await _refused(call, "436", "A-1", settings=settings)

    assert server.writes
    assert "expect_parent_display_id cannot be used: the display_id field is hidden" in message
    assert "436" not in refused.gets


@tool_param
@pytest.mark.parametrize("bad", ["A-007", "42", " ", "A 1"])
@pytest.mark.asyncio
async def test_an_expectation_that_is_not_a_display_id_is_refused_at_the_tool_boundary(call: Call, bad: str) -> None:
    server = _Server()
    client = OpenProjectClient(_write_enabled_settings(), transport=httpx.MockTransport(server.handler))
    try:
        with pytest.raises(ValueError, match="expect_parent_display_id must be a display id like 'PROJ-51'"):
            await call(FakeContext(client), "436", bad, False)
    finally:
        await client.aclose()

    assert server.gets == []


@tool_param
@pytest.mark.asyncio
async def test_an_expectation_is_trimmed(call: Call) -> None:
    _, server = await _run(call, "436", "  A-1 ")

    assert server.gets.count("436") == 1


class TestExpectationWithoutAParent:
    """An expectation with no parent to check is an error, never dropped silently."""

    @pytest.mark.asyncio
    async def test_create_work_package_without_a_parent(self) -> None:
        server = _Server()
        client = OpenProjectClient(_write_enabled_settings(), transport=httpx.MockTransport(server.handler))
        try:
            with pytest.raises(InvalidInputError, match="expect_parent_display_id was given but parent names no"):
                await client.work_package.create(
                    project="demo", type="Task", subject="Child", expect_parent_display_id="A-1"
                )
        finally:
            await client.aclose()

        assert server.gets == []

    @pytest.mark.parametrize("parent", [None, "none"], ids=["no-parent", "clear"])
    @pytest.mark.asyncio
    async def test_update_work_package_without_a_parent_to_check(self, parent: str | None) -> None:
        server = _Server()
        client = OpenProjectClient(_write_enabled_settings(), transport=httpx.MockTransport(server.handler))
        try:
            with pytest.raises(
                (ToolCallError, ToolInputError), match="expect_parent_display_id was given but parent names no"
            ):
                await update_work_package(
                    FakeContext(client),
                    "A-5",
                    subject="Renamed",
                    parent=parent,
                    expect_parent_display_id="A-1",
                    confirm=True,
                )
        finally:
            await client.aclose()

        assert server.gets == []
        assert server.writes == []

    @pytest.mark.parametrize("tool", [bulk_create_work_packages, bulk_update_work_packages])
    @pytest.mark.asyncio
    async def test_a_bulk_item_without_a_parent_fails_alone(self, tool: Any) -> None:
        server = _Server()
        client = OpenProjectClient(_write_enabled_settings(), transport=httpx.MockTransport(server.handler))
        creating = tool is bulk_create_work_packages
        base = {"project": "demo", "type": "Task"} if creating else {"work_package_id": "A-5"}
        items = [
            {**base, "subject": "Alone", "expect_parent_display_id": "A-1"},
            {**base, "subject": "Fine"},
        ]
        try:
            result = await tool(FakeContext(client), items, confirm=True)
        finally:
            await client.aclose()

        assert [item.success for item in result.items] == [False, True]
        assert "expect_parent_display_id was given but parent names no" in (result.items[0].error or "")
        assert len(server.writes) == 1

    @pytest.mark.asyncio
    async def test_an_empty_expectation_from_a_direct_client_call_names_no_ticket(self) -> None:
        server = _Server()
        client = OpenProjectClient(_write_enabled_settings(), transport=httpx.MockTransport(server.handler))
        try:
            with pytest.raises(InvalidInputError, match="expect_parent_display_id must be a display id like 'PROJ-51'"):
                await client.work_package.update(
                    work_package_id="A-5", subject="x", parent_work_package_id="436", expect_parent_display_id=""
                )
        finally:
            await client.aclose()

        assert server.gets == []

    @pytest.mark.asyncio
    async def test_clearing_the_parent_without_an_expectation_stays_valid(self) -> None:
        result, server = await _run(_update, "none", confirm=True)

        assert result.state == "confirmed"
        assert len(server.writes) == 1


class TestUpdateGuardsTargetAndParentIndependently:
    @pytest.mark.asyncio
    async def test_each_reference_is_checked_against_its_own_expectation(self) -> None:
        server = _Server()
        client = OpenProjectClient(_write_enabled_settings(), transport=httpx.MockTransport(server.handler))
        try:
            result = await update_work_package(
                FakeContext(client),
                "436",
                parent="PROJ-436",
                expect_display_id="A-1",
                confirm=False,
            )
        finally:
            await client.aclose()

        payload = _to_payload(result)
        assert payload["target"]["display_id"] == "A-1"
        assert payload["parent_target"]["display_id"] == "PROJ-436"

    @pytest.mark.asyncio
    async def test_the_target_expectation_does_not_stand_in_for_the_parent_expectation(self) -> None:
        server = _Server()
        client = OpenProjectClient(_write_enabled_settings(), transport=httpx.MockTransport(server.handler))
        try:
            with pytest.raises((ToolCallError, ToolInputError)) as caught:
                await update_work_package(
                    FakeContext(client), "436", parent="436", expect_display_id="A-1", confirm=True
                )
        finally:
            await client.aclose()

        assert "repeat with expect_parent_display_id 'A-1'" in str(caught.value)
        assert server.writes == []

    @pytest.mark.asyncio
    async def test_the_parent_expectation_does_not_stand_in_for_the_target_expectation(self) -> None:
        server = _Server()
        client = OpenProjectClient(_write_enabled_settings(), transport=httpx.MockTransport(server.handler))
        try:
            with pytest.raises((ToolCallError, ToolInputError)) as caught:
                await update_work_package(
                    FakeContext(client), "436", parent="436", expect_parent_display_id="A-1", confirm=True
                )
        finally:
            await client.aclose()

        assert "repeat with expect_display_id 'A-1'" in str(caught.value)
        assert server.writes == []
