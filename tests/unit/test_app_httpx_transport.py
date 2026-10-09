from __future__ import annotations

import httpx
import pytest

from openproject_ce_mcp.app.errors import NotFoundError, OpenProjectServerError, TransportError
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport
from openproject_ce_mcp.retry_transport import RetryTransport

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


_CREDENTIALS = {
    "authorization": _AUTH,
    "cookie": "_open_project_session=s3cr3t",
    "proxy-authorization": "Basic cHJveHk6cHc=",
    "x-api-key": "token",
}
_SAFE_HEADERS = {"accept": "application/hal+json, application/json", "user-agent": "openproject-ce-mcp/test"}


def _credentialed_client(handler) -> httpx.AsyncClient:
    """Every kind of credential a request can carry: client default headers
    (Authorization, a proxy or token header from the deployment) and a session
    cookie the jar holds for the instance."""
    cookies = httpx.Cookies()
    cookies.set("_open_project_session", "s3cr3t", domain="op.example.com")
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/",
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
        headers={
            "Authorization": _AUTH,
            "Proxy-Authorization": _CREDENTIALS["proxy-authorization"],
            "X-Api-Key": _CREDENTIALS["x-api-key"],
            "Accept": _SAFE_HEADERS["accept"],
            "User-Agent": _SAFE_HEADERS["user-agent"],
        },
        cookies=cookies,
    )


async def _hops(status: int, location: str) -> list[httpx.Request]:
    hops: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        hops.append(request)
        if len(hops) == 1:
            return httpx.Response(status, headers={"Location": location}, request=request)
        return httpx.Response(200, content=_PNG, request=request)

    async with _credentialed_client(handler) as http_client:
        result = await HttpxTransport(http_client).get_binary("attachments/5/content", max_bytes=1024)

    assert result.data == _PNG
    return hops


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize(
    "location",
    [
        "https://bucket.example.net/signed/report.png?X-Sig=abc",
        "http://op.example.com/attachments/5/report.png",
        "https://op.example.com:8443/attachments/5/report.png",
    ],
)
@pytest.mark.asyncio
async def test_get_binary_cross_origin_redirect_carries_no_credential(status: int, location: str) -> None:
    first, second = await _hops(status, location)

    assert {name: first.headers.get(name) for name in _CREDENTIALS} == _CREDENTIALS
    assert str(second.url) == location
    assert set(second.headers.keys()) == {"host", "accept", "accept-encoding", "user-agent"}
    assert second.headers["host"] == second.url.netloc.decode()
    assert {name: second.headers[name] for name in _SAFE_HEADERS} == _SAFE_HEADERS


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize(
    "location", ["/attachments/5/report.png", "https://OP.example.com:443/attachments/5/report.png"]
)
@pytest.mark.asyncio
async def test_get_binary_same_origin_redirect_keeps_every_header(status: int, location: str) -> None:
    first, second = await _hops(status, location)

    assert second.url.host == "op.example.com"
    assert second.url.path == "/attachments/5/report.png"
    assert {name: second.headers.get(name) for name in _CREDENTIALS} == _CREDENTIALS
    assert second.headers.multi_items() == first.headers.multi_items()


@pytest.mark.asyncio
async def test_get_binary_redirect_back_to_the_instance_does_not_regain_credentials() -> None:
    hops: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        hops.append(request)
        if len(hops) == 1:
            return httpx.Response(302, headers={"Location": "https://bucket.example.net/signed"}, request=request)
        if len(hops) == 2:
            return httpx.Response(302, headers={"Location": f"{BASE_URL}/attachments/5/report.png"}, request=request)
        return httpx.Response(200, content=_PNG, request=request)

    async with _credentialed_client(handler) as http_client:
        await HttpxTransport(http_client).get_binary("attachments/5/content", max_bytes=1024)

    assert hops[2].url.host == "op.example.com"
    assert set(hops[2].headers.keys()) == {"host", "accept", "accept-encoding", "user-agent"}


def _client_auth_hops(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/",
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
        auth=httpx.BasicAuth("apikey", "token"),
    )


@pytest.mark.parametrize(
    ("locations", "expected"),
    [
        (["https://bucket.example.net/signed"], [_AUTH, None]),
        (["https://bucket.example.net/signed", f"{BASE_URL}/attachments/5/report.png"], [_AUTH, None, None]),
        (["/attachments/5/report.png"], [_AUTH, _AUTH]),
    ],
)
@pytest.mark.asyncio
async def test_get_binary_applies_client_auth_only_until_the_chain_leaves_the_origin(
    locations: list[str], expected: list[str | None]
) -> None:
    seen: list[str | None] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization"))
        if len(seen) <= len(locations):
            return httpx.Response(302, headers={"Location": locations[len(seen) - 1]}, request=request)
        return httpx.Response(200, content=_PNG, request=request)

    async with _client_auth_hops(handler) as http_client:
        await HttpxTransport(http_client).get_binary("attachments/5/content", max_bytes=1024)

    assert seen == expected


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


# --- get_binary through RetryTransport -----------------------------------------
#
# The production client wraps its httpx transport in RetryTransport whenever
# OPENPROJECT_MAX_RETRIES > 0 (the default), so every get_binary above really
# runs one layer higher than it is tested. get_binary is the only method that
# streams its response and walks its own redirect chain, and RetryTransport
# closes and re-sends a response underneath it -- these tests pin that the two
# compose. Still httpx.MockTransport: no Docker, no live instance.


def _retry_client(handler, **kwargs) -> httpx.AsyncClient:
    """`_client`, with a RetryTransport between the client and the mock. The
    tiny base_delay keeps the backoff out of the test's runtime."""
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/api/v3/",
        transport=RetryTransport(httpx.MockTransport(handler), max_retries=3, base_delay=0.001),
        follow_redirects=True,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_get_binary_through_retry_transport_retries_a_transient_status() -> None:
    """A 503 on the download is retried by the layer below and get_binary sees
    only the successful attempt -- it must not report the 503 as an error, nor
    read the abandoned response's body."""
    attempts: list[int] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) < 3:
            return httpx.Response(503, content=b"try again", request=request)
        return httpx.Response(200, content=_PNG, headers={"Content-Type": "image/png"}, request=request)

    async with _retry_client(handler) as http_client:
        result = await HttpxTransport(http_client).get_binary("attachments/5/content", max_bytes=1024)

    assert result.data == _PNG
    assert result.content_type == "image/png"
    assert result.truncated is False
    assert len(attempts) == 3


@pytest.mark.parametrize(
    "credentials", [{"headers": {"Authorization": _AUTH}}, {"auth": httpx.BasicAuth("apikey", "token")}]
)
@pytest.mark.asyncio
async def test_get_binary_through_retry_transport_keeps_the_byte_limit_on_a_retried_redirect(
    credentials: dict,
) -> None:
    """The full chain in one call: a redirect get_binary follows itself, a
    transient failure on the target that the retry layer absorbs, and the byte
    cap still enforced on the body that finally arrives."""
    seen: list[tuple[str, str | None]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.host, request.headers.get("authorization")))
        if request.url.host == "op.example.com":
            return httpx.Response(
                302, headers={"Location": "https://bucket.example.net/signed/report.png"}, request=request
            )
        if len([host for host, _ in seen if host == "bucket.example.net"]) == 1:
            return httpx.Response(503, content=b"try again", request=request)
        return httpx.Response(200, content=b"abcdefghijklmnop", request=request)

    async with _retry_client(handler, **credentials) as http_client:
        result = await HttpxTransport(http_client).get_binary("attachments/5/content", max_bytes=10)

    assert result.data == b"abcdefghij"
    assert result.truncated is True
    # The retried hop is the cross-origin one: it must not regain the
    # credentials the redirect stripped just because it is sent twice.
    assert seen == [
        ("op.example.com", _AUTH),
        ("bucket.example.net", None),
        ("bucket.example.net", None),
    ]


@pytest.mark.asyncio
async def test_get_binary_through_retry_transport_maps_a_persistent_transient_status() -> None:
    """Retries exhausted: the last response is handed up as-is, so get_binary
    maps its status the same way it maps any error status."""
    attempts: list[int] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(503, json={"message": "unavailable"}, request=request)

    async with _retry_client(handler) as http_client:
        with pytest.raises(OpenProjectServerError):
            await HttpxTransport(http_client).get_binary("attachments/5/content", max_bytes=1024)

    assert len(attempts) == 4
