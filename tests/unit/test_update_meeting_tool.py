from __future__ import annotations

import pytest
from _tools_test_helpers import FakeContext

from openproject_ce_mcp.tools_meetings import update_meeting


class _RecordingClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    @property
    def meeting(self) -> _RecordingClient:
        return self

    async def update(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        return kwargs


@pytest.mark.asyncio
async def test_update_meeting_tool_clears_the_location_with_an_empty_string() -> None:
    client = _RecordingClient()

    await update_meeting(FakeContext(client), 7, location="", confirm=True)  # type: ignore[arg-type]

    assert client.calls[0]["location"] == ""


@pytest.mark.asyncio
async def test_update_meeting_tool_leaves_the_location_unchanged_when_omitted() -> None:
    client = _RecordingClient()

    await update_meeting(FakeContext(client), 7, title="Weekly", confirm=True)  # type: ignore[arg-type]

    assert client.calls[0]["location"] is None
