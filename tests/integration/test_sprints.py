"""Integration tests for Backlogs sprint reads.

Sprints has no create/update/delete endpoint in the OpenProject v3 API
(list x2 + single-item GET only) -- sprint assignment happens via
work-package writes, not here. get_sprint is exercised against a
pre-existing sprint sourced via list_sprints -- if the test project/instance
has none (or the Backlogs module isn't installed), the tests skip rather
than fail, since there's no API to seed a sprint.
"""

from __future__ import annotations

import pytest

from openproject_ce_mcp.client import NotFoundError, OpenProjectClient

pytestmark = pytest.mark.integration


async def test_list_sprints(client: OpenProjectClient) -> None:
    try:
        result = await client.list_sprints()
    except NotFoundError:
        pytest.skip("Backlogs module not installed/enabled on this instance")
    assert result is not None
    assert result.count >= 0


async def test_list_project_sprints(client: OpenProjectClient, test_project: str) -> None:
    try:
        result = await client.list_project_sprints(test_project)
    except NotFoundError:
        pytest.skip("Backlogs module not installed/enabled on this instance")
    assert result is not None
    assert result.count >= 0


async def test_get_sprint(client: OpenProjectClient) -> None:
    try:
        existing = await client.list_sprints()
    except NotFoundError:
        pytest.skip("Backlogs module not installed/enabled on this instance")
    if existing.count == 0:
        pytest.skip("no existing sprint on this instance to read (no create_sprint API to seed one)")

    sprint_id = existing.results[0].id

    sprint = await client.get_sprint(sprint_id)
    assert sprint.id == sprint_id
