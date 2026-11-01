"""Container attachment integration tests; use a disposable instance only."""

from __future__ import annotations

import dataclasses
import os
import uuid

import httpx
import pytest

from openproject_ce_mcp.client import NotFoundError, OpenProjectClient

from ._write_ref import write_ref

pytestmark = pytest.mark.integration

_SUBJECT = "[integration-test] container-attachments"


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
        response = await http.delete(f"{base_url}/api/v3/attachments/{attachment_id}")
        response.raise_for_status()


async def _upload_list_cleanup(
    client: OpenProjectClient, tmp_path, container_type: str, container_id: int, open_client
) -> None:
    rooted = await open_client(dataclasses.replace(client.settings, attachment_root=str(tmp_path)))
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


async def test_wiki_page_attachments(client: OpenProjectClient, tmp_path, seed_wiki_page_id: int, open_client) -> None:
    await _upload_list_cleanup(client, tmp_path, "wiki_page", seed_wiki_page_id, open_client)


async def test_post_attachments(client: OpenProjectClient, tmp_path, seed_post_id: int, open_client) -> None:
    await _upload_list_cleanup(client, tmp_path, "post", seed_post_id, open_client)


async def test_meeting_attachments(
    client: OpenProjectClient, tmp_path, test_project: str, meeting_ids: list[int], open_client
) -> None:
    try:
        meeting = await client.meeting.create(project=test_project, title=f"{_SUBJECT} attachments", confirm=True)
    except NotFoundError:
        pytest.skip("Meetings module not installed/enabled on this instance")
    assert meeting.ready, meeting.validation_errors
    meeting_ids.append(meeting.meeting_id)
    await _upload_list_cleanup(client, tmp_path, "meeting", meeting.meeting_id, open_client)


async def test_comment_attachments(
    client: OpenProjectClient, tmp_path, test_project: str, wp_ids: list[int], open_client
) -> None:
    work_package_id = await _new_work_package(client, test_project, wp_ids, "comment-attachment")
    comment = await client.work_package.add_comment(
        work_package_id=await write_ref(client, work_package_id), comment="comment with a file", confirm=True
    )
    assert comment.result is not None
    await _upload_list_cleanup(client, tmp_path, "activity", comment.result.id, open_client)
