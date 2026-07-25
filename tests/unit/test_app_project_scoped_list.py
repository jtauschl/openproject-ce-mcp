from __future__ import annotations

from dataclasses import dataclass

import pytest

from openproject_ce_mcp.app.services.project_scoped_list import (
    resolve_project_filter_candidates,
    summary_matches_project_candidates,
    trim_text,
)


@dataclass
class _Summary:
    project_id: int | None
    project: str | None


def test_trim_text_short_text_passes_through() -> None:
    assert trim_text("hello", limit=10) == "hello"


def test_trim_text_none_returns_none() -> None:
    assert trim_text(None, limit=10) is None


def test_trim_text_truncates_and_appends_ellipsis() -> None:
    result = trim_text("x" * 20, limit=10)
    assert result is not None
    assert len(result) == 10
    assert result.endswith("…")


@pytest.mark.asyncio
async def test_resolve_project_filter_candidates_returns_none_when_no_project() -> None:
    async def resolve_project_ref(project_ref: str, *, write: bool = False, context=None) -> dict:
        raise AssertionError("must not be called when project is None")

    result = await resolve_project_filter_candidates(None, resolve_project_ref=resolve_project_ref)

    assert result is None


@pytest.mark.asyncio
async def test_resolve_project_filter_candidates_builds_id_identifier_name_set() -> None:
    async def resolve_project_ref(project_ref: str, *, write: bool = False, context=None) -> dict:
        assert write is False
        return {"id": 6, "identifier": "demo", "name": "Demo Project"}

    result = await resolve_project_filter_candidates("demo", resolve_project_ref=resolve_project_ref)

    assert result == {"6", "demo", "demo project"}


def test_summary_matches_project_candidates_by_id() -> None:
    summary = _Summary(project_id=6, project="Other Name")
    assert summary_matches_project_candidates(summary, {"6"}) is True


def test_summary_matches_project_candidates_by_name() -> None:
    summary = _Summary(project_id=99, project="Demo Project")
    assert summary_matches_project_candidates(summary, {"demo project"}) is True


def test_summary_matches_project_candidates_no_overlap_returns_false() -> None:
    summary = _Summary(project_id=99, project="Other Project")
    assert summary_matches_project_candidates(summary, {"demo project", "6"}) is False
