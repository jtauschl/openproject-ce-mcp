from __future__ import annotations

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_document_api import HttpxDocumentApi
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


def _document_payload(document_id: int = 1) -> dict:
    return {
        "id": document_id,
        "title": "Architecture",
        "description": {"format": "markdown", "raw": "Detailed document description content"},
        "_links": {
            "project": {"href": "/api/v3/projects/6", "title": "Demo Project"},
            "update": {"href": f"/api/v3/documents/{document_id}"},
            "attachments": {"href": f"/api/v3/documents/{document_id}/attachments"},
        },
        "_embedded": {"attachments": {"count": 2}},
        "createdAt": "2026-01-01T00:00:00Z",
    }


@pytest.mark.asyncio
async def test_list_all_sends_bounded_page_and_builds_records() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/documents"
        params = dict(request.url.params)
        assert params["offset"] == "1"
        assert params["pageSize"] == "50"
        return httpx.Response(200, json={"_embedded": {"elements": [_document_payload()]}}, request=request)

    async with _client(handler) as http_client:
        api = HttpxDocumentApi(HttpxTransport(http_client), base_url=BASE_URL)
        records, total = await api.list_all(offset=1, page_size=50)

    assert total == 1
    assert len(records) == 1
    assert records[0].summary.id == 1
    assert records[0].summary.title == "Architecture"
    assert records[0].summary.attachment_count == 2
    assert records[0].project_link == {"href": "/api/v3/projects/6", "title": "Demo Project"}
    # to_detail() is lazy -- list_all()'s per-row records must still be able
    # to produce a correct DocumentDetail on demand, it's just never called
    # by DocumentService.list() today.
    assert records[0].to_detail().id == 1


@pytest.mark.asyncio
async def test_list_all_missing_embedded_elements_returns_empty_list() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={}, request=request)

    async with _client(handler) as http_client:
        api = HttpxDocumentApi(HttpxTransport(http_client), base_url=BASE_URL)
        records, total = await api.list_all(offset=1, page_size=50)

    assert records == []
    assert total == 0


@pytest.mark.asyncio
async def test_get_builds_record_with_detail_shaped_description_and_raw_project_link() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/documents/1"
        return httpx.Response(200, json=_document_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxDocumentApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.get(1)

    assert record.summary.id == 1
    detail = record.to_detail()
    assert detail.id == 1
    assert record.summary.description == "<user-content>Detailed document description content</user-content>"
    assert detail.description == "<user-content>Detailed document description content</user-content>"
    assert detail.attachment_count == 2
    assert detail.attachments_url == f"{BASE_URL}/api/v3/documents/1/attachments"
    assert record.project_link == {"href": "/api/v3/projects/6", "title": "Demo Project"}


@pytest.mark.asyncio
async def test_get_summary_and_detail_apply_different_truncation_limits_to_same_raw_description() -> None:
    long_text = "x" * 2_000  # longer than SUBJECT_LIMIT (255) and FORMATTABLE_LIMIT (1200)
    payload = _document_payload()
    payload["description"] = {"format": "markdown", "raw": long_text}

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    async with _client(handler) as http_client:
        api = HttpxDocumentApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.get(1)

    detail = record.to_detail()
    assert record.summary.description is not None
    assert detail.description is not None
    assert len(record.summary.description) < len(detail.description)


@pytest.mark.asyncio
async def test_get_falls_back_to_html_when_raw_is_absent() -> None:
    """Regression coverage for the fallback that HttpxNewsApi's local
    _extract_formattable_text copy is missing (found during the Documents
    migration's self-review): client.py's original _extract_formattable_text
    does `value.get("raw") or value.get("html")`, so a description payload
    with only an `html` key (no `raw`) must still be extracted, not dropped.
    """
    payload = _document_payload()
    payload["description"] = {"format": "markdown", "html": "<p>HTML only content</p>"}

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    async with _client(handler) as http_client:
        api = HttpxDocumentApi(HttpxTransport(http_client), base_url=BASE_URL)
        record = await api.get(1)

    assert record.summary.description == "<user-content><p>HTML only content</p></user-content>"


@pytest.mark.asyncio
async def test_commit_update_patches_and_returns_detail() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/documents/1"
        assert request.method == "PATCH"
        return httpx.Response(200, json=_document_payload(), request=request)

    async with _client(handler) as http_client:
        api = HttpxDocumentApi(HttpxTransport(http_client), base_url=BASE_URL)
        detail = await api.commit_update(1, {"title": "Updated"})

    assert detail.id == 1
