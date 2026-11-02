"""Results name only what the read allowlist covers.

A readable project can sit below, or work with, a project the allowlist does not cover. The
parent, the activity's project list and a write preview's links must not name that project.
"""

from __future__ import annotations

import dataclasses
import json
import uuid

import pytest

from openproject_ce_mcp.app.errors import InvalidInputError
from openproject_ce_mcp.app.services._work_package_references import HIDDEN_GROUP_LABEL
from openproject_ce_mcp.app.services.work_package_service import CLEAR_VERSION
from openproject_ce_mcp.client import OpenProjectClient
from openproject_ce_mcp.models import SortCriterion

from ._write_ref import write_ref
from .conftest import disposable_project_identifier

pytestmark = pytest.mark.integration


async def _two_projects(everywhere: OpenProjectClient, project_refs: list[str]) -> tuple[str, str]:
    parent, child = disposable_project_identifier(), disposable_project_identifier()
    for identifier, parent_ref in ((parent, None), (child, parent)):
        created = await everywhere.project.create(
            name=f"[integration-test] {identifier}",
            identifier=identifier,
            confirm=True,
            **({"parent": parent_ref} if parent_ref else {}),
        )
        assert created.ready, created.validation_errors
    # Deleting a project deletes its subprojects; deleting the child as well would race that job.
    project_refs.append(parent)
    return parent, child


async def test_a_project_does_not_name_a_parent_outside_the_read_scope(
    project_refs: list[str], start_scoped_client
) -> None:
    everywhere = await start_scoped_client(read_projects=("*",), write_projects=("*",))
    parent, child = await _two_projects(everywhere, project_refs)

    child_only = await start_scoped_client(read_projects=(child,), write_projects=(child,))
    project = await child_only.project.get(child)
    listed = next(row for row in (await child_only.project.list(search=child)).results if row.identifier == child)

    for result in (project, listed):
        assert (result.parent_id, result.parent_name) == (None, None)
    assert project.ancestors is None

    both = await start_scoped_client(read_projects=(parent, child), write_projects=(child,))
    assert (await both.project.get(child)).parent_name is not None


async def test_a_work_package_does_not_name_a_parent_in_a_project_outside_the_read_scope(
    project_refs: list[str], start_scoped_client
) -> None:
    everywhere = await start_scoped_client(read_projects=("*",), write_projects=("*",))
    parent_project, child_project = await _two_projects(everywhere, project_refs)
    secret = f"SECRET {uuid.uuid4().hex[:8]}"
    child_wp = await everywhere.work_package.create(project=child_project, type="Task", subject=secret, confirm=True)
    assert child_wp.ready, child_wp.validation_errors
    below = await everywhere.work_package.create(
        project=parent_project,
        type="Task",
        subject="[integration-test] below a foreign parent",
        parent_work_package_id=await write_ref(everywhere, child_wp.work_package_id),
        confirm=True,
    )
    assert below.ready, below.validation_errors

    parent_only = await start_scoped_client(read_projects=(parent_project,), write_projects=(parent_project,))

    detail = await parent_only.work_package.get(below.work_package_id)
    assert (detail.parent_id, detail.parent_display_id) == (None, None)

    rows = await parent_only.work_package.list(project=parent_project)
    assert [(row.parent_id, row.parent_display_id) for row in rows.results] == [(None, None)]

    preview = await parent_only.work_package.update(
        work_package_id=await write_ref(everywhere, below.work_package_id),
        subject="[integration-test] renamed",
        confirm=False,
    )
    assert secret not in str(preview.payload)
    assert preview.payload["_links"]["parent"] == {"href": f"/api/v3/work_packages/{child_wp.work_package_id}"}

    both = await start_scoped_client(read_projects=(parent_project, child_project), write_projects=(parent_project,))
    assert (await both.work_package.get(below.work_package_id)).parent_id == child_wp.work_package_id


async def test_time_entry_activities_name_only_projects_the_read_scope_covers(
    test_project: str, project_refs: list[str], start_scoped_client
) -> None:
    everywhere = await start_scoped_client(read_projects=("*",), write_projects=("*",))
    other, _ = await _two_projects(everywhere, project_refs)
    scoped = await start_scoped_client(read_projects=(test_project,), write_projects=(test_project,))

    activities = await scoped.time_entry.list_activities()

    if not activities.results:
        pytest.skip("this instance lists no time entry activities")
    named = {name for activity in activities.results for name in activity.projects}
    assert not any(other in name for name in named)
    everyone = await everywhere.time_entry.list_activities()
    assert any(other in name or f"[integration-test] {other}" == name for a in everyone.results for name in a.projects)


async def test_activity_details_are_left_out_unless_the_read_scope_allows_all(
    project_refs: list[str], start_scoped_client
) -> None:
    everywhere = await start_scoped_client(read_projects=("*",), write_projects=("*",))
    parent_project, child_project = await _two_projects(everywhere, project_refs)
    secret = f"SECRET {uuid.uuid4().hex[:8]}"
    foreign = await everywhere.work_package.create(project=child_project, type="Task", subject=secret, confirm=True)
    assert foreign.ready, foreign.validation_errors
    below = await everywhere.work_package.create(
        project=parent_project,
        type="Task",
        subject="[integration-test] activity details",
        parent_work_package_id=await write_ref(everywhere, foreign.work_package_id),
        confirm=True,
    )
    assert below.ready, below.validation_errors

    unrestricted = await everywhere.activity.list_for_work_package(below.work_package_id)
    assert any(secret in detail["raw"] for row in unrestricted.results for detail in row.details or [])

    for read_projects in ((parent_project,), (parent_project, child_project)):
        scoped_client = await start_scoped_client(read_projects=read_projects, write_projects=(parent_project,))
        scoped = await scoped_client.activity.list_for_work_package(below.work_package_id)
        assert scoped.results
        for row in scoped.results:
            assert row.details is None
            assert row.details_omitted is True
        assert secret not in str(scoped)


def _text(result: object) -> str:
    return json.dumps(dataclasses.asdict(result), default=str)  # type: ignore[call-overload]


async def _work_package_with_a_hidden_version(
    test_project: str, project_refs: list[str], wp_ids: list[int], start_scoped_client
) -> tuple[object, str, str, int]:
    """(client over every project, name of a system-wide version defined in another project, subject, id of
    a work package of the test project that uses it)."""
    everywhere = await start_scoped_client(read_projects=("*",), write_projects=("*",))
    other_project = disposable_project_identifier()
    created_project = await everywhere.project.create(
        name=f"[integration-test] {other_project}", identifier=other_project, confirm=True
    )
    assert created_project.ready, created_project.validation_errors
    project_refs.append(other_project)

    secret = f"[integration-test] secret {uuid.uuid4().hex[:8]}"
    version = await everywhere.version.create(project=other_project, name=secret, sharing="system", confirm=True)
    assert version.ready, version.validation_errors
    subject = f"[integration-test] shared version {uuid.uuid4().hex[:8]}"
    created = await everywhere.work_package.create(
        project=test_project, type="Task", subject=subject, version=secret, confirm=True
    )
    assert created.ready, created.validation_errors
    wp_ids.append(created.work_package_id)

    return everywhere, secret, subject, created.work_package_id


async def test_work_package_results_leave_out_a_version_defined_outside_the_read_scope(
    test_project: str, project_refs: list[str], wp_ids: list[int], start_scoped_client
) -> None:
    everywhere, secret, subject, wp_id = await _work_package_with_a_hidden_version(
        test_project, project_refs, wp_ids, start_scoped_client
    )

    scoped = await start_scoped_client(read_projects=(test_project,), write_projects=(test_project,))
    reads = {
        "get": await scoped.work_package.get(wp_id),
        "get_batch": await scoped.work_package.get_batch(ids=[wp_id]),
        "list": await scoped.work_package.list(
            project=test_project, limit=100, sort_by=[SortCriterion(field="id", direction="desc")]
        ),
        "search": await scoped.work_package.search(search=subject),
        "grouped": await scoped.work_package.list(
            project=test_project, limit=100, group_by="version", include_sums=True
        ),
        "update": await scoped.work_package.update(
            work_package_id=await write_ref(everywhere, wp_id), subject=subject, confirm=True
        ),
        "delete_preview": await scoped.work_package.delete(
            work_package_id=await write_ref(everywhere, wp_id), confirm=False
        ),
    }

    for path, result in reads.items():
        assert secret not in _text(result), path
    assert wp_id in [row.id for row in reads["list"].results]
    assert HIDDEN_GROUP_LABEL in [g.value for g in reads["grouped"].groups or []]
    assert reads["grouped"].total_sums is not None

    open_detail = await everywhere.work_package.get(wp_id)
    assert secret in _text(open_detail)
    open_groups = await everywhere.work_package.list(
        project=test_project, limit=100, group_by="version", include_sums=True
    )
    assert secret in [g.value for g in open_groups.groups or []]


async def test_an_update_refuses_to_remove_a_version_the_read_scope_hides(
    test_project: str, project_refs: list[str], wp_ids: list[int], start_scoped_client
) -> None:
    everywhere, secret, subject, wp_id = await _work_package_with_a_hidden_version(
        test_project, project_refs, wp_ids, start_scoped_client
    )
    scoped = await start_scoped_client(read_projects=(test_project,), write_projects=(test_project,))

    with pytest.raises(InvalidInputError) as refused:
        await scoped.work_package.update(
            work_package_id=await write_ref(everywhere, wp_id), version=CLEAR_VERSION, confirm=True
        )

    assert secret not in str(refused.value)
    assert secret in _text(await everywhere.work_package.get(wp_id))

    renamed = await scoped.work_package.update(
        work_package_id=await write_ref(everywhere, wp_id), subject=f"{subject} renamed", confirm=True
    )
    assert renamed.ready, renamed.validation_errors
    assert secret in _text(await everywhere.work_package.get(wp_id))

    cleared = await everywhere.work_package.update(
        work_package_id=await write_ref(everywhere, wp_id), version=CLEAR_VERSION, confirm=True
    )
    assert cleared.ready, cleared.validation_errors
    assert secret not in _text(await everywhere.work_package.get(wp_id))
