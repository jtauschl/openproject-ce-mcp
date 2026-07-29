"""Integration tests for work package reminder write operations."""

from __future__ import annotations

import dataclasses

import pytest

from openproject_ce_mcp.client import InvalidInputError, OpenProjectClient

pytestmark = pytest.mark.integration


async def test_create_reminder_rejects_hidden_note_field(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    """Regression: attachment/reminder/relation/group writes bypassed the
    hidden-fields guard -- reminder.note/remind_at could be written even
    with OPENPROJECT_HIDE_REMINDER_FIELDS set, unlike every other
    write-capable entity."""
    result = await client.create_work_package(
        project=test_project,
        type="Task",
        subject="[integration-test] reminder hidden field",
        confirm=True,
    )
    assert result.ready
    wp_ids.append(result.work_package_id)

    hidden_settings = dataclasses.replace(client.settings, hidden_fields={"reminder": ("note",)})
    hidden_client = OpenProjectClient(hidden_settings)
    await hidden_client.initialize()

    with pytest.raises(InvalidInputError, match="OPENPROJECT_HIDE_REMINDER_FIELDS"):
        await hidden_client.create_work_package_reminder(
            work_package_id=result.work_package_id,
            remind_at="2027-01-01T09:00:00Z",
            note="hidden note",
            confirm=False,
        )
