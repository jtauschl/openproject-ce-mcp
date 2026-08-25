from __future__ import annotations

import pytest

from openproject_ce_mcp.app.errors import NotFoundError, OpenProjectServerError
from openproject_ce_mcp.app.version_gate import call_version_gated


@pytest.mark.asyncio
async def test_call_version_gated_returns_the_call_result_on_success() -> None:
    async def call() -> str:
        return "ok"

    assert await call_version_gated(call, feature="Meetings", floor="17.4") == "ok"


@pytest.mark.asyncio
async def test_call_version_gated_translates_not_found_into_a_version_hint() -> None:
    async def call() -> None:
        raise NotFoundError("boom")

    with pytest.raises(
        NotFoundError, match="Meetings requires OpenProject 17.4 or newer; this instance appears to be older."
    ):
        await call_version_gated(call, feature="Meetings", floor="17.4")


@pytest.mark.asyncio
async def test_call_version_gated_chains_the_original_exception() -> None:
    original = NotFoundError("boom")

    async def call() -> None:
        raise original

    with pytest.raises(NotFoundError) as exc_info:
        await call_version_gated(call, feature="Meetings", floor="17.4")
    assert exc_info.value.__cause__ is original


@pytest.mark.asyncio
async def test_call_version_gated_only_translates_not_found_error() -> None:
    async def call() -> None:
        raise OpenProjectServerError("something else")

    with pytest.raises(OpenProjectServerError, match="something else"):
        await call_version_gated(call, feature="Meetings", floor="17.4")
