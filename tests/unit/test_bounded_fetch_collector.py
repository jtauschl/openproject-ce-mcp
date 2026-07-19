"""Direct unit tests for OpenProjectClient._fetch_bounded_and_paginate (OPM-88).

Covers the shared bounded-fetch-filter-paginate shape used by list_views/
list_documents/list_news/list_time_entries/list_sprints/list_project_sprints/
list_boards: fetch one bounded page, normalize + filter raw elements via
item_allowed, apply an optional post_filter over the normalized results, then
paginate the survivors in memory.
"""

from __future__ import annotations

import httpx
import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.client import OpenProjectClient


def _handler_for(elements: list[dict]) -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/widgets"
        assert request.url.params["pageSize"] == "100"
        return httpx.Response(200, json={"_embedded": {"elements": elements}}, request=request)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_fetch_bounded_and_paginate_empty_page() -> None:
    client = OpenProjectClient(make_settings(), transport=_handler_for([]))

    page, total, next_offset, truncated = await client._fetch_bounded_and_paginate(
        path="widgets",
        params_extra=None,
        normalize=lambda item: item["name"],
        item_allowed=None,
        post_filter=None,
        offset=1,
        limit=10,
    )
    assert page == []
    assert total == 0
    assert next_offset is None
    assert truncated is False

    await client.aclose()


@pytest.mark.asyncio
async def test_fetch_bounded_and_paginate_applies_item_allowed_filter() -> None:
    elements = [
        {"name": "alpha", "allowed": True},
        {"name": "beta", "allowed": False},
        {"name": "gamma", "allowed": True},
    ]
    client = OpenProjectClient(make_settings(), transport=_handler_for(elements))

    page, total, next_offset, truncated = await client._fetch_bounded_and_paginate(
        path="widgets",
        params_extra=None,
        normalize=lambda item: item["name"],
        item_allowed=lambda item: bool(item["allowed"]),
        post_filter=None,
        offset=1,
        limit=10,
    )
    assert page == ["alpha", "gamma"]
    assert total == 2
    assert next_offset is None
    assert truncated is False

    await client.aclose()


@pytest.mark.asyncio
async def test_fetch_bounded_and_paginate_applies_post_filter_after_normalize() -> None:
    elements = [{"name": "alpha"}, {"name": "beta"}, {"name": "gamma"}]
    client = OpenProjectClient(make_settings(), transport=_handler_for(elements))

    page, total, next_offset, truncated = await client._fetch_bounded_and_paginate(
        path="widgets",
        params_extra=None,
        normalize=lambda item: item["name"],
        item_allowed=None,
        post_filter=lambda results: [name for name in results if name != "beta"],
        offset=1,
        limit=10,
    )
    assert page == ["alpha", "gamma"]
    assert total == 2

    await client.aclose()


@pytest.mark.asyncio
async def test_fetch_bounded_and_paginate_boundary_respects_offset_and_limit() -> None:
    elements = [{"name": f"item-{i}"} for i in range(5)]
    client = OpenProjectClient(make_settings(), transport=_handler_for(elements))

    page, total, next_offset, truncated = await client._fetch_bounded_and_paginate(
        path="widgets",
        params_extra=None,
        normalize=lambda item: item["name"],
        item_allowed=None,
        post_filter=None,
        offset=2,
        limit=2,
    )
    assert page == ["item-2", "item-3"]
    assert total == 5
    assert next_offset == 3
    assert truncated is True

    await client.aclose()
