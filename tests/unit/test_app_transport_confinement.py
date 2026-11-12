"""No request of the client leaves the instance origin or its API path.

The client is built the way production builds it (`_build_http_client`), so these tests prove the wiring and
not only the hook: a redirect or an absolute URL that would carry a request body, or the token, to another
origin, or out of `/api/v3`, is refused before anything is sent.

Regression guards that were green before the hook existed: the followed same-origin redirect, the download that
follows its storage redirect, the instance under a root path and an internationalized host, and the check that no
public transport method takes `extensions`. Everything else fails on the code without the hook.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
from _client_test_helpers import _base_settings

from openproject_ce_mcp.app.errors import OpenProjectServerError, TransportError
from openproject_ce_mcp.app.transport.httpx_transport import UNCONFINED, HttpxTransport
from openproject_ce_mcp.client import OpenProjectClient, _build_http_client, with_instance_page_limit

BASE = "https://op.example.com"
_PNG = b"\x89PNG-bytes"

Call = Callable[[HttpxTransport], Awaitable[Any]]

_CALLS: dict[str, Call] = {
    "get_json": lambda t: t.get_json("projects"),
    "post_json": lambda t: t.post_json("projects", json_body={"description": "private text"}),
    "patch_json": lambda t: t.patch_json("projects/1", json_body={"description": "private text"}),
    "delete": lambda t: t.delete("projects/1"),
    "delete_json": lambda t: t.delete_json("projects/1"),
    "post_text": lambda t: t.post_text("render", content=b"private text", headers={"Content-Type": "text/plain"}),
    "post_multipart": lambda t: t.post_multipart(
        "attachments", metadata={"fileName": "a.txt"}, file_name="a.txt", file_bytes=b"x", content_type="text/plain"
    ),
    "request_raw": lambda t: t.request_raw("POST", "projects/1/copy", json_body={"name": "private text"}),
}


class _Server:
    """Answers the first request on the instance with `redirect` (when given) and records every request."""

    def __init__(self, redirect: tuple[int, str] | None = None) -> None:
        self.redirect = redirect
        self.seen: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        if self.redirect is not None and len(self.seen) == 1:
            status, location = self.redirect
            return httpx.Response(status, headers={"Location": location}, request=request)
        return httpx.Response(200, json={}, request=request)


def _http(server: _Server, *, base_url: str = BASE) -> httpx.AsyncClient:
    return _build_http_client(_base_settings(base_url=base_url), httpx.MockTransport(server))


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize(
    "location",
    [
        "https://evil.example/steal",
        "http://op.example.com/api/v3/projects",
        "https://op.example.com:8443/api/v3/projects",
        "https://user:pw@op.example.com/api/v3/projects",
        "/admin/users",
        "/api/v3/../admin/users",
        "/api/v3/%2e%2e/admin/users",
    ],
)
@pytest.mark.parametrize("call", sorted(_CALLS))
@pytest.mark.asyncio
async def test_a_redirect_that_leaves_the_instance_is_refused_before_it_is_sent(
    call: str, location: str, status: int
) -> None:
    server = _Server(redirect=(status, location))
    async with _http(server) as http:
        with pytest.raises(OpenProjectServerError) as raised:
            await _CALLS[call](HttpxTransport(http))

    assert type(raised.value) is OpenProjectServerError
    assert len(server.seen) == 1
    assert server.seen[0].url.host == "op.example.com"


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("call", sorted(_CALLS))
@pytest.mark.asyncio
async def test_a_redirect_inside_the_api_path_of_the_instance_is_followed(call: str, status: int) -> None:
    server = _Server(redirect=(status, "/api/v3/job_statuses/7"))
    async with _http(server) as http:
        await _CALLS[call](HttpxTransport(http))

    assert [request.url.path for request in server.seen][-1] == "/api/v3/job_statuses/7"
    assert len(server.seen) == 2


@pytest.mark.parametrize(
    "path",
    [
        "https://evil.example/api/v3/projects",
        "http://op.example.com/api/v3/projects",
        "https://user:pw@op.example.com/api/v3/projects",
        "../../admin/users",
        "projects/../../../admin/users",
        "%2e%2e/%2e%2e/admin/users",
        "..%2f..%2fadmin/users",
    ],
)
@pytest.mark.asyncio
async def test_a_request_to_another_origin_or_out_of_the_api_path_is_refused(path: str) -> None:
    server = _Server()
    async with _http(server) as http:
        transport = HttpxTransport(http)
        with pytest.raises(OpenProjectServerError):
            await transport.get_json(path)
        with pytest.raises(OpenProjectServerError):
            await transport.post_json(path, json_body={"description": "private text"})
        with pytest.raises(OpenProjectServerError):
            await transport.get_binary(path, max_bytes=10)

    assert server.seen == []


@pytest.mark.asyncio
async def test_the_refusal_names_both_origins_and_never_a_path_or_a_query() -> None:
    server = _Server(redirect=(307, "https://evil.example:8443/steal?token=abc"))
    async with _http(server) as http:
        with pytest.raises(OpenProjectServerError) as raised:
            await HttpxTransport(http).post_json("projects", json_body={})

    message = str(raised.value)
    assert message == "OpenProject request left the instance: https://evil.example:8443 is not https://op.example.com."
    assert "steal" not in message
    assert "token" not in message


@pytest.mark.asyncio
async def test_the_refusal_of_a_path_outside_the_api_names_no_url() -> None:
    server = _Server(redirect=(307, "/admin/users?token=abc"))
    async with _http(server) as http:
        with pytest.raises(OpenProjectServerError) as raised:
            await HttpxTransport(http).post_json("projects", json_body={})

    assert str(raised.value) == "OpenProject request left the API path of the instance."


@pytest.mark.asyncio
async def test_an_instance_under_a_root_path_and_an_internationalized_host_still_works() -> None:
    server = _Server()
    async with _http(server, base_url="https://Bücher.Example:443/OP") as http:
        await HttpxTransport(http).get_json("projects")

    assert [str(request.url) for request in server.seen] == ["https://xn--bcher-kva.example/OP/api/v3/projects"]


@pytest.mark.asyncio
async def test_an_instance_under_a_root_path_refuses_the_api_path_of_the_bare_host() -> None:
    server = _Server(redirect=(307, "/api/v3/projects"))
    async with _http(server, base_url="https://op.example.com/OP") as http:
        with pytest.raises(OpenProjectServerError):
            await HttpxTransport(http).post_json("projects", json_body={})


@pytest.mark.parametrize("location", ["/api/v3x/projects", "/api/v30/projects", "/api/v3"])
@pytest.mark.asyncio
async def test_a_path_that_only_starts_like_the_api_path_is_refused(location: str) -> None:
    server = _Server(redirect=(307, location))
    async with _http(server) as http:
        with pytest.raises(OpenProjectServerError, match="API path"):
            await HttpxTransport(http).post_json("projects", json_body={})
        with pytest.raises(OpenProjectServerError, match="API path"):
            await HttpxTransport(http).get_json("../v3x/projects")


@pytest.mark.parametrize("marker", [True, 1, "1", "openproject_ce_mcp.unconfined", object()])
@pytest.mark.asyncio
async def test_a_request_that_claims_to_be_unconfined_is_still_refused(marker: object) -> None:
    server = _Server()
    async with _http(server) as http:
        with pytest.raises(OpenProjectServerError):
            await http.send(http.build_request("POST", "https://evil.example/steal", extensions={UNCONFINED: marker}))

    assert server.seen == []


@pytest.mark.asyncio
async def test_the_refusal_of_credentials_in_a_url_says_so_instead_of_naming_the_same_origin_twice() -> None:
    server = _Server(redirect=(307, "https://user:pw@op.example.com/api/v3/projects"))
    async with _http(server) as http:
        with pytest.raises(OpenProjectServerError) as raised:
            await HttpxTransport(http).post_json("projects", json_body={})

    assert str(raised.value) == "OpenProject request carried credentials in its URL."
    assert "pw" not in str(raised.value)


@pytest.mark.asyncio
async def test_the_refusal_names_an_ipv6_origin_in_brackets() -> None:
    server = _Server(redirect=(307, "http://[::1]:8081/api/v3/projects"))
    async with _http(server, base_url="http://[::1]:8080") as http:
        with pytest.raises(OpenProjectServerError) as raised:
            await HttpxTransport(http).post_json("projects", json_body={})

    assert str(raised.value) == "OpenProject request left the instance: http://[::1]:8081 is not http://[::1]:8080."


def _binary_hops(status: int, location: str) -> tuple[_Server, Callable[[], Awaitable[Any]]]:
    server = _Server(redirect=(status, location))

    async def download() -> Any:
        async with _http(server) as http:
            return await HttpxTransport(http).get_binary("attachments/5/content", max_bytes=1024)

    return server, download


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize(
    "location",
    [
        "https://bucket.example.net/signed/report.png?X-Sig=abc",
        "http://op.example.com/attachments/5/report.png",
        "https://op.example.com:8443/attachments/5/report.png",
        "/attachments/5/report.png",
    ],
)
@pytest.mark.asyncio
async def test_a_download_still_follows_its_redirect_to_a_storage_origin(status: int, location: str) -> None:
    server, download = _binary_hops(status, location)

    await download()

    assert len(server.seen) == 2
    assert str(server.seen[1].url) == (location if location.startswith("http") else f"{BASE}{location}")
    assert ("authorization" in server.seen[1].headers) == location.startswith("/")


@pytest.mark.asyncio
async def test_no_public_transport_method_lets_a_caller_mark_a_request_unconfined() -> None:
    methods = [name for name, _ in inspect.getmembers(HttpxTransport, inspect.isfunction)]

    assert "get_binary" in methods
    for name in methods:
        assert "extensions" not in inspect.signature(getattr(HttpxTransport, name)).parameters, name


@pytest.mark.asyncio
async def test_the_page_limit_probe_survives_a_refused_redirect() -> None:
    server = _Server(redirect=(307, "https://evil.example/steal"))
    settings = _base_settings()

    assert await with_instance_page_limit(settings, transport=httpx.MockTransport(server)) == settings
    assert len(server.seen) == 1


@pytest.mark.asyncio
async def test_the_legacy_client_request_path_is_confined_too() -> None:
    server = _Server(redirect=(307, "https://evil.example/steal"))
    client = OpenProjectClient(_base_settings(), transport=httpx.MockTransport(server))
    try:
        with pytest.raises(OpenProjectServerError) as raised:
            await client._request("POST", "projects", json_body={"description": "private text"})
    finally:
        await client.aclose()

    assert not isinstance(raised.value, TransportError)
    assert len(server.seen) == 1


@pytest.mark.asyncio
async def test_a_client_that_builds_its_own_transport_is_confined_too() -> None:
    http = _build_http_client(_base_settings(), None)
    try:
        assert http.event_hooks["request"]
        with pytest.raises(OpenProjectServerError):
            await http.event_hooks["request"][0](httpx.Request("POST", "https://evil.example/steal"))
    finally:
        await http.aclose()
