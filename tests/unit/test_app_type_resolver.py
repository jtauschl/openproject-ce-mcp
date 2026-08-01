from __future__ import annotations

import pytest

from openproject_ce_mcp.app.errors import InvalidInputError
from openproject_ce_mcp.app.ports.status_priority_type_api import TypeRecord
from openproject_ce_mcp.app.resolvers.type_resolver import TypeResolver
from openproject_ce_mcp.models import TypeSummary


def _type(type_id: int, name: str) -> TypeRecord:
    return TypeRecord(
        summary=TypeSummary(
            id=type_id,
            name=name,
            color=None,
            position=1,
            is_default=False,
            is_milestone=False,
            url=f"https://op.example.com/types/{type_id}",
            created_at=None,
            updated_at=None,
        )
    )


class _FakeApi:
    def __init__(self, *, types: list[TypeRecord] | None = None) -> None:
        self._types = types or []
        self.last_project_id: int | None = None

    async def list_types(self, *, project_id: int | None) -> list[TypeRecord]:
        self.last_project_id = project_id
        return self._types


async def _resolve_project_ref(project_ref: str, *, write: bool = False, context=None) -> dict:
    return {"id": int(project_ref), "identifier": f"P{project_ref}"}


@pytest.mark.asyncio
async def test_resolve_id_numeric_passthrough_never_calls_the_api() -> None:
    api = _FakeApi()
    resolver = TypeResolver(api=api, resolve_project_ref=_resolve_project_ref)
    assert await resolver.resolve_id("7", project=None) == "7"
    assert api.last_project_id is None


@pytest.mark.asyncio
async def test_resolve_id_requires_a_project_for_a_name_lookup() -> None:
    api = _FakeApi()
    resolver = TypeResolver(api=api, resolve_project_ref=_resolve_project_ref)
    with pytest.raises(InvalidInputError, match="type names require a project filter"):
        await resolver.resolve_id("Task", project=None)


@pytest.mark.asyncio
async def test_resolve_id_matches_by_case_insensitive_name_within_the_resolved_project() -> None:
    api = _FakeApi(types=[_type(1, "Task"), _type(2, "Bug")])
    resolver = TypeResolver(api=api, resolve_project_ref=_resolve_project_ref)
    assert await resolver.resolve_id("task", project="5") == "1"
    assert api.last_project_id == 5


@pytest.mark.asyncio
async def test_resolve_id_raises_when_not_found() -> None:
    api = _FakeApi(types=[_type(1, "Task")])
    resolver = TypeResolver(api=api, resolve_project_ref=_resolve_project_ref)
    with pytest.raises(InvalidInputError, match="was not found in project"):
        await resolver.resolve_id("Ghost", project="5")


@pytest.mark.asyncio
async def test_resolve_id_raises_when_ambiguous() -> None:
    """Unlike StatusPriorityTypeResolver's status/priority methods, an
    ambiguous type name raises rather than silently picking the first
    match -- preserved verbatim from the flat _resolve_type_id."""
    api = _FakeApi(types=[_type(1, "Task"), _type(2, "Task")])
    resolver = TypeResolver(api=api, resolve_project_ref=_resolve_project_ref)
    with pytest.raises(InvalidInputError, match="ambiguous"):
        await resolver.resolve_id("Task", project="5")
