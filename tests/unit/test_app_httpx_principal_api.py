from __future__ import annotations

import httpx
import pytest

from openproject_ce_mcp.app.adapters.httpx_principal_api import HttpxPrincipalApi, normalize_principal
from openproject_ce_mcp.app.transport.httpx_transport import HttpxTransport

BASE_URL = "https://op.example.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=f"{BASE_URL}/api/v3/", transport=httpx.MockTransport(handler))


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
    assert principal.email is None


@pytest.mark.asyncio
async def test_list_principals_skips_an_element_with_a_missing_id() -> None:
    """Regression test for the has_usable_id unification: list_*
    must not raise on one malformed element among otherwise well-formed
    ones -- skip it, don't fail every other principal. Principal previously
    had no collection-path test at all for this behavior."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "_embedded": {
                    "elements": [
                        {"_type": "User", "name": "No id here"},
                        {"id": 5, "_type": "User", "name": "Alice"},
                    ]
                },
                "total": 2,
            },
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxPrincipalApi(HttpxTransport(http_client))
        records, _total = await api.list_principals(search=None, offset=1, page_size=50)

    assert [record.summary.id for record in records] == [5]


@pytest.mark.asyncio
async def test_list_principals_accepts_a_numeric_string_id() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"_embedded": {"elements": [{"id": "7", "_type": "User", "name": "Bob"}]}, "total": 1},
            request=request,
        )

    async with _client(handler) as http_client:
        api = HttpxPrincipalApi(HttpxTransport(http_client))
        records, _total = await api.list_principals(search=None, offset=1, page_size=50)

    assert [record.summary.id for record in records] == [7]
