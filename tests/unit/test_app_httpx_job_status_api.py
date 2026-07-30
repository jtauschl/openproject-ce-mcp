from __future__ import annotations

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_job_status_api import HttpxJobStatusApi, normalize_job_status
from openproject_ce_mcp.app.errors import InvalidInputError
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
            "jobId": "77",
            "status": "in_progress",
            "message": "Copy running",
            "percentageDone": 40,
            "createdAt": "2026-03-20T10:00:00Z",
            "updatedAt": "2026-03-20T10:05:00Z",
            # OpenProject nests a job's own resource links one level down,
            # inside `payload._links` -- top-level `_links` only ever
            # carries `self`.
            "payload": {
                "_links": {
                    "project": {"href": "/api/v3/projects/6", "title": "Demo"},
                    "createdProject": {"href": "/api/v3/projects/88", "title": "Demo Copy"},
                },
            },
            "_links": {
                "self": {"href": "/api/v3/job_statuses/77"},
            },
        },
        base_url=BASE_URL,
        origin=BASE_URL,
    )
    assert detail.id == "77"
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
            "jobId": "77",
            "payload": {
                "_links": {
                    "sourceProject": {"href": "/api/v3/projects/9", "title": "Source Project"},
                },
            },
            "_links": {"self": {"href": "/api/v3/job_statuses/77"}},
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
    assert detail.id == "42"


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
                "jobId": "77",
                "status": "in_progress",
                "_links": {"self": {"href": "/api/v3/job_statuses/77"}},
            },
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxJobStatusApi(HttpxTransport(http_client), base_url=BASE_URL, origin=BASE_URL)
        record = await api.get("77")

    assert record.summary.id == "77"
    assert record.summary.status == "in_progress"
    assert record.project_link is None


@pytest.mark.asyncio
async def test_get_rejects_path_traversal_id() -> None:
    """Regression (found via self-review on release/0.3.4, ported here):
    job_status_id was interpolated into the URL path with no validation --
    a value like "../projects/42" quotes to itself unchanged (quote()
    never escapes ".") and httpx then normalizes ".." away when building
    the request, redirecting it to an entirely different endpoint and
    bypassing this domain's own allowlist check."""

    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"No request should ever be issued: {request.method} {request.url}")

    async with _client(handler) as http_client:
        api = HttpxJobStatusApi(HttpxTransport(http_client), base_url=BASE_URL, origin=BASE_URL)
        with pytest.raises(InvalidInputError, match="job_status_id"):
            await api.get("../projects/42")


@pytest.mark.asyncio
async def test_get_record_carries_raw_project_link_for_allowlist_check() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jobId": "77",
                "payload": {
                    "_links": {
                        "project": {"href": "/api/v3/projects/6", "title": "Demo"},
                    },
                },
                "_links": {"self": {"href": "/api/v3/job_statuses/77"}},
            },
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxJobStatusApi(HttpxTransport(http_client), base_url=BASE_URL, origin=BASE_URL)
        record = await api.get("77")

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
                "jobId": "77",
                "payload": {
                    "_links": {
                        "sourceProject": {"href": "/api/v3/projects/9", "title": "Source Project"},
                    },
                },
                "_links": {"self": {"href": "/api/v3/job_statuses/77"}},
            },
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxJobStatusApi(HttpxTransport(http_client), base_url=BASE_URL, origin=BASE_URL)
        record = await api.get("77")

    assert record.project_link == {"href": "/api/v3/projects/9", "title": "Source Project"}


@pytest.mark.asyncio
async def test_get_record_keeps_falsy_present_project_link_instead_of_falling_back_to_source_project() -> None:
    """A falsy-but-present "project" link (here: {}) is structurally
    malformed, not absent -- the Record must carry it as-is so the Service's
    scope policy can classify and reject it, not silently replace it with an
    allowlisted "sourceProject" link."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jobId": "77",
                "payload": {
                    "_links": {
                        "project": {},
                        "sourceProject": {"href": "/api/v3/projects/9", "title": "Source Project"},
                    },
                },
                "_links": {"self": {"href": "/api/v3/job_statuses/77"}},
            },
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxJobStatusApi(HttpxTransport(http_client), base_url=BASE_URL, origin=BASE_URL)
        record = await api.get("77")

    assert record.project_link == {}


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
                "jobId": "77",
                "payload": {
                    "_links": {
                        "createdProject": {"href": "/api/v3/projects/88", "title": "Demo Copy"},
                    },
                },
                "_links": {"self": {"href": "/api/v3/job_statuses/77"}},
            },
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxJobStatusApi(HttpxTransport(http_client), base_url=BASE_URL, origin=BASE_URL)
        record = await api.get("77")

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
