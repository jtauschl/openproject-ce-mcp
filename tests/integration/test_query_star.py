"""Integration tests for starring a saved query.

This server has no query create endpoint; docker/test/seed.rb seeds a public query "Seed query" and a private query
"Seed private query" (owned by the calling admin) in the test project. The star belongs to the query, so each test
puts it back as it found it. The state is read straight from the API,
not through the tool under test.
"""

from __future__ import annotations

import httpx
import pytest

from openproject_ce_mcp.client import OpenProjectClient

pytestmark = pytest.mark.integration


async def _seeded_query(http: httpx.AsyncClient, name: str) -> dict:
    response = await http.get("queries", params={"pageSize": "100"})
    response.raise_for_status()
    for item in response.json()["_embedded"]["elements"]:
        if item["name"] == name:
            return item
    pytest.fail("the seeded query is missing: re-run docker/test/up.sh to seed it")


async def _starred(http: httpx.AsyncClient, query_id: int) -> bool:
    response = await http.get(f"queries/{query_id}", params={"pageSize": "0"})
    response.raise_for_status()
    return bool(response.json()["starred"])


@pytest.mark.parametrize("name", ["Seed query", "Seed private query"])
async def test_star_and_unstar_a_query_of_the_test_project(client: OpenProjectClient, name: str) -> None:
    async with httpx.AsyncClient(
        base_url=f"{client.settings.api_base_url}/",
        auth=("apikey", client.settings.api_token.get_secret_value()),
        timeout=client.settings.timeout,
    ) as http:
        query_id = int((await _seeded_query(http, name))["id"])
        original = await _starred(http, query_id)
        wanted = not original
        try:
            preview = await client.query_star.set_starred(query_id, starred=wanted)
            assert (preview.state, preview.starred) == ("preview", wanted)
            assert await _starred(http, query_id) is original

            done = await client.query_star.set_starred(query_id, starred=wanted, confirm=True)
            assert done.state == "confirmed"
            assert await _starred(http, query_id) is wanted

            again = await client.query_star.set_starred(query_id, starred=wanted, confirm=True)
            assert "already" in again.message
        finally:
            await client.query_star.set_starred(query_id, starred=original, confirm=True)
        assert await _starred(http, query_id) is original
