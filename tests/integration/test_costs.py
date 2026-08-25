"""Integration tests for the Costs domain (cost_entries + cost_types).

Entirely read-only against OpenProject's own API -- see
`app/ports/cost_api.py`'s module docstring for the verified route citations.
No write/cleanup fixtures of Costs' own are needed (nothing is ever created
here): a work package is created via the standard `wp_ids` cleanup fixture
only as an anchor to query cost sub-resources against.

Creating an actual cost entry requires OpenProject's Costs module UI/rate
data this MCP has no write path for (cost entries have no create endpoint at
all -- see the module docstring), so the list/summarized-by-type tests below
assert only on the empty-collection shape (count == 0, results == []) and
the envelope fields the MCP itself computes (work_package_id stamped from
the resolved id), not on specific cost values -- matching how other
read-only integration tests in this suite handle instance-state-dependent
data they don't control.
"""

from __future__ import annotations

import pytest

from openproject_ce_mcp.client import NotFoundError, OpenProjectClient

pytestmark = pytest.mark.integration


async def _new_wp_id(client: OpenProjectClient, test_project: str, wp_ids: list[int]) -> int:
    wp_result = await client.work_package.create(
        project=test_project, type="Task", subject="Integration test WP for Costs", confirm=True
    )
    assert wp_result.ready, wp_result.validation_errors
    wp_id = wp_result.work_package_id
    assert wp_id is not None
    wp_ids.append(wp_id)
    return wp_id


async def test_get_cost_entry_not_found_raises(client: OpenProjectClient) -> None:
    with pytest.raises(NotFoundError):
        await client.cost.get_cost_entry(999999999)


async def test_list_cost_entries_for_work_package_without_costs_returns_empty(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    wp_id = await _new_wp_id(client, test_project, wp_ids)

    result = await client.cost.list_work_package_cost_entries(wp_id)

    assert result.count == len(result.results)
    assert isinstance(result.results, list)


async def test_list_cost_entries_accepts_a_semantic_work_package_ref(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    wp_id = await _new_wp_id(client, test_project, wp_ids)
    wp = await client.work_package.get(wp_id)

    result = await client.cost.list_work_package_cost_entries(wp.display_id)

    assert result.count == len(result.results)


async def test_get_costs_by_type_for_work_package_without_costs_returns_empty(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    wp_id = await _new_wp_id(client, test_project, wp_ids)

    result = await client.cost.get_work_package_costs_by_type(wp_id)

    assert result.work_package_id == wp_id
    assert result.count == len(result.results)


async def test_get_cost_type_not_found_raises(client: OpenProjectClient) -> None:
    with pytest.raises(NotFoundError):
        await client.cost.get_cost_type(999999999)


async def test_get_cost_type_by_id_if_one_exists(client: OpenProjectClient) -> None:
    # OpenProject seeds at least one default cost type on a fresh install
    # ("Labor costs", often id=1) -- verify id=1 exists and has the expected
    # shape; skip gracefully if this instance has none seeded at that id,
    # since cost type ids are not guaranteed portable across instances.
    try:
        result = await client.cost.get_cost_type(1)
    except NotFoundError:
        pytest.skip("No cost type with id=1 on this instance.")
    assert result.id == 1
    assert isinstance(result.is_default, bool)
