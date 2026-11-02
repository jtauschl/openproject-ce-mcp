"""A confirmed write that names a work package by a bare number says which ticket it means, on every write tool.

Same rules as `test_work_package_display_id_guard.py`, for the writes outside the work package domain: on a
record with a semantic display id a bare number is refused, in preview and in confirm, unless
`expect_display_id` names the ticket the number resolves to. The requests go through the real client,
resolver, adapter and service behind a recording server; every refusal is asserted to have sent no write
request.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest
from _work_package_target_helpers import R1, work_package_record
from _work_package_write_harness import (
    RECORDS_BY_REFERENCE,
    TOOLS,
    Call,
    _run,
    _Server,
    _settings,
)

from openproject_ce_mcp.presentation import _to_payload
from openproject_ce_mcp.tool_errors import ToolCallError, ToolInputError

GUARDED = (
    "create_work_package_attachment",
    "set_work_package_watcher_add",
    "set_work_package_watcher_remove",
)
tool_param = pytest.mark.parametrize("call", [TOOLS[name] for name in GUARDED], ids=list(GUARDED))
confirm_param = pytest.mark.parametrize("confirm", [False, True], ids=["preview", "confirm"])


async def _refused(
    call: Call,
    ref: str,
    tmp_path: Path,
    expect: str | None = None,
    *,
    confirm: bool = False,
    records: dict[str, dict[str, Any]] | None = None,
    settings: Any = None,
    code: str = "VALIDATION_FAILED",
) -> tuple[str, _Server]:
    server = _Server(records)
    with pytest.raises((ToolCallError, ToolInputError)) as caught:
        await _run(call, ref, tmp_path, confirm=confirm, expect=expect, settings=settings, server=server)
    assert f"[{code}]" in str(caught.value)
    assert server.writes == [], "a refused write must send no write request"
    return str(caught.value), server


@tool_param
@confirm_param
@pytest.mark.asyncio
async def test_a_bare_number_alone_is_refused_and_the_message_names_the_ticket_it_resolved_to(
    call: Call, confirm: bool, tmp_path: Path
) -> None:
    message, server = await _refused(call, "436", tmp_path, confirm=confirm)

    assert "436 is A-1 (Project A)." in message
    assert "expect_display_id 'A-1'" in message
    assert server.work_package_gets == ["436"]


@tool_param
@confirm_param
@pytest.mark.asyncio
async def test_an_expectation_naming_another_ticket_is_refused(call: Call, confirm: bool, tmp_path: Path) -> None:
    message, _ = await _refused(call, "436", tmp_path, "PROJ-436", confirm=confirm)

    assert (
        "expect_display_id 'PROJ-436' does not name the work package that 436 resolved to (A-1 (Project A))" in message
    )


@tool_param
@confirm_param
@pytest.mark.asyncio
async def test_an_expectation_naming_the_resolved_ticket_passes_without_a_second_lookup(
    call: Call, confirm: bool, tmp_path: Path
) -> None:
    result, server = await _run(call, "436", tmp_path, confirm=confirm, expect="A-1")

    assert _to_payload(result)["target"]["display_id"] == "A-1"
    assert server.work_package_gets == ["436"]
    assert bool(server.writes) is confirm


@tool_param
@pytest.mark.asyncio
async def test_a_display_reference_needs_no_expectation(call: Call, tmp_path: Path) -> None:
    result, server = await _run(call, "PROJ-436", tmp_path, confirm=True)

    assert _to_payload(result)["target"]["id"] == 9001
    assert server.work_package_gets == ["PROJ-436"]


@tool_param
@pytest.mark.asyncio
async def test_an_expectation_is_checked_against_a_display_reference_too(call: Call, tmp_path: Path) -> None:
    records = {**RECORDS_BY_REFERENCE, "A-1": R1}

    message, server = await _refused(call, "PROJ-436", tmp_path, "A-1", records=records)

    assert "does not name the work package that PROJ-436 resolved to (PROJ-436 (Project B))" in message
    assert server.work_package_gets == ["PROJ-436", "A-1"]


@tool_param
@pytest.mark.asyncio
async def test_a_former_identifier_that_resolves_to_the_same_work_package_passes(call: Call, tmp_path: Path) -> None:
    server = _Server({**RECORDS_BY_REFERENCE, "OLD-1": R1})

    result, _ = await _run(call, "436", tmp_path, confirm=True, expect="OLD-1", server=server)

    assert result.state == "confirmed"
    assert server.work_package_gets == ["436", "OLD-1"]


@tool_param
@pytest.mark.asyncio
async def test_an_expectation_that_does_not_exist_is_refused_with_the_resolver_hint(call: Call, tmp_path: Path) -> None:
    message, _ = await _refused(call, "436", tmp_path, "NOPE-1")

    assert "expect_display_id 'NOPE-1' does not name the work package that 436 resolved to" in message
    assert "'NOPE-1' was not found" in message


NUMERIC_DISPLAY_ID = work_package_record(436, "436", "Classic mode", "New", 1, "Project A")
NO_DISPLAY_ID = {key: value for key, value in R1.items() if key != "displayId"}
RECORD_WITHOUT_SEMANTIC_ID = pytest.mark.parametrize(
    "record", [NUMERIC_DISPLAY_ID, NO_DISPLAY_ID], ids=["numeric-display-id", "no-display-id-before-17.4"]
)


@tool_param
@RECORD_WITHOUT_SEMANTIC_ID
@pytest.mark.asyncio
async def test_a_record_without_a_semantic_display_id_takes_a_bare_number_unchanged(
    call: Call, record: dict, tmp_path: Path
) -> None:
    result, _ = await _run(call, "436", tmp_path, confirm=True, server=_Server({"436": record}))

    assert result.state == "confirmed"


@tool_param
@RECORD_WITHOUT_SEMANTIC_ID
@pytest.mark.asyncio
async def test_an_expectation_on_a_record_without_a_semantic_display_id_is_refused(
    call: Call, record: dict, tmp_path: Path
) -> None:
    message, _ = await _refused(call, "436", tmp_path, "A-1", records={"436": record})

    assert "Work package 436 has no semantic display id" in message


@tool_param
@pytest.mark.asyncio
async def test_an_out_of_scope_work_package_gives_the_scope_denial_and_no_guard_text(
    call: Call, tmp_path: Path
) -> None:
    settings = dataclasses.replace(_settings(tmp_path), write_projects=("2",))

    message, _ = await _refused(call, "436", tmp_path, settings=settings, code="PROJECT_SCOPE_DENIED")

    assert "OPENPROJECT_WRITE_PROJECTS" in message
    assert "A-1" not in message
    assert "Project A" not in message


@tool_param
@pytest.mark.asyncio
async def test_a_hidden_project_and_subject_are_not_named_in_a_guard_message(call: Call, tmp_path: Path) -> None:
    settings = dataclasses.replace(_settings(tmp_path), hide_work_package_fields=("project", "subject"))

    required, _ = await _refused(call, "436", tmp_path, settings=settings)
    mismatch, _ = await _refused(call, "436", tmp_path, "PROJ-436", settings=settings)

    assert "436 is A-1." in required
    assert "A-1" in mismatch
    for message in (required, mismatch):
        assert "Project A" not in message
        assert R1["subject"] not in message


@tool_param
@pytest.mark.asyncio
async def test_a_hidden_display_id_drops_the_requirement_and_refuses_an_expectation_before_any_fetch(
    call: Call, tmp_path: Path
) -> None:
    settings = dataclasses.replace(_settings(tmp_path), hide_work_package_fields=("display_id",))

    result, _ = await _run(call, "436", tmp_path, confirm=True, settings=settings)
    message, server = await _refused(call, "436", tmp_path, "A-1", settings=settings)

    assert result.state == "confirmed"
    assert "the display_id field is hidden by OPENPROJECT_HIDE_WORK_PACKAGE_FIELDS" in message
    assert "A-1" not in message.replace("expect_display_id", "")
    assert server.work_package_gets == []


@tool_param
@pytest.mark.parametrize("bad", ["A-007", "42", " ", "A 1"])
@pytest.mark.asyncio
async def test_an_expectation_that_is_not_a_display_id_is_refused_at_the_tool_boundary(
    call: Call, bad: str, tmp_path: Path
) -> None:
    server = _Server()

    with pytest.raises(ValueError, match="expect_display_id must be a display id like 'PROJ-51'"):
        await _run(call, "436", tmp_path, confirm=False, expect=bad, server=server)

    assert server.work_package_gets == []


@tool_param
@pytest.mark.asyncio
async def test_an_expectation_is_trimmed(call: Call, tmp_path: Path) -> None:
    result, server = await _run(call, "436", tmp_path, confirm=False, expect="  A-1 ")

    assert _to_payload(result)["target"]["id"] == 436
    assert server.work_package_gets == ["436"]
