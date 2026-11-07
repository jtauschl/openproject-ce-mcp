"""Tool descriptions state how OpenProject reads an ISO 8601 duration.

Hour fields (`estimated_time`, `remaining_time`, a time entry's `hours`) take `P1D` as 24 hours:
OpenProject never applies the instance's hours per day, and renders 30 hours back as `P1DT6H`.
`duration` is stored as whole days (`hours.to_i / 24`), so `PT8H` is rejected there. A description
that mixes the two sends a caller who means one working day to 24 hours, or to a rejection.
"""

from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.server import create_app

_DAY_RULE = "A day in a duration string is 24 hours, so write 'PT8H' for a working day."
_WHOLE_DAYS_RULE = "duration counts whole days (e.g., 'P1D', 'P2W'); OpenProject rejects less than one day."
_HOUR_FIELD_TOOLS = ("create_work_package", "update_work_package", "create_time_entry", "update_time_entry")


def _descriptions() -> dict[str, str]:
    app = create_app(dataclasses.replace(make_settings(), write_projects=("*",)))
    return {tool.name: tool.description or "" for tool in app._tool_manager.list_tools()}


@pytest.mark.parametrize("tool_name", _HOUR_FIELD_TOOLS)
def test_a_tool_with_an_hour_field_states_that_a_day_is_24_hours(tool_name: str) -> None:
    assert _DAY_RULE in _descriptions()[tool_name]


@pytest.mark.parametrize("tool_name", ("create_work_package", "update_work_package"))
def test_a_work_package_tool_describes_duration_as_whole_days(tool_name: str) -> None:
    assert _WHOLE_DAYS_RULE in _descriptions()[tool_name]


def test_no_description_offers_p1d_as_a_day_for_an_hour_field() -> None:
    offenders = [
        name for name, text in _descriptions().items() if "'P1D' for 1 day" in text or "'PT8H' or 'P1D'" in text
    ]

    assert offenders == []
