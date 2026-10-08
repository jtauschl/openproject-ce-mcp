"""Integration tests for async job status tracking (copy_project).

Job status ids are ephemeral, only ever created as a side effect of an async
operation like copy_project, and copy_project itself creates a real project.
Unit tests cover the link fallback and the allowlist logic against hand-built
payloads; only a real instance proves that its job payload names the copied
project in a shape the allowlist recognises. Copied projects go through the
project_refs fixture, so they are cleaned up like any other disposable test
project.
"""

from __future__ import annotations

import asyncio

import pytest

from openproject_ce_mcp.client import OpenProjectClient, PermissionDeniedError

from .conftest import disposable_project_identifier

pytestmark = pytest.mark.integration


async def _poll_until_done(client: OpenProjectClient, job_status_id: str, *, timeout: float = 30.0):
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        status = await client.job_status.get(job_status_id)
        if status.status in ("success", "failure", "error"):
            return status
        if asyncio.get_event_loop().time() > deadline:
            pytest.fail(f"copy_project job did not finish within {timeout}s (last status: {status.status})")
        await asyncio.sleep(0.5)


async def _copy_a_fresh_project(client: OpenProjectClient, project_refs: list[str]):
    """Copy a project created here, returning the copy's identifier and the copy result.

    The shared test project grows with every run; copying it would tie the
    job's duration, and with it the poll limit above, to the instance's history.
    """
    source = disposable_project_identifier()
    created = await client.project.create(name=f"[integration-test] {source}", identifier=source, confirm=True)
    assert created.ready, created.validation_errors
    project_refs.append(source)

    target = disposable_project_identifier()
    copy_result = await client.project.copy(
        source_project=source,
        name=f"[integration-test] {target}",
        identifier=target,
        confirm=True,
    )
    assert copy_result.ready, copy_result.validation_errors
    assert copy_result.job_status_id is not None
    project_refs.append(target)
    return target, copy_result


async def test_a_client_started_before_a_copy_reads_the_copy_by_its_allowlist_pattern(
    start_scoped_client, project_refs: list[str]
) -> None:
    """The copy did not exist when the scoped client scanned the project
    list; its job status only links it by numeric id."""
    unrestricted = await start_scoped_client(read_projects=("*",), write_projects=("*",))
    scoped = await start_scoped_client(read_projects=("IT*",), write_projects=("IT*",))

    new_identifier, copy_result = await _copy_a_fresh_project(unrestricted, project_refs)
    finished = await _poll_until_done(unrestricted, copy_result.job_status_id)
    assert finished.status == "success", finished.message
    copy = await unrestricted.project.get(new_identifier)
    work_package = await unrestricted.work_package.create(
        project=new_identifier, type="Task", subject="[integration-test] in a copied project", confirm=True
    )
    assert work_package.ready, work_package.validation_errors

    status = await scoped.job_status.get(copy_result.job_status_id)
    read_back = await scoped.work_package.get(work_package.work_package_id)

    assert status.project_id == copy.id
    assert scoped._project_id_to_identifier[copy.id] == new_identifier
    assert read_back.id == work_package.work_package_id


async def test_a_client_started_before_a_copy_denies_it_outside_its_allowlist(
    start_scoped_client, project_refs: list[str]
) -> None:
    unrestricted = await start_scoped_client(read_projects=("*",), write_projects=("*",))
    scoped = await start_scoped_client(
        read_projects=("no-such-project-for-integration-tests",),
        write_projects=("no-such-project-for-integration-tests",),
    )

    new_identifier, copy_result = await _copy_a_fresh_project(unrestricted, project_refs)
    finished = await _poll_until_done(unrestricted, copy_result.job_status_id)
    assert finished.status == "success", finished.message
    copy = await unrestricted.project.get(new_identifier)
    # The denial below must come from the copy's own link, not from a
    # missing one: a restrictive scope denies a job without a project link too.
    assert finished.project_id == copy.id

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await scoped.job_status.get(copy_result.job_status_id)
    assert copy.id not in scoped._project_id_to_identifier
