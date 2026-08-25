"""Integration tests for group read operations.

Requires admin write: group create/delete is instance-wide, not project-scoped
(unlike every other integration test file here, which stays within
``test_project``). Only run this against a disposable Docker test instance —
never against a real, actively-used OpenProject instance.
"""

from __future__ import annotations

import dataclasses
import uuid

import pytest

from openproject_ce_mcp.client import InvalidInputError, NotFoundError, OpenProjectClient, PermissionDeniedError

pytestmark = pytest.mark.integration


async def test_get_group_normalizes_visible_members_admin(client: OpenProjectClient, group_ids: list[int]) -> None:
    me = await client.current_user.get_current_user()
    name = f"[integration-test] {uuid.uuid4().hex[:8]}"

    create_result = await client.group.create(name=name, user_ids=[me.id], confirm=True)
    assert create_result.ready, create_result.validation_errors
    group_id = create_result.group_id
    assert group_id is not None
    group_ids.append(group_id)

    group = await client.group.get_group(group_id)

    # The critical assertion: OpenProject's real API renders _embedded.members
    # as a bare array, not a {count, elements} collection.
    assert isinstance(group.members, list), "members should be a list"
    assert me.name in group.members


async def test_list_groups_reports_correct_member_count(client: OpenProjectClient, group_ids: list[int]) -> None:
    """Regression: list_groups' real response has no _embedded.members at
    all for each element -- membership there is only ever exposed via
    _links.members (a bare array of HAL links), unlike get_group's
    single-item response shape. member_count silently stayed 0 for every
    group returned by list_groups specifically."""
    me = await client.current_user.get_current_user()
    name = f"[integration-test] {uuid.uuid4().hex[:8]}"

    create_result = await client.group.create(name=name, user_ids=[me.id], confirm=True)
    assert create_result.ready, create_result.validation_errors
    group_id = create_result.group_id
    assert group_id is not None
    group_ids.append(group_id)

    listed = await client.group.list_groups(search=name)
    matches = [g for g in listed.results if g.id == group_id]
    assert len(matches) == 1
    assert matches[0].member_count == 1


async def test_update_group_renames_and_manages_members(client: OpenProjectClient, group_ids: list[int]) -> None:
    """update_group PATCHes groups/{id} with a full _links.members replacement
    (add/remove computed client-side from the current membership). Also
    exercises delete_group indirectly via the group_ids cleanup fixture."""
    me = await client.current_user.get_current_user()
    name = f"[integration-test] {uuid.uuid4().hex[:8]}"

    create_result = await client.group.create(name=name, user_ids=[me.id], confirm=True)
    assert create_result.ready, create_result.validation_errors
    group_id = create_result.group_id
    assert group_id is not None
    group_ids.append(group_id)

    new_name = f"{name}-renamed"
    updated = await client.group.update(group_id, name=new_name, remove_user_ids=[me.id], confirm=True)
    assert updated.state == "confirmed"
    assert updated.result is not None
    assert updated.result.name == new_name
    assert updated.result.member_count == 0

    added_back = await client.group.update(group_id, add_user_ids=[me.id], confirm=True)
    assert added_back.state == "confirmed"
    assert added_back.result is not None
    assert added_back.result.member_count == 1


async def test_delete_group_removes_it(client: OpenProjectClient) -> None:
    """Direct assertion for delete_group's own success path -- previously
    only ever exercised indirectly via the group_ids cleanup fixture."""
    name = f"[integration-test] {uuid.uuid4().hex[:8]}"
    created = await client.group.create(name=name, confirm=True)
    assert created.ready, created.validation_errors
    group_id = created.group_id
    assert group_id is not None

    deleted = await client.group.delete(group_id, confirm=True)
    assert deleted.ready and deleted.state == "confirmed"

    with pytest.raises(NotFoundError):
        await client.group.get_group(group_id)


async def test_create_and_delete_group_denied_when_admin_write_disabled(
    admin_write_disabled_client: OpenProjectClient,
) -> None:
    with pytest.raises(PermissionDeniedError):
        await admin_write_disabled_client.group.create(
            name=f"[integration-test] denied {uuid.uuid4().hex[:8]}", confirm=True
        )

    with pytest.raises(PermissionDeniedError):
        # delete_group checks admin-write unconditionally before any lookup,
        # so a non-existent id is fine here.
        await admin_write_disabled_client.group.delete(999999999, confirm=True)


async def test_create_group_rejects_hidden_name_field(client: OpenProjectClient) -> None:
    """Regression: attachment/reminder/relation/group writes bypassed the
    hidden-fields guard -- group.name/members could be written even with
    OPENPROJECT_HIDE_GROUP_FIELDS set, unlike every other write-capable
    entity."""
    hidden_settings = dataclasses.replace(client.settings, hidden_fields={"group": ("name",)})
    hidden_client = OpenProjectClient(hidden_settings)
    await hidden_client.initialize()

    with pytest.raises(InvalidInputError, match="OPENPROJECT_HIDE_GROUP_FIELDS"):
        await hidden_client.group.create(name=f"[integration-test] {uuid.uuid4().hex[:8]}", confirm=False)
