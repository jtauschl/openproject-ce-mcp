"""Integration tests for notification read/write operations.

OpenProject never sends a notification for a change the acting user makes
themselves (self-notifications are suppressed by design) -- confirmed live
against this suite's own test instance: creating a work package, assigning
it to the calling user, and adding a comment all produced zero
notifications for that same user. Most tests here exercise the real
(possibly empty) notification list from the admin token's own inbox, and
mark_all_notifications_read is only ever previewed, never confirmed -- doing
so would mark the ENTIRE real inbox of whichever account holds
OPENPROJECT_API_TOKEN as read, with no way to undo that.

test_mark_notification_read_confirmed_roundtrip is the one exception: it
uses second_user_client (a real second user, its own minted token -- see
conftest.py) to actually trigger a notification FOR the admin (comment from
a different, real user on a work package the admin watches), then confirms
marking that ONE specific, known notification id as read -- never
mark_all_notifications_read, so the rest of the admin's real inbox stays
untouched.
"""

from __future__ import annotations

import asyncio
import dataclasses

import pytest

from openproject_ce_mcp.client import OpenProjectClient, PermissionDeniedError

pytestmark = pytest.mark.integration


async def test_list_notifications(client: OpenProjectClient) -> None:
    result = await client.list_notifications()
    assert result is not None
    assert result.count >= 0
    assert result.total >= 0


async def test_list_notifications_unread_only(client: OpenProjectClient) -> None:
    result = await client.list_notifications(unread_only=True)
    assert result is not None
    assert result.count >= 0


async def test_list_notifications_scoped_by_read_allowlist(client: OpenProjectClient) -> None:
    """_notification_payload_allowed gates each notification by its project
    (or, absent a project link, its resolved work package) -- under a
    read-allowlist that permits nothing, the list must come back empty
    rather than raising."""
    denied_settings = dataclasses.replace(client.settings, read_projects=())
    denied_client = OpenProjectClient(denied_settings)
    await denied_client.initialize()

    result = await denied_client.list_notifications()
    assert result.count == 0


async def test_mark_notification_read_preview_does_not_write(client: OpenProjectClient) -> None:
    """No real notification exists to mark read in this suite (see module
    docstring) -- confirm the preview path is side-effect-free and reports
    requires_confirmation, without ever calling confirm=true against a real
    notification id."""
    preview = await client.mark_notification_read(999999999, confirm=False)
    assert preview.requires_confirmation
    assert not preview.confirmed


async def test_mark_all_notifications_read_preview_does_not_write(client: OpenProjectClient) -> None:
    """Deliberately never confirmed -- see module docstring. Only the
    preview/dry-run path is safe to exercise against a real account."""
    preview = await client.mark_all_notifications_read(confirm=False)
    assert preview.requires_confirmation
    assert not preview.confirmed


async def test_mark_notification_read_denied_when_personal_write_disabled(client: OpenProjectClient) -> None:
    disabled_settings = dataclasses.replace(client.settings, enable_personal_write=False)
    disabled_client = OpenProjectClient(disabled_settings)
    await disabled_client.initialize()

    with pytest.raises(PermissionDeniedError):
        await disabled_client.mark_notification_read(999999999, confirm=True)


async def test_mark_notification_read_confirmed_roundtrip(
    client: OpenProjectClient,
    test_project: str,
    wp_ids: list[int],
    second_user_client: tuple[int, OpenProjectClient],
) -> None:
    """The one test in this file that confirms a real write, against a
    single, specifically-identified notification -- never
    mark_all_notifications_read. See module docstring for why a second real
    user is required to trigger a genuine notification at all."""
    second_user_id, second_client = second_user_client

    me = await client.get_current_user()

    roles = await client.list_roles()
    role_name = next((r.name for r in roles.results if r.name == "Member"), None)
    if role_name is None:
        pytest.skip("instance has no 'Member' role configured")
    membership = await client.create_membership(
        project=test_project, principal=str(second_user_id), roles=[role_name], confirm=True
    )
    assert membership.ready, membership.validation_errors

    # second_client.initialize() (already called once by the second_user_client
    # fixture, before this membership existed) is what populates
    # project_id_to_identifier -- it walks list_projects() for projects the
    # token owner can currently see. At fixture-creation time the second user
    # had no membership yet, so that walk found nothing and the cache stayed
    # empty; re-running it now (after create_membership above) populates it,
    # which the write-allowlist check below needs to map the work package's
    # numeric project id back to test_project's identifier.
    await second_client.initialize()

    wp_result = await client.create_work_package(
        project=test_project, type="Task", subject="Integration test WP for notification roundtrip", confirm=True
    )
    assert wp_result.ready, wp_result.validation_errors
    wp_id = wp_result.work_package_id
    assert wp_id is not None
    wp_ids.append(wp_id)

    watch_result = await client.add_work_package_watcher(wp_id, me.id, confirm=True)
    assert watch_result.confirmed

    # The comment must come from a DIFFERENT user (second_client) -- OpenProject
    # never notifies a user about their own change (see module docstring).
    # notify=True is required here: OpenProject's own `notify` request param
    # maps directly to `send_notifications`, and False (this tool's own
    # default, chosen to avoid unwanted emails in the common case) suppresses
    # notification creation entirely server-side, not just outbound email --
    # confirmed live (a notify=False comment produced zero Notification rows
    # and zero enqueued Notifications::WorkflowJob work at all).
    comment_result = await second_client.add_work_package_comment(
        work_package_id=wp_id,
        comment="Comment from a different user to trigger a real notification",
        notify=True,
        confirm=True,
    )
    assert comment_result.ready, comment_result.validation_errors

    # This is a genuine test failure, not a skip, if it never appears: every
    # precondition above (comment from a different user, notify=True,
    # work_package_commented enabled via docker/test/seed.rb) was set up
    # specifically to make this deterministic against the seeded Docker
    # instance this suite is meant to run against -- an absent notification
    # here means notification generation or listing actually regressed, not
    # environment flakiness to shrug off.
    notification_id = None
    for _ in range(10):
        listed = await client.list_notifications(unread_only=True)
        match = next((n for n in listed.results if n.work_package_id == wp_id), None)
        if match is not None:
            notification_id = match.id
            break
        await asyncio.sleep(1)
    if notification_id is None:
        pytest.fail("no notification appeared for the watched work package within the wait window")

    marked = await client.mark_notification_read(notification_id, confirm=True)
    assert marked.confirmed
    assert marked.notification_id == notification_id

    # Confirm the read actually took effect server-side, not just that the
    # write call itself reported success -- a no-op 2xx response would
    # otherwise pass this test just as well as a real state change.
    after = await client.list_notifications(unread_only=True)
    assert notification_id not in {n.id for n in after.results}
