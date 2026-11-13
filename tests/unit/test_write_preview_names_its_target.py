"""The preview of a delete or an admin action tells the person who approves it what the action reaches.

A preview that carries nothing but an id asks for approval of something unseen: a wrong id deletes or locks the wrong
record and the preview looked the same. Every delete, cancel, end, lock and unlock tool of the contract cases is
previewed (`confirm=false`), and the preview must carry its target as a `result`, a `target`, or a payload value that is
text (a name, a title, a date). A tool that cannot, for a reason of the server, sits in `EXEMPT` with it.
"""

from __future__ import annotations

import inspect
import re

import httpx
import pytest
from _tools_test_helpers import FakeContext
from _write_contract_cases import WRITE_TOOL_CASES
from _write_contract_cases_types import materialize_case

from openproject_ce_mcp.client import OpenProjectClient
from openproject_ce_mcp.tools import WRITE_TOOLS_BY_SCOPE
from openproject_ce_mcp.tools_runtime import _TOOL_FUNCTIONS

EXEMPT = {
    "delete_user_non_working_time": "OpenProject has no GET for one user non-working time, so there is nothing to look up",
    "delete_grid": "a grid has no name; its lookup is made, the message says it was found",
}
# Where each preview carries its target: the looked-up record (`result`), the work package it belongs to (`target`), or
# the payload key that names it. A tool that is not listed fails, so a new delete or admin action must say where.
TARGET_FIELD = {
    "delete_project": "payload:name",
    "delete_news": "result",
    "delete_work_package": "result",
    "delete_reminder": "target",
    "delete_relation": "result",
    "delete_attachment": "result",
    "delete_work_package_wiki_link": "target",
    "delete_time_entry": "result",
    "delete_file_link": "result",
    "delete_membership": "payload:principal",
    "delete_version": "payload:name",
    "delete_board": "payload:name",
    "delete_user": "result",
    "set_user_locked": "result",
    "delete_group": "result",
    "delete_storage": "result",
    "delete_user_working_hours": "result",
    "delete_meeting": "payload:title",
    "delete_meeting_agenda_item": "payload:title",
    "delete_meeting_outcome": "payload:kind",
    "delete_meeting_section": "payload:title",
    "delete_recurring_meeting": "payload:title",
    "cancel_recurring_meeting_occurrence": "payload:start_time",
}
_TOOLS = sorted(name for name in WRITE_TOOL_CASES if re.match(r"(delete|cancel|end)_|set_user_locked$", name))


def _target(result: object, field: str) -> object:
    where, _, key = field.partition(":")
    if where == "payload":
        return (getattr(result, "payload", None) or {}).get(key)
    return getattr(result, where, None)


def _is_named(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    return value is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", _TOOLS)
async def test_the_preview_of_a_delete_or_admin_action_names_its_target(tool: str, tmp_path) -> None:
    case = WRITE_TOOL_CASES[tool]
    materialized = materialize_case(case, tmp_path)

    async def handler(request: httpx.Request) -> httpx.Response:
        result = case.handler(request)
        return await result if inspect.isawaitable(result) else result

    client = OpenProjectClient(materialized.settings, transport=httpx.MockTransport(handler))
    try:
        preview = await _TOOL_FUNCTIONS[tool](FakeContext(client), **materialized.kwargs, confirm=False)
    finally:
        await client.aclose()

    assert preview.state == "preview"
    if tool in EXEMPT:
        assert tool not in TARGET_FIELD
        pytest.skip(EXEMPT[tool])
    assert tool in TARGET_FIELD, f"{tool} is a delete or admin action: say where its preview names the target"
    assert _is_named(_target(preview, TARGET_FIELD[tool])), f"the preview of {tool} does not name its target"


def test_the_matrix_covers_every_delete_and_admin_action_of_the_contract_cases() -> None:
    registered = {name for names in WRITE_TOOLS_BY_SCOPE.values() for name in names}

    assert set(EXEMPT) <= set(_TOOLS)
    assert set(TARGET_FIELD) | set(EXEMPT) == set(_TOOLS)
    assert {name for name in registered if re.match(r"(delete|cancel|end)_|set_user_locked$", name)} <= set(_TOOLS)
    assert {"delete_reminder", "delete_user_working_hours", "set_user_locked", "delete_user"} <= set(_TOOLS)


def test_the_check_tells_a_named_target_from_an_id_a_blank_or_a_message() -> None:
    class Preview:
        payload = {"id": 5, "title": "  ", "start_time": "2026-01-01T00:00:00Z"}
        result = None
        target = None
        message = "OpenProject found the thing."

    assert not _is_named(_target(Preview, "result"))
    assert not _is_named(_target(Preview, "target"))
    assert not _is_named(_target(Preview, "payload:title"))
    assert not _is_named(_target(Preview, "payload:name"))
    assert _is_named(_target(Preview, "payload:start_time"))
    assert _is_named(_target(Preview, "payload:id"))
