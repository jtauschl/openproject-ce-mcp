from __future__ import annotations

import httpx
import pytest

from openproject_ce_mcp.app.errors import OpenProjectServerError, TransportError
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler), follow_redirects=True
    )


@pytest.mark.asyncio
async def test_request_raw_returns_status_and_lowercase_headers() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/workspaces/6/favorite"
        assert request.method == "POST"
        return httpx.Response(204, headers={"X-Custom": "value"}, request=request)

    async with _client(handler) as http_client:
        transport = HttpxTransport(http_client)
        result = await transport.request_raw("POST", "workspaces/6/favorite", json_body={})

    assert result.status_code == 204
    assert result.headers["x-custom"] == "value"
    assert "X-Custom" not in result.headers
    assert result.redirect_headers == ()


@pytest.mark.asyncio
async def test_request_raw_normalizes_mixed_case_location_header() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Location": "/api/v3/projects/6/copy/status/42"}, request=request)

    async with _client(handler) as http_client:
        transport = HttpxTransport(http_client)
        result = await transport.request_raw("POST", "projects/6/copy", json_body={})

    assert result.headers["location"] == "/api/v3/projects/6/copy/status/42"


@pytest.mark.asyncio
async def test_request_raw_exposes_redirect_history_headers() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/6/copy":
            return httpx.Response(
                302,
                headers={"Location": "https://op.example.com/api/v3/projects/6/copy/status/42"},
                request=request,
            )
        return httpx.Response(200, json={"status": "in_progress"}, request=request)

    async with _client(handler) as http_client:
        transport = HttpxTransport(http_client)
        result = await transport.request_raw("POST", "projects/6/copy", json_body={})

    assert result.status_code == 200
    assert len(result.redirect_headers) == 1
    assert result.redirect_headers[0]["location"] == "https://op.example.com/api/v3/projects/6/copy/status/42"
    assert "location" not in result.headers


@pytest.mark.asyncio
async def test_request_raw_no_history_falls_back_to_final_response_headers() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Location": "/api/v3/projects/6/copy/status/42"}, request=request)

    async with _client(handler) as http_client:
        transport = HttpxTransport(http_client)
        result = await transport.request_raw("POST", "projects/6/copy", json_body={})

    assert result.redirect_headers == ()
    assert result.headers["location"] == "/api/v3/projects/6/copy/status/42"


@pytest.mark.asyncio
async def test_request_raw_raises_on_error_status() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={}, request=request)

    async with _client(handler) as http_client:
        transport = HttpxTransport(http_client)
        with pytest.raises(OpenProjectServerError):
            await transport.request_raw("POST", "workspaces/6/favorite", json_body={})


@pytest.mark.asyncio
async def test_request_raw_wraps_timeout_as_transport_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    async with _client(handler) as http_client:
        transport = HttpxTransport(http_client)
        with pytest.raises(TransportError):
            await transport.request_raw("POST", "workspaces/6/favorite", json_body={})


# --- post_raw_json (added for the Extended Metadata migration's render_text) ---
# Regression coverage added during that migration's step-6 self-audit: post_raw_json
# was initially written as a near-duplicate of _request's error-handling instead of
# sharing it, which had left these exact error paths untested.


@pytest.mark.asyncio
async def test_post_raw_json_sends_content_and_headers_and_parses_json() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v3/render/markdown"
        assert request.headers["content-type"] == "text/plain"
        assert request.content == b"**Hello**"
        return httpx.Response(200, json={"html": "<p><b>Hello</b></p>"}, request=request)

    async with _client(handler) as http_client:
        transport = HttpxTransport(http_client)
        result = await transport.post_raw_json(
            "render/markdown", content=b"**Hello**", headers={"Content-Type": "text/plain"}
        )

    assert result["html"] == "<p><b>Hello</b></p>"


@pytest.mark.asyncio
async def test_post_raw_json_raises_on_error_status() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={}, request=request)

    async with _client(handler) as http_client:
        transport = HttpxTransport(http_client)
        with pytest.raises(OpenProjectServerError):
            await transport.post_raw_json("render/markdown", content=b"x", headers={"Content-Type": "text/plain"})


@pytest.mark.asyncio
async def test_post_raw_json_wraps_timeout_as_transport_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    async with _client(handler) as http_client:
        transport = HttpxTransport(http_client)
        with pytest.raises(TransportError):
            await transport.post_raw_json("render/markdown", content=b"x", headers={"Content-Type": "text/plain"})


@pytest.mark.asyncio
async def test_post_raw_json_raises_on_invalid_json_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json", request=request)

    async with _client(handler) as http_client:
        transport = HttpxTransport(http_client)
        with pytest.raises(OpenProjectServerError):
            await transport.post_raw_json("render/markdown", content=b"x", headers={"Content-Type": "text/plain"})
