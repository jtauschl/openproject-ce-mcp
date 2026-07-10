"""Live checks that the project write allowlist is enforced from a real HAL link.

Both flows here derive their allowlist-check target from a link embedded in a
live OpenProject response (a file link's container work package, an
activity's linked work package) rather than a caller-supplied project. The
denial logic itself is thoroughly unit-tested against hand-built payloads;
what only a live run can prove is that a real response's link shapes feed
that logic correctly end-to-end.
"""

from __future__ import annotations

import pytest

from openproject_ce_mcp.client import OpenProjectClient, PermissionDeniedError

pytestmark = pytest.mark.integration


async def test_delete_file_link_denied_outside_allowlist(
    client: OpenProjectClient, denied_client: OpenProjectClient, test_project: str
) -> None:
    # File links come from external storage integrations this MCP cannot
    # create, so this is inherently best-effort: skip if none exist anywhere
    # in test_project rather than failing (consistent with this suite's
    # existing graceful-skip pattern for other unseeded live preconditions).
    work_packages = await client.list_work_packages(project=test_project, limit=50)
    file_link_id = None
    for wp in work_packages.results:
        links = await client.list_work_package_file_links(wp.id)
        if links.count > 0:
            file_link_id = links.results[0].id
            break
    if file_link_id is None:
        pytest.skip("no file link available in test_project to verify denial against")

    with pytest.raises(PermissionDeniedError):
        await denied_client.delete_file_link(file_link_id, confirm=True)


async def test_toggle_emoji_reaction_denied_outside_allowlist(
    client: OpenProjectClient, denied_client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    wp_result = await client.create_work_package(
        project=test_project, type="Task", subject="Integration test WP for emoji denial", confirm=True
    )
    assert wp_result.ready, wp_result.validation_errors
    wp_id = wp_result.work_package_id
    assert wp_id is not None
    wp_ids.append(wp_id)

    # Work package creation always generates at least one activity.
    activities = await client.get_work_package_activities(wp_id)
    assert activities.count > 0
    activity_id = activities.results[0].id

    with pytest.raises(PermissionDeniedError):
        await denied_client.toggle_activity_emoji_reaction(activity_id, "thumbs_up")
