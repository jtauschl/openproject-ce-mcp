from __future__ import annotations

import json

import httpx
import pytest
from _client_test_helpers import (
    _notification_payload,
    _personal_write_enabled_settings,
    _write_enabled_settings,
)

from openproject_ce_mcp.client import (
    InvalidInputError,
    OpenProjectClient,
    PermissionDeniedError,
)
from openproject_ce_mcp.config import Settings


@pytest.mark.asyncio
async def test_list_notifications_filters_by_read_projects() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/notifications":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            _notification_payload(1, project_href="/api/v3/projects/1"),
                            _notification_payload(2, project_href="/api/v3/projects/2", project_title="Other"),
                        ]
                    },
                    "total": 2,
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings(
        base_url="https://op.example.com",
        api_token="token",
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
        read_projects=("demo",),
        enable_personal_read=True,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.list_notifications()

    assert [n.id for n in result.results] == [1]
    assert result.count == 1
    assert result.total == 1

    await client.aclose()


@pytest.mark.asyncio
async def test_list_notifications_returns_only_project_less_under_empty_read_projects() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/notifications":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            _notification_payload(1, project_href="/api/v3/projects/1"),
                            _notification_payload(2),  # no project link, no resource link: personal/global
                        ]
                    },
                    "total": 2,
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings(
        base_url="https://op.example.com",
        api_token="token",
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
        enable_personal_read=True,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.list_notifications()

    assert [n.id for n in result.results] == [2]

    await client.aclose()


@pytest.mark.asyncio
async def test_list_notifications_allows_all_under_wildcard_scope() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/notifications":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            _notification_payload(1, project_href="/api/v3/projects/1"),
                            _notification_payload(2, project_href="/api/v3/projects/2"),
                        ]
                    },
                    "total": 2,
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings(
        base_url="https://op.example.com",
        api_token="token",
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
        read_projects=("*",),
        enable_personal_read=True,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.list_notifications()

    assert [n.id for n in result.results] == [1, 2]

    await client.aclose()


@pytest.mark.asyncio
async def test_list_notifications_denied_by_personal_read_not_work_package_read() -> None:
    """list_notifications' home scope is "personal", not "work_package" —
    enable_work_package_read=True must not be sufficient on its own,
    and enable_personal_read=False must deny it even with every other read on."""

    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request must be issued without personal read enabled")

    settings = Settings(
        base_url="https://op.example.com",
        api_token="token",
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
        read_projects=("*",),
        enable_work_package_read=True,
        enable_personal_read=False,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))
    with pytest.raises(PermissionDeniedError, match="personal"):
        await client.list_notifications()
    await client.aclose()


@pytest.mark.asyncio
async def test_list_notifications_resolves_work_package_notification_without_project_link() -> None:
    # A notification with a work-package resource link but
    # no project link of its own must be resolved via the work package, not
    # trusted as "no project link therefore personal/global".
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/notifications":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            _notification_payload(1, resource_href="/api/v3/work_packages/9"),
                        ]
                    },
                    "total": 1,
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/9":
            return httpx.Response(
                200,
                json={"id": 9, "_links": {"project": {"href": "/api/v3/projects/2", "title": "Other"}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings(
        base_url="https://op.example.com",
        api_token="token",
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
        read_projects=("demo",),  # does not match the work package's "other" project
        enable_personal_read=True,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.list_notifications()

    assert result.results == []
    assert result.count == 0

    await client.aclose()


@pytest.mark.asyncio
async def test_list_reminders_returns_empty_without_a_request_under_empty_read_projects() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request must be issued when read_projects is empty")

    settings = Settings(
        base_url="https://op.example.com",
        api_token="token",
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.list_reminders()

    assert result.count == 0
    assert result.results == []

    await client.aclose()


@pytest.mark.asyncio
async def test_list_reminders_filters_by_read_projects_via_work_package() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/reminders":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            {
                                "id": 1,
                                "remindAt": "2026-01-01T00:00:00Z",
                                "note": "Allowed",
                                "_links": {"remindable": {"href": "/api/v3/work_packages/1"}},
                            },
                            {
                                "id": 2,
                                "remindAt": "2026-01-01T00:00:00Z",
                                "note": "Denied",
                                "_links": {"remindable": {"href": "/api/v3/work_packages/2"}},
                            },
                        ]
                    }
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/1":
            return httpx.Response(
                200,
                json={"id": 1, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/2":
            return httpx.Response(
                200,
                json={"id": 2, "_links": {"project": {"href": "/api/v3/projects/2", "title": "Other"}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings(
        base_url="https://op.example.com",
        api_token="token",
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
        read_projects=("demo",),
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.list_reminders()

    assert [r.id for r in result.results] == [1]

    await client.aclose()


@pytest.mark.asyncio
async def test_mark_notification_read_previews_without_confirm() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request must be issued without confirm=true")

    client = OpenProjectClient(_personal_write_enabled_settings(), transport=httpx.MockTransport(handler))

    result = await client.mark_notification_read(10)

    assert result.confirmed is False
    assert result.requires_confirmation is True
    assert result.notification_id == 10

    await client.aclose()


@pytest.mark.asyncio
async def test_mark_notification_read_posts_after_confirmation() -> None:
    requests: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.url.path == "/api/v3/notifications/10/read_ian" and request.method == "POST":
            return httpx.Response(204, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_personal_write_enabled_settings(), transport=httpx.MockTransport(handler))

    result = await client.mark_notification_read(10, confirm=True)

    assert result.confirmed is True
    assert result.notification_id == 10
    assert requests == [("POST", "/api/v3/notifications/10/read_ian")]

    await client.aclose()


@pytest.mark.asyncio
async def test_mark_all_notifications_read_previews_without_confirm() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request must be issued without confirm=true")

    client = OpenProjectClient(_personal_write_enabled_settings(), transport=httpx.MockTransport(handler))

    result = await client.mark_all_notifications_read()

    assert result.confirmed is False
    assert result.requires_confirmation is True
    assert result.notification_id is None

    await client.aclose()


@pytest.mark.asyncio
async def test_mark_all_notifications_read_posts_after_confirmation() -> None:
    requests: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.url.path == "/api/v3/notifications/read_ian" and request.method == "POST":
            return httpx.Response(204, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_personal_write_enabled_settings(), transport=httpx.MockTransport(handler))

    result = await client.mark_all_notifications_read(confirm=True)

    assert result.confirmed is True
    assert result.notification_id is None
    assert requests == [("POST", "/api/v3/notifications/read_ian")]

    await client.aclose()


@pytest.mark.asyncio
async def test_create_work_package_reminder_posts_and_normalizes() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 42, "_links": {"project": {"href": "/api/v3/projects/1"}}},
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42/reminders" and request.method == "POST":
            assert json.loads(request.content) == {"remindAt": "2026-12-01T09:00:00Z", "note": "n"}
            return httpx.Response(
                201,
                json={
                    "_type": "Reminder",
                    "id": 7,
                    "remindAt": "2026-12-01T09:00:00.000Z",
                    "note": "n",
                    "_embedded": {"creator": {"name": "Alice"}},
                    "_links": {
                        "self": {"href": "/api/v3/reminders/7"},
                        "remindable": {"href": "/api/v3/work_packages/42"},
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_write_enabled_settings(), transport=httpx.MockTransport(handler))

    result = await client.create_work_package_reminder(
        work_package_id=42, remind_at="2026-12-01T09:00:00Z", note="n", confirm=True
    )

    assert result.confirmed is True
    assert result.reminder_id == 7
    assert result.result is not None
    assert result.result.work_package_id == 42
    assert result.result.creator == "Alice"

    await client.aclose()


@pytest.mark.asyncio
async def test_update_reminder_denies_malformed_remindable_link_even_under_open_scope() -> None:
    # An unresolvable remindable link must be denied even under a fully open
    # READ_PROJECTS=*/WRITE_PROJECTS=* scope — an open scope must not bypass
    # this check.
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/reminders/7":
            return httpx.Response(200, json={"_links": {}}, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_write_enabled_settings(), transport=httpx.MockTransport(handler))

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await client.update_reminder(reminder_id=7, note="Updated", confirm=True)

    await client.aclose()


@pytest.mark.asyncio
async def test_update_reminder_requires_a_field() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/reminders/7":
            return httpx.Response(
                200,
                json={"_links": {"remindable": {"href": "/api/v3/work_packages/1"}}},
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/1":
            return httpx.Response(
                200,
                json={"_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_write_enabled_settings(), transport=httpx.MockTransport(handler))

    with pytest.raises(InvalidInputError, match="At least one field"):
        await client.update_reminder(reminder_id=7, confirm=True)

    await client.aclose()
