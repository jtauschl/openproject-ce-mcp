"""Integration tests for work package relation write/read operations."""

from __future__ import annotations

import dataclasses
import uuid

import pytest

from openproject_ce_mcp.client import InvalidInputError, OpenProjectClient, PermissionDeniedError

pytestmark = pytest.mark.integration


async def test_create_relation_denied_when_target_outside_write_allowlist(
    client: OpenProjectClient, test_project: str, wp_ids: list[int], project_refs: list[str]
) -> None:
    """Regression: create_work_package_relation authorized only the source
    work package's project against OPENPROJECT_WRITE_PROJECTS -- the
    relation target was resolved read-only, letting a caller with write
    access to one project link it to a work package in a project they
    could only read."""
    unrestricted_settings = dataclasses.replace(
        client.settings,
        read_projects=("*",),
        write_projects=("*",),
    )
    unrestricted_client = OpenProjectClient(unrestricted_settings)
    await unrestricted_client.initialize()

    other_identifier = f"integration-test-{uuid.uuid4().hex[:8]}"
    create_project_result = await unrestricted_client.create_project(
        name=f"[integration-test] {other_identifier}", identifier=other_identifier, confirm=True
    )
    assert create_project_result.ready, create_project_result.validation_errors
    project_refs.append(other_identifier)

    source = await client.create_work_package(
        project=test_project, type="Task", subject="[integration-test] relation source", confirm=True
    )
    assert source.ready
    wp_ids.append(source.work_package_id)

    target = await unrestricted_client.create_work_package(
        project=other_identifier, type="Task", subject="[integration-test] relation target", confirm=True
    )
    assert target.ready

    # `client` can write test_project but only read `other_identifier`
    # (default allowlist is test_project-only for both scopes) -- so this
    # relation write must be denied.
    with pytest.raises(PermissionDeniedError):
        await client.create_work_package_relation(
            work_package_id=source.work_package_id,
            related_to_work_package_id=target.work_package_id,
            relation_type="relates",
            confirm=True,
        )


async def test_create_relation_rejects_hidden_type_field(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    """Regression: relation.type/description bypassed the hidden-fields
    guard on writes (only description was covered, not type)."""
    source = await client.create_work_package(
        project=test_project, type="Task", subject="[integration-test] relation hidden field source", confirm=True
    )
    assert source.ready
    wp_ids.append(source.work_package_id)
    target = await client.create_work_package(
        project=test_project, type="Task", subject="[integration-test] relation hidden field target", confirm=True
    )
    assert target.ready
    wp_ids.append(target.work_package_id)

    hidden_settings = dataclasses.replace(client.settings, hidden_fields={"relation": ("type",)})
    hidden_client = OpenProjectClient(hidden_settings)
    await hidden_client.initialize()

    with pytest.raises(InvalidInputError, match="OPENPROJECT_HIDE_RELATION_FIELDS"):
        await hidden_client.create_work_package_relation(
            work_package_id=source.work_package_id,
            related_to_work_package_id=target.work_package_id,
            relation_type="relates",
            confirm=False,
        )


async def test_delete_relation_denied_outside_write_allowlist(
    denied_client: OpenProjectClient, client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    """delete_relation resolves the relation's source work package and
    authorizes the delete against its project -- a caller without write
    access to that project must be denied."""
    source = await client.create_work_package(
        project=test_project, type="Task", subject="[integration-test] delete_relation denied source", confirm=True
    )
    assert source.ready
    wp_ids.append(source.work_package_id)
    target = await client.create_work_package(
        project=test_project, type="Task", subject="[integration-test] delete_relation denied target", confirm=True
    )
    assert target.ready
    wp_ids.append(target.work_package_id)

    created = await client.create_work_package_relation(
        work_package_id=source.work_package_id,
        related_to_work_package_id=target.work_package_id,
        relation_type="relates",
        confirm=True,
    )
    assert created.ready
    relation_id = created.result.id

    with pytest.raises(PermissionDeniedError):
        await denied_client.delete_relation(relation_id=relation_id, confirm=True)

    # Clean up directly since the denied client couldn't remove it.
    await client.delete_relation(relation_id=relation_id, confirm=True)


async def test_delete_relation_removes_it(client: OpenProjectClient, test_project: str, wp_ids: list[int]) -> None:
    """Round-trips delete_relation against the real DELETE relations/{id}
    endpoint: create a relation, delete it, then confirm it no longer shows
    up via list_relations."""
    source = await client.create_work_package(
        project=test_project, type="Task", subject="[integration-test] delete_relation source", confirm=True
    )
    assert source.ready
    wp_ids.append(source.work_package_id)
    target = await client.create_work_package(
        project=test_project, type="Task", subject="[integration-test] delete_relation target", confirm=True
    )
    assert target.ready
    wp_ids.append(target.work_package_id)

    created = await client.create_work_package_relation(
        work_package_id=source.work_package_id,
        related_to_work_package_id=target.work_package_id,
        relation_type="relates",
        confirm=True,
    )
    assert created.ready
    relation_id = created.result.id

    preview = await client.delete_relation(relation_id=relation_id)
    assert preview.requires_confirmation

    deleted = await client.delete_relation(relation_id=relation_id, confirm=True)
    assert deleted.confirmed

    result = await client.list_relations(relation_type="relates")
    assert not any(r.id == relation_id for r in result.results)
