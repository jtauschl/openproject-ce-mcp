"""set_query_starred, and attachments on wiki pages, posts, meetings and comments.

Both check authorization before any write, in preview too. A container's
project comes from the container itself, or for a comment from its work
package; its own scope flag (project, meeting, work_package) is the one
checked.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from _client_test_helpers import _base_settings

from openproject_ce_mcp.app.errors import (
    CapabilityDisabledError,
    InvalidInputError,
    OpenProjectServerError,
    ProjectScopeDeniedError,
)
from openproject_ce_mcp.client import OpenProjectClient

# --- set_query_starred ------------------------------------------------------


def _query_client(query: dict, writes: list[httpx.Request], **settings) -> OpenProjectClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/v3/queries/31":
            assert request.url.params["pageSize"] == "1"
            return httpx.Response(200, json=query, request=request)
        if request.method == "PATCH" and request.url.path in ("/api/v3/queries/31/star", "/api/v3/queries/31/unstar"):
            writes.append(request)
            starred = request.url.path.endswith("/star")
            return httpx.Response(200, json={**query, "starred": starred}, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    return OpenProjectClient(_base_settings(**settings), transport=httpx.MockTransport(handler))


_QUERY = {
    "id": 31,
    "name": "Open bugs",
    "starred": False,
    "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}},
}


@pytest.mark.asyncio
@pytest.mark.parametrize(("starred", "path"), [(True, "/api/v3/queries/31/star"), (False, "/api/v3/queries/31/unstar")])
async def test_star_previews_then_patches(starred: bool, path: str) -> None:
    writes: list[httpx.Request] = []
    client = _query_client(_QUERY, writes)
    preview = await client.query_execution.set_starred(31, starred=starred)
    assert preview.state == "preview" and writes == []
    confirmed = await client.query_execution.set_starred(31, starred=starred, confirm=True)
    assert [w.url.path for w in writes] == [path]
    assert json.loads(writes[0].content) == {}
    assert confirmed.state == "confirmed" and confirmed.starred is starred and confirmed.query_name == "Open bugs"
    await client.aclose()


@pytest.mark.asyncio
async def test_star_preview_says_when_nothing_would_change() -> None:
    client = _query_client({**_QUERY, "starred": True}, [])
    preview = await client.query_execution.set_starred(31, starred=True)
    assert "already starred" in preview.message
    await client.aclose()


@pytest.mark.asyncio
async def test_star_is_refused_for_a_query_outside_the_write_allowlist_even_in_preview() -> None:
    writes: list[httpx.Request] = []
    client = _query_client(_QUERY, writes, write_projects=("other",))
    with pytest.raises(ProjectScopeDeniedError):
        await client.query_execution.set_starred(31, starred=True)
    assert writes == []
    await client.aclose()


@pytest.mark.asyncio
async def test_a_global_query_is_allowed_only_under_an_open_write_scope() -> None:
    global_query = {**_QUERY, "_links": {}}
    client = _query_client(global_query, [])
    assert (await client.query_execution.set_starred(31, starred=True)).state == "preview"
    await client.aclose()
    restricted = _query_client(global_query, [], write_projects=("demo",))
    with pytest.raises(ProjectScopeDeniedError):
        await restricted.query_execution.set_starred(31, starred=True)
    await restricted.aclose()


# --- container attachments --------------------------------------------------


def _attachment(attachment_id: int, container_href: str) -> dict:
    return {
        "id": attachment_id,
        "fileName": f"file-{attachment_id}.txt",
        "fileSize": 10,
        "_links": {"self": {"href": f"/api/v3/attachments/{attachment_id}"}, "container": {"href": container_href}},
    }


_CONTAINERS = {
    "/api/v3/wiki_pages/12": {"id": 12, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
    "/api/v3/posts/3": {"id": 3, "_links": {"project": {"href": "/api/v3/projects/7", "title": "Other"}}},
    "/api/v3/meetings/6": {"id": 6, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
    "/api/v3/activities/77": {"id": 77, "_links": {"workPackage": {"href": "/api/v3/work_packages/42"}}},
    "/api/v3/activities/78": {"id": 78, "_links": {}},
    "/api/v3/work_packages/42": {"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
}


def _attachment_client(requests: list[httpx.Request], **settings) -> OpenProjectClient:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if request.method == "GET" and path in _CONTAINERS:
            return httpx.Response(200, json=_CONTAINERS[path], request=request)
        if request.method == "GET" and path == "/api/v3/configuration":
            return httpx.Response(200, json={"maximumAttachmentFileSize": 5000}, request=request)
        if request.method == "GET" and path.endswith("/attachments"):
            container = path.removesuffix("/attachments")
            elements = [_attachment(1, container), _attachment(2, "/api/v3/wiki_pages/99")]
            return httpx.Response(200, json={"_embedded": {"elements": elements}}, request=request)
        if request.method == "POST" and path.endswith("/attachments"):
            assert request.headers["content-type"].startswith("multipart/form-data")
            return httpx.Response(200, json=_attachment(5, path.removesuffix("/attachments")), request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    return OpenProjectClient(_base_settings(**settings), transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("container_type", "container_id", "expected_type"),
    [("wiki_page", 12, "WikiPage"), ("meeting", 6, "Meeting"), ("activity", 77, "Activity")],
)
async def test_list_returns_only_the_containers_own_attachments(
    container_type: str, container_id: int, expected_type: str
) -> None:
    client = _attachment_client([], read_projects=("demo",))
    result = await client.attachment.list_for_container(container_type, container_id)
    assert [(a.id, a.container_type, a.container_id) for a in result.results] == [(1, expected_type, container_id)]
    await client.aclose()


@pytest.mark.asyncio
async def test_list_refuses_a_container_in_an_unreadable_project() -> None:
    requests: list[httpx.Request] = []
    client = _attachment_client(requests, read_projects=("demo",))
    with pytest.raises(ProjectScopeDeniedError):
        await client.attachment.list_for_container("post", 3)
    assert all(not r.url.path.endswith("/attachments") for r in requests)
    await client.aclose()


@pytest.mark.asyncio
async def test_a_comment_without_a_work_package_link_fails_closed() -> None:
    client = _attachment_client([])
    with pytest.raises(OpenProjectServerError, match="work package link"):
        await client.attachment.list_for_container("activity", 78)
    await client.aclose()


@pytest.mark.asyncio
async def test_an_unknown_container_type_is_rejected_without_a_request() -> None:
    requests: list[httpx.Request] = []
    client = _attachment_client(requests)
    with pytest.raises(InvalidInputError, match="container_type"):
        await client.attachment.list_for_container("document", 1)
    assert requests == []
    await client.aclose()


@pytest.mark.asyncio
async def test_the_containers_own_read_flag_is_checked() -> None:
    client = _attachment_client([], enable_meeting_read=False)
    with pytest.raises(CapabilityDisabledError):
        await client.attachment.list_for_container("meeting", 6)
    await client.aclose()


def _upload_settings(tmp_path: Path, **overrides) -> dict:
    return {"attachment_root": str(tmp_path), **overrides}


@pytest.mark.asyncio
async def test_upload_previews_without_posting_then_posts_to_the_container(tmp_path: Path) -> None:
    file_path = tmp_path / "note.txt"
    file_path.write_text("hello")
    requests: list[httpx.Request] = []
    client = _attachment_client(requests, **_upload_settings(tmp_path))

    preview = await client.attachment.create_for_container(
        container_type="wiki_page", container_id=12, file_path=str(file_path)
    )
    assert preview.state == "preview"
    assert all(r.method != "POST" for r in requests)

    confirmed = await client.attachment.create_for_container(
        container_type="wiki_page", container_id=12, file_path=str(file_path), confirm=True
    )
    posts = [r for r in requests if r.method == "POST"]
    assert [r.url.path for r in posts] == ["/api/v3/wiki_pages/12/attachments"]
    assert (confirmed.state, confirmed.attachment_id, confirmed.container_type, confirmed.container_id) == (
        "confirmed",
        5,
        "wiki_page",
        12,
    )
    await client.aclose()


@pytest.mark.asyncio
async def test_upload_is_refused_outside_the_write_allowlist(tmp_path: Path) -> None:
    file_path = tmp_path / "note.txt"
    file_path.write_text("hello")
    requests: list[httpx.Request] = []
    client = _attachment_client(requests, **_upload_settings(tmp_path, write_projects=("other",)))
    with pytest.raises(ProjectScopeDeniedError):
        await client.attachment.create_for_container(
            container_type="activity", container_id=77, file_path=str(file_path), confirm=True
        )
    assert all(r.method != "POST" for r in requests)
    await client.aclose()


@pytest.mark.asyncio
async def test_upload_checks_the_containers_own_write_flag(tmp_path: Path) -> None:
    file_path = tmp_path / "note.txt"
    file_path.write_text("hello")
    requests: list[httpx.Request] = []
    settings = _upload_settings(tmp_path, enable_meeting_write=False)
    client = _attachment_client(requests, **settings)
    with pytest.raises(CapabilityDisabledError):
        await client.attachment.create_for_container(
            container_type="meeting", container_id=6, file_path=str(file_path), confirm=True
        )
    assert all(r.method != "POST" for r in requests)
    await client.aclose()


@pytest.mark.asyncio
async def test_upload_keeps_the_attachment_root_confinement(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-root.txt"
    outside.write_text("secret")
    root = tmp_path / "root"
    root.mkdir()
    client = _attachment_client([], attachment_root=str(root))
    with pytest.raises(InvalidInputError, match="outside the allowed attachment directory"):
        await client.attachment.create_for_container(
            container_type="wiki_page", container_id=12, file_path=str(outside)
        )
    await client.aclose()
