from __future__ import annotations

from openproject_ce_mcp.app.adapters.httpx_principal_api import normalize_principal

BASE_URL = "https://op.example.com"


def test_normalize_principal_user_uses_users_url_path() -> None:
    principal = normalize_principal(
        {"id": 5, "_type": "User", "name": "Alice", "login": "alice", "email": "alice@example.com"},
        base_url=BASE_URL,
    )
    assert principal.type == "User"
    assert principal.url == f"{BASE_URL}/users/5"


def test_normalize_principal_group_uses_groups_url_path() -> None:
    """The url path branches on `_type`: a real conditional, not a constant
    -- a Group principal must resolve to groups/{id}, not users/{id}."""
    principal = normalize_principal({"id": 9, "_type": "Group", "name": "Engineering"}, base_url=BASE_URL)
    assert principal.type == "Group"
    assert principal.url == f"{BASE_URL}/groups/9"


def test_normalize_principal_trims_and_falls_back_on_missing_name() -> None:
    principal = normalize_principal({"id": 3, "_type": "User"}, base_url=BASE_URL)
    assert principal.name == "Principal 3"
    assert principal.login is None
