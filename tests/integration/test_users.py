"""Integration tests for user admin write operations.

Only OPENPROJECT_HIDE_USER_FIELDS pre-write validation is exercised here --
these checks raise InvalidInputError before any HTTP request is made, so no
real user needs to be created (create_user/lock_user's live-write behavior
against a disposable admin account is intentionally out of scope for these
tests to avoid instance-wide side effects beyond test_project).
"""

from __future__ import annotations

import dataclasses

import pytest

from openproject_ce_mcp.client import InvalidInputError, OpenProjectClient

pytestmark = pytest.mark.integration


async def test_create_user_rejects_hidden_field(client: OpenProjectClient) -> None:
    """Regression: create_user/update_user/lock_user/unlock_user bypassed
    OPENPROJECT_HIDE_USER_FIELDS entirely on writes -- only reads were
    masked. A hidden field passed to a write should be rejected up front,
    the same as every other hidden-fields-guarded entity."""
    hidden_settings = dataclasses.replace(client.settings, hidden_fields={"user": ("email",)})
    hidden_client = OpenProjectClient(hidden_settings)
    await hidden_client.initialize()

    with pytest.raises(InvalidInputError, match="OPENPROJECT_HIDE_USER_FIELDS"):
        await hidden_client.create_user(
            login="integration-test-user",
            email="integration-test@example.org",
            firstname="Integration",
            lastname="Test",
            confirm=False,
        )


async def test_lock_user_rejects_hidden_locked_field(client: OpenProjectClient) -> None:
    hidden_settings = dataclasses.replace(client.settings, hidden_fields={"user": ("locked",)})
    hidden_client = OpenProjectClient(hidden_settings)
    await hidden_client.initialize()

    me = await client.get_current_user()

    with pytest.raises(InvalidInputError, match="OPENPROJECT_HIDE_USER_FIELDS"):
        await hidden_client.lock_user(user_id=me.id, confirm=False)
