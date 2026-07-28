from __future__ import annotations

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_job_status_api import HttpxJobStatusApi, normalize_job_status
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def test_normalize_job_status_builds_summary_from_project_link() -> None:
    detail = normalize_job_status(
        {
            "_type": "JobStatus",
            "id": 77,
            "status": "in_progress",
            "message": "Copy running",
            "percentageDone": 40,
            "createdAt": "2026-03-20T10:00:00Z",
            "updatedAt": "2026-03-20T10:05:00Z",
            "_links": {
                "self": {"href": "/api/v3/job_statuses/77"},
                "project": {"href": "/api/v3/projects/6", "title": "Demo"},
                "createdProject": {"href": "/api/v3/projects/88", "title": "Demo Copy"},
            },
        },
        base_url=BASE_URL,
        origin=BASE_URL,
    )
    assert detail.id == 77
    assert detail.status == "in_progress"
    assert detail.message == "Copy running"
    assert detail.percentage_complete == 40
    assert detail.project_id == 6
    assert detail.project == "Demo"
    assert detail.created_resource_id == 88
    assert detail.created_resource_name == "Demo Copy"
    assert detail.url == f"{BASE_URL}/api/v3/job_statuses/77"


def test_normalize_job_status_falls_back_to_source_project_link() -> None:
    """The project-or-sourceProject fallback: a payload whose only project
    link is under sourceProject still populates project/project_id (matching
    client.py's original normalize_job_status behavior)."""
    detail = normalize_job_status(
        {
            "id": 77,
            "_links": {
                "self": {"href": "/api/v3/job_statuses/77"},
                "sourceProject": {"href": "/api/v3/projects/9", "title": "Source Project"},
            },
        },
        base_url=BASE_URL,
        origin=BASE_URL,
    )
    assert detail.project_id == 9
    assert detail.project == "Source Project"


def test_normalize_job_status_uses_self_href_id_fallback_when_no_id_field() -> None:
    detail = normalize_job_status(
        {"_links": {"self": {"href": "/api/v3/job_statuses/42"}}},
        base_url=BASE_URL,
        origin=BASE_URL,
    )
    assert detail.id == 42


def test_normalize_job_status_trims_long_message_to_formattable_limit() -> None:
    long_message = "x" * 2000
    detail = normalize_job_status(
        {"id": 1, "message": long_message, "_links": {}},
        base_url=BASE_URL,
        origin=BASE_URL,
    )
    assert detail.message is not None
    assert len(detail.message) <= 1_200


@pytest.mark.asyncio
async def test_get_requests_job_status_by_id() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/job_statuses/77"
        return httpx.Response(
            200,
            json={
                "_type": "JobStatus",
                "id": 77,
                "status": "in_progress",
                "_links": {"self": {"href": "/api/v3/job_statuses/77"}},
            },
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxJobStatusApi(HttpxTransport(http_client), base_url=BASE_URL, origin=BASE_URL)
        record = await api.get(77)

    assert record.summary.id == 77
    assert record.summary.status == "in_progress"
    assert record.project_link is None


@pytest.mark.asyncio
async def test_get_record_carries_raw_project_link_for_allowlist_check() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": 77,
                "_links": {
                    "self": {"href": "/api/v3/job_statuses/77"},
                    "project": {"href": "/api/v3/projects/6", "title": "Demo"},
                },
            },
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxJobStatusApi(HttpxTransport(http_client), base_url=BASE_URL, origin=BASE_URL)
        record = await api.get(77)

    assert record.project_link == {"href": "/api/v3/projects/6", "title": "Demo"}


@pytest.mark.asyncio
async def test_get_record_project_link_falls_back_to_source_project() -> None:
    """The Adapter's Record.project_link -- the raw link the Service checks
    against the allowlist -- must use the same project-or-sourceProject
    fallback as the display fields, closing the allowlist-leak bug where the
    old client.py code checked only _links["project"]."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": 77,
                "_links": {
                    "self": {"href": "/api/v3/job_statuses/77"},
                    "sourceProject": {"href": "/api/v3/projects/9", "title": "Source Project"},
                },
            },
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxJobStatusApi(HttpxTransport(http_client), base_url=BASE_URL, origin=BASE_URL)
        record = await api.get(77)

    assert record.project_link == {"href": "/api/v3/projects/9", "title": "Source Project"}


@pytest.mark.asyncio
async def test_get_record_created_project_id_extracted_from_created_project_link() -> None:
    """OpenProject's real createdProject link carries only href/title, no
    type field -- created_project_id is derived from the LINK KEY's presence,
    not from summary.created_resource_type (which stays None for this
    payload shape, a bug a Codex review caught in an earlier version of the
    OPM-316 fix)."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": 77,
                "_links": {
                    "self": {"href": "/api/v3/job_statuses/77"},
                    "createdProject": {"href": "/api/v3/projects/88", "title": "Demo Copy"},
                },
            },
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxJobStatusApi(HttpxTransport(http_client), base_url=BASE_URL, origin=BASE_URL)
        record = await api.get(77)

    assert record.created_project_id == 88
    assert record.summary.created_resource_type is None


@pytest.mark.asyncio
async def test_get_record_created_project_id_is_none_without_created_project_link() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"id": 77, "_links": {"self": {"href": "/api/v3/job_statuses/77"}}},
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxJobStatusApi(HttpxTransport(http_client), base_url=BASE_URL, origin=BASE_URL)
        record = await api.get(77)

    assert record.created_project_id is None
