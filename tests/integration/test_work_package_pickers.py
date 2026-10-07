"""Assignee and relation picker integration tests; use a disposable instance only."""

from __future__ import annotations

import uuid

import pytest

from openproject_ce_mcp.client import OpenProjectClient

pytestmark = pytest.mark.integration
_SUBJECT = "[integration-test] pickers"


async def _new_work_package(client: OpenProjectClient, test_project: str, wp_ids: list[int], suffix: str) -> int:
    result = await client.work_package.create(
        project=test_project, type="Task", subject=f"{_SUBJECT} {suffix}", confirm=True
    )
    assert result.ready, result.validation_errors
    wp_ids.append(result.work_package_id)
    return result.work_package_id


async def test_work_package_pickers(client: OpenProjectClient, test_project: str, wp_ids: list[int]) -> None:
    first = await _new_work_package(client, test_project, wp_ids, f"picker-a {uuid.uuid4().hex}")
    second_suffix = uuid.uuid4().hex
    second = await _new_work_package(client, test_project, wp_ids, f"picker-b {second_suffix}")

    assignees = await client.work_package_picker.available_assignees(work_package_id=first)
    project_assignees = await client.work_package_picker.available_assignees(project_ref=test_project)
    assert assignees.count == len(assignees.results)
    assert {p.id for p in project_assignees.results} <= {p.id for p in assignees.results}

    candidates = await client.work_package_picker.relation_candidates(
        first, query=second_suffix, relation_type="relates"
    )
    assert second in {c.id for c in candidates.results}
    assert first not in {c.id for c in candidates.results}
