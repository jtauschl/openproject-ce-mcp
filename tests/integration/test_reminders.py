"""Integration tests for work package reminder write operations."""

from __future__ import annotations

import dataclasses

import pytest

from openproject_ce_mcp.client import InvalidInputError, OpenProjectClient, PermissionDeniedError

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


async def test_list_reminders_finds_created_reminder(
    client: OpenProjectClient, test_project: str, wp_ids: list[int], reminder_ids: list[int]
) -> None:
    """list_reminders fetches the caller's own reminders instance-wide, then
    filters by the read allowlist via the reminder's remindable work package
    link (_work_package_project_allowed) -- a reminder on a work package in
    the readable test_project must survive that filter."""
    wp = await client.create_work_package(
        project=test_project, type="Task", subject="[integration-test] list_reminders", confirm=True
    )
    assert wp.ready
    wp_ids.append(wp.work_package_id)

    created = await client.create_work_package_reminder(
        work_package_id=wp.work_package_id, remind_at="2027-01-01T09:00:00Z", confirm=True
    )
    assert created.confirmed
    reminder_ids.append(created.reminder_id)

    result = await client.list_reminders()
    assert any(r.id == created.reminder_id for r in result.results)


async def test_update_reminder_denied_outside_write_allowlist(
    denied_client: OpenProjectClient, client: OpenProjectClient, test_project: str, wp_ids: list[int], reminder_ids: list[int]
) -> None:
    """update_reminder resolves the reminder's underlying work package and
    authorizes the write against its project -- a caller without write
    access to that project must be denied."""
    wp = await client.create_work_package(
        project=test_project, type="Task", subject="[integration-test] update_reminder denied", confirm=True
    )
    assert wp.ready
    wp_ids.append(wp.work_package_id)

    created = await client.create_work_package_reminder(
        work_package_id=wp.work_package_id, remind_at="2027-01-01T09:00:00Z", confirm=True
    )
    assert created.confirmed
    reminder_ids.append(created.reminder_id)

    with pytest.raises(PermissionDeniedError):
        await denied_client.update_reminder(reminder_id=created.reminder_id, note="denied", confirm=True)


async def test_update_reminder_changes_note(
    client: OpenProjectClient, test_project: str, wp_ids: list[int], reminder_ids: list[int]
) -> None:
    wp = await client.create_work_package(
        project=test_project, type="Task", subject="[integration-test] update_reminder note", confirm=True
    )
    assert wp.ready
    wp_ids.append(wp.work_package_id)

    created = await client.create_work_package_reminder(
        work_package_id=wp.work_package_id, remind_at="2027-01-01T09:00:00Z", confirm=True
    )
    assert created.confirmed
    reminder_ids.append(created.reminder_id)

    preview = await client.update_reminder(reminder_id=created.reminder_id, note="updated by integration test")
    assert preview.requires_confirmation

    updated = await client.update_reminder(
        reminder_id=created.reminder_id, note="updated by integration test", confirm=True
    )
    assert updated.confirmed
    assert updated.result.note == "updated by integration test"


async def test_delete_reminder_denied_outside_write_allowlist(
    denied_client: OpenProjectClient, client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    """delete_reminder shares _ensure_reminder_project_write_allowed with
    update_reminder -- regression (found while adding this suite): that
    helper called a GET reminders/{id} endpoint that doesn't exist in
    OpenProject's API (only PATCH/DELETE are mounted on the single-item
    route), 404ing before the allowlist check could even run."""
    wp = await client.create_work_package(
        project=test_project, type="Task", subject="[integration-test] delete_reminder denied", confirm=True
    )
    assert wp.ready
    wp_ids.append(wp.work_package_id)

    created = await client.create_work_package_reminder(
        work_package_id=wp.work_package_id, remind_at="2027-01-01T09:00:00Z", confirm=True
    )
    assert created.confirmed

    with pytest.raises(PermissionDeniedError):
        await denied_client.delete_reminder(reminder_id=created.reminder_id, confirm=True)

    # Not denied -- clean up for real via the allowed client.
    await client.delete_reminder(reminder_id=created.reminder_id, confirm=True)


async def test_delete_reminder_removes_it(client: OpenProjectClient, test_project: str, wp_ids: list[int]) -> None:
    wp = await client.create_work_package(
        project=test_project, type="Task", subject="[integration-test] delete_reminder", confirm=True
    )
    assert wp.ready
    wp_ids.append(wp.work_package_id)

    created = await client.create_work_package_reminder(
        work_package_id=wp.work_package_id, remind_at="2027-01-01T09:00:00Z", confirm=True
    )
    assert created.confirmed

    deleted = await client.delete_reminder(reminder_id=created.reminder_id, confirm=True)
    assert deleted.confirmed

    result = await client.list_reminders()
    assert not any(r.id == created.reminder_id for r in result.results)
