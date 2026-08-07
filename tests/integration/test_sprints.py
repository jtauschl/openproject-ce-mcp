"""Integration tests for Backlogs sprint reads.

Sprints has no create/update/delete endpoint in the OpenProject v3 API
(list x2 + single-item GET only) -- sprint assignment happens via
work-package writes, not here. get_sprint is exercised against a
pre-existing sprint sourced via list_sprints -- if the test project/instance
has none (or the Backlogs module isn't installed), the tests skip rather
than fail, since there's no API to seed a sprint.

ACCEPTED GAP (OPM-345, 2026-08-07): unlike views/documents/relations (this
branch's list_project_memberships has no offset/limit param at all -- see
test_memberships.py), sprints has NO paginate-beyond-a-single-page
regression test in this file. The Docker test instance has zero sprints
(confirmed live via a direct admin-token API call) -- with no create API and
no pre-existing data on the standard test harness, there is no way to
construct a >=2-item precondition the way the other domains' tests do. Add
one if a future seed.rb change ever provisions sprints.
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
    # No create_sprint API exists to seed one -- a fresh instance can
    # genuinely have zero sprints.
    if result.count > 0:
        assert result.results[0].name


async def test_list_project_sprints(client: OpenProjectClient, test_project: str) -> None:
    try:
        result = await client.list_project_sprints(test_project)
    except NotFoundError:
        pytest.skip("Backlogs module not installed/enabled on this instance")
    assert result is not None
    if result.count > 0:
        assert result.results[0].name


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
