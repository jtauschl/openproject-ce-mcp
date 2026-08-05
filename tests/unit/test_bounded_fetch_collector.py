"""Direct unit tests for app.pagination.fetch_bounded_and_paginate.

Covers the shared scan-server-pages-filter-normalize-and-stop shape used by
RelationService/TimeEntryService: scan server pages, normalize + filter raw
elements via an async item_allowed, and stop as soon as `limit + 1` allowed
items are confirmed (or the collection is genuinely exhausted) -- never
walks the full collection first (OPM-373 Phase 5).

Previously exercised indirectly via OpenProjectClient._fetch_bounded_and_paginate
(a thin wrapper hardcoded to a single `self._get(path, ...)` fetch); now
calls the shared function directly with a fake `fetch_page`, since no
client.py wrapper remains to drive it through.
"""

from __future__ import annotations

from typing import Any

import pytest

from openproject_ce_mcp.app.pagination import fetch_bounded_and_paginate


def _fetch_page_for(elements: list[dict], *, page_size: int = 50):
    async def fetch_page(offset: int, requested_page_size: int) -> dict[str, Any]:
        assert requested_page_size == page_size
        return {"_embedded": {"elements": elements}}

    return fetch_page


@pytest.mark.asyncio
async def test_fetch_bounded_and_paginate_empty_page() -> None:
    page, total, next_offset, truncated = await fetch_bounded_and_paginate(
        fetch_page=_fetch_page_for([]),
        normalize=lambda item: item["name"],
        item_allowed=None,
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
        server_page_size=50,
        offset=1,
        limit=10,
    )
    assert page == ["alpha", "gamma"]
    assert total == 2
    assert next_offset is None
    assert truncated is False


@pytest.mark.asyncio
async def test_fetch_bounded_and_paginate_boundary_respects_offset_and_limit() -> None:
    """5 items on one raw page, limit=2 at offset=2: must skip the 2 allowed
    items belonging to offset=1's window, return the next 2, and correctly
    report truncated=True (a 5th item exists beyond this window) without
    walking a second server page (server_page_size=50 comfortably covers
    all 5 raw elements in one fetch)."""
    elements = [{"name": f"item-{i}"} for i in range(5)]

    page, total, next_offset, truncated = await fetch_bounded_and_paginate(
        fetch_page=_fetch_page_for(elements),
        normalize=lambda item: item["name"],
        item_allowed=None,
        server_page_size=50,
        offset=2,
        limit=2,
    )
    assert page == ["item-2", "item-3"]
    assert total == 2
    assert next_offset == 3
    assert truncated is True


@pytest.mark.asyncio
async def test_fetch_bounded_and_paginate_stops_once_limit_plus_one_is_confirmed_across_pages() -> None:
    """OPM-373 Phase 5: unlike the old walk-to-completion shape, this must
    fetch only as many server pages as needed to confirm limit+1 allowed
    matches, not the entire collection. Here limit=2 needs a 3rd confirmed
    match to prove truncation; page 1 (page_size=2) only has 2 raw elements,
    so page 2 must be fetched to find that 3rd match -- but a 3rd server
    page (which would exist if this walked to completion) must NOT be
    fetched, since the 3rd match is already found on page 2."""
    calls: list[int] = []

    async def fetch_page(offset: int, page_size: int) -> dict[str, Any]:
        calls.append(offset)
        pages = {
            1: [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}],
            2: [{"id": 3, "name": "c"}, {"id": 4, "name": "d"}],
        }
        return {"_embedded": {"elements": pages.get(offset, [])}}

    page, total, next_offset, truncated = await fetch_bounded_and_paginate(
        fetch_page=fetch_page,
        normalize=lambda item: item["name"],
        item_allowed=None,
        server_page_size=2,
        offset=1,
        limit=2,
    )
    assert page == ["a", "b"]
    assert total == 2
    assert truncated is True
    assert next_offset == 2
    # 2 raw elements on page 1 aren't enough to confirm the 3rd (limit+1)
    # match, so page 2 is fetched too -- but stops there, never reaching a
    # hypothetical page 3.
    assert calls == [1, 2]


@pytest.mark.asyncio
async def test_fetch_bounded_and_paginate_does_not_evaluate_item_allowed_past_the_limit_plus_one_match() -> None:
    """Efficiency regression: item_allowed must not be called for items
    AFTER the limit+1-th allowed match is found on a single page -- an
    earlier draft collected the whole page's allowed subset via a list
    comprehension before slicing, which called item_allowed (and normalized
    every match) regardless of where the limit+1 cutoff fell."""
    checked_ids: list[int] = []
    elements = [{"id": i, "name": f"item-{i}"} for i in range(1, 6)]  # 5 raw elements, one page

    async def item_allowed(item: dict) -> bool:
        checked_ids.append(item["id"])
        return True

    page, total, next_offset, truncated = await fetch_bounded_and_paginate(
        fetch_page=_fetch_page_for(elements),
        normalize=lambda item: item["name"],
        item_allowed=item_allowed,
        server_page_size=50,
        offset=1,
        limit=1,
    )
    assert page == ["item-1"]
    assert truncated is True
    # limit+1=2 confirmed matches is enough to stop -- ids 3/4/5 must never
    # be passed to item_allowed.
    assert checked_ids == [1, 2]


@pytest.mark.asyncio
async def test_fetch_bounded_and_paginate_not_truncated_when_exactly_limit_allowed_matches_exist() -> None:
    """Regression (OPM-373 Phase 5): the old shape (and a naive early-stopping
    port of it) can set truncated=True as soon as `limit` allowed items are
    collected, without checking whether a matching item actually exists
    beyond that window."""
    page, total, next_offset, truncated = await fetch_bounded_and_paginate(
        fetch_page=_fetch_page_for([{"name": "only"}]),
        normalize=lambda item: item["name"],
        item_allowed=None,
        server_page_size=50,
        offset=1,
        limit=1,
    )
    assert page == ["only"]
    assert total == 1
    assert truncated is False
    assert next_offset is None
