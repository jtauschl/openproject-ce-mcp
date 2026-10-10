from __future__ import annotations

import asyncio
import json
import ssl
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace

import pytest
import trustme
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import TransportError
from openproject_ce_mcp.client import OpenProjectClient
from openproject_ce_mcp.config import Settings

_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")
_USER = {"_type": "User", "id": 1, "name": "Test User", "login": "test"}


@dataclass
class _Server:
    port: int
    statuses: list[int]
    request_targets: list[str] = field(default_factory=list)


@asynccontextmanager
async def _serve(statuses: list[int], ssl_context: ssl.SSLContext | None = None) -> AsyncIterator[_Server]:
    server_state = _Server(port=0, statuses=statuses)

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await reader.readuntil(b"\r\n\r\n")
        except (asyncio.IncompleteReadError, ConnectionResetError, ssl.SSLError):
            writer.close()
            return
        server_state.request_targets.append(head.split(b" ", 2)[1].decode())
        status = server_state.statuses.pop(0) if len(server_state.statuses) > 1 else server_state.statuses[0]
        body = json.dumps(_USER).encode()
        writer.write(
            f"HTTP/1.1 {status} X\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
            + body
        )
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0, ssl=ssl_context)
    server_state.port = server.sockets[0].getsockname()[1]
    async with server:
        yield server_state


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    while data := await reader.read(65536):
        writer.write(data)
        await writer.drain()


async def _relay(
    client: tuple[asyncio.StreamReader, asyncio.StreamWriter],
    upstream: tuple[asyncio.StreamReader, asyncio.StreamWriter],
) -> None:
    # Closing only the side that ended leaves the other one open, and a TLS
    # server then waits out its 30-second shutdown timeout for the peer.
    pipes = [
        asyncio.create_task(_pipe(client[0], upstream[1])),
        asyncio.create_task(_pipe(upstream[0], client[1])),
    ]
    await asyncio.wait(pipes, return_when=asyncio.FIRST_COMPLETED)
    for pipe in pipes:
        pipe.cancel()
    client[1].close()
    upstream[1].close()


@dataclass
class _Proxy:
    port: int
    destinations: list[str] = field(default_factory=list)


@asynccontextmanager
async def _socks5_proxy(forward_port: int) -> AsyncIterator[_Proxy]:
    """Relays every destination to `forward_port`, so tests can name hosts that do not resolve."""
    proxy_state = _Proxy(port=0)

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        _, method_count = await reader.readexactly(2)
        await reader.readexactly(method_count)
        writer.write(b"\x05\x00")
        _, _, _, address_type = await reader.readexactly(4)
        assert address_type == 3, "the client sends the host name, not a resolved address"
        host = (await reader.readexactly((await reader.readexactly(1))[0])).decode()
        port = int.from_bytes(await reader.readexactly(2), "big")
        proxy_state.destinations.append(f"{host}:{port}")
        upstream_reader, upstream_writer = await asyncio.open_connection("127.0.0.1", forward_port)
        writer.write(b"\x05\x00\x00\x01" + bytes(6))
        await writer.drain()
        await _relay((reader, writer), (upstream_reader, upstream_writer))

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    proxy_state.port = server.sockets[0].getsockname()[1]
    async with server:
        yield proxy_state


@asynccontextmanager
async def _connect_proxy(forward_port: int) -> AsyncIterator[_Proxy]:
    """Relays every destination to `forward_port`, so tests can name hosts that do not resolve."""
    proxy_state = _Proxy(port=0)

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = await reader.readuntil(b"\r\n\r\n")
        method, destination, _ = head.split(b" ", 2)
        assert method == b"CONNECT"
        proxy_state.destinations.append(destination.decode())
        upstream_reader, upstream_writer = await asyncio.open_connection("127.0.0.1", forward_port)
        writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        await writer.drain()
        await _relay((reader, writer), (upstream_reader, upstream_writer))

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    proxy_state.port = server.sockets[0].getsockname()[1]
    async with server:
        yield proxy_state


@pytest.fixture
def without_proxies(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _PROXY_VARS:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
    # A set NO_PROXY keeps urllib from falling back to the OS proxy settings.
    monkeypatch.setenv("NO_PROXY", "*")


@pytest.fixture
def ca() -> trustme.CA:
    return trustme.CA()


@pytest.fixture
def server_ssl_context(ca: trustme.CA) -> ssl.SSLContext:
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ca.issue_cert("127.0.0.1").configure_cert(context)
    return context


def _settings(base_url: str, **overrides: object) -> Settings:
    return replace(make_settings(), base_url=base_url, retry_base_delay=0.0, retry_max_delay=0.0, **overrides)


async def _get_current_user_name(settings: Settings) -> str:
    client = OpenProjectClient(settings)
    try:
        user = await client.current_user.get_current_user()
    finally:
        await client.aclose()
    return user.name


@pytest.mark.parametrize("max_retries", [0, 3])
async def test_verify_ssl_false_accepts_an_untrusted_certificate(
    without_proxies: None, server_ssl_context: ssl.SSLContext, max_retries: int
) -> None:
    async with _serve([200], server_ssl_context) as server:
        settings = _settings(f"https://127.0.0.1:{server.port}", verify_ssl=False, max_retries=max_retries)

        assert await _get_current_user_name(settings) == "Test User"


@pytest.mark.parametrize("max_retries", [0, 3])
async def test_verify_ssl_true_rejects_an_untrusted_certificate(
    without_proxies: None, server_ssl_context: ssl.SSLContext, max_retries: int
) -> None:
    async with _serve([200], server_ssl_context) as server:
        settings = _settings(f"https://127.0.0.1:{server.port}", verify_ssl=True, max_retries=max_retries)

        with pytest.raises(TransportError) as raised:
            await _get_current_user_name(settings)

        assert "CERTIFICATE_VERIFY_FAILED" in str(raised.value.__cause__)


@pytest.mark.parametrize("max_retries", [0, 3])
async def test_requests_go_through_the_proxy_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, without_proxies: None, max_retries: int
) -> None:
    async with _serve([200]) as proxy:
        monkeypatch.delenv("NO_PROXY")
        monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{proxy.port}")
        settings = _settings("http://op.invalid", max_retries=max_retries)

        assert await _get_current_user_name(settings) == "Test User"
        assert proxy.request_targets == ["http://op.invalid/api/v3/users/me"]


async def test_retries_apply_to_requests_through_the_proxy(
    monkeypatch: pytest.MonkeyPatch, without_proxies: None
) -> None:
    async with _serve([503, 200]) as proxy:
        monkeypatch.delenv("NO_PROXY")
        monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{proxy.port}")
        settings = _settings("http://op.invalid", max_retries=1)

        assert await _get_current_user_name(settings) == "Test User"
        assert len(proxy.request_targets) == 2


async def test_retries_apply_to_direct_requests(without_proxies: None) -> None:
    async with _serve([503, 200]) as server:
        settings = _settings(f"http://127.0.0.1:{server.port}", max_retries=1)

        assert await _get_current_user_name(settings) == "Test User"
        assert server.request_targets == ["/api/v3/users/me", "/api/v3/users/me"]


@pytest.mark.parametrize("max_retries", [0, 3])
async def test_requests_go_through_a_socks_proxy_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, without_proxies: None, max_retries: int
) -> None:
    async with _serve([200]) as server, _socks5_proxy(server.port) as proxy:
        monkeypatch.delenv("NO_PROXY")
        monkeypatch.setenv("ALL_PROXY", f"socks5://127.0.0.1:{proxy.port}")
        settings = _settings("http://op.invalid", max_retries=max_retries)

        assert await _get_current_user_name(settings) == "Test User"
        assert proxy.destinations == ["op.invalid:80"]
        assert server.request_targets == ["/api/v3/users/me"]


async def test_no_proxy_hosts_bypass_the_proxy_and_keep_retries(
    monkeypatch: pytest.MonkeyPatch, without_proxies: None
) -> None:
    async with _serve([200]) as proxy, _serve([503, 200]) as server:
        monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{proxy.port}")
        monkeypatch.setenv("NO_PROXY", "127.0.0.1")
        settings = _settings(f"http://127.0.0.1:{server.port}", max_retries=1)

        assert await _get_current_user_name(settings) == "Test User"
        assert proxy.request_targets == []
        assert server.request_targets == ["/api/v3/users/me", "/api/v3/users/me"]


async def test_https_requests_tunnel_through_the_proxy_with_verify_ssl_and_retries(
    monkeypatch: pytest.MonkeyPatch, without_proxies: None, server_ssl_context: ssl.SSLContext
) -> None:
    async with _serve([503, 200], server_ssl_context) as server, _connect_proxy(server.port) as proxy:
        monkeypatch.delenv("NO_PROXY")
        monkeypatch.setenv("HTTPS_PROXY", f"http://127.0.0.1:{proxy.port}")
        settings = _settings("https://op.invalid", verify_ssl=False, max_retries=1)

        assert await _get_current_user_name(settings) == "Test User"
        assert proxy.destinations == ["op.invalid:443", "op.invalid:443"]
        assert server.request_targets == ["/api/v3/users/me", "/api/v3/users/me"]
