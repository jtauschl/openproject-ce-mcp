"""get_notification and mark_notifications_unread.

get() applies list_all()'s three-way allowlist branch to its one record: a
project link is checked directly, a work-package resource link through the
work package, and a notification with neither is personal and passes.
"""

from __future__ import annotations

import dataclasses

import httpx
import pytest
from _client_test_helpers import _base_settings, _notification_payload

from openproject_ce_mcp.app.errors import CapabilityDisabledError, ProjectScopeDeniedError
from openproject_ce_mcp.client import OpenProjectClient


def _personal(**overrides) -> object:
    return _base_settings(enable_personal_read=True, enable_personal_write=True, **overrides)


def _client(settings, handler) -> OpenProjectClient:
    return OpenProjectClient(settings, transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_get_returns_a_notification_in_an_allowed_project() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET" and request.url.path == "/api/v3/notifications/10"
        return httpx.Response(200, json=_notification_payload(10, project_href="/api/v3/projects/1"), request=request)

    client = _client(_personal(read_projects=("demo",)), handler)
    notification = await client.notification.get(10)
    assert notification.id == 10 and notification.project_name == "Demo"
    await client.aclose()


@pytest.mark.asyncio
async def test_get_refuses_a_notification_about_a_project_outside_the_read_allowlist() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = _notification_payload(10, project_href="/api/v3/projects/7", project_title="Other")
        return httpx.Response(200, json=payload, request=request)

    client = _client(_personal(read_projects=("demo",)), handler)
    with pytest.raises(ProjectScopeDeniedError):
        await client.notification.get(10)
    await client.aclose()


@pytest.mark.asyncio
async def test_get_resolves_a_work_package_resource_through_its_project() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/api/v3/notifications/10":
            payload = _notification_payload(10, resource_href="/api/v3/work_packages/42")
            return httpx.Response(200, json=payload, request=request)
        if request.url.path == "/api/v3/work_packages/42":
            return httpx.Response(
                200,
                json={"id": 42, "_links": {"project": {"href": "/api/v3/projects/7", "title": "Other"}}},
                request=request,
            )
        raise AssertionError(request.url.path)

    client = _client(_personal(read_projects=("demo",)), handler)
    with pytest.raises(ProjectScopeDeniedError):
        await client.notification.get(10)
    assert "/api/v3/work_packages/42" in seen
    await client.aclose()


@pytest.mark.asyncio
async def test_get_passes_a_personal_notification_with_no_project_or_resource() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_notification_payload(10), request=request)

    client = _client(_personal(read_projects=("demo",)), handler)
    assert (await client.notification.get(10)).id == 10
    await client.aclose()


@pytest.mark.asyncio
async def test_get_needs_personal_read() -> None:
    client = _client(_base_settings(), lambda request: httpx.Response(500, request=request))
    with pytest.raises(CapabilityDisabledError):
        await client.notification.get(10)
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("notification_id", "path"),
    [(10, "/api/v3/notifications/10/unread_ian"), (None, "/api/v3/notifications/unread_ian")],
)
async def test_mark_unread_previews_without_writing_then_posts(notification_id: int | None, path: str) -> None:
    posts: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        posts.append((request.method, request.url.path))
        # A bodyless POST would carry no Content-Type and OpenProject answers 406.
        assert request.headers.get("content-type", "").startswith("application/json")
        return httpx.Response(204, request=request)

    client = _client(_personal(), handler)
    mark = client.notification.mark_unread if notification_id else client.notification.mark_all_unread
    args = (notification_id,) if notification_id else ()

    preview = await mark(*args)
    assert preview.state == "preview" and posts == []

    confirmed = await mark(*args, confirm=True)
    assert confirmed.state == "confirmed"
    assert posts == [("POST", path)]
    await client.aclose()


@pytest.mark.asyncio
async def test_mark_unread_needs_personal_write_even_to_preview() -> None:
    settings = dataclasses.replace(_personal(), enable_personal_write=False)
    client = _client(settings, lambda request: httpx.Response(500, request=request))
    with pytest.raises(CapabilityDisabledError):
        await client.notification.mark_unread(10)
    await client.aclose()
