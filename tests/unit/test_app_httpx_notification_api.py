from __future__ import annotations

import json

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_notification_api import HttpxNotificationApi, normalize_notification
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _notification_payload(
    notification_id: int = 7,
    *,
    project_href: str | None = None,
    resource_href: str | None = None,
    subject: str | None = "Something happened",
) -> dict:
    links: dict = {}
    if project_href is not None:
        links["project"] = {"href": project_href, "title": "Demo"}
    if resource_href is not None:
        links["resource"] = {"href": resource_href, "title": "Task"}
    payload: dict = {
        "id": notification_id,
        "readIAN": False,
        "createdAt": "2026-01-01T00:00:00Z",
        "_links": links,
    }
    if subject is not None:
        payload["subject"] = subject
    return payload


@pytest.mark.asyncio
async def test_list_all_requests_notifications_and_builds_records() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/notifications"
        assert request.url.params["offset"] == "1"
        assert request.url.params["pageSize"] == "20"
        return httpx.Response(
            200,
            json={
                "_embedded": {"elements": [_notification_payload(project_href="/api/v3/projects/1")]},
                "total": 1,
            },
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxNotificationApi(HttpxTransport(http_client, redact_server_text=False))
        page = await api.list_all(unread_only=False, offset=1, limit=20)

    assert page.total == 1
    assert len(page.records) == 1
    record = page.records[0]
    assert record.project_link == {"href": "/api/v3/projects/1", "title": "Demo"}
    assert record.resource_link is None
    assert record.summary().id == 7
    assert page.exhausted is True  # 1 offset * 20 page_size >= total (1)


@pytest.mark.asyncio
async def test_list_all_reports_not_exhausted_when_more_pages_remain() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"_embedded": {"elements": [_notification_payload()]}, "total": 100},
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxNotificationApi(HttpxTransport(http_client, redact_server_text=False))
        page = await api.list_all(unread_only=False, offset=1, limit=20)

    assert page.exhausted is False  # 1 * 20 = 20 < 100


@pytest.mark.asyncio
async def test_list_all_missing_embedded_elements_returns_empty_page() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={}, request=request)

    async with _client(handler) as http_client:
        api = HttpxNotificationApi(HttpxTransport(http_client, redact_server_text=False))
        page = await api.list_all(unread_only=False, offset=1, limit=20)

    assert page.records == []
    assert page.total == 0


@pytest.mark.asyncio
async def test_list_all_unread_only_sends_read_ian_filter() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["filters"] == '[{"readIAN":{"operator":"=","values":["f"]}}]'
        return httpx.Response(200, json={"_embedded": {"elements": []}, "total": 0}, request=request)

    async with _client(handler) as http_client:
        api = HttpxNotificationApi(HttpxTransport(http_client, redact_server_text=False))
        await api.list_all(unread_only=True, offset=1, limit=20)


@pytest.mark.asyncio
async def test_list_all_never_normalizes_until_summary_is_called() -> None:
    """`summary` must be lazy: building the record must not itself normalize
    (and potentially crash on) a payload missing unrelated fields."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"_embedded": {"elements": [{"id": 1, "_links": {}}]}, "total": 1},
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxNotificationApi(HttpxTransport(http_client, redact_server_text=False))
        page = await api.list_all(unread_only=False, offset=1, limit=20)

    assert page.records[0].summary().id == 1


@pytest.mark.asyncio
async def test_mark_read_posts_an_empty_json_body() -> None:
    """Regression: an omitted json_body (None) sends no Content-Type header
    at all (httpx only sets one when `json` is non-None) -- OpenProject's
    Grape endpoint rejects a bodyless POST here with 406 "Missing
    content-type header" even though the request carries no real data.
    Confirmed live against a real instance; `json_body={}` is required."""
    requests: list[tuple[str, str, bytes]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path, request.content))
        return httpx.Response(204, request=request)

    async with _client(handler) as http_client:
        api = HttpxNotificationApi(HttpxTransport(http_client, redact_server_text=False))
        await api.mark_read(10)

    assert requests == [("POST", "/api/v3/notifications/10/read_ian", b"{}")]


@pytest.mark.asyncio
async def test_mark_all_read_posts_an_empty_json_body_limited_to_unread() -> None:
    """Unfiltered, the bulk route also rewrites every already-read
    notification and moves its updatedAt."""
    requests: list[tuple[str, str, dict[str, str], bytes]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path, dict(request.url.params), request.content))
        return httpx.Response(204, request=request)

    async with _client(handler) as http_client:
        api = HttpxNotificationApi(HttpxTransport(http_client, redact_server_text=False))
        await api.mark_all_read(project_ids=None)

    assert requests == [
        (
            "POST",
            "/api/v3/notifications/read_ian",
            {"filters": '[{"readIAN":{"operator":"=","values":["f"]}}]'},
            b"{}",
        )
    ]


@pytest.mark.asyncio
async def test_mark_all_read_narrows_to_the_given_projects_sorted_by_id() -> None:
    requests: list[tuple[str, str, list, bytes]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        filters = json.loads(request.url.params["filters"])
        requests.append((request.method, request.url.path, filters, request.content))
        return httpx.Response(204, request=request)

    async with _client(handler) as http_client:
        api = HttpxNotificationApi(HttpxTransport(http_client, redact_server_text=False))
        await api.mark_all_read(project_ids=frozenset({10, 7, 3}))

    assert requests == [
        (
            "POST",
            "/api/v3/notifications/read_ian",
            [
                {"readIAN": {"operator": "=", "values": ["f"]}},
                {"project": {"operator": "=", "values": ["3", "7", "10"]}},
            ],
            b"{}",
        )
    ]


@pytest.mark.asyncio
async def test_mark_all_read_refuses_an_empty_project_set_without_a_request() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    async with _client(handler) as http_client:
        api = HttpxNotificationApi(HttpxTransport(http_client, redact_server_text=False))
        with pytest.raises(ValueError, match="at least one project"):
            await api.mark_all_read(project_ids=frozenset())


@pytest.mark.asyncio
async def test_get_reads_one_notification() -> None:
    requests: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        return httpx.Response(
            200,
            json=_notification_payload(10, project_href="/api/v3/projects/1", resource_href="/api/v3/work_packages/9"),
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxNotificationApi(HttpxTransport(http_client, redact_server_text=False))
        record = await api.get(10)

    assert requests == [("GET", "/api/v3/notifications/10")]
    assert record.project_link == {"href": "/api/v3/projects/1", "title": "Demo"}
    assert record.resource_link == {"href": "/api/v3/work_packages/9", "title": "Task"}
    assert record.summary().id == 10


def test_normalize_notification_resolves_work_package_resource_link() -> None:
    payload = _notification_payload(resource_href="/api/v3/work_packages/9")

    summary = normalize_notification(payload)

    assert summary.work_package_id == 9
    assert summary.work_package_subject == "Task"
    assert summary.project_id is None


def test_normalize_notification_falls_back_to_subject_when_missing() -> None:
    payload = _notification_payload(subject=None)

    summary = normalize_notification(payload)

    assert summary.subject == "Notification 7"


@pytest.mark.asyncio
async def test_list_all_is_not_exhausted_while_a_server_that_cut_the_page_size_has_more_pages() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["pageSize"] == "100"
        return httpx.Response(
            200,
            json={"_embedded": {"elements": [_notification_payload()]}, "total": 100, "pageSize": 20},
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxNotificationApi(HttpxTransport(http_client, redact_server_text=False))
        page = await api.list_all(unread_only=False, offset=2, limit=100)

    assert page.exhausted is False  # 2 * 20 = 40 < 100, although 2 * 100 >= 100
