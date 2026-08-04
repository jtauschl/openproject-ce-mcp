from __future__ import annotations

from openproject_ce_mcp.app.adapters.httpx_current_user_api import normalize_current_user


def test_normalize_current_user_maps_fields() -> None:
    user = normalize_current_user({"id": 42, "name": "Alice Example", "login": "alice"})
    assert user.id == 42
    assert user.name == "Alice Example"
    assert user.login == "alice"
    assert not hasattr(user, "url")


def test_normalize_current_user_does_not_trim_whitespace() -> None:
    """Unlike the sibling normalize_principal (which trims name/login/email/
    status via SUBJECT_LIMIT), the current-user normalizer passes name/login
    through raw -- this asymmetry is pre-existing behavior, not a bug."""
    user = normalize_current_user({"id": 1, "name": "  Padded Name  ", "login": "  padded_login  "})
    assert user.name == "  Padded Name  "
    assert user.login == "  padded_login  "
