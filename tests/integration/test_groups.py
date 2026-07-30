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

from openproject_ce_mcp.client import InvalidInputError, OpenProjectClient

pytestmark = pytest.mark.integration


async def test_get_group_normalizes_visible_members_admin(client: OpenProjectClient, group_ids: list[int]) -> None:
    me = await client.get_current_user()
    name = f"[integration-test] {uuid.uuid4().hex[:8]}"

    create_result = await client.create_group(name=name, user_ids=[me.id], confirm=True)
    assert create_result.ready, create_result.validation_errors
    group_id = create_result.group_id
    assert group_id is not None
    group_ids.append(group_id)

    group = await client.get_group(group_id)

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
    me = await client.get_current_user()
    name = f"[integration-test] {uuid.uuid4().hex[:8]}"

    create_result = await client.create_group(name=name, user_ids=[me.id], confirm=True)
    assert create_result.ready, create_result.validation_errors
    group_id = create_result.group_id
    assert group_id is not None
    group_ids.append(group_id)

    listed = await client.list_groups(search=name)
    matches = [g for g in listed.results if g.id == group_id]
    assert len(matches) == 1
    assert matches[0].member_count == 1


async def test_update_group_renames_and_manages_members(client: OpenProjectClient, group_ids: list[int]) -> None:
    """update_group PATCHes groups/{id} with a full _links.members replacement
    (add/remove computed client-side from the current membership). Also
    exercises delete_group indirectly via the group_ids cleanup fixture."""
    me = await client.get_current_user()
    name = f"[integration-test] {uuid.uuid4().hex[:8]}"

    create_result = await client.create_group(name=name, user_ids=[me.id], confirm=True)
    assert create_result.ready, create_result.validation_errors
    group_id = create_result.group_id
    assert group_id is not None
    group_ids.append(group_id)

    new_name = f"{name}-renamed"
    updated = await client.update_group(group_id, name=new_name, remove_user_ids=[me.id], confirm=True)
    assert updated.confirmed
    assert updated.result is not None
    assert updated.result.name == new_name
    assert updated.result.member_count == 0

    added_back = await client.update_group(group_id, add_user_ids=[me.id], confirm=True)
    assert added_back.confirmed
    assert added_back.result is not None
    assert added_back.result.member_count == 1


async def test_create_group_rejects_hidden_name_field(client: OpenProjectClient) -> None:
    """Regression: attachment/reminder/relation/group writes bypassed the
    hidden-fields guard -- group.name/members could be written even with
    OPENPROJECT_HIDE_GROUP_FIELDS set, unlike every other write-capable
    entity."""
    hidden_settings = dataclasses.replace(client.settings, hidden_fields={"group": ("name",)})
    hidden_client = OpenProjectClient(hidden_settings)
    await hidden_client.initialize()

    with pytest.raises(InvalidInputError, match="OPENPROJECT_HIDE_GROUP_FIELDS"):
        await hidden_client.create_group(name=f"[integration-test] {uuid.uuid4().hex[:8]}", confirm=False)
