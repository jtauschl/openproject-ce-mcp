"""Integration tests: a write that takes a work package reference names the work package it resolved to."""

from __future__ import annotations

import pytest

from openproject_ce_mcp.client import CLEAR_PARENT, OpenProjectClient

pytestmark = pytest.mark.integration


async def _create(client: OpenProjectClient, project: str, wp_ids: list[int], subject: str):
    created = await client.work_package.create(project=project, type="Task", subject=subject, confirm=True)
    assert created.ready
    wp_ids.append(created.work_package_id)
    assert created.result is not None
    return created.result


def _references(wp) -> tuple[int | str, ...]:
    """Every reference the instance accepts for a work package: instances before 17.4 return no `displayId`."""
    return (wp.id,) if wp.display_id is None else (wp.id, wp.display_id)


async def test_previews_name_the_work_package_for_a_numeric_and_a_display_reference(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    wp = await _create(client, test_project, wp_ids, "[integration-test] write target")

    for reference in _references(wp):
        comment = await client.work_package.add_comment(
            work_package_id=reference, comment="[integration-test] preview only", confirm=False
        )
        update = await client.work_package.update(
            work_package_id=reference, subject="[integration-test] write target renamed", confirm=False
        )
        delete = await client.work_package.delete(work_package_id=reference, confirm=False)

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
        work_package_id=source.id, comment="[integration-test] confirmed comment", confirm=True
    )
    relation = await client.relation.create(
        work_package_id=source.id,
        related_to_work_package_id=_references(related)[-1],
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


async def test_an_update_names_the_parent_its_reference_resolved_to(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    child = await _create(client, test_project, wp_ids, "[integration-test] parent target child")
    parent = await _create(client, test_project, wp_ids, "[integration-test] parent target parent")

    for reference in _references(parent):
        preview = await client.work_package.update(
            work_package_id=child.id, parent_work_package_id=reference, confirm=False
        )
        assert preview.target is not None and preview.target.id == child.id
        assert preview.parent_target is not None
        assert preview.parent_target.id == parent.id
        assert preview.parent_target.display_id == parent.display_id
        assert preview.parent_target.subject == "[integration-test] parent target parent"

    confirmed = await client.work_package.update(
        work_package_id=child.id, parent_work_package_id=_references(parent)[-1], confirm=True
    )
    assert confirmed.ready, confirmed.validation_errors
    assert confirmed.parent_target is not None and confirmed.parent_target.id == parent.id
    assert (await client.work_package.get(child.id)).parent_id == parent.id

    cleared = await client.work_package.update(
        work_package_id=child.id, parent_work_package_id=CLEAR_PARENT, confirm=False
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
