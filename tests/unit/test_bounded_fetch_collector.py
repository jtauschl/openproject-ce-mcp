"""Direct unit tests for app.pagination.fetch_bounded_and_paginate.

Covers the shared walk-every-server-page-filter-paginate shape used by
RelationService/TimeEntryService (client.py's own thin wrapper around this
function was removed once list_time_entries -- its last remaining flat
caller -- migrated to TimeEntryService): walk every server page, normalize +
filter raw elements via an async item_allowed, apply an optional post_filter
over the normalized results, then paginate the survivors in memory.

Previously exercised indirectly via OpenProjectClient._fetch_bounded_and_paginate
(a thin wrapper hardcoded to a single `self._get(path, ...)` fetch); now
calls the shared function directly with a fake `fetch_page`, since no
client.py wrapper remains to drive it through.
"""

from __future__ import annotations

from typing import Any

import pytest

from openproject_ce_mcp.app.pagination import fetch_bounded_and_paginate


def _fetch_page_for(elements: list[dict]):
    async def fetch_page(offset: int, page_size: int) -> dict[str, Any]:
        assert page_size == 50
        return {"_embedded": {"elements": elements}}

    return fetch_page


@pytest.mark.asyncio
async def test_fetch_bounded_and_paginate_empty_page() -> None:
    page, total, next_offset, truncated = await fetch_bounded_and_paginate(
        fetch_page=_fetch_page_for([]),
        normalize=lambda item: item["name"],
        item_allowed=None,
        post_filter=None,
        server_page_size=50,
        offset=1,
        limit=10,
    )
    assert page == []
    assert total == 0
    assert next_offset is None
    assert truncated is False


@pytest.mark.asyncio
async def test_fetch_bounded_and_paginate_applies_item_allowed_filter() -> None:
    elements = [
        {"name": "alpha", "allowed": True},
        {"name": "beta", "allowed": False},
        {"name": "gamma", "allowed": True},
    ]

    async def item_allowed(item: dict) -> bool:
        return bool(item["allowed"])

    page, total, next_offset, truncated = await fetch_bounded_and_paginate(
        fetch_page=_fetch_page_for(elements),
        normalize=lambda item: item["name"],
        item_allowed=item_allowed,
        post_filter=None,
        server_page_size=50,
        offset=1,
        limit=10,
    )
    assert page == ["alpha", "gamma"]
    assert total == 2
    assert next_offset is None
    assert truncated is False


@pytest.mark.asyncio
async def test_fetch_bounded_and_paginate_applies_post_filter_after_normalize() -> None:
    elements = [{"name": "alpha"}, {"name": "beta"}, {"name": "gamma"}]

    page, total, next_offset, truncated = await fetch_bounded_and_paginate(
        fetch_page=_fetch_page_for(elements),
        normalize=lambda item: item["name"],
        item_allowed=None,
        post_filter=lambda results: [name for name in results if name != "beta"],
        server_page_size=50,
        offset=1,
        limit=10,
    )
    assert page == ["alpha", "gamma"]
    assert total == 2


@pytest.mark.asyncio
async def test_fetch_bounded_and_paginate_boundary_respects_offset_and_limit() -> None:
    elements = [{"name": f"item-{i}"} for i in range(5)]

    page, total, next_offset, truncated = await fetch_bounded_and_paginate(
        fetch_page=_fetch_page_for(elements),
        normalize=lambda item: item["name"],
        item_allowed=None,
        post_filter=None,
        server_page_size=50,
        offset=2,
        limit=2,
    )
    assert page == ["item-2", "item-3"]
    assert total == 5
    assert next_offset == 3
    assert truncated is True
