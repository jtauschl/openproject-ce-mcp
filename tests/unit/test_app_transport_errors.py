from __future__ import annotations

import pytest

from openproject_ce_mcp.app.errors import (
    AuthenticationError,
    InvalidInputError,
    NotFoundError,
    OpenProjectServerError,
    PermissionDeniedError,
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


@pytest.mark.parametrize("status_code", [400, 409, 422])
def test_raise_for_status_4xx_raises_invalid_input_error_with_message(status_code: int) -> None:
    with pytest.raises(InvalidInputError, match="Filters Context malformed value"):
        raise_for_status(status_code, {"message": "Filters Context malformed value"})


def test_raise_for_status_5xx_raises_server_error() -> None:
    with pytest.raises(OpenProjectServerError):
        raise_for_status(500, {"message": "internal error"})


def test_raise_for_status_unmapped_4xx_raises_server_error_with_status_code() -> None:
    with pytest.raises(OpenProjectServerError, match="418"):
        raise_for_status(418, {"message": "I'm a teapot"})


def test_raise_for_status_multiple_errors_surfaces_embedded_detail_messages() -> None:
    """Live-verified regression guard (2026-08-13, real 17.7.1 instance): a
    MultipleErrors HAL payload's top-level `message` alone
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
