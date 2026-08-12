"""Integration tests for the Meetings domain (5 sub-resources, OPM-154):
Meetings, Meeting Agenda Items, Meeting Sections, Meeting Outcomes,
Recurring Meetings + virtual Occurrences.

Requires OpenProject 17.4+ for Meetings/Agenda Items/Sections/Recurring
Meetings -- the meetings module's agenda/section/participant shape does not
exist on 16.6 (verified against op-sources: 16.6/17.3 carry only `meetings`+
`attachments`, no `meeting_agenda_items`/`meeting_sections`/
`recurring_meetings` directories at all). Meeting Outcomes additionally
require 17.6+ (verified: the `meeting_outcomes` directory does not exist in
op-sources/17.4 or 17.5, only 17.6+). Tests for domain pieces unavailable on
the target instance skip via NotFoundError, matching this project's
established pattern (see test_backlog_buckets.py) -- there is no
version-detection API to gate on directly, so the runtime 404 IS the gate.

Live-verify items flagged in the implementation plan, documented with their
actual outcome once observed against a real instance:

- Whether `lock_version` is required on Meeting/Agenda Item/Section PATCH:
  not required in practice -- update_meeting/update_meeting_agenda_item/
  update_meeting_section all succeed here without ever passing lock_version.
- Whether the ISO8601 `start_time` URL-path-encoding assumption for
  Recurring Meeting Occurrences round-trips correctly: confirmed by
  test_recurring_meeting_occurrence_init_and_cancel below actually reaching
  the server and getting a real response back (a wrong percent-encoding
  scheme would 404 immediately).
"""

from __future__ import annotations

import uuid

import pytest

from openproject_ce_mcp.client import InvalidInputError, NotFoundError, OpenProjectClient

pytestmark = pytest.mark.integration


# --- Meetings ----------------------------------------------------------


async def test_create_get_update_delete_meeting(
    client: OpenProjectClient, test_project: str, meeting_ids: list[int]
) -> None:
    title = f"[integration-test] meeting {uuid.uuid4().hex[:8]}"
    try:
        result = await client.create_meeting(project=test_project, title=title, confirm=True)
    except NotFoundError:
        pytest.skip("Meetings module not installed/enabled, or OpenProject < 17.4, on this instance")
    assert result.ready, result.validation_errors
    meeting_id = result.meeting_id
    assert meeting_id is not None and meeting_id > 0
    meeting_ids.append(meeting_id)

    meeting = await client.get_meeting(meeting_id)
    assert meeting.id == meeting_id
    assert meeting.title == title
    assert meeting.project is not None

    update_result = await client.update_meeting(meeting_id=meeting_id, title=f"{title} updated", confirm=True)
    assert update_result.ready, update_result.validation_errors

    updated = await client.get_meeting(meeting_id)
    assert updated.title == f"{title} updated"

    delete_result = await client.delete_meeting(meeting_id=meeting_id, confirm=True)
    assert delete_result.ready and delete_result.state == "confirmed"
    meeting_ids.remove(meeting_id)


async def test_create_meeting_preview_without_confirm_does_not_write(
    client: OpenProjectClient, test_project: str
) -> None:
    title = f"[integration-test] meeting preview {uuid.uuid4().hex[:8]}"
    try:
        preview_result = await client.create_meeting(project=test_project, title=title, confirm=False)
    except NotFoundError:
        pytest.skip("Meetings module not installed/enabled, or OpenProject < 17.4, on this instance")
    assert preview_result.state == "preview"
    assert preview_result.result is None

    listed = await client.list_meetings(project=test_project)
    assert not any(m.title == title for m in listed.results)


async def test_list_meetings(client: OpenProjectClient, test_project: str, meeting_ids: list[int]) -> None:
    title = f"[integration-test] meeting list {uuid.uuid4().hex[:8]}"
    try:
        create_result = await client.create_meeting(project=test_project, title=title, confirm=True)
    except NotFoundError:
        pytest.skip("Meetings module not installed/enabled, or OpenProject < 17.4, on this instance")
    assert create_result.ready, create_result.validation_errors
    meeting_ids.append(create_result.meeting_id)

    result = await client.list_meetings(project=test_project)
    assert result.count > 0
    assert any(m.title == title for m in result.results)


# --- Meeting Sections + Agenda Items ----------------------------------------


async def test_create_get_update_delete_meeting_section(
    client: OpenProjectClient, test_project: str, meeting_ids: list[int]
) -> None:
    try:
        meeting_result = await client.create_meeting(
            project=test_project, title=f"[integration-test] {uuid.uuid4().hex[:8]}", confirm=True
        )
    except NotFoundError:
        pytest.skip("Meetings module not installed/enabled, or OpenProject < 17.4, on this instance")
    assert meeting_result.ready, meeting_result.validation_errors
    meeting_id = meeting_result.meeting_id
    meeting_ids.append(meeting_id)

    title = f"[integration-test] section {uuid.uuid4().hex[:8]}"
    create_result = await client.create_meeting_section(meeting_id=meeting_id, title=title, confirm=True)
    assert create_result.ready, create_result.validation_errors
    section_id = create_result.section_id
    assert section_id is not None

    section = await client.get_meeting_section(section_id)
    assert section.id == section_id
    assert section.meeting_id == meeting_id

    listed = await client.list_meeting_sections(meeting_id)
    assert any(s.id == section_id for s in listed.results)

    update_result = await client.update_meeting_section(section_id=section_id, title=f"{title} updated", confirm=True)
    assert update_result.ready, update_result.validation_errors

    updated = await client.get_meeting_section(section_id)
    assert updated.title == f"{title} updated"

    delete_result = await client.delete_meeting_section(section_id=section_id, confirm=True)
    assert delete_result.ready and delete_result.state == "confirmed"


async def test_create_get_update_delete_meeting_agenda_item(
    client: OpenProjectClient, test_project: str, meeting_ids: list[int]
) -> None:
    try:
        meeting_result = await client.create_meeting(
            project=test_project, title=f"[integration-test] {uuid.uuid4().hex[:8]}", confirm=True
        )
    except NotFoundError:
        pytest.skip("Meetings module not installed/enabled, or OpenProject < 17.4, on this instance")
    assert meeting_result.ready, meeting_result.validation_errors
    meeting_id = meeting_result.meeting_id
    meeting_ids.append(meeting_id)

    title = f"[integration-test] agenda item {uuid.uuid4().hex[:8]}"
    create_result = await client.create_meeting_agenda_item(meeting_id=meeting_id, title=title, confirm=True)
    assert create_result.ready, create_result.validation_errors
    agenda_item_id = create_result.agenda_item_id
    assert agenda_item_id is not None

    item = await client.get_meeting_agenda_item(agenda_item_id)
    assert item.id == agenda_item_id
    assert item.meeting_id == meeting_id

    listed = await client.list_meeting_agenda_items(meeting_id)
    assert any(i.id == agenda_item_id for i in listed.results)

    update_result = await client.update_meeting_agenda_item(
        agenda_item_id=agenda_item_id, title=f"{title} updated", confirm=True
    )
    assert update_result.ready, update_result.validation_errors

    updated = await client.get_meeting_agenda_item(agenda_item_id)
    assert updated.title == f"{title} updated"

    delete_result = await client.delete_meeting_agenda_item(agenda_item_id=agenda_item_id, confirm=True)
    assert delete_result.ready and delete_result.state == "confirmed"


async def test_meeting_agenda_item_links_to_work_package(
    client: OpenProjectClient, test_project: str, meeting_ids: list[int], wp_ids: list[int]
) -> None:
    try:
        meeting_result = await client.create_meeting(
            project=test_project, title=f"[integration-test] {uuid.uuid4().hex[:8]}", confirm=True
        )
    except NotFoundError:
        pytest.skip("Meetings module not installed/enabled, or OpenProject < 17.4, on this instance")
    assert meeting_result.ready, meeting_result.validation_errors
    meeting_id = meeting_result.meeting_id
    meeting_ids.append(meeting_id)

    wp_result = await client.create_work_package(
        project=test_project,
        type="Task",
        subject=f"[integration-test] meeting agenda item wp {uuid.uuid4().hex[:8]}",
        confirm=True,
    )
    assert wp_result.ready, wp_result.validation_errors
    work_package_id = wp_result.work_package_id
    wp_ids.append(work_package_id)

    create_result = await client.create_meeting_agenda_item(
        meeting_id=meeting_id,
        title="[integration-test] linked agenda item",
        work_package_id=work_package_id,
        confirm=True,
    )
    assert create_result.ready, create_result.validation_errors
    agenda_item_id = create_result.agenda_item_id

    item = await client.get_meeting_agenda_item(agenda_item_id)
    assert item.work_package_id == work_package_id

    listed = await client.list_work_package_meeting_agenda_items(work_package_id)
    assert any(i.id == agenda_item_id for i in listed.results)


# --- Meeting Outcomes (17.6+) ------------------------------------------


async def test_create_get_update_delete_meeting_outcome(
    client: OpenProjectClient, test_project: str, meeting_ids: list[int]
) -> None:
    try:
        meeting_result = await client.create_meeting(
            project=test_project, title=f"[integration-test] {uuid.uuid4().hex[:8]}", confirm=True
        )
    except NotFoundError:
        pytest.skip("Meetings module not installed/enabled, or OpenProject < 17.4, on this instance")
    assert meeting_result.ready, meeting_result.validation_errors
    meeting_id = meeting_result.meeting_id
    meeting_ids.append(meeting_id)

    agenda_result = await client.create_meeting_agenda_item(
        meeting_id=meeting_id, title="[integration-test] agenda item for outcome", confirm=True
    )
    assert agenda_result.ready, agenda_result.validation_errors
    agenda_item_id = agenda_result.agenda_item_id

    try:
        create_result = await client.create_meeting_outcome(agenda_item_id=agenda_item_id, kind="info", confirm=True)
    except NotFoundError:
        pytest.skip("meeting_outcomes endpoint not available (requires OpenProject 17.6+)")
    assert create_result.ready, create_result.validation_errors
    outcome_id = create_result.outcome_id
    assert outcome_id is not None

    outcome = await client.get_meeting_outcome(outcome_id)
    assert outcome.id == outcome_id
    assert outcome.meeting_agenda_item_id == agenda_item_id

    listed = await client.list_meeting_outcomes(agenda_item_id)
    assert any(o.id == outcome_id for o in listed.results)

    update_result = await client.update_meeting_outcome(outcome_id=outcome_id, kind="action", confirm=True)
    assert update_result.ready, update_result.validation_errors

    updated = await client.get_meeting_outcome(outcome_id)
    assert updated.kind == "action"

    delete_result = await client.delete_meeting_outcome(outcome_id=outcome_id, confirm=True)
    assert delete_result.ready and delete_result.state == "confirmed"


# --- Recurring Meetings + Occurrences ------------------------------------


async def test_create_get_update_delete_recurring_meeting(
    client: OpenProjectClient, test_project: str, recurring_meeting_ids: list[int]
) -> None:
    title = f"[integration-test] recurring {uuid.uuid4().hex[:8]}"
    try:
        result = await client.create_recurring_meeting(
            project=test_project,
            title=title,
            frequency="weekly",
            start_time="2030-01-07T09:00:00Z",
            confirm=True,
        )
    except NotFoundError:
        pytest.skip("Recurring meetings not available, or OpenProject < 17.4, on this instance")
    assert result.ready, result.validation_errors
    recurring_meeting_id = result.recurring_meeting_id
    assert recurring_meeting_id is not None
    recurring_meeting_ids.append(recurring_meeting_id)

    recurring = await client.get_recurring_meeting(recurring_meeting_id)
    assert recurring.id == recurring_meeting_id
    assert recurring.title == title

    update_result = await client.update_recurring_meeting(
        recurring_meeting_id=recurring_meeting_id, title=f"{title} updated", confirm=True
    )
    assert update_result.ready, update_result.validation_errors

    updated = await client.get_recurring_meeting(recurring_meeting_id)
    assert updated.title == f"{title} updated"

    delete_result = await client.delete_recurring_meeting(recurring_meeting_id=recurring_meeting_id, confirm=True)
    assert delete_result.ready and delete_result.state == "confirmed"
    recurring_meeting_ids.remove(recurring_meeting_id)


async def test_list_recurring_meeting_occurrences_all_four_filters(
    client: OpenProjectClient, test_project: str, recurring_meeting_ids: list[int]
) -> None:
    try:
        result = await client.create_recurring_meeting(
            project=test_project,
            title=f"[integration-test] occurrences {uuid.uuid4().hex[:8]}",
            frequency="weekly",
            start_time="2030-02-04T09:00:00Z",
            confirm=True,
        )
    except NotFoundError:
        pytest.skip("Recurring meetings not available, or OpenProject < 17.4, on this instance")
    assert result.ready, result.validation_errors
    recurring_meeting_id = result.recurring_meeting_id
    recurring_meeting_ids.append(recurring_meeting_id)

    for filter_name in ("upcoming", "past", "cancelled", "open"):
        listed = await client.list_recurring_meeting_occurrences(recurring_meeting_id, filter=filter_name)
        assert listed.filter == filter_name
        assert listed.count >= 0


async def test_recurring_meeting_occurrence_init_and_cancel(
    client: OpenProjectClient,
    test_project: str,
    recurring_meeting_ids: list[int],
    meeting_ids: list[int],
) -> None:
    """Materializes one upcoming occurrence into a real Meeting, and cancels
    a different, not-yet-materialized one. The cancelled occurrence's
    server-created cancellation Meeting is NOT independently cleaned up here
    (its id is not returned to the caller at all -- see this domain's
    documented quirk in tools.py/docs/tools.md); it is a genuine, expected,
    permanent side effect of calling cancel on a virtual occurrence, not a
    test-cleanup gap."""
    try:
        result = await client.create_recurring_meeting(
            project=test_project,
            title=f"[integration-test] init-cancel {uuid.uuid4().hex[:8]}",
            frequency="weekly",
            start_time="2030-03-04T09:00:00Z",
            confirm=True,
        )
    except NotFoundError:
        pytest.skip("Recurring meetings not available, or OpenProject < 17.4, on this instance")
    assert result.ready, result.validation_errors
    recurring_meeting_id = result.recurring_meeting_id
    recurring_meeting_ids.append(recurring_meeting_id)

    upcoming = await client.list_recurring_meeting_occurrences(recurring_meeting_id, filter="upcoming", limit=5)
    if len(upcoming.results) < 2:
        pytest.skip("fewer than 2 upcoming occurrences computed by the server for this recurrence rule")

    init_target = upcoming.results[0]
    init_result = await client.init_recurring_meeting_occurrence(
        recurring_meeting_id=recurring_meeting_id, start_time=init_target.start_time, confirm=True
    )
    assert init_result.ready and init_result.state == "confirmed", init_result.validation_errors
    assert init_result.result is not None
    materialized_meeting_id = init_result.result.id
    meeting_ids.append(materialized_meeting_id)

    cancel_target = upcoming.results[1]
    cancel_result = await client.cancel_recurring_meeting_occurrence(
        recurring_meeting_id=recurring_meeting_id, start_time=cancel_target.start_time, confirm=True
    )
    assert cancel_result.ready and cancel_result.state == "confirmed", cancel_result.validation_errors

    cancelled = await client.list_recurring_meeting_occurrences(recurring_meeting_id, filter="cancelled")
    assert any(o.start_time == cancel_target.start_time for o in cancelled.results)


async def test_cancel_already_materialized_occurrence_fails(
    client: OpenProjectClient,
    test_project: str,
    recurring_meeting_ids: list[int],
    meeting_ids: list[int],
) -> None:
    """Documents the real OpenProject 409 for the "already materialized,
    not cancelled" case -- surfaces as InvalidInputError with no
    special-casing needed client-side."""
    try:
        result = await client.create_recurring_meeting(
            project=test_project,
            title=f"[integration-test] already-materialized {uuid.uuid4().hex[:8]}",
            frequency="weekly",
            start_time="2030-04-01T09:00:00Z",
            confirm=True,
        )
    except NotFoundError:
        pytest.skip("Recurring meetings not available, or OpenProject < 17.4, on this instance")
    assert result.ready, result.validation_errors
    recurring_meeting_id = result.recurring_meeting_id
    recurring_meeting_ids.append(recurring_meeting_id)

    upcoming = await client.list_recurring_meeting_occurrences(recurring_meeting_id, filter="upcoming", limit=1)
    if not upcoming.results:
        pytest.skip("no upcoming occurrence computed by the server for this recurrence rule")
    target = upcoming.results[0]

    init_result = await client.init_recurring_meeting_occurrence(
        recurring_meeting_id=recurring_meeting_id, start_time=target.start_time, confirm=True
    )
    assert init_result.ready, init_result.validation_errors
    meeting_ids.append(init_result.result.id)

    with pytest.raises(InvalidInputError):
        await client.cancel_recurring_meeting_occurrence(
            recurring_meeting_id=recurring_meeting_id, start_time=target.start_time, confirm=True
        )
