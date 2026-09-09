from __future__ import annotations

import httpx
import pytest

from openproject_ce_mcp.app.errors import NotFoundError, OpenProjectServerError, TransportError
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


# --- get_binary --------------------------------------------------------------

_AUTH = "Basic YXBpa2V5OnRva2Vu"
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24


def _auth_client(handler) -> httpx.AsyncClient:
    """Like _client, but carrying an Authorization default header the way
    OpenProjectClient's real httpx.AsyncClient does -- the redirect tests
    below are about what happens to exactly that header."""
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/",
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
        headers={"Authorization": _AUTH},
    )


@pytest.mark.asyncio
async def test_get_binary_returns_body_and_served_content_type() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/v3/attachments/5/content"
        return httpx.Response(200, content=_PNG, headers={"Content-Type": "image/png"}, request=request)

    async with _client(handler) as http_client:
        result = await HttpxTransport(http_client).get_binary("attachments/5/content", max_bytes=1024)

    assert result.data == _PNG
    assert result.content_type == "image/png"
    assert result.truncated is False


@pytest.mark.asyncio
async def test_get_binary_body_exactly_at_limit_is_not_truncated() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"0123456789", request=request)

    async with _client(handler) as http_client:
        result = await HttpxTransport(http_client).get_binary("attachments/5/content", max_bytes=10)

    assert result.data == b"0123456789"
    assert result.truncated is False
    assert result.content_type is None


@pytest.mark.asyncio
async def test_get_binary_stops_at_limit_and_reports_truncation() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"abcdefghijklmnop", request=request)

    async with _client(handler) as http_client:
        result = await HttpxTransport(http_client).get_binary("attachments/5/content", max_bytes=10)

    assert result.data == b"abcdefghij"
    assert result.truncated is True


@pytest.mark.asyncio
async def test_get_binary_same_origin_redirect_keeps_authorization() -> None:
    """Local-filesystem storage: OpenProject 302s to a path on its own host,
    which still needs the instance credentials to serve the file."""
    seen: list[tuple[str, str | None]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, request.headers.get("authorization")))
        if request.url.path == "/api/v3/attachments/5/content":
            return httpx.Response(302, headers={"Location": "/attachments/5/report.png"}, request=request)
        return httpx.Response(200, content=_PNG, headers={"Content-Type": "image/png"}, request=request)

    async with _auth_client(handler) as http_client:
        result = await HttpxTransport(http_client).get_binary("attachments/5/content", max_bytes=1024)

    assert result.data == _PNG
    assert seen == [
        ("/api/v3/attachments/5/content", _AUTH),
        ("/attachments/5/report.png", _AUTH),
    ]


@pytest.mark.asyncio
async def test_get_binary_cross_origin_redirect_drops_authorization_but_follows() -> None:
    """S3-backed storage: the redirect target is a pre-signed URL on a foreign
    host. It must be followed (or S3 instances cannot serve any attachment),
    but the instance's Basic credentials must not travel to that host."""
    seen: list[tuple[str, str | None]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.host, request.headers.get("authorization")))
        if request.url.host == "op.example.com":
            return httpx.Response(
                302, headers={"Location": "https://bucket.example.net/signed/report.png?X-Sig=abc"}, request=request
            )
        assert request.url.params["X-Sig"] == "abc"
        return httpx.Response(200, content=_PNG, headers={"Content-Type": "application/octet-stream"}, request=request)

    async with _auth_client(handler) as http_client:
        result = await HttpxTransport(http_client).get_binary("attachments/5/content", max_bytes=1024)

    assert result.data == _PNG
    assert result.content_type == "application/octet-stream"
    assert seen == [("op.example.com", _AUTH), ("bucket.example.net", None)]


@pytest.mark.asyncio
async def test_get_binary_gives_up_after_too_many_redirects() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": str(request.url)}, request=request)

    async with _client(handler) as http_client:
        with pytest.raises(OpenProjectServerError, match="too many times"):
            await HttpxTransport(http_client).get_binary("attachments/5/content", max_bytes=1024)


@pytest.mark.asyncio
async def test_get_binary_maps_error_status_like_json_requests() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404, json={"errorIdentifier": "urn:openproject-org:api:v3:errors:NotFound"}, request=request
        )

    async with _client(handler) as http_client:
        with pytest.raises(NotFoundError):
            await HttpxTransport(http_client).get_binary("attachments/5/content", max_bytes=1024)


@pytest.mark.asyncio
async def test_get_binary_wraps_timeout_as_transport_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    async with _client(handler) as http_client:
        with pytest.raises(TransportError):
            await HttpxTransport(http_client).get_binary("attachments/5/content", max_bytes=1024)
