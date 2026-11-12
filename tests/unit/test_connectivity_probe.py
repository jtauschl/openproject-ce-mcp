"""The connection check child: it uses the entry's environment, not the doctor's."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import ssl
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from _loopback_http import connect_proxy, serve

from openproject_ce_mcp.doctor import probe as connectivity_probe
from openproject_ce_mcp.doctor.probe import ProbeResult, _parse_result, run_connectivity_probe

# Free of "token" and "authenticate", which would turn a 403 into an authentication error.
SENTINEL = "sentinel-secret-probe-546"


def _child_env(**values: str) -> dict[str, str]:
    env = {name: os.environ[name] for name in ("HOME", "PATH", "SYSTEMROOT") if name in os.environ}
    env.update(
        OPENPROJECT_API_TOKEN=SENTINEL,
        OPENPROJECT_MAX_RETRIES="0",
        OPENPROJECT_TIMEOUT="5",
    )
    env.update(values)
    return env


async def test_the_entry_https_proxy_is_used_while_the_doctor_has_none(without_proxies, server_ssl_context):
    async with serve([200], server_ssl_context) as server, connect_proxy(server.port) as proxy:
        env = _child_env(
            OPENPROJECT_BASE_URL="https://op.invalid",
            OPENPROJECT_VERIFY_SSL="false",
            HTTPS_PROXY=f"http://127.0.0.1:{proxy.port}",
        )
        result = await asyncio.to_thread(run_connectivity_probe, env)

    assert "HTTPS_PROXY" not in os.environ
    assert result == ProbeResult(True, user="Test User")
    assert proxy.destinations == ["op.invalid:443"]


async def test_verify_ssl_false_accepts_the_untrusted_certificate(without_proxies, server_ssl_context):
    async with serve([200], server_ssl_context) as server:
        base = f"https://127.0.0.1:{server.port}"
        accepted = await asyncio.to_thread(
            run_connectivity_probe, _child_env(OPENPROJECT_BASE_URL=base, OPENPROJECT_VERIFY_SSL="false", NO_PROXY="*")
        )
        rejected = await asyncio.to_thread(
            run_connectivity_probe, _child_env(OPENPROJECT_BASE_URL=base, OPENPROJECT_VERIFY_SSL="true", NO_PROXY="*")
        )

    assert accepted == ProbeResult(True, user="Test User")
    assert rejected.ok is False and rejected.category == "tls_error"


async def test_the_token_is_absent_from_every_result(without_proxies):
    async with serve([401]) as server:
        result = await asyncio.to_thread(
            run_connectivity_probe, _child_env(OPENPROJECT_BASE_URL=f"http://127.0.0.1:{server.port}", NO_PROXY="*")
        )

    assert result.category == "auth_error"
    assert SENTINEL not in repr(result)


@pytest.mark.parametrize("status", [401, 403, 404, 422, 500])
async def test_a_server_echoing_the_credentials_never_reaches_the_result(without_proxies, status):
    async with serve([status], echo_credentials=True) as server:
        env = _child_env(OPENPROJECT_BASE_URL=f"http://127.0.0.1:{server.port}", NO_PROXY="*")
        result = await asyncio.to_thread(run_connectivity_probe, env)

    assert result.ok is False
    assert SENTINEL not in repr(result)
    assert "Basic " not in repr(result) and "Authorization" not in repr(result)


async def test_a_user_name_echoing_the_credentials_is_shown_without_them(without_proxies):
    async with serve([200], echo_credentials=True) as server:
        env = _child_env(OPENPROJECT_BASE_URL=f"http://127.0.0.1:{server.port}", NO_PROXY="*")
        result = await asyncio.to_thread(run_connectivity_probe, env)

    assert result.ok is True
    assert result.user is not None and "apikey:***" in result.user
    assert SENTINEL not in result.user
    assert base64.b64encode(f"apikey:{SENTINEL}".encode()).decode() not in result.user


@asynccontextmanager
async def _silent_server() -> AsyncIterator[int]:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.read()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    async with server:
        yield server.sockets[0].getsockname()[1]


async def test_a_child_that_does_not_finish_is_killed_at_the_wall_clock_limit(without_proxies):
    async with _silent_server() as port:
        env = _child_env(OPENPROJECT_BASE_URL=f"http://127.0.0.1:{port}", OPENPROJECT_TIMEOUT="60", NO_PROXY="*")
        started = time.monotonic()
        result = await asyncio.to_thread(run_connectivity_probe, env, timeout=2.0)

    assert result == ProbeResult(False, category="timeout", message="no answer within 2 s")
    assert time.monotonic() - started < 10


# ── in-process, for the classification ─────────────────────────────────────────


async def test_check_reports_configuration_errors(monkeypatch):
    monkeypatch.delenv("OPENPROJECT_API_TOKEN", raising=False)
    monkeypatch.setenv("OPENPROJECT_BASE_URL", "https://op.invalid")

    assert await connectivity_probe.check() == {
        "ok": False,
        "category": "configuration_error",
        "message": "OPENPROJECT_API_TOKEN is required; or set OPENPROJECT_API_TOKEN_VAR to the name of the variable that holds it.",
    }


@pytest.mark.parametrize(
    ("status", "category"),
    [(200, None), (401, "auth_error"), (403, "permission_error"), (500, "server_error")],
)
async def test_check_classifies_the_answer(monkeypatch, without_proxies, status, category):
    async with serve([status]) as server:
        monkeypatch.setenv("OPENPROJECT_BASE_URL", f"http://127.0.0.1:{server.port}")
        monkeypatch.setenv("OPENPROJECT_API_TOKEN", SENTINEL)
        monkeypatch.setenv("OPENPROJECT_MAX_RETRIES", "0")
        result = await connectivity_probe.check()

    if category is None:
        assert result == {"ok": True, "user": "Test User"}
    else:
        assert result["category"] == category
    assert SENTINEL not in json.dumps(result)


async def test_check_tells_a_refused_connection_from_a_timeout(monkeypatch, without_proxies):
    async with _silent_server() as port:
        monkeypatch.setenv("OPENPROJECT_BASE_URL", f"http://127.0.0.1:{port}")
        monkeypatch.setenv("OPENPROJECT_API_TOKEN", SENTINEL)
        monkeypatch.setenv("OPENPROJECT_MAX_RETRIES", "0")
        monkeypatch.setenv("OPENPROJECT_TIMEOUT", "1")
        timed_out = await connectivity_probe.check()
    # The port is closed once the server is gone, so this connection is refused.
    refused = await connectivity_probe.check()

    assert timed_out["category"] == refused["category"] == "network_error"
    assert str(timed_out["message"]).startswith("the request timed out (ReadTimeout)")
    assert str(refused["message"]).startswith("could not reach OpenProject (ConnectError)")


def test_main_prints_one_json_line_even_when_the_check_crashes(monkeypatch, capsys):
    async def crash() -> dict[str, object]:
        raise ssl.SSLError("boom")

    monkeypatch.setattr(connectivity_probe, "check", crash)

    assert connectivity_probe.main() == 0
    assert json.loads(capsys.readouterr().out) == {"ok": False, "category": "unexpected_error", "message": "SSLError"}


@pytest.mark.parametrize("stdout", ["", "not json", "[1]", '{"ok": "yes"}'])
def test_unusable_child_output_is_an_unexpected_error(stdout):
    assert _parse_result(stdout) == ProbeResult(
        False, category="unexpected_error", message="the connection check gave no result"
    )


def test_last_json_line_wins_over_earlier_noise():
    assert _parse_result('warning\n{"ok": true, "user": "U"}\n') == ProbeResult(True, user="U")
