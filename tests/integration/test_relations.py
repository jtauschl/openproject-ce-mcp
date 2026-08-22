"""Integration tests for work package relation write/read operations."""

from __future__ import annotations

import dataclasses

import pytest

from openproject_ce_mcp.client import InvalidInputError, OpenProjectClient, PermissionDeniedError

from .conftest import disposable_project_identifier

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

    other_identifier = disposable_project_identifier()
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


async def test_update_relation_changes_description_and_type(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    source = await client.create_work_package(
        project=test_project, type="Task", subject="[integration-test] update_relation source", confirm=True
    )
    assert source.ready
    wp_ids.append(source.work_package_id)
    target = await client.create_work_package(
        project=test_project, type="Task", subject="[integration-test] update_relation target", confirm=True
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

    try:
        preview = await client.update_relation(
            relation_id=relation_id, description="Integration test description", confirm=False
        )
        assert preview.state == "preview"

        updated = await client.update_relation(
            relation_id=relation_id, description="Integration test description", relation_type="blocks", confirm=True
        )
        assert updated.state == "confirmed"
        assert updated.result is not None
        # description is wrapped in <user-content> delimiters (prompt-injection
        # boundary marker for user-supplied text), same as every other
        # free-text field this server normalizes.
        assert updated.result.description == "<user-content>Integration test description</user-content>"
        assert updated.result.type == "blocks"
    finally:
        await client.delete_relation(relation_id=relation_id, confirm=True)


async def test_get_work_package_relations_stamps_queried_perspective_from_both_sides(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    """A "follows" relation read from get_work_package_relations
    must carry a caller-relative queried_perspective alongside the raw,
    unchanged type/from_id/to_id -- from BOTH involved work packages'
    perspectives, not just the one the relation happened to be created
    from."""
    source = await client.create_work_package(
        project=test_project, type="Task", subject="[integration-test] perspective source", confirm=True
    )
    assert source.ready
    wp_ids.append(source.work_package_id)
    target = await client.create_work_package(
        project=test_project, type="Task", subject="[integration-test] perspective target", confirm=True
    )
    assert target.ready
    wp_ids.append(target.work_package_id)

    created = await client.create_work_package_relation(
        work_package_id=source.work_package_id,
        related_to_work_package_id=target.work_package_id,
        relation_type="follows",
        confirm=True,
    )
    assert created.ready
    relation_id = created.result.id

    try:
        from_side = await client.get_work_package_relations(source.work_package_id)
        from_side_relation = next(r for r in from_side.results if r.id == relation_id)
        assert from_side_relation.type == "follows"
        assert from_side_relation.from_id == source.work_package_id
        assert from_side_relation.to_id == target.work_package_id
        perspective = from_side_relation.queried_perspective
        assert perspective is not None
        assert perspective.queried_work_package_id == source.work_package_id
        assert perspective.direction == "from"
        assert perspective.effective_type == "follows"
        # Mirrors OpenProject's own Relation#predecessor_id/successor_id:
        # predecessor = to, successor = from.
        assert perspective.predecessor_id == target.work_package_id
        assert perspective.successor_id == source.work_package_id

        to_side = await client.get_work_package_relations(target.work_package_id)
        to_side_relation = next(r for r in to_side.results if r.id == relation_id)
        # Raw fields are perspective-stable: identical regardless of which
        # work package's relations were queried.
        assert to_side_relation.type == "follows"
        assert to_side_relation.from_id == source.work_package_id
        assert to_side_relation.to_id == target.work_package_id
        to_perspective = to_side_relation.queried_perspective
        assert to_perspective is not None
        assert to_perspective.queried_work_package_id == target.work_package_id
        assert to_perspective.direction == "to"
        assert to_perspective.effective_type == "precedes"
        assert to_perspective.predecessor_id == target.work_package_id
        assert to_perspective.successor_id == source.work_package_id
    finally:
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
    assert preview.state == "preview"

    deleted = await client.delete_relation(relation_id=relation_id, confirm=True)
    assert deleted.state == "confirmed"

    result = await client.list_relations(relation_type="relates")
    assert not any(r.id == relation_id for r in result.results)


async def test_list_relations_paginates_beyond_a_single_page(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    """Regression: list_relations never sent offset/pageSize to OpenProject
    at all, so a limit smaller than the total available relations silently
    returned everything the server happened to include in that first page
    rather than genuinely paginating. Creates two independent "relates"
    relations from a shared hub work package (star topology) to guarantee at
    least 2 results scoped to this single relation_type, regardless of
    whatever pre-existing relations the instance already has."""
    hub = await client.create_work_package(
        project=test_project, type="Task", subject="[integration-test] pagination relation hub", confirm=True
    )
    assert hub.ready
    wp_ids.append(hub.work_package_id)

    leaf_a = await client.create_work_package(
        project=test_project, type="Task", subject="[integration-test] pagination relation leaf a", confirm=True
    )
    assert leaf_a.ready
    wp_ids.append(leaf_a.work_package_id)

    leaf_b = await client.create_work_package(
        project=test_project, type="Task", subject="[integration-test] pagination relation leaf b", confirm=True
    )
    assert leaf_b.ready
    wp_ids.append(leaf_b.work_package_id)

    relation_a = await client.create_work_package_relation(
        work_package_id=hub.work_package_id,
        related_to_work_package_id=leaf_a.work_package_id,
        relation_type="relates",
        confirm=True,
    )
    assert relation_a.ready

    relation_b = await client.create_work_package_relation(
        work_package_id=hub.work_package_id,
        related_to_work_package_id=leaf_b.work_package_id,
        relation_type="relates",
        confirm=True,
    )
    assert relation_b.ready

    unfiltered = await client.list_relations(relation_type="relates", limit=100)
    if unfiltered.total < 2:
        pytest.skip("Not enough 'relates' relations on this instance to prove pagination")

    first_page = await client.list_relations(relation_type="relates", limit=1)
    assert first_page.count == 1
    assert first_page.truncated
    assert first_page.next_offset == 2

    second_page = await client.list_relations(relation_type="relates", limit=1, offset=2)
    assert second_page.count == 1
    assert second_page.results[0].id != first_page.results[0].id
