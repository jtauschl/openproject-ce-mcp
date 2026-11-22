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
    GENERIC_REJECTION,
    VERBATIM_CODES,
    AuthenticationError,
    ConflictError,
    InvalidInputError,
    NotFoundError,
    OpenProjectPermissionDeniedError,
    OpenProjectServerError,
    RateLimitedError,
    ServerErrorEntry,
    render_entries,
)
from ..form_result import error_attribute, error_code

LOGGER = logging.getLogger(__name__)


def _entry(error: dict[str, Any]) -> ServerErrorEntry:
    return ServerErrorEntry(
        attribute=error_attribute(error), code=error_code(error), message=str(error.get("message") or "").strip()
    )


def _error_objects(payload: dict[str, Any]) -> list[dict[str, Any]]:
    embedded = payload.get("_embedded")
    nested = embedded.get("errors") if isinstance(embedded, dict) else None
    return [item for item in nested if isinstance(item, dict)] if isinstance(nested, list) else []


def parse_error(payload: dict[str, Any]) -> tuple[tuple[ServerErrorEntry, ...], str]:
    """The entries of a server error and the wrapper message above them.

    OpenProject wraps several violations in a `MultipleErrors` HAL error: the real per-field detail lives in
    `_embedded.errors[]`, each itself a full Error payload with its own message, identifier and
    `_embedded.details.attribute`, and the top-level message is a generic summary kept as the wrapper. A single
    error is one entry and has no wrapper."""
    top = str(payload.get("message") or "").strip()
    entries = tuple(_entry(err) for err in _error_objects(payload) if str(err.get("message") or "").strip())
    if entries:
        return entries, top
    return (_entry(payload),) if top else (), ""


def _server_text(payload: dict[str, Any], *, redact: bool) -> tuple[str, tuple[ServerErrorEntry, ...], str]:
    entries, top = parse_error(payload)
    if redact and error_code(payload) not in VERBATIM_CODES:
        return "", entries, top
    return render_entries(entries, top=top), entries, top


def _denied(server_text: str) -> str:
    """The denial sentence, with the server's text after it unless there is none or a render has replaced it by
    the generic rejection (an attribute-less 403 while a hide is active), which says nothing the sentence does not."""
    sentence = "OpenProject denied access to this resource."
    return f"{sentence} ({server_text})" if server_text and server_text != GENERIC_REJECTION else sentence


def _rejected(server_text: str) -> str:
    return server_text or GENERIC_REJECTION


def _conflict(server_text: str) -> str:
    return server_text or "OpenProject rejected the request due to a conflict."


def _validation(payload: dict[str, Any], *, redact: bool) -> InvalidInputError | None:
    """The 422: a leading header of OpenProject's error classes, then the messages.

    The header lists `Code (attribute)` pairs (the top-level error first, unless it is the generic
    `MultipleErrors` wrapper, then each nested error in order; a pair that fails the shape check is
    skipped and identical pairs appear once), followed by `": "` and the messages. A consumer reads only
    that anchored header, so text inside a message cannot add to it. The attribute stays in the header while
    a hide is active (an API name, as the key of `validation_errors`); only the messages are redacted. Without
    any well-formed code the text is the plain one (`_server_text`), which keeps a non-OpenProject body from
    looking like a rendered one; `None` then."""
    wrapper = error_code(payload) == "MultipleErrors"
    sources = ([] if wrapper else [payload]) + _error_objects(payload)
    pairs = dict.fromkeys(
        (code, error_attribute(source)) for source in sources if (code := error_code(source)) is not None
    )
    if not pairs:
        return None
    header = ", ".join(f"{code} ({attribute})" if attribute else code for code, attribute in pairs)
    entries = tuple(_entry(source) for source in sources if str(source.get("message") or "").strip())

    def compose(server_text: str) -> str:
        return f"{header}: {server_text or GENERIC_REJECTION}"

    verbatim = error_code(payload) in VERBATIM_CODES
    text = "" if redact and not verbatim else render_entries(entries)
    return InvalidInputError(compose(text), entries=entries, compose=compose)


def raise_for_status(status_code: int, payload: dict[str, Any] | None, *, redact_server_text: bool) -> None:
    """Tier-2 mapper: HTTP status + HAL error payload -> typed exception.

    Takes (status_code, payload) rather than an httpx.Response so this module
    stays httpx-free. Callers (HttpxTransport) extract status_code/payload from
    the real response before calling this.

    With `redact_server_text` (any hide setting is active) the server's text is not shown: it can name or
    quote a hidden field and only the attribute of each entry says which. The exception keeps the `entries`,
    so a service that knows the entity renders them again without the hidden ones
    (`services/_error_masking.py`); an error nobody renders stays the generic sentence.
    """
    if status_code < 400:
        return

    payload = payload or {}
    message, entries, top = _server_text(payload, redact=redact_server_text)
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
        raise OpenProjectPermissionDeniedError(_denied(message), entries=entries, top=top, compose=_denied)
    if status_code == 404:
        raise NotFoundError("OpenProject resource not found.")
    if status_code == 422:
        validation = _validation(payload, redact=redact_server_text)
        raise validation or InvalidInputError(_rejected(message), entries=entries, top=top, compose=_rejected)
    if status_code == 400:
        raise InvalidInputError(_rejected(message), entries=entries, top=top, compose=_rejected)
    if status_code == 409:
        raise ConflictError(_conflict(message), entries=entries, top=top, compose=_conflict)
    if status_code == 429:
        raise RateLimitedError("OpenProject is rate-limiting this client.")
    if 500 <= status_code < 600:
        LOGGER.warning("OpenProject server error: status=%s", status_code)
        raise OpenProjectServerError("OpenProject returned a server error.")
    raise OpenProjectServerError(f"OpenProject request failed with status {status_code}.")
