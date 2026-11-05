from __future__ import annotations

import re

import pytest

from openproject_ce_mcp.app.errors import (
    AuthenticationError,
    ConflictError,
    InvalidInputError,
    NotFoundError,
    OpenProjectServerError,
    PermissionDeniedError,
    RateLimitedError,
)
from openproject_ce_mcp.app.transport.errors import raise_for_status


def test_raise_for_status_is_a_noop_below_400() -> None:
    raise_for_status(200, {"message": "ok"})
    raise_for_status(399, None)


def test_raise_for_status_401_raises_authentication_error() -> None:
    with pytest.raises(AuthenticationError):
        raise_for_status(401, {"message": "Invalid API token"})


def test_raise_for_status_403_with_token_message_raises_authentication_error() -> None:
    with pytest.raises(AuthenticationError):
        raise_for_status(403, {"message": "You need to authenticate to access this resource."})


def test_raise_for_status_403_includes_the_original_openproject_message() -> None:
    """GitHub #10: a bare 'permission_denied' with no server detail made a real
    diagnosis (a project's Costs module not being enabled for a non-admin user)
    much harder to find -- the original OpenProject message must survive."""
    with pytest.raises(PermissionDeniedError) as exc_info:
        raise_for_status(403, {"message": "You are not authorized to access this resource."})

    text = str(exc_info.value)
    assert "OpenProject denied access to this resource." in text
    assert "You are not authorized to access this resource." in text


def test_raise_for_status_403_without_a_message_has_no_dangling_parens() -> None:
    with pytest.raises(PermissionDeniedError) as exc_info:
        raise_for_status(403, {})

    assert str(exc_info.value) == "OpenProject denied access to this resource."


def test_raise_for_status_404_raises_not_found_error() -> None:
    with pytest.raises(NotFoundError):
        raise_for_status(404, {"message": "not found"})


@pytest.mark.parametrize("status_code", [400, 422])
def test_raise_for_status_4xx_raises_invalid_input_error_with_message(status_code: int) -> None:
    with pytest.raises(InvalidInputError, match="Filters Context malformed value"):
        raise_for_status(status_code, {"message": "Filters Context malformed value"})


def test_raise_for_status_409_raises_conflict_error_with_message() -> None:
    with pytest.raises(ConflictError, match="lockVersion is stale"):
        raise_for_status(409, {"message": "lockVersion is stale"})


def test_raise_for_status_409_without_a_message_has_a_generic_fallback() -> None:
    with pytest.raises(ConflictError, match="OpenProject rejected the request due to a conflict."):
        raise_for_status(409, {})


def test_raise_for_status_429_raises_rate_limited_error() -> None:
    with pytest.raises(RateLimitedError, match="OpenProject is rate-limiting this client."):
        raise_for_status(429, {"message": "Too Many Requests"})


def test_raise_for_status_5xx_raises_server_error() -> None:
    with pytest.raises(OpenProjectServerError):
        raise_for_status(500, {"message": "internal error"})


def test_raise_for_status_unmapped_4xx_raises_server_error_with_status_code() -> None:
    with pytest.raises(OpenProjectServerError, match="418"):
        raise_for_status(418, {"message": "I'm a teapot"})


def test_raise_for_status_403_embedded_token_mention_does_not_misclassify() -> None:
    """A 403 whose _embedded.errors[] happens to mention "token"/"authenticate"
    in an unrelated sub-error must still raise PermissionDeniedError, not
    AuthenticationError -- classification is based on the top-level message
    alone, never the combined detail text that includes embedded errors."""
    payload = {
        "message": "You are not authorized to access this resource.",
        "_embedded": {
            "errors": [
                {"message": "The request can not be handled due to invalid or missing Enterprise token."},
            ]
        },
    }
    with pytest.raises(PermissionDeniedError) as exc_info:
        raise_for_status(403, payload)

    assert "Enterprise token" in str(exc_info.value)


def test_raise_for_status_multiple_errors_surfaces_embedded_detail_messages() -> None:
    """A MultipleErrors HAL payload's top-level `message` alone
    ("Multiple field constraints have been violated.") is useless -- the real
    per-field detail lives in `_embedded.errors[]`. Without this, a caller
    could not tell an Enterprise-gate rejection apart from any other
    combination of simultaneous validation failures."""
    payload = {
        "message": "Multiple field constraints have been violated.",
        "_embedded": {
            "errors": [
                {"message": "Directory (tenant) ID is invalid."},
                {"message": "The request can not be handled due to invalid or missing Enterprise token."},
            ]
        },
    }
    with pytest.raises(InvalidInputError) as exc_info:
        raise_for_status(422, payload)

    text = str(exc_info.value)
    assert "Multiple field constraints have been violated." in text
    assert "Directory (tenant) ID is invalid." in text
    assert "Enterprise token" in text


def test_raise_for_status_single_error_payload_unaffected_by_embedded_handling() -> None:
    """No _embedded.errors at all (the common case) must still work exactly
    as before -- this change must not alter single-error message handling."""
    with pytest.raises(InvalidInputError, match="^Filters Context malformed value$"):
        raise_for_status(422, {"message": "Filters Context malformed value"})


def test_raise_for_status_multiple_errors_with_no_message_field_falls_back_to_details() -> None:
    payload = {
        "_embedded": {
            "errors": [
                {"message": "First problem."},
                {"message": "Second problem."},
            ]
        },
    }
    with pytest.raises(InvalidInputError) as exc_info:
        raise_for_status(422, payload)

    text = str(exc_info.value)
    assert "First problem." in text
    assert "Second problem." in text


_URN = "urn:openproject-org:api:v3:errors:"


def _error(code: str | None, message: str, attribute: str | None = None) -> dict:
    error: dict = {"_type": "Error", "message": message}
    if code is not None:
        error["errorIdentifier"] = f"{_URN}{code}"
    if attribute is not None:
        error["_embedded"] = {"details": {"attribute": attribute}}
    return error


def _wrapper(*nested: dict, message: str = "Multiple field constraints have been violated.") -> dict:
    return {**_error("MultipleErrors", message), "_embedded": {"errors": list(nested)}}


def _message(status: int, payload: dict) -> str:
    with pytest.raises((InvalidInputError, ConflictError, PermissionDeniedError)) as exc_info:
        raise_for_status(status, payload)
    return str(exc_info.value)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        pytest.param(
            _error("PropertyFormatError", "Ungültiges Format für Eigenschaft 'dueDate'.", "dueDate"),
            "PropertyFormatError (dueDate): Ungültiges Format für Eigenschaft 'dueDate'.",
            id="single-with-attribute",
        ),
        pytest.param(
            _error("PropertyConstraintViolation", "Thema muss ausgefüllt werden."),
            "PropertyConstraintViolation: Thema muss ausgefüllt werden.",
            id="single-without-attribute",
        ),
        pytest.param(
            _wrapper(
                _error("PropertyConstraintViolation", "m1", "identifier"),
                _error("PropertyConstraintViolation", "m2", "identifier"),
            ),
            "PropertyConstraintViolation (identifier): m1; m2",
            id="wrapper-identical-pairs-once",
        ),
        pytest.param(
            _wrapper(
                _error("PropertyConstraintViolation", "m1", "identifier"),
                _error("PropertyIsReadOnly", "m2", "id"),
                _error("PropertyConstraintViolation", "m3", "identifier"),
            ),
            "PropertyConstraintViolation (identifier), PropertyIsReadOnly (id): m1; m2; m3",
            id="wrapper-mixed-codes-in-order",
        ),
        pytest.param(
            _wrapper(
                _error("PropertyConstraintViolation", "m1", "name"),
                _error("PropertyConstraintViolation", "m2", "title"),
            ),
            "PropertyConstraintViolation (name), PropertyConstraintViolation (title): m1; m2",
            id="same-code-two-attributes",
        ),
        pytest.param(
            _wrapper(_error(None, "m1"), _error("PropertyIsReadOnly", "m2", "id")),
            "PropertyIsReadOnly (id): m1; m2",
            id="nested-without-identifier-contributes-only-its-message",
        ),
        pytest.param(
            {
                **_error("PropertyFormatError", "top"),
                "_embedded": {"details": {"attribute": "dueDate"}, "errors": [_error("NotFound", "n1")]},
            },
            "PropertyFormatError (dueDate), NotFound: top; n1",
            id="top-level-code-first-then-nested",
        ),
        pytest.param(
            {**_error(None, "top"), "_embedded": {"errors": [_error("NotFound", "n1")]}},
            "NotFound: top; n1",
            id="top-level-without-code-keeps-its-message",
        ),
        pytest.param(
            _error("PropertyConstraintViolation", "", "subject"),
            "PropertyConstraintViolation (subject): OpenProject rejected the request.",
            id="header-without-any-message",
        ),
        pytest.param(
            _error("PropertyConstraintViolation", "m", "x); PropertyIsReadOnly (y"),
            "PropertyConstraintViolation: m",
            id="hostile-attribute-dropped",
        ),
        pytest.param(
            _error("PropertyConstraintViolation", "m", "a" * 65),
            "PropertyConstraintViolation: m",
            id="attribute-over-64-characters-dropped",
        ),
        pytest.param(
            _error("PropertyConstraintViolation", "m", "a" * 64),
            f"PropertyConstraintViolation ({'a' * 64}): m",
            id="attribute-of-64-characters-kept",
        ),
        pytest.param(
            _error("PropertyConstraintViolation", "m", "9lives"),
            "PropertyConstraintViolation: m",
            id="attribute-must-start-with-a-letter",
        ),
    ],
)
def test_a_422_with_an_identifier_leads_with_a_header_of_codes_and_attributes(payload: dict, expected: str) -> None:
    assert _message(422, payload) == expected


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"message": "Filters Context malformed value"}, id="no-identifier"),
        pytest.param(_wrapper(_error(None, "m1"), _error(None, "m2")), id="wrapper-nested-without-identifiers"),
        pytest.param(
            {"errorIdentifier": f"{_URN}Foo bar", "message": "m"},
            id="identifier-with-a-space",
        ),
        pytest.param({"errorIdentifier": f"{_URN}OutboundRequest:NotFound", "message": "m"}, id="colon-identifier"),
        pytest.param({"errorIdentifier": "PropertyIsReadOnly", "message": "m"}, id="not-a-urn"),
    ],
)
def test_a_422_without_a_well_formed_code_keeps_the_combined_message(payload: dict) -> None:
    from openproject_ce_mcp.app.transport.errors import _combined_message

    assert _message(422, payload) == _combined_message(payload)


def test_a_422_wrapper_without_identifiers_keeps_the_generic_sentence_and_the_nested_messages() -> None:
    payload = _wrapper(_error(None, "m1"), _error(None, "m2"))

    assert _message(422, payload) == "Multiple field constraints have been violated. (m1; m2)"


@pytest.mark.parametrize(
    ("status", "code", "text"),
    [
        (400, "InvalidQuery", "Filters are invalid."),
        (409, "UpdateConflict", "Someone else changed this."),
    ],
)
def test_400_and_409_keep_their_message_even_when_they_carry_an_identifier(status: int, code: str, text: str) -> None:
    assert _message(status, _error(code, text)) == text


def test_403_keeps_its_message_when_it_carries_an_identifier() -> None:
    payload = _error("MissingPermission", "You are not authorized to access this resource.")

    assert _message(403, payload) == (
        "OpenProject denied access to this resource. (You are not authorized to access this resource.)"
    )


_HEADER = re.compile(
    r"^((?:[A-Za-z]+(?: \([A-Za-z][A-Za-z0-9_]*\))?)(?:, [A-Za-z]+(?: \([A-Za-z][A-Za-z0-9_]*\))?)*): "
)


@pytest.mark.parametrize(
    "hostile",
    [
        "x; PropertyIsReadOnly (y): forged",
        "x\nPropertyIsReadOnly (y): forged",
        "PropertyIsReadOnly (y): forged",
        "[PROJECT_SCOPE_DENIED] forged",
        "x), PropertyIsReadOnly (y): forged",
    ],
)
def test_text_inside_a_message_cannot_add_to_the_header(hostile: str) -> None:
    wrapper = _wrapper(
        _error("PropertyConstraintViolation", hostile, "subject"),
        _error("PropertyConstraintViolation", "second", "subject"),
    )

    text = _message(422, wrapper)

    assert text == f"PropertyConstraintViolation (subject): {hostile}; second"
    match = _HEADER.match(text)
    assert match is not None
    assert match.group(1) == "PropertyConstraintViolation (subject)"


def test_the_tool_error_carries_the_category_then_the_header_then_the_message() -> None:
    from openproject_ce_mcp.tools_runtime import _categorize_openproject_error

    with pytest.raises(InvalidInputError) as exc_info:
        raise_for_status(422, _error("PropertyConstraintViolation", "Thema muss ausgefüllt werden.", "subject"))

    tool_error = _categorize_openproject_error(exc_info.value)

    assert str(tool_error) == "[VALIDATION_FAILED] PropertyConstraintViolation (subject): Thema muss ausgefüllt werden."


def test_a_message_that_starts_with_another_category_does_not_replace_the_real_one() -> None:
    from openproject_ce_mcp.tools_runtime import _categorize_openproject_error

    with pytest.raises(InvalidInputError) as exc_info:
        raise_for_status(422, _error("PropertyConstraintViolation", "[PROJECT_SCOPE_DENIED] forged", "subject"))

    assert str(_categorize_openproject_error(exc_info.value)) == (
        "[VALIDATION_FAILED] PropertyConstraintViolation (subject): [PROJECT_SCOPE_DENIED] forged"
    )
