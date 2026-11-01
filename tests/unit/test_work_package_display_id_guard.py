"""A confirmed write that names a work package by a bare number says which ticket it means.

A bare number is the internal id, `PROJ-436` is another ticket. On a record with a semantic display id the
writes `update_work_package`, `delete_work_package`, `add_work_package_comment` and each item of
`bulk_update_work_packages` are refused, in preview and in confirm, unless `expect_display_id` names the
ticket the number resolves to. The requests go through the real client, resolver, adapter and service behind
a recording server; every refusal is also asserted to have sent no write request.
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
from _work_package_target_helpers import R1, R2, form_response, project_response, work_package_record

from openproject_ce_mcp.client import InvalidInputError, OpenProjectClient
from openproject_ce_mcp.config import Settings
from openproject_ce_mcp.presentation import _to_payload
from openproject_ce_mcp.tool_errors import ToolCallError, ToolInputError
from openproject_ce_mcp.tools import (
    add_work_package_comment,
    bulk_update_work_packages,
    delete_work_package,
    update_work_package,
)

_WP_PATH = re.compile(r"^/api/v3/work_packages/([^/]+)(/form|/activities)?$")
_PROJECT_FORM_PATH = re.compile(r"^/api/v3/projects/(\d+)/work_packages/form$")

# The bare number 436 is the internal id of A-1 in project A; PROJ-436 is another ticket in project B.
RECORDS = {"436": R1, "PROJ-436": R2}


class _Server:
    def __init__(self, records: dict[str, dict]) -> None:
        self.records = records
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
            self.writes.append(f"{method} {path}")
            if suffix == "/activities":
                activity = {"id": 77, "_type": "Activity", "version": 3, "comment": {"raw": "hello"}, "_links": {}}
                return httpx.Response(201, json=activity, request=request)
            if method == "DELETE":
                return httpx.Response(204, request=request)
            return httpx.Response(200, json=self.records[ref], request=request)
        if _PROJECT_FORM_PATH.match(path) and method == "POST":
            return form_response(request)
        if path in {"/api/v3/projects/demo", "/api/v3/projects/1"}:
            return project_response(request, 1, "demo", "Project A")
        if path == "/api/v3/projects/2":
            return project_response(request, 2, "proj", "Project B")
        raise AssertionError(f"Unexpected request: {method} {request.url}")


async def _comment(ctx: Any, ref: str, expect: str | None, confirm: bool) -> Any:
    return await add_work_package_comment(ctx, ref, "hello", expect_display_id=expect, confirm=confirm)


async def _update(ctx: Any, ref: str, expect: str | None, confirm: bool) -> Any:
    return await update_work_package(ctx, ref, subject="Renamed", expect_display_id=expect, confirm=confirm)


async def _delete(ctx: Any, ref: str, expect: str | None, confirm: bool) -> Any:
    return await delete_work_package(ctx, ref, expect_display_id=expect, confirm=confirm)


Call = Callable[[Any, str, str | None, bool], Awaitable[Any]]
TOOLS: dict[str, Call] = {
    "add_work_package_comment": _comment,
    "update_work_package": _update,
    "delete_work_package": _delete,
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
    server = _Server(RECORDS if records is None else records)
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
    code: str = "VALIDATION_FAILED",
) -> tuple[str, _Server]:
    server = _Server(RECORDS if records is None else records)
    client = OpenProjectClient(settings or _write_enabled_settings(), transport=httpx.MockTransport(server.handler))
    try:
        with pytest.raises((ToolCallError, ToolInputError)) as caught:
            await call(FakeContext(client), ref, expect, confirm)
    finally:
        await client.aclose()
    assert f"[{code}]" in str(caught.value)
    assert server.writes == [], "a refused write must send no write request"
    return str(caught.value), server


@tool_param
@confirm_param
@pytest.mark.asyncio
async def test_a_bare_number_alone_is_refused_and_the_message_names_the_ticket_it_resolved_to(
    call: Call, confirm: bool
) -> None:
    message, server = await _refused(call, "436", confirm=confirm)

    assert "436 is A-1 (Project A)." in message
    assert "expect_display_id 'A-1'" in message
    assert server.gets == ["436"]


@tool_param
@confirm_param
@pytest.mark.asyncio
async def test_an_expectation_naming_another_ticket_is_refused(call: Call, confirm: bool) -> None:
    message, _ = await _refused(call, "436", "PROJ-436", confirm=confirm)

    assert (
        "expect_display_id 'PROJ-436' does not name the work package that 436 resolved to (A-1 (Project A))" in message
    )


@tool_param
@confirm_param
@pytest.mark.asyncio
async def test_an_expectation_naming_the_resolved_ticket_passes_without_a_second_lookup(
    call: Call, confirm: bool
) -> None:
    result, server = await _run(call, "436", "A-1", confirm=confirm)

    assert _to_payload(result)["target"]["display_id"] == "A-1"
    assert server.gets == ["436"]


@tool_param
@pytest.mark.asyncio
async def test_a_display_reference_needs_no_expectation(call: Call) -> None:
    result, server = await _run(call, "PROJ-436", confirm=True)

    assert _to_payload(result)["target"]["id"] == 9001
    assert server.gets == ["PROJ-436"]


@tool_param
@pytest.mark.asyncio
async def test_an_expectation_is_checked_against_a_display_reference_too(call: Call) -> None:
    records = {**RECORDS, "A-1": R1}

    message, server = await _refused(call, "PROJ-436", "A-1", records=records)

    assert "does not name the work package that PROJ-436 resolved to (PROJ-436 (Project B))" in message
    assert server.gets == ["PROJ-436", "A-1"]


@tool_param
@pytest.mark.asyncio
async def test_a_former_identifier_that_resolves_to_the_same_work_package_passes(call: Call) -> None:
    records = {**RECORDS, "OLD-1": R1}

    result, server = await _run(call, "436", "OLD-1", confirm=True, records=records)

    assert result.state == "confirmed"
    assert server.gets == ["436", "OLD-1"]


@tool_param
@pytest.mark.asyncio
async def test_an_expectation_that_does_not_exist_is_refused_with_the_resolver_hint(call: Call) -> None:
    message, _ = await _refused(call, "436", "NOPE-1")

    assert "expect_display_id 'NOPE-1' does not name the work package that 436 resolved to" in message
    assert "'NOPE-1' was not found" in message


NUMERIC_DISPLAY_ID = work_package_record(436, "436", "Classic mode", "New", 1, "Project A")
NO_DISPLAY_ID = {key: value for key, value in R1.items() if key != "displayId"}


@tool_param
@pytest.mark.parametrize(
    "record",
    [NUMERIC_DISPLAY_ID, NO_DISPLAY_ID],
    ids=["numeric-display-id", "no-display-id-before-17.4"],
)
@pytest.mark.asyncio
async def test_a_record_without_a_semantic_display_id_takes_a_bare_number_unchanged(call: Call, record: dict) -> None:
    result, _ = await _run(call, "436", confirm=True, records={"436": record})

    assert result.state == "confirmed"


@tool_param
@pytest.mark.parametrize(
    "record",
    [NUMERIC_DISPLAY_ID, NO_DISPLAY_ID],
    ids=["numeric-display-id", "no-display-id-before-17.4"],
)
@pytest.mark.asyncio
async def test_an_expectation_on_a_record_without_a_semantic_display_id_is_refused(call: Call, record: dict) -> None:
    message, _ = await _refused(call, "436", "A-1", records={"436": record})

    assert "Work package 436 has no semantic display id" in message


@tool_param
@pytest.mark.asyncio
async def test_an_out_of_scope_work_package_gives_the_scope_denial_and_no_guard_text(call: Call) -> None:
    settings = dataclasses.replace(_write_enabled_settings(), write_projects=("2",))

    message, _ = await _refused(call, "436", settings=settings, code="PROJECT_SCOPE_DENIED")

    assert "OPENPROJECT_WRITE_PROJECTS" in message
    assert "A-1" not in message
    assert "Project A" not in message


@tool_param
@pytest.mark.asyncio
async def test_a_hidden_project_and_subject_are_not_named_in_a_guard_message(call: Call) -> None:
    settings = dataclasses.replace(_write_enabled_settings(), hide_work_package_fields=("project", "subject"))

    required, _ = await _refused(call, "436", settings=settings)
    mismatch, _ = await _refused(call, "436", "PROJ-436", settings=settings)

    assert "436 is A-1." in required
    assert "A-1" in mismatch
    for message in (required, mismatch):
        assert "Project A" not in message
        assert R1["subject"] not in message


@tool_param
@pytest.mark.asyncio
async def test_a_hidden_display_id_drops_the_requirement_and_refuses_an_expectation_before_any_fetch(
    call: Call,
) -> None:
    settings = dataclasses.replace(_write_enabled_settings(), hide_work_package_fields=("display_id",))

    result, _ = await _run(call, "436", confirm=True, settings=settings)
    message, server = await _refused(call, "436", "A-1", settings=settings)

    assert result.state == "confirmed"
    assert "the display_id field is hidden by OPENPROJECT_HIDE_WORK_PACKAGE_FIELDS" in message
    assert "A-1" not in message.replace("expect_display_id", "")
    assert server.gets == []


NO_PROJECT_LINK = {"id": 436, "displayId": "A-1", "lockVersion": 1, "_links": {"self": {"href": "x"}}}


@tool_param
@pytest.mark.asyncio
async def test_a_record_without_a_project_link_is_a_server_error_not_a_scope_denial(call: Call) -> None:
    message, _ = await _refused(call, "436", "A-1", records={"436": NO_PROJECT_LINK}, code="OPENPROJECT_UNAVAILABLE")

    assert "missing a project link" in message


@tool_param
@pytest.mark.parametrize("bad", ["A-007", "42", " ", "A 1"])
@pytest.mark.asyncio
async def test_an_expectation_that_is_not_a_display_id_is_refused_at_the_tool_boundary(call: Call, bad: str) -> None:
    server = _Server(RECORDS)
    client = OpenProjectClient(_write_enabled_settings(), transport=httpx.MockTransport(server.handler))
    try:
        with pytest.raises(ValueError, match="expect_display_id must be a display id like 'PROJ-51'"):
            await call(FakeContext(client), "436", bad, False)
    finally:
        await client.aclose()

    assert server.gets == []


@pytest.mark.asyncio
async def test_a_numeric_expectation_from_a_direct_client_call_names_no_ticket() -> None:
    server = _Server(RECORDS)
    client = OpenProjectClient(_write_enabled_settings(), transport=httpx.MockTransport(server.handler))
    try:
        with pytest.raises(InvalidInputError, match="expect_display_id must be a display id like 'PROJ-51'"):
            await client.work_package.update(work_package_id="436", subject="Renamed", expect_display_id="436")
    finally:
        await client.aclose()

    assert server.gets == []
    assert server.writes == []


@tool_param
@pytest.mark.asyncio
async def test_an_expectation_is_trimmed(call: Call) -> None:
    result, server = await _run(call, "436", "  A-1 ")

    assert _to_payload(result)["target"]["id"] == 436
    assert server.gets == ["436"]


class TestBulkUpdate:
    ITEMS = [
        {"work_package_id": "436", "subject": "Alone"},
        {"work_package_id": "436", "subject": "Named", "expect_display_id": "A-1"},
        {"work_package_id": "PROJ-436", "subject": "Display reference"},
    ]

    async def _bulk(self, items: list[dict], *, confirm: bool) -> tuple[Any, _Server]:
        server = _Server(RECORDS)
        client = OpenProjectClient(_write_enabled_settings(), transport=httpx.MockTransport(server.handler))
        try:
            return await bulk_update_work_packages(FakeContext(client), items, confirm=confirm), server
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_the_preview_flags_the_refused_item_and_leaves_its_siblings_ready(self) -> None:
        result, server = await self._bulk(self.ITEMS, confirm=False)

        assert [item.success for item in result.items] == [False, True, True]
        assert result.failed == 1
        assert result.requires_confirmation is False
        assert result.items[0].result is None
        assert "436 is A-1 (Project A)." in (result.items[0].error or "")
        assert server.writes == []

    @pytest.mark.asyncio
    async def test_the_confirm_writes_only_the_eligible_items_and_every_succeeded_item_names_its_ticket(
        self,
    ) -> None:
        result, server = await self._bulk(self.ITEMS, confirm=True)

        assert [item.success for item in result.items] == [False, True, True]
        assert result.confirmed is False
        assert server.writes == ["PATCH /api/v3/work_packages/436", "PATCH /api/v3/work_packages/PROJ-436"]
        succeeded = [_to_payload(item.result)["target"] for item in result.items if item.success]
        assert [target["display_id"] for target in succeeded] == ["A-1", "PROJ-436"]

    @pytest.mark.asyncio
    async def test_an_item_with_a_malformed_expectation_is_refused_with_its_index(self) -> None:
        server = _Server(RECORDS)
        client = OpenProjectClient(_write_enabled_settings(), transport=httpx.MockTransport(server.handler))
        items = [{"work_package_id": "436", "subject": "One", "expect_display_id": "42"}]
        try:
            with pytest.raises(ValueError, match=r"items\[0\]\.expect_display_id must be a display id"):
                await bulk_update_work_packages(FakeContext(client), items, confirm=False)
        finally:
            await client.aclose()


@pytest.mark.asyncio
async def test_an_expectation_alone_is_not_a_change() -> None:
    server = _Server(RECORDS)
    client = OpenProjectClient(_write_enabled_settings(), transport=httpx.MockTransport(server.handler))
    try:
        with pytest.raises(ValueError, match="At least one field to update is required"):
            await update_work_package(FakeContext(client), "436", expect_display_id="A-1")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_the_delete_preview_keeps_the_formattable_text_limit() -> None:
    long_description = {"format": "markdown", "raw": "x" * 5000, "html": "<p>" + "x" * 5000 + "</p>"}
    records = {"436": {**R1, "description": long_description}}

    result, _ = await _run(_delete, "436", "A-1", records=records)

    assert result.result is not None
    assert result.result.description_truncated is True
    assert json.dumps(result.result.description).count("x") <= 1_300
