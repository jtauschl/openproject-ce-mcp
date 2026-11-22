"""What raise_for_status does and does NOT leak into an error message.

Renamed from test_error_message_does_not_leak_upstream_details.py: that name
overclaimed relative to this file's own contents -- one of the three tests
here (test_raise_for_status_passes_through_upstream_message_text_verbatim)
documents, and asserts, the opposite for OpenProject's own server-provided
error text. This file's actual scope is the boundary between what's
structurally unreachable (the API token/Authorization header -- Tests 1/3
below) and what's a deliberate, accepted pass-through (upstream error text
-- Test 2), not a blanket "nothing ever leaks" guarantee.

Verified directly against the code before writing these tests (not assumed):
the API token becomes an `Authorization: Basic ...` header once, at
`httpx.AsyncClient` construction time (`client.py`'s Settings-to-client
wiring) -- it is a default header on the client, never read back out of a
request or response afterward. `raise_for_status(status_code, payload, redact_server_text=...)`
(`app/transport/errors.py`) and its only two call sites
(`app/transport/httpx_transport.py`) extract nothing but the parsed JSON
response BODY before mapping it to a typed exception; `response.request`/
`response.request.headers` (which would carry the Authorization header) are
never read on the error path. There is therefore no code path by which the
real API token could reach a raised exception's message -- testing for its
*absence* in some assembled string would be vacuous (it was never reachable
to begin with), so Test 1/Test 3 below prove that absence structurally
(no parameter exists to carry it) rather than by searching a haystack.

The one thing that DOES reach a raised exception verbatim is OpenProject's
own server-provided `message`/`_embedded.errors[].message` text
(`_server_text`) while no hide setting is active -- Test 2 documents this honestly as current,
intentional-by-omission behavior (trusting a self-hosted instance's own
error text), not something this ticket redacts. See this module's own
`test_...passes_through_upstream_message_text_verbatim` docstring for why
redaction is a deliberate non-goal here, not an oversight.
"""

from __future__ import annotations

import inspect

from openproject_ce_mcp.app.transport.errors import raise_for_status


def test_raise_for_status_signature_has_no_request_or_header_parameter() -> None:
    """Structural guard: if a future refactor ever threaded the request
    object or its headers into this function (e.g. to log more context on
    an error), that would put the Authorization header in reach of the
    error-mapping code path for the first time -- this test fails loudly on
    that change so it gets a deliberate security review, rather than passing
    silently."""
    signature = inspect.signature(raise_for_status)
    assert list(signature.parameters) == ["status_code", "payload", "redact_server_text"]


def test_raise_for_status_401_never_echoes_the_response_payload() -> None:
    """A 401 always raises a fixed, generic message regardless of what the
    server's JSON body contained -- even if an upstream response somehow
    echoed the token or a header value in its body, a 401 specifically can
    never surface it."""
    payload_with_a_realistic_looking_credential = {
        "message": "Authorization failed for token 'sk-fake-marker-do-not-treat-as-real'"
    }
    try:
        raise_for_status(401, payload_with_a_realistic_looking_credential, redact_server_text=False)
    except Exception as exc:  # noqa: BLE001 -- asserting on whichever type/message it actually raises
        assert str(exc) == "OpenProject authentication failed."
    else:
        raise AssertionError("raise_for_status(401, ...) did not raise")


def test_raise_for_status_passes_through_upstream_message_text_verbatim() -> None:
    """Honest documentation of current behavior, not a defect being fixed
    here: OpenProject's own server-provided error text (a MultipleErrors
    HAL payload's `_embedded.errors[].message`) passes through into the
    raised exception's message completely unredacted while no hide setting is active
    (`redact_server_text=False`; a hide setting makes the text generic, tests/unit/test_server_error_texts_*). This is an accepted
    risk boundary (a self-hosted OpenProject instance's own error text is
    already trusted, per this project's documented scope), not a leak of
    anything this MCP itself controls -- if the project ever wants to
    redact/allowlist upstream error text, that is a deliberate product
    change to `_server_text`, out of this ticket's test-only scope.

    A synthetic, clearly-fake marker stands in for "OpenProject's own
    response body happened to include something identifying" -- this
    is NOT a real secret and is not shaped like this project's own API
    token format.
    """
    marker = "sk-fake-marker-do-not-treat-as-real"
    payload = {
        "message": "Multiple field constraints have been violated.",
        "_embedded": {"errors": [{"message": f"internal reference {marker} rejected"}]},
    }
    try:
        raise_for_status(422, payload, redact_server_text=False)
    except Exception as exc:  # noqa: BLE001
        assert marker in str(exc)
    else:
        raise AssertionError("raise_for_status(422, ...) did not raise")
