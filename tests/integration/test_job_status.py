"""Integration tests for async job status tracking (copy_project), 20th
migrated domain (OPM-311).

Originally documented as a deliberate skip of live coverage (job status ids
are ephemeral, only ever created as a side effect of an async operation like
copy_project, and copy_project itself creates a real project). That
rationale no longer holds: JobStatusService.get (app/services/job_status_service.py)
now has a well-understood, live-verifiable bug-fix history of its own (the
project-or-sourceProject link fallback, and the copy-path
project_id_to_identifier write-through via created_project_id) that is only
provable against a real instance's actual response shapes -- unit tests
against hand-built payloads already cover the normalization/allowlist logic,
but not that OpenProject's real payload shape feeds it correctly. Both new
tests below use copy_project deliberately (via the project_refs fixture, so
the copied project is cleaned up like any other disposable test project).
"""

from __future__ import annotations

import asyncio
import dataclasses
import uuid

import pytest

from openproject_ce_mcp.client import OpenProjectClient, PermissionDeniedError

pytestmark = pytest.mark.integration


async def _poll_until_done(client: OpenProjectClient, job_status_id: str, *, timeout: float = 30.0):
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        status = await client.get_job_status(job_status_id)
        if status.status in ("success", "failure", "error"):
            return status
        if asyncio.get_event_loop().time() > deadline:
            pytest.fail(f"copy_project job did not finish within {timeout}s (last status: {status.status})")
        await asyncio.sleep(0.5)


async def test_copy_project_result_becomes_visible_to_allowlist_immediately(
    client: OpenProjectClient, test_project: str, project_refs: list[str]
) -> None:
    """Regression: get_job_status only wrote the copied project's real
    identifier into project_id_to_identifier when the job payload's own
    createdProject link was present -- and a prior bug (fixed in the same
    round) meant that write-through path was never exercised at all, since
    the created_resource_type=="Project" check it relied on never fired
    (the real payload has no top-level `type` field). Without a restart, the
    new project's numeric id was unresolvable by any link-shaped allowlist
    check anywhere else in the client."""
    unrestricted_settings = dataclasses.replace(
        client.settings,
        read_projects=("*",),
        write_projects=("*",),
    )
    unrestricted_client = OpenProjectClient(unrestricted_settings)
    await unrestricted_client.initialize()

    new_identifier = f"integration-test-{uuid.uuid4().hex[:8]}"
    copy_result = await unrestricted_client.copy_project(
        source_project=test_project,
        name=f"[integration-test] {new_identifier}",
        identifier=new_identifier,
        confirm=True,
    )
    assert copy_result.ready, copy_result.validation_errors
    assert copy_result.job_status_id is not None
    project_refs.append(new_identifier)

    status = await _poll_until_done(unrestricted_client, copy_result.job_status_id)
    assert status.status == "success", status.message

    # Immediately, no restart: the new project must already be resolvable.
    new_project = await unrestricted_client.get_project(new_identifier)
    assert new_project.identifier == new_identifier


async def test_get_job_status_denies_project_link_outside_read_allowlist(
    client: OpenProjectClient, test_project: str, project_refs: list[str]
) -> None:
    """Regression: get_job_status read project/sourceProject/createdProject
    links from the response's top-level `_links`, but OpenProject only ever
    puts a `self` link there -- every job-specific resource link (verified
    live: a completed copy_project job's `project` link, which points at
    the newly created project) lives one level down, inside the job's own
    `payload` object. The allowlist check on that link was therefore
    silently never exercised at all against real data."""
    unrestricted_settings = dataclasses.replace(
        client.settings,
        read_projects=("*",),
        write_projects=("*",),
    )
    unrestricted_client = OpenProjectClient(unrestricted_settings)
    await unrestricted_client.initialize()

    new_identifier = f"integration-test-{uuid.uuid4().hex[:8]}"
    copy_result = await unrestricted_client.copy_project(
        source_project=test_project,
        name=f"[integration-test] {new_identifier}",
        identifier=new_identifier,
        confirm=True,
    )
    assert copy_result.ready, copy_result.validation_errors
    assert copy_result.job_status_id is not None
    project_refs.append(new_identifier)

    status = await _poll_until_done(unrestricted_client, copy_result.job_status_id)
    assert status.status == "success", status.message

    denied_settings = dataclasses.replace(client.settings, read_projects=("no-such-project-for-integration-tests",))
    denied_client = OpenProjectClient(denied_settings)
    await denied_client.initialize()

    with pytest.raises(PermissionDeniedError):
        await denied_client.get_job_status(copy_result.job_status_id)
