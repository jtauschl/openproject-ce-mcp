from __future__ import annotations

import pytest

from openproject_ce_mcp.app.pagination import paginate_all


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
