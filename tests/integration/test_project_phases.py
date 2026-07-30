"""Integration tests for project phase reads.

list_project_phase_definitions/get_project_phase_definition have no create/
update/delete endpoint (admin-UI-configured, instance-wide, pre-seeded by
OpenProject itself with Initiating/Planning/Executing/Closing). get_project_phase
has no list/create endpoint either -- a project has zero Project::Phase
instances by default (it's an opt-in "life cycle" concept), so
docker/test/seed.rb creates one ahead of time and its id is resolved via the
seed_project_phase_id fixture (a Rails-runner side channel, since there's no
list endpoint to discover it through the API itself).
"""

from __future__ import annotations

import pytest

from openproject_ce_mcp.client import OpenProjectClient

pytestmark = pytest.mark.integration


async def test_list_project_phase_definitions(client: OpenProjectClient) -> None:
    result = await client.list_project_phase_definitions()
    # OpenProject pre-seeds this instance-wide list itself (Initiating/
    # Planning/Executing/Closing, see module docstring) -- a real, healthy
    # instance always has at least one, so `count >= 0` alone (true even for
    # an empty/broken response) isn't a meaningful assertion here.
    assert result.count > 0
    assert all(definition.name for definition in result.results)


async def test_get_project_phase_definition(client: OpenProjectClient) -> None:
    listed = await client.list_project_phase_definitions()
    if listed.count == 0:
        pytest.skip("instance has no project phase definitions configured")

    definition_id = listed.results[0].id
    definition = await client.get_project_phase_definition(definition_id)
    assert definition.id == definition_id


async def test_get_project_phase(client: OpenProjectClient, seed_project_phase_id: int) -> None:
    phase = await client.get_project_phase(seed_project_phase_id)
    assert phase.id == seed_project_phase_id
    assert phase.name
