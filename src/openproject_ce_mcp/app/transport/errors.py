"""HTTP-status/HAL-error-payload -> typed exception mapping (ADR 0001, tier 2).

Imports exception types from the package-root shared kernel (app/errors.py), not
defined here -- keeps this module httpx-free (only app/transport/httpx_transport.py
may import httpx), and keeps Policies free to raise these same types without
importing from transport/ (which would itself be a layering violation).
"""

from __future__ import annotations

import logging
from typing import Any

from ..errors import (
    AuthenticationError,
    InvalidInputError,
    NotFoundError,
    OpenProjectServerError,
    PermissionDeniedError,
)

LOGGER = logging.getLogger(__name__)


def raise_for_status(status_code: int, payload: dict[str, Any] | None) -> None:
    """Tier-2 mapper (ADR 0001): HTTP status + HAL error payload -> typed exception.

    Verbatim port of client.py's `_raise_for_status` body, reshaped to take
    (status_code, payload) instead of an httpx.Response so this module stays
    httpx-free. Callers (HttpxTransport) extract status_code/payload from the
    real response before calling this.
    """
    if status_code < 400:
        return

    payload = payload or {}
    message = str(payload.get("message") or "").strip()
    if status_code == 401:
        raise AuthenticationError("OpenProject authentication failed.")
    if status_code == 403:
        lowered = message.lower()
        if "token" in lowered or "authenticate" in lowered:
            raise AuthenticationError("OpenProject authentication failed.")
        raise PermissionDeniedError("OpenProject denied access to this resource.")
    if status_code == 404:
        raise NotFoundError("OpenProject resource not found.")
    if status_code in {400, 409, 422}:
        raise InvalidInputError(message or "OpenProject rejected the request.")
    if 500 <= status_code < 600:
        LOGGER.warning("OpenProject server error: status=%s", status_code)
        raise OpenProjectServerError("OpenProject returned a server error.")
    raise OpenProjectServerError(f"OpenProject request failed with status {status_code}.")
