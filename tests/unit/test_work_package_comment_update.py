"""update_comment: replacing the text of an existing work package comment.

PATCH `activities/{id}` is addressed by the activity alone, so the service
derives the work package (and with it the project write allowlist) from the
activity's own `_links.workPackage`, and reads OpenProject's `_links.update`
to report an edit OpenProject would refuse before sending it.
"""

from __future__ import annotations

import dataclasses
import json

import httpx
import pytest
from _client_test_helpers import _write_enabled_settings, make_settings, started_client

from openproject_ce_mcp.app.errors import (
    CapabilityDisabledError,
    InvalidInputError,
    OpenProjectPermissionDeniedError,
    OpenProjectServerError,
    ProjectScopeDeniedError,
)
from openproject_ce_mcp.client import OpenProjectClient


def _activity(*, update_link: bool = True, work_package_link: bool = True) -> dict:
    links: dict = {"user": {"title": "Alice"}}
    if work_package_link:
        links["workPackage"] = {"href": "/api/v3/work_packages/42"}
    if update_link:
        links["update"] = {"href": "/api/v3/activities/77", "method": "patch"}
    return {"id": 77, "_type": "Activity::Comment", "comment": {"raw": "Old text."}, "_links": links}


def _handler(activity: dict, patches: list[dict], *, project_href: str = "/api/v3/projects/1"):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/v3/activities/77":
            return httpx.Response(200, json=activity, request=request)
        if request.method == "GET" and request.url.path == "/api/v3/work_packages/42":
            return httpx.Response(
                200, json={"id": 42, "_links": {"project": {"href": project_href, "title": "Demo"}}}, request=request
            )
        if request.method == "PATCH" and request.url.path == "/api/v3/activities/77":
            body = json.loads(request.content)
            patches.append(body)
            return httpx.Response(
                200,
                json={
                    "id": 77,
                    "_type": "Activity::Comment",
                    "version": 2,
                    "comment": {"format": "markdown", "raw": body["comment"], "html": ""},
                    "_links": {"user": {"title": "Alice"}},
                    "createdAt": "2026-03-20T11:00:00Z",
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    return handler


@pytest.mark.asyncio
async def test_confirmed_update_patches_only_the_comment_and_returns_the_new_text() -> None:
    patches: list[dict] = []
    client = OpenProjectClient(_write_enabled_settings(), transport=httpx.MockTransport(_handler(_activity(), patches)))

    result = await client.work_package.update_comment(activity_id=77, comment="New text.", confirm=True)

    assert patches == [{"comment": "New text."}], "a plain string: the endpoint rejects {raw: ...}"
    assert result.state == "confirmed" and result.ready
    assert result.work_package_id == 42
    assert result.result is not None
    assert result.result.id == 77
    assert result.result.comment == "<user-content>New text.</user-content>"
    await client.aclose()


@pytest.mark.asyncio
async def test_preview_does_not_write() -> None:
    patches: list[dict] = []
    client = OpenProjectClient(_write_enabled_settings(), transport=httpx.MockTransport(_handler(_activity(), patches)))

    result = await client.work_package.update_comment(activity_id=77, comment="New text.")

    assert patches == []
    assert result.state == "preview" and result.ready
    assert result.payload == {"comment": "New text."}
    assert result.result is None
    assert "notify=false" in result.message
    assert "no comment-version history" in result.message
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("confirm", [False, True])
async def test_a_comment_openproject_would_not_let_us_edit_is_refused_before_writing(confirm: bool) -> None:
    patches: list[dict] = []
    client = OpenProjectClient(
        _write_enabled_settings(), transport=httpx.MockTransport(_handler(_activity(update_link=False), patches))
    )

    with pytest.raises(OpenProjectPermissionDeniedError, match="activity 77"):
        await client.work_package.update_comment(activity_id=77, comment="New text.", confirm=confirm)

    assert patches == []
    await client.aclose()


@pytest.mark.asyncio
async def test_an_activity_without_a_work_package_link_fails_closed() -> None:
    patches: list[dict] = []
    client = OpenProjectClient(
        _write_enabled_settings(), transport=httpx.MockTransport(_handler(_activity(work_package_link=False), patches))
    )

    with pytest.raises(OpenProjectServerError, match="work package link"):
        await client.work_package.update_comment(activity_id=77, comment="New text.", confirm=True)

    assert patches == []
    await client.aclose()


@pytest.mark.asyncio
async def test_the_work_packages_project_must_be_writable() -> None:
    patches: list[dict] = []
    settings = dataclasses.replace(_write_enabled_settings(), write_projects=("other",))
    client = await started_client(
        settings, _handler(_activity(), patches), [(1, "demo", "Demo"), (7, "other", "Other")]
    )

    with pytest.raises(ProjectScopeDeniedError):
        await client.work_package.update_comment(activity_id=77, comment="New text.", confirm=True)

    assert patches == []
    await client.aclose()


@pytest.mark.asyncio
async def test_writes_disabled_blocks_the_confirmed_call() -> None:
    patches: list[dict] = []
    settings = dataclasses.replace(make_settings(), enable_work_package_write=False)
    client = OpenProjectClient(settings, transport=httpx.MockTransport(_handler(_activity(), patches)))

    with pytest.raises(CapabilityDisabledError):
        await client.work_package.update_comment(activity_id=77, comment="New text.", confirm=True)

    assert patches == []
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("confirm", [False, True])
@pytest.mark.parametrize("existing_comment", [None, {}, {"raw": ""}, {"raw": " \n\t"}])
async def test_activity_without_existing_comment_is_rejected(existing_comment: dict | None, confirm: bool) -> None:
    activity = _activity()
    if existing_comment is None:
        del activity["comment"]
    else:
        activity["comment"] = existing_comment
    patches: list[dict] = []
    client = OpenProjectClient(_write_enabled_settings(), transport=httpx.MockTransport(_handler(activity, patches)))

    with pytest.raises(InvalidInputError, match="no existing comment"):
        await client.work_package.update_comment(activity_id=77, comment="New text.", confirm=confirm)

    assert patches == []
    await client.aclose()
