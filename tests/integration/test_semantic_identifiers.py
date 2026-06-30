"""Integration tests for work-package reference resolution across identifier modes.

Mode-agnostic: the test creates a work package, reads its display_id, and branches
on the form it sees — so the same file is meaningful against both a classic
instance (numeric display_id, e.g. 16.6) and a semantic one (project-prefixed,
e.g. 17.5 with project-based identifiers). See docker/test/ for spinning up both.
"""
from __future__ import annotations

import pytest

from openproject_mcp.client import NotFoundError, OpenProjectClient

pytestmark = pytest.mark.integration

_SUBJECT = "[integration-test] semantic-id WP"


async def test_numeric_reference_always_resolves(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    created = await client.create_work_package(
        project=test_project, type="Task", subject=_SUBJECT, confirm=True
    )
    assert created.ready, created.validation_errors
    wp_ids.append(created.work_package_id)

    # The numeric id must resolve on every version/mode (backwards compatible).
    wp = await client.get_work_package(created.work_package_id)
    assert wp.id == created.work_package_id


async def test_reference_resolution_matches_instance_mode(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    created = await client.create_work_package(
        project=test_project, type="Task", subject=_SUBJECT, confirm=True
    )
    assert created.ready, created.validation_errors
    wp_ids.append(created.work_package_id)

    wp = await client.get_work_package(created.work_package_id)
    display_id = wp.display_id or ""
    is_semantic = "-" in display_id and not display_id.isdigit()

    if is_semantic:
        # Semantic instance: the project-prefixed reference resolves to the same WP,
        # and sub-resource lookups accept it too.
        by_ref = await client.get_work_package(display_id)
        assert by_ref.id == created.work_package_id

        activities = await client.get_work_package_activities(display_id)
        assert activities is not None

        relations = await client.get_work_package_relations(display_id)
        assert relations is not None
    else:
        # Classic instance: display_id is just the numeric id as a string, and a
        # made-up project-prefixed reference degrades cleanly to not-found.
        assert display_id == str(created.work_package_id)
        with pytest.raises(NotFoundError):
            await client.get_work_package("TST-999999")
