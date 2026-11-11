"""Connection check run in a child process with one MCP entry's environment.

The child builds ``Settings`` and the client exactly as the server does, so proxy,
certificate and ``verify`` handling come from that environment, not the doctor's.
It prints one JSON line. Messages are fixed per category: a server or proxy can put
anything into an error, including the Authorization header it received.
"""

from __future__ import annotations

import asyncio
import base64
import json
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass

PROBE_TIMEOUT_SECONDS = 15.0
_MODULE = "openproject_ce_mcp.doctor.probe"


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    user: str | None = None
    category: str = ""
    message: str = ""


async def check() -> dict[str, object]:
    from ..client import (
        AuthenticationError,
        NotFoundError,
        OpenProjectClient,
        OpenProjectError,
        PermissionDeniedError,
        TransportError,
    )
    from ..config import ConfigError, Settings

    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        # Settings' own messages name variables, never their values.
        return {"ok": False, "category": "configuration_error", "message": str(exc)}
    client = OpenProjectClient(settings)
    try:
        user = await client.current_user.get_current_user()
    except AuthenticationError:
        return _failure(
            "auth_error", "authentication failed; check that OPENPROJECT_API_TOKEN is current and not revoked"
        )
    except PermissionDeniedError:
        return _failure("permission_error", "the token may not read the current user")
    except NotFoundError:
        return _failure("not_found_error", "the API was not found at this base URL")
    except TransportError as exc:
        if _is_tls_failure(exc):
            return _failure(
                "tls_error",
                "TLS/certificate error; check the server's certificate, "
                "or set SSL_CERT_FILE to the CA bundle of a trusted internal CA",
            )
        cause = exc.__cause__
        detail = f" ({type(cause).__name__})" if cause is not None else ""
        # The client's own fixed TransportError text, never server-supplied.
        if "timed out" in str(exc):
            return _failure(
                "network_error", f"the request timed out{detail}; the server is slow, or a firewall drops the packets"
            )
        return _failure(
            "network_error", f"could not reach OpenProject{detail}; check the URL and that the server is reachable"
        )
    except OpenProjectError:
        return _failure("server_error", "OpenProject answered with an error")
    finally:
        await client.aclose()
    name = None if user.name is None else _without_credentials(user.name, settings.api_token.get_secret_value())
    return {"ok": True, "user": name}


def _is_tls_failure(exc: BaseException) -> bool:
    """A TLS failure reaches here as a TransportError wrapping httpx's ConnectError, whose
    text (never an ssl.SSLError on the cause chain) carries CPython's "[SSL: ...]" marker.
    Only classified on, never shown: the text can come from the server's certificate."""
    seen: set[int] = set()
    cause: BaseException | None = exc
    while cause is not None and id(cause) not in seen:
        if "[SSL:" in str(cause):
            return True
        seen.add(id(cause))
        cause = cause.__cause__
    return False


def _without_credentials(text: str, token: str) -> str:
    """The user name is the one server text shown, so it gets the same distrust as errors."""
    for secret in (token, base64.b64encode(f"apikey:{token}".encode()).decode()):
        text = text.replace(secret, "***")
    return text


def _failure(category: str, message: str) -> dict[str, object]:
    return {"ok": False, "category": category, "message": message}


def main() -> int:
    try:
        result = asyncio.run(check())
    except Exception as exc:  # noqa: BLE001 - the parent needs one JSON line, whatever failed
        result = _failure("unexpected_error", type(exc).__name__)
    print(json.dumps(result))
    return 0


def run_connectivity_probe(env: Mapping[str, str], *, timeout: float = PROBE_TIMEOUT_SECONDS) -> ProbeResult:
    """Run the check in a child with exactly ``env``; killed after ``timeout`` seconds."""
    # An empty working directory: ``-m`` puts it first on sys.path, so modules in the
    # directory the doctor was started from cannot shadow the client's imports.
    with tempfile.TemporaryDirectory() as cwd:
        try:
            completed = subprocess.run(
                [sys.executable, "-m", _MODULE],
                cwd=cwd,
                env=dict(env),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ProbeResult(False, category="timeout", message=f"no answer within {timeout:g} s")
    return _parse_result(completed.stdout)


def _parse_result(stdout: str) -> ProbeResult:
    lines = stdout.strip().splitlines()
    try:
        data = json.loads(lines[-1]) if lines else None
    except json.JSONDecodeError:
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("ok"), bool):
        return ProbeResult(False, category="unexpected_error", message="the connection check gave no result")
    if data["ok"]:
        return ProbeResult(True, user=str(data.get("user")))
    return ProbeResult(False, category=str(data.get("category")), message=str(data.get("message")))


if __name__ == "__main__":
    sys.exit(main())
