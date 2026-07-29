"""Integration tests for notification read/write operations.

OpenProject never sends a notification for a change the acting user makes
themselves (self-notifications are suppressed by design) -- confirmed live
against this suite's own test instance: creating a work package, assigning
it to the calling user, and adding a comment all produced zero
notifications for that same user. Seeding a real, unread notification would
require a second real user account, which this suite deliberately avoids
creating (see test_users.py's own docstring on the same tradeoff). Read
paths are therefore exercised against the real (possibly empty) notification
list, and mark_all_notifications_read is only ever previewed here, never
confirmed -- confirming it would mark the ENTIRE real inbox of whichever
account holds OPENPROJECT_API_TOKEN as read, with no way to undo that.
"""

from __future__ import annotations

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
