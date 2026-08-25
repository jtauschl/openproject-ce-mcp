"""Integration tests for Backlogs sprint reads.

Sprints has no create/update/delete endpoint in the OpenProject v3 API
(list x2 + single-item GET only) -- sprint assignment happens via
work-package writes, not here. Confirmed by source (op-sources/full-17.6/
modules/backlogs/lib/api/v3/sprints/{sprints_api,sprints_by_project_api}.rb):
both route files mount only Index/Show endpoints, no Create/Update/Delete
anywhere in the module. get_sprint is exercised against a pre-existing
sprint sourced via list_sprints -- if the test project/instance has none (or
the Backlogs module isn't installed), the tests skip rather than fail, since
there's no API to seed a sprint.

Accepted gap: unlike views/documents/relations/memberships, sprints has NO
paginate-beyond-a-single-page regression test in this file. The Docker test
instance has zero sprints (a direct `GET /api/v3/sprints` admin-token call
returns `total: 0`) -- with no create API and no pre-existing data on the
standard test harness, there is no way to construct a >=2-item precondition
the way the other domains' tests do. Add one if a future seed.rb change ever provisions
sprints (e.g. via a Backlogs-module Rails-runner seed step), following the
same `if unfiltered.total < 2: skip` pattern as
test_list_grids_paginates_beyond_a_single_page.
"""

from __future__ import annotations

import pytest

from openproject_ce_mcp.client import NotFoundError, OpenProjectClient

pytestmark = pytest.mark.integration

_SUBJECT = "[integration-test] temp WP sprint-by-name"


async def test_list_sprints(client: OpenProjectClient) -> None:
    try:
        result = await client.sprint.list()
    except NotFoundError:
        pytest.skip("Backlogs module not installed/enabled on this instance")
    assert result is not None
    assert result.count >= 0


async def test_list_project_sprints(client: OpenProjectClient, test_project: str) -> None:
    try:
        result = await client.sprint.list_for_project(test_project)
    except NotFoundError:
        pytest.skip("Backlogs module not installed/enabled on this instance")
    assert result is not None
    assert result.count >= 0


async def test_get_sprint(client: OpenProjectClient) -> None:
    try:
        existing = await client.sprint.list()
    except NotFoundError:
        pytest.skip("Backlogs module not installed/enabled on this instance")
    if existing.count == 0:
        pytest.skip("no existing sprint on this instance to read (no create_sprint API to seed one)")

    sprint_id = existing.results[0].id

    sprint = await client.sprint.get(sprint_id)
    assert sprint.id == sprint_id


async def test_update_work_package_accepts_sprint_by_name(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    """Gap-fill test, written before the flat _resolve_sprint_id is
    relocated into a SprintResolver: name-based sprint resolution on the
    work-package write path had no live coverage at all. Skips cleanly if
    the test project has no existing sprint to reference -- there is no
    create_sprint API to seed one (same constraint as test_get_sprint
    above), and as of this migration the Docker seed fleet doesn't create
    one either. Run unchanged before and after the resolver relocation."""
    try:
        existing = await client.sprint.list_for_project(test_project)
    except NotFoundError:
        pytest.skip("Backlogs module not installed/enabled on this instance")
    if existing.count == 0:
        pytest.skip("no existing sprint on this project to resolve by name (no create_sprint API to seed one)")

    sprint_name = existing.results[0].name

    result = await client.work_package.create(
        project=test_project,
        type="Task",
        subject=_SUBJECT,
        confirm=True,
    )
    assert result.ready, result.validation_errors
    wp_ids.append(result.work_package_id)

    update_result = await client.work_package.update(
        work_package_id=result.work_package_id,
        sprint=sprint_name,
        confirm=True,
    )
    assert update_result.ready, update_result.validation_errors
