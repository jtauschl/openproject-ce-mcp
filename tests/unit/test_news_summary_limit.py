"""The news summary limit is the one OpenProject enforces: 255 characters (app/models/news.rb)."""

from __future__ import annotations

import pytest
from _tools_test_helpers import FakeContext

from openproject_ce_mcp.tools import create_news, update_news

SERVER_LIMIT = 255


class _NewsNamespace:
    async def create(self, **kwargs):
        return kwargs

    async def update(self, **kwargs):
        return kwargs


class _StubClient:
    news = _NewsNamespace()


@pytest.mark.asyncio
async def test_create_news_accepts_the_server_limit_and_refuses_one_more() -> None:
    ctx = FakeContext(_StubClient())  # type: ignore[arg-type]

    accepted = await create_news(ctx, project="demo", title="T", summary="x" * SERVER_LIMIT)

    assert accepted["summary"] == "x" * SERVER_LIMIT
    with pytest.raises(ValueError, match=f"summary must be at most {SERVER_LIMIT} characters"):
        await create_news(ctx, project="demo", title="T", summary="x" * (SERVER_LIMIT + 1))


@pytest.mark.asyncio
async def test_update_news_accepts_the_server_limit_and_refuses_one_more() -> None:
    ctx = FakeContext(_StubClient())  # type: ignore[arg-type]

    accepted = await update_news(ctx, 7, summary="x" * SERVER_LIMIT)

    assert accepted["summary"] == "x" * SERVER_LIMIT
    with pytest.raises(ValueError, match=f"summary must be at most {SERVER_LIMIT} characters"):
        await update_news(ctx, 7, summary="x" * (SERVER_LIMIT + 1))
