from __future__ import annotations

import pytest

from openproject_ce_mcp.app.pagination import paginate_all, scan_and_paginate, scan_records_and_paginate


@pytest.mark.asyncio
async def test_scan_and_paginate_stops_after_limit_plus_one_allowed_matches() -> None:
    """OPM-373 Phase 5: unlike paginate_all, this must NOT walk the entire
    collection -- only enough pages to confirm limit+1 allowed matches (or
    genuine exhaustion)."""
    calls: list[int] = []

    async def fetch_page(offset: int, page_size: int) -> dict:
        calls.append(offset)
        pages = {
            1: [{"id": 1}, {"id": 2}],
            2: [{"id": 3}, {"id": 4}],
            3: [{"id": 5}, {"id": 6}],
        }
        elements = pages.get(offset, [])
        return {"_embedded": {"elements": elements}}

    async def item_allowed(item: dict) -> bool:
        return True

    results, truncated = await scan_and_paginate(
        fetch_page=fetch_page, item_allowed=item_allowed, server_page_size=2, offset=1, limit=2
    )

    assert [r["id"] for r in results] == [1, 2]
    assert truncated is True
    # limit=2 needs limit+1=3 confirmed matches before it can stop -- page 1
    # gives 2, page 2's first item is the 3rd -- must not walk page 3.
    assert calls == [1, 2]


@pytest.mark.asyncio
async def test_scan_and_paginate_not_truncated_when_exactly_limit_matches_exist() -> None:
    async def fetch_page(offset: int, page_size: int) -> dict:
        if offset == 1:
            return {"_embedded": {"elements": [{"id": 1}]}}
        raise AssertionError(f"unexpected offset {offset}")

    async def item_allowed(item: dict) -> bool:
        return True

    results, truncated = await scan_and_paginate(
        fetch_page=fetch_page, item_allowed=item_allowed, server_page_size=2, offset=1, limit=1
    )

    assert [r["id"] for r in results] == [1]
    assert truncated is False


@pytest.mark.asyncio
async def test_scan_and_paginate_does_not_evaluate_item_allowed_past_the_limit_plus_one_match() -> None:
    """Efficiency regression: item_allowed must not be called for items
    AFTER the limit+1-th allowed match is found on a single page -- an
    earlier draft collected the whole page's allowed subset via a list
    comprehension before slicing, which called item_allowed on every raw
    element regardless of where the limit+1 cutoff fell."""
    checked_ids: list[int] = []

    async def fetch_page(offset: int, page_size: int) -> dict:
        return {"_embedded": {"elements": [{"id": i} for i in range(1, 6)]}}  # 5 raw elements, one page

    async def item_allowed(item: dict) -> bool:
        checked_ids.append(item["id"])
        return True

    results, truncated = await scan_and_paginate(
        fetch_page=fetch_page, item_allowed=item_allowed, server_page_size=5, offset=1, limit=1
    )

    assert [r["id"] for r in results] == [1]
    assert truncated is True
    # limit+1=2 confirmed matches is enough to stop -- ids 3/4/5 must never
    # be passed to item_allowed.
    assert checked_ids == [1, 2]


@pytest.mark.asyncio
async def test_scan_records_and_paginate_stops_after_limit_plus_one_allowed_matches() -> None:
    calls: list[int] = []

    async def fetch_page(offset: int, page_size: int) -> tuple[list[int], int]:
        calls.append(offset)
        pages = {1: [1, 2], 2: [3, 4], 3: [5, 6]}
        return pages.get(offset, []), 999

    results, truncated = await scan_records_and_paginate(
        fetch_page, item_allowed=lambda item: True, server_page_size=2, offset=1, limit=2, key=lambda item: item
    )

    assert results == [1, 2]
    assert truncated is True
    assert calls == [1, 2]


@pytest.mark.asyncio
async def test_scan_records_and_paginate_not_truncated_when_exactly_limit_matches_exist() -> None:
    async def fetch_page(offset: int, page_size: int) -> tuple[list[int], int]:
        if offset == 1:
            return [1], 1
        raise AssertionError(f"unexpected offset {offset}")

    results, truncated = await scan_records_and_paginate(
        fetch_page, item_allowed=lambda item: True, server_page_size=2, offset=1, limit=1, key=lambda item: item
    )

    assert results == [1]
    assert truncated is False


@pytest.mark.asyncio
async def test_scan_records_and_paginate_does_not_evaluate_item_allowed_past_the_limit_plus_one_match() -> None:
    """Same efficiency regression as scan_and_paginate's equivalent test,
    for the already-normalized-record variant."""
    checked: list[int] = []

    async def fetch_page(offset: int, page_size: int) -> tuple[list[int], int]:
        return [1, 2, 3, 4, 5], 999  # 5 records, one page

    def item_allowed(item: int) -> bool:
        checked.append(item)
        return True

    results, truncated = await scan_records_and_paginate(
        fetch_page, item_allowed=item_allowed, server_page_size=5, offset=1, limit=1, key=lambda item: item
    )

    assert results == [1]
    assert truncated is True
    assert checked == [1, 2]


@pytest.mark.asyncio
async def test_scan_records_and_paginate_ignores_reported_total_for_exhaustion() -> None:
    """Regression: an earlier draft used server_offset * server_page_size >=
    total as an additional exhaustion signal, which is unsafe when an
    adapter falls back to total = len(records) for a response with no
    server-reported total (verified against httpx_sprint_api.py) -- that
    would make a full first page look exhausted even when a genuine second
    page of matches exists. Exhaustion must be judged purely by a short
    page, never by a caller-supplied total value."""

    async def fetch_page(offset: int, page_size: int) -> tuple[list[int], int]:
        if offset == 1:
            # total == len(page) here, exactly the "adapter fell back"
            # shape -- server_offset(1) * server_page_size(2) = 2 >= total(2)
            # would have looked exhausted under the removed check.
            return [1, 2], 2
        if offset == 2:
            return [3], 3
        raise AssertionError(f"unexpected offset {offset}")

    results, truncated = await scan_records_and_paginate(
        fetch_page, item_allowed=lambda item: True, server_page_size=2, offset=1, limit=10, key=lambda item: item
    )

    assert results == [1, 2, 3], "page 2's real match must not be hidden by a misleading reported total"
    assert truncated is False


@pytest.mark.asyncio
async def test_paginate_all_collects_a_single_page() -> None:
    async def fetch_page(offset: int, page_size: int) -> tuple[list[int], int]:
        assert (offset, page_size) == (1, 10)
        return [1, 2, 3], 3

    result = await paginate_all(fetch_page, page_size=10)

    assert result == [1, 2, 3]


@pytest.mark.asyncio
async def test_paginate_all_walks_multiple_pages_until_exhausted() -> None:
    pages = {1: (["a", "b"], 5), 2: (["c", "d"], 5), 3: (["e"], 5)}
    calls: list[tuple[int, int]] = []

    async def fetch_page(offset: int, page_size: int) -> tuple[list[str], int]:
        calls.append((offset, page_size))
        return pages[offset]

    result = await paginate_all(fetch_page, page_size=2)

    assert result == ["a", "b", "c", "d", "e"]
    assert calls == [(1, 2), (2, 2), (3, 2)]


@pytest.mark.asyncio
async def test_paginate_all_returns_empty_list_when_no_items() -> None:
    async def fetch_page(offset: int, page_size: int) -> tuple[list[int], int]:
        return [], 0

    result = await paginate_all(fetch_page, page_size=10)

    assert result == []
