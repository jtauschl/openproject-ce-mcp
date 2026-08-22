"""HTTP-status/HAL-error-payload -> typed exception mapping (tier 2).

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


def _combined_message(payload: dict[str, Any]) -> str:
    """The top-level `message` alone is a generic, useless summary
    ("Multiple field constraints have been violated.") when OpenProject
    wraps several validation failures in a `MultipleErrors` HAL error --
    the real per-field detail lives in `_embedded.errors[]`, each itself a
    full Error payload with its own `message`. A two-provider storage create
    with an Enterprise-gate violation AND an unrelated field error returns
    exactly this shape, and without this, InvalidInputError only ever surfaced
    "Multiple field constraints have been violated." with no way for a
    caller (or a test asserting on the message) to see which fields, or
    that the Enterprise gate was even involved.

    Falls back to the top-level message alone (or "" if absent) when there
    is no `_embedded.errors` list, or it's empty -- the common single-error
    case is unaffected by this change.
    """
    message = str(payload.get("message") or "").strip()
    embedded = payload.get("_embedded")
    errors = embedded.get("errors") if isinstance(embedded, dict) else None
    if not isinstance(errors, list) or not errors:
        return message
    detail_messages = [
        str(err.get("message")).strip()
        for err in errors
        if isinstance(err, dict) and str(err.get("message") or "").strip()
    ]
    if not detail_messages:
        return message
    details = "; ".join(detail_messages)
    return f"{message} ({details})" if message else details


def raise_for_status(status_code: int, payload: dict[str, Any] | None) -> None:
    """Tier-2 mapper: HTTP status + HAL error payload -> typed exception.

    Takes (status_code, payload) rather than an httpx.Response so this module
    stays httpx-free. Callers (HttpxTransport) extract status_code/payload from
    the real response before calling this.
    """
    if status_code < 400:
        return

    payload = payload or {}
    message = _combined_message(payload)
    if status_code == 401:
        raise AuthenticationError("OpenProject authentication failed.")
    if status_code == 403:
        # Classify on the top-level message alone, not the combined one: an
        # embedded sub-error unrelated to auth (e.g. an Enterprise-gate message
        # that happens to mention "token") could otherwise misclassify a real
        # PermissionDeniedError as AuthenticationError.
        top_level_message = str(payload.get("message") or "").strip().lower()
        if "token" in top_level_message or "authenticate" in top_level_message:
            raise AuthenticationError("OpenProject authentication failed.")
        detail = f" ({message})" if message else ""
        raise PermissionDeniedError(f"OpenProject denied access to this resource.{detail}")
    if status_code == 404:
        raise NotFoundError("OpenProject resource not found.")
    if status_code in {400, 409, 422}:
        raise InvalidInputError(message or "OpenProject rejected the request.")
    if 500 <= status_code < 600:
        LOGGER.warning("OpenProject server error: status=%s", status_code)
        raise OpenProjectServerError("OpenProject returned a server error.")
    raise OpenProjectServerError(f"OpenProject request failed with status {status_code}.")
