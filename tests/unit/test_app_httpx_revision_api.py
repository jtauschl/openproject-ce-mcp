from __future__ import annotations

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_revision_api import HttpxRevisionApi
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _revision(revision_id: int = 3, **overrides: object) -> dict:
    payload: dict = {
        "_type": "Revision",
        "id": revision_id,
        "identifier": "a1b2c3d4e5f6",
        "formattedIdentifier": "a1b2c3d4",
        "authorName": "Ada <ada@example.com>",
        "message": {"format": "plain", "raw": "Fix the login", "html": "<p>Fix the login</p>"},
        "createdAt": "2026-10-01T10:00:00Z",
        "_links": {
            "project": {"href": "/api/v3/projects/6", "title": "Demo"},
            "showRevision": {"href": "/projects/demo/repository/revisions/a1b2c3d4e5f6"},
        },
    }
    payload.update(overrides)
    return payload


async def _list(*elements: dict, text_limit: int | None = 500):
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/v3/work_packages/42/revisions"
        return httpx.Response(200, json={"_embedded": {"elements": list(elements)}}, request=request)

    async with _client(handler) as http_client:
        return await HttpxRevisionApi(HttpxTransport(http_client, redact_server_text=False)).list_for_work_package(
            42, text_limit=text_limit
        )


@pytest.mark.asyncio
async def test_list_reads_the_work_package_revisions_route_and_maps_the_fields() -> None:
    records = await _list(_revision())

    summary = records[0].summary
    assert (summary.id, summary.identifier, summary.formatted_identifier) == (3, "a1b2c3d4e5f6", "a1b2c3d4")
    assert (summary.project_id, summary.project) == (6, "Demo")
    assert summary.created_at == "2026-10-01T10:00:00Z"
    assert records[0].project_link == {"href": "/api/v3/projects/6", "title": "Demo"}


@pytest.mark.asyncio
async def test_the_author_name_and_message_come_from_the_repository_and_are_delimited() -> None:
    summary = (await _list(_revision()))[0].summary

    assert summary.author_name == "<user-content>Ada <ada@example.com></user-content>"
    assert summary.message == "<user-content>Fix the login</user-content>"


@pytest.mark.asyncio
async def test_a_long_message_is_cut_and_reports_its_real_length() -> None:
    summary = (await _list(_revision(message={"raw": "m" * 600}), text_limit=100))[0].summary

    assert summary.message_truncated is True
    assert summary.message_length == 600


@pytest.mark.asyncio
async def test_a_revision_without_a_project_link_keeps_no_project_and_no_link() -> None:
    record = (await _list(_revision(_links={})))[0]

    assert record.project_link is None
    assert (record.summary.project_id, record.summary.project) == (None, None)


@pytest.mark.asyncio
async def test_an_empty_collection_is_an_empty_list() -> None:
    assert await _list() == []
