"""Every write that takes a caller-typed work package reference names the record it resolved to, in `target`.

Same method as `test_work_package_write_target.py`, for the writes outside the work package domain: the bare
number `436` and the display reference `PROJ-436` resolve to two different work packages behind the real
client, resolver, adapter and service, and each preview and confirmed result must name the record its own
reference resolved to. A tool that takes the work package as an option has no `target` without it.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest
from _client_test_helpers import _write_enabled_settings
from _work_package_target_helpers import (
    EXPECTED_R1,
    EXPECTED_R2,
    REFERENCES,
)
from _work_package_write_harness import (
    EXPECTATION_FOR_REFERENCE,
    TOOLS,
    Call,
    _run,
    _settings,
)

from openproject_ce_mcp.presentation import _to_payload
from openproject_ce_mcp.tool_errors import ToolCallError
from openproject_ce_mcp.tools import (
    create_time_entry,
    create_time_entry_until,
    create_work_package_relation,
)
from openproject_ce_mcp.tools_meetings import (
    create_meeting_agenda_item,
    create_meeting_outcome,
    update_meeting_agenda_item,
    update_meeting_outcome,
)

tool_param = pytest.mark.parametrize("call", list(TOOLS.values()), ids=list(TOOLS))
reference_param = pytest.mark.parametrize(("ref", "expected"), REFERENCES, ids=["bare-number", "display-reference"])


@tool_param
@reference_param
@pytest.mark.asyncio
async def test_preview_names_the_work_package_the_reference_resolved_to(
    call: Call, ref: str, expected: dict, tmp_path: Path
) -> None:
    result, server = await _run(call, ref, tmp_path, confirm=False, expect=EXPECTATION_FOR_REFERENCE[ref])

    assert result.state == "preview"
    assert _to_payload(result)["target"] == expected
    assert server.work_package_gets == [ref]


@tool_param
@reference_param
@pytest.mark.asyncio
async def test_confirmed_result_names_the_same_work_package(
    call: Call, ref: str, expected: dict, tmp_path: Path
) -> None:
    result, server = await _run(call, ref, tmp_path, confirm=True, expect=EXPECTATION_FOR_REFERENCE[ref])

    assert result.state == "confirmed"
    assert _to_payload(result)["target"] == expected
    assert server.work_package_gets == [ref]


@tool_param
@pytest.mark.asyncio
async def test_hidden_fields_are_absent_from_the_serialized_target(call: Call, tmp_path: Path) -> None:
    settings = dataclasses.replace(_settings(tmp_path), hide_work_package_fields=("status", "display_id", "subject"))

    result, _ = await _run(call, "PROJ-436", tmp_path, confirm=False, settings=settings)

    assert _to_payload(result)["target"] == {"id": 9001, "project": "Project B"}


async def _time_entry_in_project(ctx: Any, _ref: str, confirm: bool) -> Any:
    return await create_time_entry(ctx, "1", "PT1H", "2026-11-01", project="1", confirm=confirm)


async def _time_entry_until_in_project(ctx: Any, _ref: str, confirm: bool) -> Any:
    return await create_time_entry_until(
        ctx, "1", "2026-11-01T09:00:00Z", "2026-11-01T10:00:00Z", "2026-11-01", project="1", confirm=confirm
    )


async def _agenda_create_unlinked(ctx: Any, _ref: str, confirm: bool) -> Any:
    return await create_meeting_agenda_item(ctx, 4, "Item", confirm=confirm)


async def _agenda_update_unlinked(ctx: Any, _ref: str, confirm: bool) -> Any:
    return await update_meeting_agenda_item(ctx, 21, title="Renamed", confirm=confirm)


async def _outcome_create_unlinked(ctx: Any, _ref: str, confirm: bool) -> Any:
    return await create_meeting_outcome(ctx, 21, "decision", notes="n", confirm=confirm)


async def _outcome_update_unlinked(ctx: Any, _ref: str, confirm: bool) -> Any:
    return await update_meeting_outcome(ctx, 31, notes="n", confirm=confirm)


WITHOUT_WORK_PACKAGE: dict[str, Call] = {
    "create_time_entry": _time_entry_in_project,
    "create_time_entry_until": _time_entry_until_in_project,
    "create_meeting_agenda_item": _agenda_create_unlinked,
    "update_meeting_agenda_item": _agenda_update_unlinked,
    "create_meeting_outcome": _outcome_create_unlinked,
    "update_meeting_outcome": _outcome_update_unlinked,
}


@pytest.mark.parametrize("confirm", [False, True], ids=["preview", "confirmed"])
@pytest.mark.parametrize("call", list(WITHOUT_WORK_PACKAGE.values()), ids=list(WITHOUT_WORK_PACKAGE))
@pytest.mark.asyncio
async def test_a_write_without_a_work_package_has_no_target(call: Call, confirm: bool, tmp_path: Path) -> None:
    result, server = await _run(call, "", tmp_path, confirm=confirm)

    assert result.target is None
    assert "target" not in _to_payload(result)
    assert server.work_package_gets == []


RELATION_ENDS = [
    ("436", "PROJ-436", EXPECTED_R1, EXPECTED_R2),
    ("PROJ-436", "436", EXPECTED_R2, EXPECTED_R1),
]
relation_ends_param = pytest.mark.parametrize(
    ("source", "related", "expected_target", "expected_related_target"),
    RELATION_ENDS,
    ids=["bare-number-source", "display-reference-source"],
)


@relation_ends_param
@pytest.mark.parametrize("confirm", [False, True], ids=["preview", "confirmed"])
@pytest.mark.asyncio
async def test_a_relation_names_both_ends(
    source: str, related: str, expected_target: dict, expected_related_target: dict, confirm: bool, tmp_path: Path
) -> None:
    async def relate(ctx: Any, _ref: str, confirm: bool) -> Any:
        return await create_work_package_relation(ctx, source, related, "relates", confirm=confirm)

    result, server = await _run(relate, "", tmp_path, confirm=confirm)

    payload = _to_payload(result)
    assert payload["target"] == expected_target
    assert payload["related_target"] == expected_related_target
    assert sorted(server.work_package_gets) == sorted([source, related])


@pytest.mark.asyncio
async def test_a_hidden_field_is_absent_from_both_ends_of_a_relation(tmp_path: Path) -> None:
    settings = dataclasses.replace(_settings(tmp_path), hide_work_package_fields=("subject",))

    async def relate(ctx: Any, _ref: str, confirm: bool) -> Any:
        return await create_work_package_relation(ctx, "436", "PROJ-436", "relates", confirm=confirm)

    result, _ = await _run(relate, "", tmp_path, confirm=False, settings=settings)

    payload = _to_payload(result)
    assert "subject" not in payload["target"]
    assert "subject" not in payload["related_target"]
    assert payload["target"]["display_id"] == "A-1"
    assert payload["related_target"]["display_id"] == "PROJ-436"


OUT_OF_READ_SCOPE = dataclasses.replace(_write_enabled_settings(), read_projects=("1",), write_projects=("*",))


async def _relate_outside_scope(ctx: Any, ref: str, confirm: bool) -> Any:
    return await create_work_package_relation(ctx, "436", ref, "relates", confirm=confirm)


async def _relate_source_outside_scope(ctx: Any, ref: str, confirm: bool) -> Any:
    return await create_work_package_relation(ctx, ref, "436", "relates", confirm=confirm)


@pytest.mark.parametrize(
    "call",
    [*TOOLS.values(), _relate_outside_scope, _relate_source_outside_scope],
    ids=[*TOOLS, "create_work_package_relation_related", "create_work_package_relation_source"],
)
@pytest.mark.asyncio
async def test_a_write_to_a_work_package_outside_the_read_scope_is_denied_before_any_target_exists(
    call: Call, tmp_path: Path
) -> None:
    settings = dataclasses.replace(
        OUT_OF_READ_SCOPE, enable_meeting_write=True, attachment_root=str(tmp_path), read_projects=("1",)
    )

    with pytest.raises(ToolCallError, match=r"\[PROJECT_SCOPE_DENIED\].*OPENPROJECT_READ_PROJECTS"):
        await _run(call, "PROJ-436", tmp_path, confirm=False, settings=settings)
