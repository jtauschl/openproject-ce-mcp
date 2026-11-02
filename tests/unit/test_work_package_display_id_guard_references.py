"""The expectation of a write with an optional work package reference or with two references.

`test_work_package_display_id_guard_writes.py` pins the rules every guarded tool shares. Here: an expectation
with no work package to check is refused, and a relation guards its source (`expect_display_id`) and its
related work package (`expect_related_display_id`) independently, each under its own parameter name.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest
from _work_package_write_harness import (
    Call,
    _run,
    _Server,
    _settings,
)

from openproject_ce_mcp.presentation import _to_payload
from openproject_ce_mcp.tool_errors import ToolCallError, ToolInputError
from openproject_ce_mcp.tools import create_time_entry, create_time_entry_until, create_work_package_relation
from openproject_ce_mcp.tools_meetings import (
    create_meeting_agenda_item,
    create_meeting_outcome,
    update_meeting_agenda_item,
    update_meeting_outcome,
)


async def _time_entry(ctx: Any, _ref: str, confirm: bool) -> Any:
    return await create_time_entry(
        ctx, "1", "PT1H", "2026-11-01", project="1", expect_display_id=ctx.expect_display_id, confirm=confirm
    )


async def _time_entry_until(ctx: Any, _ref: str, confirm: bool) -> Any:
    return await create_time_entry_until(
        ctx,
        "1",
        "2026-11-01T09:00:00Z",
        "2026-11-01T10:00:00Z",
        "2026-11-01",
        project="1",
        expect_display_id=ctx.expect_display_id,
        confirm=confirm,
    )


async def _agenda_create(ctx: Any, _ref: str, confirm: bool) -> Any:
    return await create_meeting_agenda_item(ctx, 4, "Item", expect_display_id=ctx.expect_display_id, confirm=confirm)


async def _agenda_update(ctx: Any, _ref: str, confirm: bool) -> Any:
    return await update_meeting_agenda_item(
        ctx, 21, title="Renamed", expect_display_id=ctx.expect_display_id, confirm=confirm
    )


async def _outcome_create(ctx: Any, _ref: str, confirm: bool) -> Any:
    return await create_meeting_outcome(
        ctx, 21, "decision", notes="n", expect_display_id=ctx.expect_display_id, confirm=confirm
    )


async def _outcome_update(ctx: Any, _ref: str, confirm: bool) -> Any:
    return await update_meeting_outcome(ctx, 31, notes="n", expect_display_id=ctx.expect_display_id, confirm=confirm)


WITHOUT_WORK_PACKAGE: dict[str, Call] = {
    "create_time_entry": _time_entry,
    "create_time_entry_until": _time_entry_until,
    "create_meeting_agenda_item": _agenda_create,
    "update_meeting_agenda_item": _agenda_update,
    "create_meeting_outcome": _outcome_create,
    "update_meeting_outcome": _outcome_update,
}
confirm_param = pytest.mark.parametrize("confirm", [False, True], ids=["preview", "confirm"])


@pytest.mark.parametrize("call", list(WITHOUT_WORK_PACKAGE.values()), ids=list(WITHOUT_WORK_PACKAGE))
@confirm_param
@pytest.mark.asyncio
async def test_an_expectation_with_no_work_package_to_check_is_refused_before_any_request(
    call: Call, confirm: bool, tmp_path: Path
) -> None:
    server = _Server()

    with pytest.raises((ToolCallError, ToolInputError)) as caught:
        await _run(call, "", tmp_path, confirm=confirm, expect="A-1", server=server)

    assert "[VALIDATION_FAILED] expect_display_id was given but work_package_id names no work package" in str(
        caught.value
    )
    assert server.requests == []


async def _relate(
    ctx: Any,
    source: str,
    related: str,
    confirm: bool,
    *,
    expect: str | None = None,
    expect_related: str | None = None,
) -> Any:
    return await create_work_package_relation(
        ctx,
        source,
        related,
        "relates",
        expect_display_id=expect,
        expect_related_display_id=expect_related,
        confirm=confirm,
    )


async def _relation_refused(
    source: str,
    related: str,
    tmp_path: Path,
    *,
    expect: str | None = None,
    expect_related: str | None = None,
    confirm: bool = False,
    settings: Any = None,
    code: str = "VALIDATION_FAILED",
) -> tuple[str, _Server]:
    server = _Server()

    async def relate(ctx: Any, _ref: str, confirm: bool) -> Any:
        return await _relate(ctx, source, related, confirm, expect=expect, expect_related=expect_related)

    with pytest.raises((ToolCallError, ToolInputError)) as caught:
        await _run(relate, "", tmp_path, confirm=confirm, settings=settings, server=server)
    assert f"[{code}]" in str(caught.value)
    assert server.writes == [], "a refused relation must send no write request"
    return str(caught.value), server


@confirm_param
@pytest.mark.asyncio
async def test_a_related_bare_number_alone_is_refused_under_the_related_parameter(
    confirm: bool, tmp_path: Path
) -> None:
    message, _ = await _relation_refused("PROJ-436", "436", tmp_path, confirm=confirm)

    assert "436 is A-1 (Project A). If you mean A-1, repeat with expect_related_display_id 'A-1'" in message


@confirm_param
@pytest.mark.asyncio
async def test_a_source_bare_number_alone_is_refused_under_the_source_parameter(confirm: bool, tmp_path: Path) -> None:
    message, _ = await _relation_refused("436", "PROJ-436", tmp_path, confirm=confirm)

    assert "436 is A-1 (Project A). If you mean A-1, repeat with expect_display_id 'A-1'" in message
    assert "expect_related_display_id" not in message


@pytest.mark.asyncio
async def test_a_refused_related_work_package_never_reaches_the_source_verdict(tmp_path: Path) -> None:
    message, server = await _relation_refused("436", "436", tmp_path)

    assert "repeat with expect_related_display_id 'A-1'" in message
    assert server.work_package_gets == ["436"]


@pytest.mark.asyncio
async def test_each_expectation_is_checked_against_its_own_reference(tmp_path: Path) -> None:
    async def relate(ctx: Any, _ref: str, confirm: bool) -> Any:
        return await _relate(ctx, "436", "436", confirm, expect="A-1", expect_related="A-1")

    result, server = await _run(relate, "", tmp_path, confirm=True)

    payload = _to_payload(result)
    assert payload["target"]["display_id"] == payload["related_target"]["display_id"] == "A-1"
    assert server.work_package_gets == ["436", "436"]


@pytest.mark.asyncio
async def test_the_source_expectation_does_not_stand_in_for_the_related_one(tmp_path: Path) -> None:
    message, _ = await _relation_refused("PROJ-436", "436", tmp_path, expect="A-1", expect_related=None)

    assert "repeat with expect_related_display_id 'A-1'" in message


@pytest.mark.asyncio
async def test_a_related_expectation_naming_another_ticket_is_refused_under_the_related_parameter(
    tmp_path: Path,
) -> None:
    message, _ = await _relation_refused("PROJ-436", "436", tmp_path, expect_related="PROJ-436")

    assert (
        "expect_related_display_id 'PROJ-436' does not name the work package that 436 resolved to "
        "(A-1 (Project A))" in message
    )


@pytest.mark.asyncio
async def test_a_source_expectation_naming_another_ticket_is_refused_under_the_source_parameter(
    tmp_path: Path,
) -> None:
    message, _ = await _relation_refused("436", "PROJ-436", tmp_path, expect="PROJ-436")

    assert (
        "expect_display_id 'PROJ-436' does not name the work package that 436 resolved to (A-1 (Project A))" in message
    )
    assert "expect_related_display_id" not in message


@pytest.mark.asyncio
async def test_a_source_outside_the_write_scope_is_denied_without_naming_the_related_ticket(tmp_path: Path) -> None:
    settings = dataclasses.replace(_settings(tmp_path), write_projects=("1",))

    message, _ = await _relation_refused(
        "PROJ-436", "436", tmp_path, expect_related="A-1", settings=settings, code="PROJECT_SCOPE_DENIED"
    )

    assert "OPENPROJECT_WRITE_PROJECTS" in message
    assert "A-1" not in message


@pytest.mark.asyncio
async def test_a_hidden_display_id_drops_the_requirement_on_both_ends_and_refuses_both_expectations(
    tmp_path: Path,
) -> None:
    settings = dataclasses.replace(_settings(tmp_path), hide_work_package_fields=("display_id",))

    async def relate(ctx: Any, _ref: str, confirm: bool) -> Any:
        return await _relate(ctx, "436", "436", confirm)

    result, _ = await _run(relate, "", tmp_path, confirm=True, settings=settings)
    related_message, related_server = await _relation_refused(
        "PROJ-436", "436", tmp_path, expect_related="A-1", settings=settings
    )
    source_message, source_server = await _relation_refused(
        "436", "PROJ-436", tmp_path, expect="A-1", settings=settings
    )

    assert result.state == "confirmed"
    assert "expect_related_display_id" in related_message
    assert "the display_id field is hidden by OPENPROJECT_HIDE_WORK_PACKAGE_FIELDS" in related_message
    assert related_server.work_package_gets == []
    assert "the display_id field is hidden by OPENPROJECT_HIDE_WORK_PACKAGE_FIELDS" in source_message
    assert source_server.work_package_gets == []


@pytest.mark.asyncio
async def test_a_malformed_related_expectation_is_refused_at_the_tool_boundary(tmp_path: Path) -> None:
    server = _Server()

    async def relate(ctx: Any, _ref: str, confirm: bool) -> Any:
        return await _relate(ctx, "PROJ-436", "436", confirm, expect_related="A-007")

    with pytest.raises(ValueError, match="expect_related_display_id must be a display id like 'PROJ-51'"):
        await _run(relate, "", tmp_path, confirm=False, server=server)

    assert server.work_package_gets == []
