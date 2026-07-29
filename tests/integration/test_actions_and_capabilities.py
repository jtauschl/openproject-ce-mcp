"""Integration tests for Actions & Capabilities reads.

Neither resource has a create/update/delete endpoint in the OpenProject v3
API (GET list only, no single-item GET for either). list_capabilities
requires the test project itself as its `project` filter (always present),
so no fixture-sourcing/skip logic is needed the way Categories' get_category
test needs one.
"""

from __future__ import annotations

import dataclasses

import pytest

from openproject_ce_mcp.client import OpenProjectClient

pytestmark = pytest.mark.integration


async def test_list_actions(client: OpenProjectClient) -> None:
    result = await client.list_actions()
    assert result is not None
    assert result.count >= 0


async def test_list_capabilities_for_project(client: OpenProjectClient, test_project: str) -> None:
    result = await client.list_capabilities(project=test_project)
    assert result is not None
    assert result.count >= 0


async def test_list_capabilities_by_id_denies_record_outside_read_allowlist(
    client: OpenProjectClient, test_project: str
) -> None:
    """Regression: capability_id-only lookups fetched the single capability
    record directly (GET capabilities/{id}) without ever checking whether its
    own context (the project it belongs to) is in OPENPROJECT_READ_PROJECTS
    -- unlike the project-filtered collection query, which resolves the
    project first and thus already enforces the allowlist. A caller with no
    read access to test_project could still read any of its capability
    records by id."""
    listed = await client.list_capabilities(project=test_project)
    if listed.count == 0:
        pytest.skip("No capability records in test project")
    capability_id = listed.results[0].id

    denied_settings = dataclasses.replace(client.settings, read_projects=("no-such-project-for-integration-tests",))
    denied_client = OpenProjectClient(denied_settings)
    await denied_client.initialize()

    denied_result = await denied_client.list_capabilities(capability_id=capability_id)
    assert denied_result.count == 0
