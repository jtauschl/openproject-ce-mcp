from __future__ import annotations

import pytest

from openproject_ce_mcp.app.errors import InvalidInputError
from openproject_ce_mcp.app.resolvers.assignee_resolver import AssigneeResolver
from openproject_ce_mcp.models import CurrentUser


async def _current_user() -> CurrentUser:
    return CurrentUser(id=99, name="Me", login="me", url="https://op.example.com/users/99")


@pytest.mark.asyncio
async def test_resolve_id_me_uses_current_user_lookup() -> None:
    resolver = AssigneeResolver(current_user=_current_user)
    assert await resolver.resolve_id("me") == "99"


@pytest.mark.asyncio
async def test_resolve_id_me_is_case_insensitive() -> None:
    resolver = AssigneeResolver(current_user=_current_user)
    assert await resolver.resolve_id("ME") == "99"


@pytest.mark.asyncio
async def test_resolve_id_numeric_passthrough() -> None:
    calls: list[str] = []

    async def current_user() -> CurrentUser:
        calls.append("called")
        return CurrentUser(id=99, name="Me", login="me", url="https://op.example.com/users/99")

    resolver = AssigneeResolver(current_user=current_user)
    assert await resolver.resolve_id("42") == "42"
    assert calls == []


@pytest.mark.asyncio
async def test_resolve_id_rejects_a_name() -> None:
    resolver = AssigneeResolver(current_user=_current_user)
    with pytest.raises(InvalidInputError, match="assignee must be a positive integer user id or 'me'"):
        await resolver.resolve_id("Alice")
