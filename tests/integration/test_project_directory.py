"""Projects created after the server started, by another client.

A client scans the project list once at startup; a project that appears later
is only known through the responses that link it. These tests start the scoped
client first and create the projects with a second, unrestricted one.
"""

from __future__ import annotations

import pytest

from openproject_ce_mcp.client import OpenProjectClient, PermissionDeniedError

from .conftest import disposable_project_identifier

pytestmark = pytest.mark.integration


def _outside_the_it_pattern(identifier: str) -> str:
    # Keeps the instance's identifier casing (see disposable_project_identifier).
    return ("ZZ" if identifier[:2].isupper() else "zz") + identifier[2:]


async def _project_with_a_work_package(
    unrestricted: OpenProjectClient, identifier: str, project_refs: list[str]
) -> int:
    created = await unrestricted.project.create(
        name=f"[integration-test] {identifier}", identifier=identifier, confirm=True
    )
    assert created.ready, created.validation_errors
    project_refs.append(identifier)
    work_package = await unrestricted.work_package.create(
        project=identifier, type="Task", subject="[integration-test] project directory", confirm=True
    )
    assert work_package.ready, work_package.validation_errors
    return work_package.work_package_id


async def _all_listed_ids(scoped: OpenProjectClient) -> set[int]:
    listed: set[int] = set()
    offset: int | None = 1
    while offset is not None:
        page = await scoped.work_package.list(offset=offset, limit=scoped.settings.max_results)
        listed.update(work_package.id for work_package in page.results)
        offset = page.next_offset
    return listed


async def test_a_project_created_by_another_client_is_read_and_listed_by_its_allowlist_pattern(
    start_scoped_client, project_refs: list[str]
) -> None:
    scoped = await start_scoped_client(read_projects=("IT*",), write_projects=("IT*",))
    unrestricted = await start_scoped_client(read_projects=("*",), write_projects=("*",))

    inside = disposable_project_identifier()
    inside_work_package = await _project_with_a_work_package(unrestricted, inside, project_refs)
    outside_work_package = await _project_with_a_work_package(
        unrestricted, _outside_the_it_pattern(disposable_project_identifier()), project_refs
    )

    read_back = await scoped.work_package.get(inside_work_package)
    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await scoped.work_package.get(outside_work_package)
    listed_ids = await _all_listed_ids(scoped)

    assert read_back.id == inside_work_package
    assert inside_work_package in listed_ids
    assert outside_work_package not in listed_ids
