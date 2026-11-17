"""The preview of a delete shows no value of a field the settings hide.

A delete preview builds its `payload` from the record it read. The hidden-field stamp marks the record but
changes no value, so a payload built from the record's attributes used to carry the hidden values. Every
delete tool of the contract cases is previewed twice: plain (the payload carries record values: the control
that keeps this test from passing on an empty payload) and with every field of its entity hidden (the
payload is empty). A tool whose payload holds only what the caller passed in is listed with that reason.
"""

from __future__ import annotations

import dataclasses
import inspect
import re

import httpx
import pytest
from _tools_test_helpers import FakeContext
from _write_contract_cases import WRITE_TOOL_CASES
from _write_contract_cases_types import materialize_case

from openproject_ce_mcp import tools  # noqa: F401 -- importing the tools registers them in _TOOL_FUNCTIONS
from openproject_ce_mcp.client import OpenProjectClient
from openproject_ce_mcp.tools_runtime import _TOOL_FUNCTIONS

# Tool -> the entity whose hide setting governs the record the preview reads.
RECORD_ENTITY = {
    "delete_project": "project",
    "delete_news": "news",
    "delete_work_package": "work_package",
    "delete_relation": "relation",
    "delete_attachment": "attachment",
    "delete_time_entry": "time_entry",
    "delete_membership": "membership",
    "delete_version": "version",
    "delete_board": "board",
    "delete_grid": "grid",
    "delete_meeting": "meeting",
    "delete_meeting_agenda_item": "meeting_agenda_item",
    "delete_meeting_outcome": "meeting_outcome",
    "delete_meeting_section": "meeting_section",
    "delete_recurring_meeting": "recurring_meeting",
}

_CALLER_INPUT = "the payload holds the id or the start time the caller passed in, no value read from a record"
CALLER_INPUT = {
    "delete_group": _CALLER_INPUT,
    "delete_storage": _CALLER_INPUT,
    "delete_user": _CALLER_INPUT,
    "delete_user_working_hours": _CALLER_INPUT,
    "delete_user_non_working_time": _CALLER_INPUT,
    "delete_reminder": _CALLER_INPUT,
    "delete_work_package_wiki_link": _CALLER_INPUT,
    "delete_file_link": _CALLER_INPUT,
    "cancel_recurring_meeting_occurrence": _CALLER_INPUT,
    "set_user_locked": "refused before the preview while status or locked is hidden (tests of the user service)",
}
_TOOLS = sorted(name for name in WRITE_TOOL_CASES if re.match(r"(delete|cancel|end)_|set_user_locked$", name))


async def _preview(tool: str, tmp_path, entity: str | None):
    case = WRITE_TOOL_CASES[tool]
    materialized = materialize_case(case, tmp_path)
    settings = materialized.settings
    if entity is not None:
        settings = dataclasses.replace(settings, hidden_fields={entity: ("*",)})

    async def handler(request: httpx.Request) -> httpx.Response:
        result = case.handler(request)
        return await result if inspect.isawaitable(result) else result

    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))
    try:
        return await _TOOL_FUNCTIONS[tool](FakeContext(client), **materialized.kwargs, confirm=False)
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", sorted(RECORD_ENTITY))
async def test_the_preview_of_a_delete_leaves_out_the_values_of_hidden_fields(tool: str, tmp_path) -> None:
    plain = await _preview(tool, tmp_path, None)
    hidden = await _preview(tool, tmp_path, RECORD_ENTITY[tool])

    assert plain.state == "preview" and hidden.state == "preview"
    assert plain.payload, f"the preview of {tool} carries no payload to hide: the control failed"
    assert hidden.payload == {}


def test_every_delete_tool_is_classified_as_reading_a_record_or_echoing_the_caller() -> None:
    assert set(RECORD_ENTITY) & set(CALLER_INPUT) == set()
    assert set(RECORD_ENTITY) | set(CALLER_INPUT) == set(_TOOLS)
