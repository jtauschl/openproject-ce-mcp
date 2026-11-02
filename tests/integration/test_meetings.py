"""Integration tests for the Meetings domain (5 sub-resources):
Meetings, Meeting Agenda Items, Meeting Sections, Meeting Outcomes,
Recurring Meetings + virtual Occurrences.

Requires OpenProject 17.4+ for Meetings/Recurring Meetings -- the meetings
module does not exist on 16.6 (verified against the OpenProject source: 16.6/17.3 carry
only `meetings`+`attachments`, no `meeting_agenda_items`/`meeting_sections`/
`recurring_meetings` directories at all). Meeting Agenda Items, Sections,
and Outcomes additionally require 17.6+: the top-level collection route each
one's create call POSTs to (`meeting_agenda_items_api.rb`,
`meeting_sections_api.rb`, `meeting_outcomes` directory) does not exist on
17.4/17.5 -- only a *nested* `sections_by_meeting_api.rb`
(`meetings/{id}/sections`) exists there, a different route this client does
not use. list_work_package_meeting_agenda_items needs a further, separate
17.7+: `meeting_agenda_items_by_work_package_api.rb` (the
`work_packages/{id}/meeting_agenda_items` route it GETs) does not exist on
17.6 -- confirmed absent there even though plain agenda item creation
already works on 17.6. Tests for domain pieces unavailable on the target
instance skip via NotFoundError, matching this project's established
pattern (see test_backlog_buckets.py) -- there is no version-detection API
to gate on
directly, so the runtime 404 IS the gate.

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

import os
import uuid
from collections.abc import Callable

import pytest

from openproject_ce_mcp.client import (
    ConflictError,
    InvalidInputError,
    NotFoundError,
    OpenProjectClient,
    PermissionDeniedError,
)

from ._write_ref import write_ref
from .conftest import _run_rails_script, disposable_project_identifier

pytestmark = pytest.mark.integration


# --- Meetings ----------------------------------------------------------


async def test_create_get_update_delete_meeting(
    client: OpenProjectClient, test_project: str, meeting_ids: list[int]
) -> None:
    title = f"[integration-test] meeting {uuid.uuid4().hex[:8]}"
    try:
        result = await client.meeting.create(project=test_project, title=title, confirm=True)
    except NotFoundError:
        pytest.skip("Meetings module not installed/enabled, or OpenProject < 17.4, on this instance")
    assert result.ready, result.validation_errors
    meeting_id = result.meeting_id
    assert meeting_id is not None and meeting_id > 0
    meeting_ids.append(meeting_id)

    meeting = await client.meeting.get(meeting_id)
    assert meeting.id == meeting_id
    assert meeting.title == title
    assert meeting.project is not None

    update_result = await client.meeting.update(meeting_id=meeting_id, title=f"{title} updated", confirm=True)
    assert update_result.ready, update_result.validation_errors

    updated = await client.meeting.get(meeting_id)
    assert updated.title == f"{title} updated"

    delete_result = await client.meeting.delete(meeting_id=meeting_id, confirm=True)
    assert delete_result.ready and delete_result.state == "confirmed"
    meeting_ids.remove(meeting_id)


async def test_create_meeting_rejects_state_and_notify_and_update_sets_the_state(
    client: OpenProjectClient, test_project: str, meeting_ids: list[int]
) -> None:
    title = f"[integration-test] create state {uuid.uuid4().hex[:8]}"
    with pytest.raises(InvalidInputError, match="does not apply state or notify"):
        await client.meeting.create(project=test_project, title=title, state="open", confirm=True)

    try:
        created = await client.meeting.create(project=test_project, title=title, confirm=True)
    except NotFoundError:
        pytest.skip("Meetings module not installed/enabled, or OpenProject < 17.4, on this instance")
    assert created.ready, created.validation_errors
    meeting_ids.append(created.meeting_id)
    fetched = await client.meeting.get(created.meeting_id)
    assert (fetched.state, fetched.notify) == ("draft", False)

    # state only: with notify off the update sends no invitations.
    updated = await client.meeting.update(meeting_id=created.meeting_id, state="open", confirm=True)
    assert updated.ready, updated.validation_errors
    assert (await client.meeting.get(created.meeting_id)).state == "open"


async def test_create_meeting_gives_exactly_the_named_participants_and_update_rejects_changes(
    client: OpenProjectClient, restricted_client: OpenProjectClient, test_project: str, meeting_ids: list[int]
) -> None:
    other = await restricted_client.current_user.get_current_user()
    me = await client.current_user.get_current_user()
    try:
        created = await client.meeting.create(
            project=test_project,
            title=f"[integration-test] participants {uuid.uuid4().hex[:8]}",
            participant_user_refs=[str(other.id)],
            confirm=True,
        )
    except NotFoundError:
        pytest.skip("Meetings module not installed/enabled, or OpenProject < 17.4, on this instance")
    assert created.ready, created.validation_errors
    meeting_ids.append(created.meeting_id)

    # Exactly the named users: the creating user is a participant only if named.
    assert [p.id for p in (await client.meeting.get(created.meeting_id)).participants] == [other.id]

    with pytest.raises(InvalidInputError, match="update_meeting cannot change participants"):
        await client.meeting.update(meeting_id=created.meeting_id, participant_user_refs=[str(me.id)], confirm=True)
    assert [p.id for p in (await client.meeting.get(created.meeting_id)).participants] == [other.id]


async def test_create_meeting_preview_without_confirm_does_not_write(
    client: OpenProjectClient, test_project: str
) -> None:
    title = f"[integration-test] meeting preview {uuid.uuid4().hex[:8]}"
    try:
        preview_result = await client.meeting.create(project=test_project, title=title, confirm=False)
    except NotFoundError:
        pytest.skip("Meetings module not installed/enabled, or OpenProject < 17.4, on this instance")
    assert preview_result.state == "preview"
    assert preview_result.result is None

    listed = await client.meeting.list_all(project=test_project)
    assert not any(m.title == title for m in listed.results)


async def test_list_meetings(client: OpenProjectClient, test_project: str, meeting_ids: list[int]) -> None:
    title = f"[integration-test] meeting list {uuid.uuid4().hex[:8]}"
    try:
        create_result = await client.meeting.create(project=test_project, title=title, confirm=True)
    except NotFoundError:
        pytest.skip("Meetings module not installed/enabled, or OpenProject < 17.4, on this instance")
    assert create_result.ready, create_result.validation_errors
    meeting_ids.append(create_result.meeting_id)

    result = await client.meeting.list_all(project=test_project)
    assert result.count > 0
    assert any(m.title == title for m in result.results)


async def test_list_meetings_title_filter(
    client: OpenProjectClient, test_project: str, meeting_ids: list[int], openproject_version: tuple[int, int]
) -> None:
    marker = uuid.uuid4().hex[:8]
    title = f"[integration-test] Title Filter {marker}"
    try:
        create_result = await client.meeting.create(project=test_project, title=title, confirm=True)
    except NotFoundError:
        pytest.skip("Meetings module not installed/enabled, or OpenProject < 17.4, on this instance")
    assert create_result.ready, create_result.validation_errors
    meeting_ids.append(create_result.meeting_id)

    try:
        matched = await client.meeting.list_all(project=test_project, title=f"title filter {marker}")
    except InvalidInputError:
        if openproject_version >= (17, 9):
            raise
        pytest.skip("Meetings title filter requires OpenProject 17.9+ on this instance")
    assert [m.id for m in matched.results] == [create_result.meeting_id]

    unmatched = await client.meeting.list_all(project=test_project, title=f"no-such-title {marker}")
    assert unmatched.results == []


async def test_create_and_update_meeting_denied_outside_write_allowlist(
    denied_client: OpenProjectClient, client: OpenProjectClient, test_project: str, meeting_ids: list[int]
) -> None:
    # denied_client's call can only ever raise PermissionDeniedError (the
    # write-allowlist check runs before the meetings endpoint is reached) --
    # the real NotFoundError risk ("Meetings module not installed/enabled,
    # or OpenProject < 17.4") is on the unrestricted client's own call below.
    with pytest.raises(PermissionDeniedError):
        await denied_client.meeting.create(
            project=test_project, title=f"[integration-test] denied {uuid.uuid4().hex[:8]}", confirm=True
        )

    try:
        existing = await client.meeting.create(
            project=test_project, title=f"[integration-test] {uuid.uuid4().hex[:8]}", confirm=True
        )
    except NotFoundError:
        pytest.skip("Meetings module not installed/enabled, or OpenProject < 17.4, on this instance")
    assert existing.ready, existing.validation_errors
    meeting_id = existing.meeting_id
    meeting_ids.append(meeting_id)

    with pytest.raises(PermissionDeniedError):
        await denied_client.meeting.update(meeting_id=meeting_id, title="denied update", confirm=True)


# --- Meeting Sections + Agenda Items ----------------------------------------


async def test_create_get_update_delete_meeting_section(
    client: OpenProjectClient, test_project: str, meeting_ids: list[int]
) -> None:
    try:
        meeting_result = await client.meeting.create(
            project=test_project, title=f"[integration-test] {uuid.uuid4().hex[:8]}", confirm=True
        )
    except NotFoundError:
        pytest.skip("Meetings module not installed/enabled, or OpenProject < 17.4, on this instance")
    assert meeting_result.ready, meeting_result.validation_errors
    meeting_id = meeting_result.meeting_id
    meeting_ids.append(meeting_id)

    title = f"[integration-test] section {uuid.uuid4().hex[:8]}"
    try:
        create_result = await client.meeting_section.create(meeting_id=meeting_id, title=title, confirm=True)
    except NotFoundError:
        pytest.skip("meeting_sections endpoint not available (requires OpenProject 17.6+)")
    assert create_result.ready, create_result.validation_errors
    section_id = create_result.section_id
    assert section_id is not None

    section = await client.meeting_section.get(section_id)
    assert section.id == section_id
    assert section.meeting_id == meeting_id

    listed = await client.meeting_section.list_for_meeting(meeting_id)
    assert any(s.id == section_id for s in listed.results)

    update_result = await client.meeting_section.update(section_id=section_id, title=f"{title} updated", confirm=True)
    assert update_result.ready, update_result.validation_errors

    updated = await client.meeting_section.get(section_id)
    assert updated.title == f"{title} updated"

    delete_result = await client.meeting_section.delete(section_id=section_id, confirm=True)
    assert delete_result.ready and delete_result.state == "confirmed"


async def test_create_update_delete_meeting_section_denied_outside_write_allowlist(
    denied_client: OpenProjectClient, client: OpenProjectClient, test_project: str, meeting_ids: list[int]
) -> None:
    """MeetingSectionService.create's allowlist check
    (_ensure_meeting_allowed) runs BEFORE the sections-specific 17.6+
    endpoint is ever touched, so a denied_client call always raises
    PermissionDeniedError regardless of instance version -- it can never
    raise NotFoundError. The 17.6+-availability skip therefore only needs to
    wrap the unrestricted client's own create_meeting_section call below,
    not the denied_client attempt above it (same reasoning as
    test_create_update_delete_meeting_outcome_denied_outside_write_allowlist)."""
    try:
        meeting_result = await client.meeting.create(
            project=test_project, title=f"[integration-test] {uuid.uuid4().hex[:8]}", confirm=True
        )
    except NotFoundError:
        pytest.skip("Meetings module not installed/enabled, or OpenProject < 17.4, on this instance")
    assert meeting_result.ready, meeting_result.validation_errors
    meeting_id = meeting_result.meeting_id
    meeting_ids.append(meeting_id)

    with pytest.raises(PermissionDeniedError):
        await denied_client.meeting_section.create(
            meeting_id=meeting_id, title="[integration-test] denied", confirm=True
        )

    try:
        existing = await client.meeting_section.create(
            meeting_id=meeting_id, title="[integration-test] section", confirm=True
        )
    except NotFoundError:
        pytest.skip("meeting_sections endpoint not available (requires OpenProject 17.6+)")
    assert existing.ready
    section_id = existing.section_id

    with pytest.raises(PermissionDeniedError):
        await denied_client.meeting_section.update(section_id=section_id, title="denied update", confirm=True)

    with pytest.raises(PermissionDeniedError):
        await denied_client.meeting_section.delete(section_id=section_id, confirm=True)


async def test_create_get_update_delete_meeting_agenda_item(
    client: OpenProjectClient, test_project: str, meeting_ids: list[int]
) -> None:
    try:
        meeting_result = await client.meeting.create(
            project=test_project, title=f"[integration-test] {uuid.uuid4().hex[:8]}", confirm=True
        )
    except NotFoundError:
        pytest.skip("Meetings module not installed/enabled, or OpenProject < 17.4, on this instance")
    assert meeting_result.ready, meeting_result.validation_errors
    meeting_id = meeting_result.meeting_id
    meeting_ids.append(meeting_id)

    title = f"[integration-test] agenda item {uuid.uuid4().hex[:8]}"
    try:
        create_result = await client.meeting_agenda_item.create(meeting_id=meeting_id, title=title, confirm=True)
    except NotFoundError:
        pytest.skip("meeting_agenda_items endpoint not available (requires OpenProject 17.6+)")
    assert create_result.ready, create_result.validation_errors
    agenda_item_id = create_result.agenda_item_id
    assert agenda_item_id is not None

    item = await client.meeting_agenda_item.get(agenda_item_id)
    assert item.id == agenda_item_id
    assert item.meeting_id == meeting_id

    listed = await client.meeting_agenda_item.list_for_meeting(meeting_id)
    assert any(i.id == agenda_item_id for i in listed.results)

    update_result = await client.meeting_agenda_item.update(
        agenda_item_id=agenda_item_id, title=f"{title} updated", confirm=True
    )
    assert update_result.ready, update_result.validation_errors

    updated = await client.meeting_agenda_item.get(agenda_item_id)
    assert updated.title == f"{title} updated"

    delete_result = await client.meeting_agenda_item.delete(agenda_item_id=agenda_item_id, confirm=True)
    assert delete_result.ready and delete_result.state == "confirmed"


async def test_list_meeting_agenda_items_text_limit_overrides_the_server_default(
    client: OpenProjectClient, test_project: str, meeting_ids: list[int]
) -> None:
    """list_meeting_agenda_items' text_limit is a per-call override,
    not just the constructor-bound server default."""
    try:
        meeting_result = await client.meeting.create(
            project=test_project, title=f"[integration-test] {uuid.uuid4().hex[:8]}", confirm=True
        )
    except NotFoundError:
        pytest.skip("Meetings module not installed/enabled, or OpenProject < 17.4, on this instance")
    assert meeting_result.ready, meeting_result.validation_errors
    meeting_id = meeting_result.meeting_id
    meeting_ids.append(meeting_id)

    long_notes = "x" * 500
    try:
        create_result = await client.meeting_agenda_item.create(
            meeting_id=meeting_id, title=f"[integration-test] {uuid.uuid4().hex[:8]}", notes=long_notes, confirm=True
        )
    except NotFoundError:
        pytest.skip("meeting_agenda_items endpoint not available (requires OpenProject 17.6+)")
    assert create_result.ready, create_result.validation_errors
    agenda_item_id = create_result.agenda_item_id
    assert agenda_item_id is not None

    limited = await client.meeting_agenda_item.list_for_meeting(meeting_id, text_limit=10)
    item = next(i for i in limited.results if i.id == agenda_item_id)
    assert item.notes_truncated is True
    assert item.notes_length == 500

    default = await client.meeting_agenda_item.list_for_meeting(meeting_id)
    item_default = next(i for i in default.results if i.id == agenda_item_id)
    assert item_default.notes_truncated is False

    await client.meeting_agenda_item.delete(agenda_item_id=agenda_item_id, confirm=True)


async def test_meeting_agenda_item_links_to_work_package(
    client: OpenProjectClient, test_project: str, meeting_ids: list[int], wp_ids: list[int]
) -> None:
    try:
        meeting_result = await client.meeting.create(
            project=test_project, title=f"[integration-test] {uuid.uuid4().hex[:8]}", confirm=True
        )
    except NotFoundError:
        pytest.skip("Meetings module not installed/enabled, or OpenProject < 17.4, on this instance")
    assert meeting_result.ready, meeting_result.validation_errors
    meeting_id = meeting_result.meeting_id
    meeting_ids.append(meeting_id)

    wp_result = await client.work_package.create(
        project=test_project,
        type="Task",
        subject=f"[integration-test] meeting agenda item wp {uuid.uuid4().hex[:8]}",
        confirm=True,
    )
    assert wp_result.ready, wp_result.validation_errors
    work_package_id = wp_result.work_package_id
    wp_ids.append(work_package_id)

    try:
        create_result = await client.meeting_agenda_item.create(
            meeting_id=meeting_id,
            title="[integration-test] linked agenda item",
            work_package_id=await write_ref(client, work_package_id),
            confirm=True,
        )
    except NotFoundError:
        pytest.skip("meeting_agenda_items endpoint not available (requires OpenProject 17.6+)")
    assert create_result.ready, create_result.validation_errors
    agenda_item_id = create_result.agenda_item_id

    item = await client.meeting_agenda_item.get(agenda_item_id)
    assert item.work_package_id == work_package_id

    try:
        listed = await client.meeting_agenda_item.list_for_work_package(work_package_id)
    except NotFoundError:
        pytest.skip("work_packages/{id}/meeting_agenda_items endpoint not available (requires OpenProject 17.7+)")
    assert any(i.id == agenda_item_id for i in listed.results)


async def test_work_package_agenda_items_follow_the_read_scope_of_their_meeting(
    client: OpenProjectClient,
    test_project: str,
    wp_ids: list[int],
    project_refs: list[str],
    start_scoped_client,
) -> None:
    """The meeting that holds an agenda item can sit in another project than the
    work package that item links, so the work package's scope does not decide."""
    everywhere = await start_scoped_client(read_projects=("*",), write_projects=("*",))
    other_project = disposable_project_identifier()
    created = await everywhere.project.create(
        name=f"[integration-test] {other_project}", identifier=other_project, confirm=True
    )
    assert created.ready, created.validation_errors
    project_refs.append(other_project)

    try:
        meeting = await everywhere.meeting.create(
            project=other_project, title=f"[integration-test] {uuid.uuid4().hex[:8]}", confirm=True
        )
    except NotFoundError:
        pytest.skip("Meetings module not installed/enabled, or OpenProject < 17.4, on this instance")
    assert meeting.ready, meeting.validation_errors

    work_package = await client.work_package.create(
        project=test_project, type="Task", subject=f"[integration-test] {uuid.uuid4().hex[:8]}", confirm=True
    )
    assert work_package.ready, work_package.validation_errors
    wp_ids.append(work_package.work_package_id)

    try:
        item = await everywhere.meeting_agenda_item.create(
            meeting_id=meeting.meeting_id,
            title="[integration-test] cross-project item",
            work_package_id=await write_ref(everywhere, work_package.work_package_id),
            confirm=True,
        )
    except NotFoundError:
        pytest.skip("meeting_agenda_items endpoint not available (requires OpenProject 17.6+)")
    assert item.ready, item.validation_errors

    try:
        seen = await everywhere.meeting_agenda_item.list_for_work_package(work_package.work_package_id)
    except NotFoundError:
        pytest.skip("work_packages/{id}/meeting_agenda_items endpoint not available (requires OpenProject 17.7+)")
    assert [i.id for i in seen.results] == [item.agenda_item_id]

    both = await start_scoped_client(read_projects=(test_project, other_project), write_projects=(test_project,))
    assert [
        i.id for i in (await both.meeting_agenda_item.list_for_work_package(work_package.work_package_id)).results
    ] == [item.agenda_item_id]

    only_work_package_project = await start_scoped_client(read_projects=(test_project,), write_projects=(test_project,))
    hidden = await only_work_package_project.meeting_agenda_item.list_for_work_package(work_package.work_package_id)
    assert hidden.results == []
    assert hidden.total == 0


async def test_create_update_delete_meeting_agenda_item_denied_outside_write_allowlist(
    denied_client: OpenProjectClient, client: OpenProjectClient, test_project: str, meeting_ids: list[int]
) -> None:
    """MeetingAgendaItemService.create's allowlist check
    (_ensure_meeting_allowed) runs BEFORE the agenda-items-specific 17.6+
    endpoint is ever touched, so a denied_client call always raises
    PermissionDeniedError regardless of instance version -- it can never
    raise NotFoundError. The 17.6+-availability skip therefore only needs to
    wrap the unrestricted client's own create_meeting_agenda_item call
    below, not the denied_client attempt above it (same reasoning as
    test_create_update_delete_meeting_outcome_denied_outside_write_allowlist)."""
    try:
        meeting_result = await client.meeting.create(
            project=test_project, title=f"[integration-test] {uuid.uuid4().hex[:8]}", confirm=True
        )
    except NotFoundError:
        pytest.skip("Meetings module not installed/enabled, or OpenProject < 17.4, on this instance")
    assert meeting_result.ready, meeting_result.validation_errors
    meeting_id = meeting_result.meeting_id
    meeting_ids.append(meeting_id)

    with pytest.raises(PermissionDeniedError):
        await denied_client.meeting_agenda_item.create(
            meeting_id=meeting_id, title="[integration-test] denied", confirm=True
        )

    try:
        existing = await client.meeting_agenda_item.create(
            meeting_id=meeting_id, title="[integration-test] agenda item", confirm=True
        )
    except NotFoundError:
        pytest.skip("meeting_agenda_items endpoint not available (requires OpenProject 17.6+)")
    assert existing.ready
    agenda_item_id = existing.agenda_item_id

    with pytest.raises(PermissionDeniedError):
        await denied_client.meeting_agenda_item.update(
            agenda_item_id=agenda_item_id, title="denied update", confirm=True
        )

    with pytest.raises(PermissionDeniedError):
        await denied_client.meeting_agenda_item.delete(agenda_item_id=agenda_item_id, confirm=True)


# --- Meeting Outcomes (17.6+) ------------------------------------------


async def test_create_get_update_delete_meeting_outcome(
    client: OpenProjectClient, test_project: str, meeting_ids: list[int]
) -> None:
    try:
        meeting_result = await client.meeting.create(
            project=test_project, title=f"[integration-test] {uuid.uuid4().hex[:8]}", confirm=True
        )
    except NotFoundError:
        pytest.skip("Meetings module not installed/enabled, or OpenProject < 17.4, on this instance")
    assert meeting_result.ready, meeting_result.validation_errors
    meeting_id = meeting_result.meeting_id
    meeting_ids.append(meeting_id)

    try:
        agenda_result = await client.meeting_agenda_item.create(
            meeting_id=meeting_id, title="[integration-test] agenda item for outcome", confirm=True
        )
    except NotFoundError:
        pytest.skip("meeting_agenda_items endpoint not available (requires OpenProject 17.6+)")
    assert agenda_result.ready, agenda_result.validation_errors
    agenda_item_id = agenda_result.agenda_item_id

    # MeetingOutcome#editable? requires meeting.in_progress? (verified against
    # the OpenProject source: modules/meeting/app/models/meeting_outcome.rb and the
    # module's own request specs, which build their outcome fixtures with
    # state: :in_progress) -- a freshly created meeting defaults to "open"
    # and outcome writes are rejected with "This outcome is not editable
    # anymore." until the meeting is moved to in_progress.
    state_result = await client.meeting.update(meeting_id=meeting_id, state="in_progress", confirm=True)
    assert state_result.ready, state_result.validation_errors

    try:
        create_result = await client.meeting_outcome.create(
            agenda_item_id=agenda_item_id, kind="information", notes="integration test note", confirm=True
        )
    except NotFoundError:
        pytest.skip("meeting_outcomes endpoint not available (requires OpenProject 17.6+)")
    assert create_result.ready, create_result.validation_errors
    outcome_id = create_result.outcome_id
    assert outcome_id is not None

    outcome = await client.meeting_outcome.get(outcome_id)
    assert outcome.id == outcome_id
    assert outcome.meeting_agenda_item_id == agenda_item_id

    listed = await client.meeting_outcome.list_for_agenda_item(agenda_item_id)
    assert any(o.id == outcome_id for o in listed.results)

    update_result = await client.meeting_outcome.update(outcome_id=outcome_id, kind="decision", confirm=True)
    assert update_result.ready, update_result.validation_errors

    updated = await client.meeting_outcome.get(outcome_id)
    assert updated.kind == "decision"

    delete_result = await client.meeting_outcome.delete(outcome_id=outcome_id, confirm=True)
    assert delete_result.ready and delete_result.state == "confirmed"


async def test_list_meeting_outcomes_text_limit_overrides_the_server_default(
    client: OpenProjectClient, test_project: str, meeting_ids: list[int]
) -> None:
    """list_meeting_outcomes' text_limit is a per-call override, not
    just the constructor-bound server default."""
    try:
        meeting_result = await client.meeting.create(
            project=test_project, title=f"[integration-test] {uuid.uuid4().hex[:8]}", confirm=True
        )
    except NotFoundError:
        pytest.skip("Meetings module not installed/enabled, or OpenProject < 17.4, on this instance")
    assert meeting_result.ready, meeting_result.validation_errors
    meeting_id = meeting_result.meeting_id
    meeting_ids.append(meeting_id)

    try:
        agenda_result = await client.meeting_agenda_item.create(
            meeting_id=meeting_id, title="[integration-test] agenda item for outcome text_limit", confirm=True
        )
    except NotFoundError:
        pytest.skip("meeting_agenda_items endpoint not available (requires OpenProject 17.6+)")
    assert agenda_result.ready, agenda_result.validation_errors
    agenda_item_id = agenda_result.agenda_item_id

    state_result = await client.meeting.update(meeting_id=meeting_id, state="in_progress", confirm=True)
    assert state_result.ready, state_result.validation_errors

    long_notes = "x" * 500
    try:
        create_result = await client.meeting_outcome.create(
            agenda_item_id=agenda_item_id, kind="information", notes=long_notes, confirm=True
        )
    except NotFoundError:
        pytest.skip("meeting_outcomes endpoint not available (requires OpenProject 17.6+)")
    assert create_result.ready, create_result.validation_errors
    outcome_id = create_result.outcome_id
    assert outcome_id is not None

    limited = await client.meeting_outcome.list_for_agenda_item(agenda_item_id, text_limit=10)
    outcome = next(o for o in limited.results if o.id == outcome_id)
    assert outcome.notes_truncated is True
    assert outcome.notes_length == 500

    default = await client.meeting_outcome.list_for_agenda_item(agenda_item_id)
    outcome_default = next(o for o in default.results if o.id == outcome_id)
    assert outcome_default.notes_truncated is False

    await client.meeting_outcome.delete(outcome_id=outcome_id, confirm=True)


async def test_create_update_delete_meeting_outcome_denied_outside_write_allowlist(
    denied_client: OpenProjectClient, client: OpenProjectClient, test_project: str, meeting_ids: list[int]
) -> None:
    """MeetingOutcomeService.create's allowlist check
    (_ensure_via_agenda_item) runs BEFORE the outcomes-specific 17.6+
    endpoint is ever touched, so a denied_client call always raises
    PermissionDeniedError regardless of instance version -- it can never
    raise NotFoundError. But the agenda item this test needs as a fixture is
    ITSELF 17.6+-only (same as create_meeting_outcome), so that call also
    needs its own skip guard -- the 17.6+-availability skip therefore wraps
    both the fixture's create_meeting_agenda_item call and the unrestricted
    client's own create_meeting_outcome call below, not the denied_client
    attempt above the latter."""
    try:
        meeting_result = await client.meeting.create(
            project=test_project, title=f"[integration-test] {uuid.uuid4().hex[:8]}", confirm=True
        )
    except NotFoundError:
        pytest.skip("Meetings module not installed/enabled, or OpenProject < 17.4, on this instance")
    assert meeting_result.ready, meeting_result.validation_errors
    meeting_id = meeting_result.meeting_id
    meeting_ids.append(meeting_id)

    try:
        agenda_result = await client.meeting_agenda_item.create(
            meeting_id=meeting_id, title="[integration-test] agenda item for outcome denial", confirm=True
        )
    except NotFoundError:
        pytest.skip("meeting_agenda_items endpoint not available (requires OpenProject 17.6+)")
    assert agenda_result.ready
    agenda_item_id = agenda_result.agenda_item_id

    # See test_create_get_update_delete_meeting_outcome's own comment: a
    # freshly created meeting defaults to state "open", but
    # MeetingOutcome#editable? requires "in_progress".
    state_result = await client.meeting.update(meeting_id=meeting_id, state="in_progress", confirm=True)
    assert state_result.ready, state_result.validation_errors

    with pytest.raises(PermissionDeniedError):
        await denied_client.meeting_outcome.create(agenda_item_id=agenda_item_id, kind="information", confirm=True)

    try:
        existing = await client.meeting_outcome.create(
            agenda_item_id=agenda_item_id, kind="information", notes="integration test note", confirm=True
        )
    except NotFoundError:
        pytest.skip("meeting_outcomes endpoint not available (requires OpenProject 17.6+)")
    assert existing.ready
    outcome_id = existing.outcome_id

    with pytest.raises(PermissionDeniedError):
        await denied_client.meeting_outcome.update(outcome_id=outcome_id, kind="decision", confirm=True)

    with pytest.raises(PermissionDeniedError):
        await denied_client.meeting_outcome.delete(outcome_id=outcome_id, confirm=True)


# --- Recurring Meetings + Occurrences ------------------------------------


async def test_create_get_update_delete_recurring_meeting(
    client: OpenProjectClient, test_project: str, recurring_meeting_ids: list[int]
) -> None:
    title = f"[integration-test] recurring {uuid.uuid4().hex[:8]}"
    try:
        result = await client.recurring_meeting.create(
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

    recurring = await client.recurring_meeting.get(recurring_meeting_id)
    assert recurring.id == recurring_meeting_id
    assert recurring.title == title

    update_result = await client.recurring_meeting.update(
        recurring_meeting_id=recurring_meeting_id, title=f"{title} updated", confirm=True
    )
    assert update_result.ready, update_result.validation_errors

    updated = await client.recurring_meeting.get(recurring_meeting_id)
    assert updated.title == f"{title} updated"

    delete_result = await client.recurring_meeting.delete(recurring_meeting_id=recurring_meeting_id, confirm=True)
    assert delete_result.ready and delete_result.state == "confirmed"
    recurring_meeting_ids.remove(recurring_meeting_id)


async def test_end_recurring_meeting(
    client: OpenProjectClient, test_project: str, recurring_meeting_ids: list[int]
) -> None:
    if not os.environ.get("OPENPROJECT_DOCKER_SERVICE"):
        pytest.skip("OPENPROJECT_DOCKER_SERVICE not set (needed to backdate the series' start)")
    title = f"[integration-test] recurring end {uuid.uuid4().hex[:8]}"
    try:
        result = await client.recurring_meeting.create(
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
    recurring_meeting_ids.append(recurring_meeting_id)

    # The API only accepts a start in the future, while ending sets the end
    # date to yesterday, which must lie after the first occurrence -- so the
    # series is backdated behind the API's back.
    _run_rails_script(
        """
        RecurringMeeting.find(ENV.fetch("RECURRING_MEETING_ID").to_i).update_columns(start_time: Time.utc(2020, 1, 6, 9))
        puts "BACKDATED=1"
        """,
        result_key="BACKDATED",
        env={"RECURRING_MEETING_ID": str(recurring_meeting_id)},
    )

    preview = await client.recurring_meeting.end(recurring_meeting_id=recurring_meeting_id)
    assert preview.state == "preview"
    assert preview.payload == {"id": recurring_meeting_id, "title": title}

    try:
        ended = await client.recurring_meeting.end(recurring_meeting_id=recurring_meeting_id, confirm=True)
    except NotFoundError:
        pytest.skip("Ending a recurring meeting series requires OpenProject 17.8+ on this instance")
    assert ended.state == "confirmed"
    assert ended.recurring_meeting_id == recurring_meeting_id

    upcoming = await client.recurring_meeting.list_occurrences(recurring_meeting_id, filter="upcoming", limit=5)
    assert upcoming.results == []


async def test_delete_meeting_rejects_the_template_of_a_recurring_series(
    client: OpenProjectClient, test_project: str, recurring_meeting_ids: list[int], meeting_ids: list[int]
) -> None:
    try:
        created = await client.recurring_meeting.create(
            project=test_project,
            title=f"[integration-test] series template {uuid.uuid4().hex[:8]}",
            frequency="weekly",
            start_time="2031-03-03T09:00:00Z",
            confirm=True,
        )
    except NotFoundError:
        pytest.skip("Recurring meetings not available, or OpenProject < 17.4, on this instance")
    assert created.ready, created.validation_errors
    series_id = created.recurring_meeting_id
    assert series_id is not None
    recurring_meeting_ids.append(series_id)
    template_id = (await client.recurring_meeting.get(series_id)).template_meeting_id

    with pytest.raises(InvalidInputError, match=f"is the template of recurring meeting {series_id}"):
        await client.meeting.delete(meeting_id=template_id, confirm=True)

    assert (await client.meeting.get(template_id)).template is True
    initialized = await client.recurring_meeting.init_occurrence(
        recurring_meeting_id=series_id, start_time="2031-03-10T09:00:00Z", confirm=True
    )
    assert initialized.state == "confirmed", initialized.validation_errors
    meeting_ids.append(initialized.result.id)


async def test_list_recurring_meetings(
    client: OpenProjectClient, test_project: str, recurring_meeting_ids: list[int]
) -> None:
    title = f"[integration-test] list {uuid.uuid4().hex[:8]}"
    try:
        result = await client.recurring_meeting.create(
            project=test_project,
            title=title,
            frequency="weekly",
            start_time="2030-07-01T09:00:00Z",
            confirm=True,
        )
    except NotFoundError:
        pytest.skip("Recurring meetings not available, or OpenProject < 17.4, on this instance")
    assert result.ready, result.validation_errors
    recurring_meeting_id = result.recurring_meeting_id
    recurring_meeting_ids.append(recurring_meeting_id)

    listed = await client.recurring_meeting.list_all(project=test_project)
    assert listed.count > 0
    assert any(rm.id == recurring_meeting_id and rm.title == title for rm in listed.results)


async def test_create_update_delete_recurring_meeting_and_init_occurrence_denied_outside_write_allowlist(
    denied_client: OpenProjectClient, client: OpenProjectClient, test_project: str, recurring_meeting_ids: list[int]
) -> None:
    """Covers the base CRUD plus one occurrence operation (init) -- both
    init_occurrence and cancel_occurrence call the identical
    _ensure_recurring_meeting_write_allowed helper (recurring_meeting_service.py),
    so exercising init alone is sufficient to prove that shared code path's
    allowlist enforcement."""
    # denied_client's call can only ever raise PermissionDeniedError (the
    # write-allowlist check runs before the recurring-meetings endpoint is
    # reached) -- the real NotFoundError risk ("Recurring meetings not
    # available, or OpenProject < 17.4") is on the unrestricted client's own
    # call below.
    with pytest.raises(PermissionDeniedError):
        await denied_client.recurring_meeting.create(
            project=test_project,
            title=f"[integration-test] denied {uuid.uuid4().hex[:8]}",
            frequency="weekly",
            start_time="2030-05-06T09:00:00Z",
            confirm=True,
        )

    try:
        existing = await client.recurring_meeting.create(
            project=test_project,
            title=f"[integration-test] {uuid.uuid4().hex[:8]}",
            frequency="weekly",
            start_time="2030-06-03T09:00:00Z",
            confirm=True,
        )
    except NotFoundError:
        pytest.skip("Recurring meetings not available, or OpenProject < 17.4, on this instance")
    assert existing.ready, existing.validation_errors
    recurring_meeting_id = existing.recurring_meeting_id
    recurring_meeting_ids.append(recurring_meeting_id)

    with pytest.raises(PermissionDeniedError):
        await denied_client.recurring_meeting.update(
            recurring_meeting_id=recurring_meeting_id, title="denied update", confirm=True
        )

    with pytest.raises(PermissionDeniedError):
        await denied_client.recurring_meeting.delete(recurring_meeting_id=recurring_meeting_id, confirm=True)

    # Occurrence denial checked last, after delete's own denial is already
    # confirmed -- an empty upcoming-occurrence result skips only this final
    # portion, not the CRUD denial assertions already run above.
    upcoming = await client.recurring_meeting.list_occurrences(recurring_meeting_id, filter="upcoming", limit=1)
    if not upcoming.results:
        pytest.skip("No upcoming occurrence available to exercise init_recurring_meeting_occurrence's denial path")
    target = upcoming.results[0]
    with pytest.raises(PermissionDeniedError):
        await denied_client.recurring_meeting.init_occurrence(
            recurring_meeting_id=recurring_meeting_id, start_time=target.start_time, confirm=True
        )


async def test_list_recurring_meeting_occurrences_all_four_filters(
    client: OpenProjectClient, test_project: str, recurring_meeting_ids: list[int]
) -> None:
    try:
        result = await client.recurring_meeting.create(
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
        listed = await client.recurring_meeting.list_occurrences(recurring_meeting_id, filter=filter_name)
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
    documented quirk in tools_meetings.py/docs/tools.md); it is a genuine, expected,
    permanent side effect of calling cancel on a virtual occurrence, not a
    test-cleanup gap."""
    try:
        result = await client.recurring_meeting.create(
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

    upcoming = await client.recurring_meeting.list_occurrences(recurring_meeting_id, filter="upcoming", limit=5)
    if len(upcoming.results) < 2:
        pytest.skip("fewer than 2 upcoming occurrences computed by the server for this recurrence rule")

    init_target = upcoming.results[0]
    init_result = await client.recurring_meeting.init_occurrence(
        recurring_meeting_id=recurring_meeting_id, start_time=init_target.start_time, confirm=True
    )
    assert init_result.ready and init_result.state == "confirmed", init_result.validation_errors
    assert init_result.result is not None
    materialized_meeting_id = init_result.result.id
    meeting_ids.append(materialized_meeting_id)

    cancel_target = upcoming.results[1]
    cancel_result = await client.recurring_meeting.cancel_occurrence(
        recurring_meeting_id=recurring_meeting_id, start_time=cancel_target.start_time, confirm=True
    )
    assert cancel_result.ready and cancel_result.state == "confirmed", cancel_result.validation_errors

    cancelled = await client.recurring_meeting.list_occurrences(recurring_meeting_id, filter="cancelled")
    assert any(o.start_time == cancel_target.start_time for o in cancelled.results)


async def test_update_recurring_meeting_without_title_keeps_occurrence_titles(
    client: OpenProjectClient,
    test_project: str,
    recurring_meeting_ids: list[int],
    meeting_ids: list[int],
    meeting_title_in_database: Callable[[int], str | None],
) -> None:
    # Two spaces: a whitespace-normalized echo would rename the series.
    title = f"[integration-test]  keep-titles {uuid.uuid4().hex[:8]}"
    try:
        result = await client.recurring_meeting.create(
            project=test_project,
            title=title,
            frequency="weekly",
            start_time="2030-08-05T09:00:00Z",
            end_after="iterations",
            iterations=6,
            confirm=True,
        )
    except NotFoundError:
        pytest.skip("Recurring meetings not available, or OpenProject < 17.4, on this instance")
    assert result.ready, result.validation_errors
    recurring_meeting_id = result.recurring_meeting_id
    recurring_meeting_ids.append(recurring_meeting_id)

    upcoming = await client.recurring_meeting.list_occurrences(recurring_meeting_id, filter="upcoming", limit=1)
    init_result = await client.recurring_meeting.init_occurrence(
        recurring_meeting_id=recurring_meeting_id, start_time=upcoming.results[0].start_time, confirm=True
    )
    assert init_result.result is not None
    occurrence_id = init_result.result.id
    meeting_ids.append(occurrence_id)
    assert meeting_title_in_database(occurrence_id) == title

    update_result = await client.recurring_meeting.update(
        recurring_meeting_id=recurring_meeting_id, iterations=8, confirm=True
    )
    assert update_result.state == "confirmed", update_result.validation_errors

    assert meeting_title_in_database(occurrence_id) == title


async def test_cancel_already_materialized_occurrence_fails(
    client: OpenProjectClient,
    test_project: str,
    recurring_meeting_ids: list[int],
    meeting_ids: list[int],
) -> None:
    """Documents the real OpenProject 409 for the "already materialized,
    not cancelled" case -- surfaces as ConflictError (the state-conflict
    class the HTTP mapper assigns to 409) with no special-casing needed
    client-side."""
    try:
        result = await client.recurring_meeting.create(
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

    upcoming = await client.recurring_meeting.list_occurrences(recurring_meeting_id, filter="upcoming", limit=1)
    if not upcoming.results:
        pytest.skip("no upcoming occurrence computed by the server for this recurrence rule")
    target = upcoming.results[0]

    init_result = await client.recurring_meeting.init_occurrence(
        recurring_meeting_id=recurring_meeting_id, start_time=target.start_time, confirm=True
    )
    assert init_result.ready, init_result.validation_errors
    meeting_ids.append(init_result.result.id)

    with pytest.raises(ConflictError) as excinfo:
        await client.recurring_meeting.cancel_occurrence(
            recurring_meeting_id=recurring_meeting_id, start_time=target.start_time, confirm=True
        )
    assert excinfo.value.code == "CONFLICT"
