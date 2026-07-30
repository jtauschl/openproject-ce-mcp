"""Integration tests for user admin write operations.

test_create_user_rejects_hidden_field/test_lock_user_rejects_hidden_locked_field
only exercise OPENPROJECT_HIDE_USER_FIELDS pre-write validation -- these
checks raise InvalidInputError before any HTTP request is made, so no real
user needs creating for them.

test_user_lifecycle_roundtrip below DOES perform real, live writes
(create/update/lock/unlock/delete) against disposable users -- only safe
against the throwaway Docker test instance this suite is meant to run
against, never a real, actively-used one (see conftest.py's module
docstring and the user_ids cleanup fixture).
"""

from __future__ import annotations

import dataclasses
import os
import uuid

import pytest

from openproject_ce_mcp.client import InvalidInputError, NotFoundError, OpenProjectClient

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


async def test_user_lifecycle_roundtrip(client: OpenProjectClient, user_ids: list[int]) -> None:
    """create -> update -> lock -> unlock -> delete against a real,
    disposable user. Regression class this guards against: the write-commit
    path silently dropping a field the create/update-form preview validated
    but never actually persisted (see the `password` fix in
    UserService.create -- the form response never echoes it back, and an
    earlier version of that method committed the form's own payload
    verbatim instead of restoring it, so a real create silently failed with
    "Password can't be blank." despite the preview reporting ready=True)."""
    if not os.environ.get("OPENPROJECT_DOCKER_SERVICE"):
        pytest.skip(
            "OPENPROJECT_DOCKER_SERVICE not set -- this test performs real "
            "instance-wide user mutations and is only safe against the "
            "disposable Docker test instance, the same guard second_user_client uses"
        )

    suffix = uuid.uuid4().hex[:8]
    login = f"integration-test-{suffix}"

    created = await client.create_user(
        login=login,
        email=f"{login}@example.invalid",
        firstname="Integration",
        lastname=f"Test {suffix}",
        password=f"Aa1!{uuid.uuid4().hex}",
        confirm=True,
    )
    assert created.ready, created.validation_errors
    assert created.confirmed
    user_id = created.user_id
    assert user_id is not None
    user_ids.append(user_id)
    assert created.result is not None
    assert created.result.login == login

    fetched = await client.get_user(str(user_id))
    assert fetched.id == user_id
    assert fetched.login == login

    updated = await client.update_user(user_id, lastname=f"Test {suffix} Renamed", confirm=True)
    assert updated.confirmed
    assert updated.result is not None
    assert updated.result.lastname == f"Test {suffix} Renamed"

    locked = await client.lock_user(user_id, confirm=True)
    assert locked.confirmed
    assert locked.result is not None
    assert locked.result.status == "locked"

    unlocked = await client.unlock_user(user_id, confirm=True)
    assert unlocked.confirmed
    assert unlocked.result is not None
    assert unlocked.result.status != "locked"

    deleted = await client.delete_user(user_id, confirm=True)
    assert deleted.confirmed
    user_ids.remove(user_id)

    with pytest.raises(NotFoundError):
        await client.get_user(str(user_id))


async def test_second_user_membership_interaction(
    client: OpenProjectClient, test_project: str, second_user_client: tuple[int, OpenProjectClient]
) -> None:
    """Realistic multi-user scenario: a second, real user (created via
    create_user, with its own minted API token -- see conftest.py's
    second_user_client fixture) is added as a project member by the first
    (admin) client, then independently confirms its own access using its
    OWN token/client -- proving create_user's output is a genuinely usable
    account, not just a database row that happens to pass validation."""
    second_user_id, second_client = second_user_client

    roles = await client.list_roles()
    role_name = next((r.name for r in roles.results if r.name == "Member"), None)
    if role_name is None:
        pytest.skip("instance has no 'Member' role configured")

    membership = await client.create_membership(
        project=test_project, principal=str(second_user_id), roles=[role_name], confirm=True
    )
    assert membership.ready, membership.validation_errors
    assert membership.confirmed

    # The second user's OWN client/token now sees itself as a member.
    access = await second_client.get_my_project_access(test_project)
    assert access.current_user_id == second_user_id
    assert role_name in access.membership.role_names
