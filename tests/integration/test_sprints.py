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

_SUBJECT = "[integration-test] temp WP sprint-by-name"


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


async def test_update_work_package_accepts_sprint_by_name(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    """OPM-371 gap-fill (written before the flat _resolve_sprint_id is
    relocated into a SprintResolver): name-based sprint resolution on the
    work-package write path had no live coverage at all. Skips cleanly if
    the test project has no existing sprint to reference -- there is no
    create_sprint API to seed one (same constraint as test_get_sprint
    above), and as of this migration the Docker seed fleet doesn't create
    one either. Run unchanged before and after the resolver relocation."""
    try:
        existing = await client.list_project_sprints(test_project)
    except NotFoundError:
        pytest.skip("Backlogs module not installed/enabled on this instance")
    if existing.count == 0:
        pytest.skip("no existing sprint on this project to resolve by name (no create_sprint API to seed one)")

    sprint_name = existing.results[0].name

    result = await client.create_work_package(
        project=test_project,
        type="Task",
        subject=_SUBJECT,
        confirm=True,
    )
    assert result.ready, result.validation_errors
    wp_ids.append(result.work_package_id)

    update_result = await client.update_work_package(
        work_package_id=result.work_package_id,
        sprint=sprint_name,
        confirm=True,
    )
    assert update_result.ready, update_result.validation_errors
