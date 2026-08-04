from __future__ import annotations

from openproject_ce_mcp.app.adapters.httpx_principal_api import normalize_principal


def test_normalize_principal_user_has_no_url_field() -> None:
    principal = normalize_principal(
        {"id": 5, "_type": "User", "name": "Alice", "login": "alice", "email": "alice@example.com"}
    )
    assert principal.type == "User"
    assert not hasattr(principal, "url")


def test_normalize_principal_group_has_no_url_field() -> None:
    principal = normalize_principal({"id": 9, "_type": "Group", "name": "Engineering"})
    assert principal.type == "Group"
    assert not hasattr(principal, "url")


def test_normalize_principal_trims_and_falls_back_on_missing_name() -> None:
    principal = normalize_principal({"id": 3, "_type": "User"})
    assert principal.name == "Principal 3"
    assert principal.login is None
