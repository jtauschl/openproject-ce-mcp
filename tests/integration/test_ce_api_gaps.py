"""Integration tests for the CE endpoints added alongside the gap-fill tools:
notification get/unread, work-package pickers, revisions, budgets, version
projects, query stars, and attachments on wiki pages, posts, meetings and
comments.

Run only against a disposable instance (see conftest.py's warning).
"""

from __future__ import annotations

import dataclasses
import os
import uuid

import httpx
import pytest

from openproject_ce_mcp.client import NotFoundError, OpenProjectClient

pytestmark = pytest.mark.integration

_SUBJECT = "[integration-test] ce-api-gaps"


async def _new_work_package(client: OpenProjectClient, test_project: str, wp_ids: list[int], suffix: str) -> int:
    result = await client.work_package.create(
        project=test_project, type="Task", subject=f"{_SUBJECT} {suffix} {uuid.uuid4().hex[:6]}", confirm=True
    )
    assert result.ready, result.validation_errors
    wp_ids.append(result.work_package_id)
    return result.work_package_id


async def _delete_attachment_raw(attachment_id: int) -> None:
    # delete_attachment accepts work package attachments only, so clean up
    # other containers' uploads through the API directly.
    base_url = os.environ["OPENPROJECT_BASE_URL"].rstrip("/")
    async with httpx.AsyncClient(auth=("apikey", os.environ["OPENPROJECT_API_TOKEN"])) as http:
        await http.delete(f"{base_url}/api/v3/attachments/{attachment_id}")


async def test_notification_get_and_unread_round_trip(client: OpenProjectClient) -> None:
    listing = await client.notification.list_all(limit=5)
    if not listing.results:
        pytest.skip("no notifications on this instance")
    target = listing.results[0]
    fetched = await client.notification.get(target.id)
    assert fetched.id == target.id

    await client.notification.mark_read(target.id, confirm=True)
    assert (await client.notification.get(target.id)).read is True
    unread = await client.notification.mark_unread(target.id, confirm=True)
    assert unread.state == "confirmed"
    assert (await client.notification.get(target.id)).read is False
    if target.read:
        await client.notification.mark_read(target.id, confirm=True)


async def test_work_package_pickers(client: OpenProjectClient, test_project: str, wp_ids: list[int]) -> None:
    first = await _new_work_package(client, test_project, wp_ids, "picker-a")
    second = await _new_work_package(client, test_project, wp_ids, "picker-b")

    assignees = await client.work_package_picker.available_assignees(work_package_id=first)
    project_assignees = await client.work_package_picker.available_assignees(project_ref=test_project)
    assert assignees.count == len(assignees.results)
    assert {p.id for p in assignees.results} == {p.id for p in project_assignees.results}

    watchers = await client.work_package_picker.available_watchers(first)
    assert watchers.count == len(watchers.results)

    projects = await client.work_package_picker.available_projects(first)
    assert projects.results, "the work package's own project must be a valid target"
    assert all(p.identifier and p.identifier.lower() == test_project.lower() for p in projects.results)

    candidates = await client.work_package_picker.relation_candidates(first, query=str(second), relation_type="relates")
    assert second in {c.id for c in candidates.results}
    assert first not in {c.id for c in candidates.results}


async def test_revisions_of_a_work_package_without_a_repository(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    work_package_id = await _new_work_package(client, test_project, wp_ids, "revisions")
    result = await client.revision.list_for_work_package(work_package_id)
    assert result.count == 0 and result.results == []


async def test_project_budgets(client: OpenProjectClient, test_project: str) -> None:
    try:
        result = await client.budget.list_for_project(test_project)
    except NotFoundError:
        pytest.skip("budgets module not enabled in the test project")
    assert result.count == len(result.results)


async def test_version_projects(client: OpenProjectClient, test_project: str, version_ids: list[int]) -> None:
    created = await client.version.create(
        project=test_project, name=f"[integration-test] shared {uuid.uuid4().hex[:6]}", confirm=True
    )
    assert created.ready, created.validation_errors
    version_ids.append(created.version_id)
    result = await client.version.list_projects(created.version_id)
    assert [p.identifier.lower() for p in result.results if p.identifier] == [test_project.lower()]


async def test_query_star_round_trip(client: OpenProjectClient, test_project: str, board_ids: list[int]) -> None:
    board = await client.board.create(
        name=f"[integration-test] star {uuid.uuid4().hex[:8]}", project=test_project, public=False, confirm=True
    )
    assert board.ready, board.validation_errors
    board_ids.append(board.board_id)

    starred = await client.query_execution.set_starred(board.board_id, starred=True, confirm=True)
    assert starred.state == "confirmed" and starred.starred is True
    preview = await client.query_execution.set_starred(board.board_id, starred=True)
    assert "already starred" in preview.message
    unstarred = await client.query_execution.set_starred(board.board_id, starred=False, confirm=True)
    assert unstarred.starred is False


async def _upload_list_cleanup(client: OpenProjectClient, tmp_path, container_type: str, container_id: int) -> None:
    rooted = OpenProjectClient(dataclasses.replace(client.settings, attachment_root=str(tmp_path)))
    await rooted.initialize()
    note = tmp_path / f"{container_type}-note.txt"
    note.write_text(f"integration test upload to {container_type}")
    preview = await rooted.attachment.create_for_container(
        container_type=container_type, container_id=container_id, file_path=str(note)
    )
    assert preview.state == "preview"
    uploaded = await rooted.attachment.create_for_container(
        container_type=container_type, container_id=container_id, file_path=str(note), confirm=True
    )
    assert uploaded.state == "confirmed" and uploaded.attachment_id
    try:
        listing = await rooted.attachment.list_for_container(container_type, container_id)
        mine = [a for a in listing.results if a.id == uploaded.attachment_id]
        assert mine and mine[0].file_name == note.name and mine[0].container_id == container_id
    finally:
        await _delete_attachment_raw(uploaded.attachment_id)
        await rooted.aclose()


async def test_wiki_page_attachments(client: OpenProjectClient, tmp_path, seed_wiki_page_id: int) -> None:
    await _upload_list_cleanup(client, tmp_path, "wiki_page", seed_wiki_page_id)


async def test_post_attachments(client: OpenProjectClient, tmp_path, seed_post_id: int) -> None:
    await _upload_list_cleanup(client, tmp_path, "post", seed_post_id)


async def test_meeting_attachments(
    client: OpenProjectClient, tmp_path, test_project: str, meeting_ids: list[int]
) -> None:
    try:
        meeting = await client.meeting.create(project=test_project, title=f"{_SUBJECT} attachments", confirm=True)
    except NotFoundError:
        pytest.skip("Meetings module not installed/enabled on this instance")
    assert meeting.ready, meeting.validation_errors
    meeting_ids.append(meeting.meeting_id)
    await _upload_list_cleanup(client, tmp_path, "meeting", meeting.meeting_id)


async def test_comment_attachments(client: OpenProjectClient, tmp_path, test_project: str, wp_ids: list[int]) -> None:
    work_package_id = await _new_work_package(client, test_project, wp_ids, "comment-attachment")
    comment = await client.work_package.add_comment(
        work_package_id=work_package_id, comment="comment with a file", confirm=True
    )
    assert comment.result is not None
    await _upload_list_cleanup(client, tmp_path, "activity", comment.result.id)
