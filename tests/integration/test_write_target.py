"""Integration tests: a write that takes a work package reference names the work package it resolved to."""

from __future__ import annotations

import pytest

from openproject_ce_mcp.client import CLEAR_PARENT, InvalidInputError, OpenProjectClient
from openproject_ce_mcp.work_package_reference import has_semantic_display_id

from ._write_ref import write_ref

pytestmark = pytest.mark.integration


async def _create(client: OpenProjectClient, project: str, wp_ids: list[int], subject: str):
    created = await client.work_package.create(project=project, type="Task", subject=subject, confirm=True)
    assert created.ready
    wp_ids.append(created.work_package_id)
    assert created.result is not None
    return created.result


async def test_previews_name_the_work_package_for_a_numeric_and_a_display_reference(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    wp = await _create(client, test_project, wp_ids, "[integration-test] write target")
    assert wp.display_id is not None

    expectation = wp.display_id if has_semantic_display_id(wp.display_id) else None
    for reference, expect in ((wp.id, expectation), (wp.display_id, None)):
        comment = await client.work_package.add_comment(
            work_package_id=reference,
            comment="[integration-test] preview only",
            expect_display_id=expect,
            confirm=False,
        )
        update = await client.work_package.update(
            work_package_id=reference,
            subject="[integration-test] write target renamed",
            expect_display_id=expect,
            confirm=False,
        )
        delete = await client.work_package.delete(work_package_id=reference, expect_display_id=expect, confirm=False)

        for result in (comment, update, delete):
            assert result.target is not None
            assert result.target.id == wp.id
            assert result.target.display_id == wp.display_id
            assert result.target.subject == "[integration-test] write target"
            assert result.target.status == wp.status
            assert result.target.project == wp.project


async def test_a_confirmed_comment_and_a_relation_preview_name_their_work_packages(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    source = await _create(client, test_project, wp_ids, "[integration-test] target source")
    related = await _create(client, test_project, wp_ids, "[integration-test] target related")

    comment = await client.work_package.add_comment(
        work_package_id=await write_ref(client, source.id),
        comment="[integration-test] confirmed comment",
        confirm=True,
    )
    relation = await client.relation.create(
        work_package_id=source.id,
        related_to_work_package_id=related.display_id,
        relation_type="relates",
        confirm=False,
    )

    assert comment.state == "confirmed"
    assert comment.target is not None
    assert comment.target.display_id == source.display_id
    assert relation.target is not None
    assert relation.related_target is not None
    assert relation.target.display_id == source.display_id
    assert relation.related_target.display_id == related.display_id
    assert relation.related_target.subject == "[integration-test] target related"


async def test_a_bare_integer_write_names_the_ticket_exactly_when_the_record_has_a_semantic_display_id(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    wp = await _create(client, test_project, wp_ids, "[integration-test] bare integer guard")
    renamed = "[integration-test] bare integer guard renamed"

    if not has_semantic_display_id(wp.display_id):
        # Classic mode, or a version before 17.4: the integer id is the ticket's only name.
        preview = await client.work_package.update(work_package_id=wp.id, subject=renamed, confirm=False)
        assert preview.target is not None and preview.target.id == wp.id
        with pytest.raises(InvalidInputError, match="has no semantic display id"):
            await client.work_package.update(
                work_package_id=wp.id, subject=renamed, expect_display_id="PROJ-1", confirm=False
            )
        return

    assert wp.display_id is not None
    for confirm in (False, True):
        with pytest.raises(InvalidInputError, match="expect_display_id"):
            await client.work_package.update(work_package_id=wp.id, subject=renamed, confirm=confirm)
    with pytest.raises(InvalidInputError, match="does not name the work package"):
        await client.work_package.update(
            work_package_id=wp.id, subject=renamed, expect_display_id=f"{wp.display_id}9", confirm=True
        )
    assert (await client.work_package.get(wp.id)).subject == wp.subject

    named = await client.work_package.update(
        work_package_id=wp.id, subject=renamed, expect_display_id=wp.display_id, confirm=True
    )
    assert named.ready, named.validation_errors
    assert named.target is not None and named.target.display_id == wp.display_id
    assert (await client.work_package.get(wp.id)).subject == renamed

    by_display_id = await client.work_package.update(work_package_id=wp.display_id, subject=wp.subject, confirm=True)
    assert by_display_id.ready, by_display_id.validation_errors

    bulk = await client.work_package.bulk_update(
        items=[
            {"work_package_id": wp.id, "subject": renamed},
            {"work_package_id": wp.id, "subject": renamed, "expect_display_id": wp.display_id},
        ],
        confirm=True,
    )
    assert (bulk.succeeded, bulk.failed) == (1, 1)
    assert bulk.items[0].error is not None and "expect_display_id" in bulk.items[0].error
    assert bulk.items[1].success


async def test_an_update_names_the_parent_its_reference_resolved_to(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    child = await _create(client, test_project, wp_ids, "[integration-test] parent target child")
    parent = await _create(client, test_project, wp_ids, "[integration-test] parent target parent")
    assert parent.display_id is not None

    for reference in (parent.id, parent.display_id):
        preview = await client.work_package.update(
            work_package_id=await write_ref(client, child.id), parent_work_package_id=reference, confirm=False
        )
        assert preview.target is not None and preview.target.id == child.id
        assert preview.parent_target is not None
        assert preview.parent_target.id == parent.id
        assert preview.parent_target.display_id == parent.display_id
        assert preview.parent_target.subject == "[integration-test] parent target parent"

    confirmed = await client.work_package.update(
        work_package_id=await write_ref(client, child.id), parent_work_package_id=parent.display_id, confirm=True
    )
    assert confirmed.ready, confirmed.validation_errors
    assert confirmed.parent_target is not None and confirmed.parent_target.id == parent.id
    assert (await client.work_package.get(child.id)).parent_id == parent.id

    cleared = await client.work_package.update(
        work_package_id=await write_ref(client, child.id), parent_work_package_id=CLEAR_PARENT, confirm=False
    )
    assert cleared.parent_target is None


async def test_a_project_update_names_the_parent_its_reference_resolved_to(
    start_scoped_client, test_project: str
) -> None:
    wide = await start_scoped_client(read_projects=("*",), write_projects=("*",))
    candidates = (await wide.project.list(limit=50)).results
    others = [project for project in candidates if project.identifier not in (None, test_project)]
    if not others:
        pytest.skip("the instance shows no second project to name as a parent")
    parent = others[0]

    for reference in (parent.identifier, str(parent.id)):
        preview = await wide.project.update(project_ref=test_project, parent=reference, confirm=False)
        assert preview.state in {"preview", "rejected"}
        assert preview.parent_target is not None
        assert preview.parent_target.id == parent.id
        assert preview.parent_target.identifier == parent.identifier
        assert preview.parent_target.name == parent.name
