"""Integration tests for membership and user read operations."""

from __future__ import annotations

import dataclasses

import pytest

from openproject_ce_mcp.client import OpenProjectClient, PermissionDeniedError

from .conftest import disposable_project_identifier

pytestmark = pytest.mark.integration


async def _other_principal_id(client: OpenProjectClient) -> str:
    """Returns a principal id other than the token owner's own, to use as a
    create_membership principal -- OpenProject auto-adds a project's creator
    as a "Project admin" member on create_project, so create_membership(
    principal="me", ...) on a freshly created project always fails with
    "user already assigned" (a real, pre-existing OpenProject constraint, not
    a client bug). Picks any other active user already on the instance
    rather than creating a new one: not every token has the instance-admin
    rights create_user's password field needs, and that happy path is
    already covered, Docker-instance-gated, by
    test_users.py::test_user_lifecycle_roundtrip -- this fixture only needs
    *a* second principal to assign, not to prove create_user works too."""
    me = await client.get_current_user()
    users = await client.list_users()
    other = next((u for u in users.results if u.id != me.id and u.status == "active"), None)
    if other is None:
        pytest.skip("Instance has no second active user to use as a create_membership principal")
    return str(other.id)


async def test_list_project_memberships(client: OpenProjectClient, test_project: str) -> None:
    result = await client.list_project_memberships(test_project)
    assert result is not None
    assert result.count >= 0


async def test_list_users(client: OpenProjectClient) -> None:
    try:
        result = await client.list_users()
    except PermissionDeniedError:
        pytest.skip("Instance requires admin rights to list users")
    assert result.count > 0
    assert result.results[0].login


async def test_get_user_me(client: OpenProjectClient) -> None:
    me = await client.get_current_user()
    user = await client.get_user(str(me.id))
    assert user.id == me.id
    assert user.login == me.login


async def test_list_groups(client: OpenProjectClient) -> None:
    result = await client.list_groups()
    assert result is not None
    assert result.count >= 0


async def test_create_and_update_membership_in_fresh_project(
    client: OpenProjectClient, project_refs: list[str]
) -> None:
    """create_membership resolves a role-name list to hrefs via
    _resolve_role_hrefs and a principal ref via _resolve_principal_id, then
    update_membership re-resolves the role list on an existing membership --
    both multi-step, form-then-write paths with no prior live coverage. Uses
    a freshly created, disposable project (not test_project) so this never
    touches an existing membership's real roles, and a second principal (not
    "me") since OpenProject auto-adds the project's creator as a member on
    create_project -- see _other_principal_id's docstring."""
    unrestricted_settings = dataclasses.replace(client.settings, read_projects=("*",), write_projects=("*",))
    unrestricted_client = OpenProjectClient(unrestricted_settings)
    await unrestricted_client.initialize()

    new_identifier = disposable_project_identifier()
    create_project_result = await unrestricted_client.create_project(
        name=f"[integration-test] {new_identifier}", identifier=new_identifier, confirm=True
    )
    assert create_project_result.ready, create_project_result.validation_errors
    project_refs.append(new_identifier)

    principal_id = await _other_principal_id(unrestricted_client)

    roles = await unrestricted_client.list_roles()
    role_name = next((r.name for r in roles.results if r.name == "Member"), None)
    other_role_name = next((r.name for r in roles.results if r.name == "Reader"), None)
    if role_name is None or other_role_name is None:
        pytest.skip("Instance has no 'Member'/'Reader' project role to assign")

    preview = await unrestricted_client.create_membership(
        project=new_identifier, principal=principal_id, roles=[role_name]
    )
    assert preview.requires_confirmation

    created = await unrestricted_client.create_membership(
        project=new_identifier, principal=principal_id, roles=[role_name], confirm=True
    )
    assert created.confirmed
    assert created.result is not None
    membership_id = created.result.id
    assert role_name in created.result.role_names

    fetched = await unrestricted_client.get_membership(membership_id)
    assert fetched.id == membership_id
    assert role_name in fetched.role_names

    updated = await unrestricted_client.update_membership(
        membership_id=membership_id, roles=[other_role_name], confirm=True
    )
    assert updated.confirmed
    assert updated.result is not None
    assert other_role_name in updated.result.role_names


async def test_delete_membership_in_fresh_project(client: OpenProjectClient, project_refs: list[str]) -> None:
    """delete_membership DELETEs memberships/{id}. Uses a freshly created,
    disposable project so this never touches an existing membership, and a
    second principal (not "me") -- see _other_principal_id's docstring."""
    unrestricted_settings = dataclasses.replace(client.settings, read_projects=("*",), write_projects=("*",))
    unrestricted_client = OpenProjectClient(unrestricted_settings)
    await unrestricted_client.initialize()

    new_identifier = disposable_project_identifier()
    create_project_result = await unrestricted_client.create_project(
        name=f"[integration-test] {new_identifier}", identifier=new_identifier, confirm=True
    )
    assert create_project_result.ready, create_project_result.validation_errors
    project_refs.append(new_identifier)

    principal_id = await _other_principal_id(unrestricted_client)

    roles = await unrestricted_client.list_roles()
    role_name = next((r.name for r in roles.results if r.name == "Member"), None)
    if role_name is None:
        pytest.skip("Instance has no 'Member' project role to assign")

    created = await unrestricted_client.create_membership(
        project=new_identifier, principal=principal_id, roles=[role_name], confirm=True
    )
    assert created.confirmed
    assert created.result is not None
    membership_id = created.result.id

    deleted = await unrestricted_client.delete_membership(membership_id=membership_id, confirm=True)
    assert deleted.confirmed

    remaining = await unrestricted_client.list_project_memberships(new_identifier)
    assert all(m.id != membership_id for m in remaining.results)


async def test_update_membership_denied_outside_write_allowlist(
    denied_client: OpenProjectClient, client: OpenProjectClient, project_refs: list[str]
) -> None:
    """update_membership resolves the membership's project link and
    authorizes the write against it -- a caller without write access to that
    project must be denied."""
    unrestricted_settings = dataclasses.replace(client.settings, read_projects=("*",), write_projects=("*",))
    unrestricted_client = OpenProjectClient(unrestricted_settings)
    await unrestricted_client.initialize()

    other_identifier = disposable_project_identifier()
    create_project_result = await unrestricted_client.create_project(
        name=f"[integration-test] {other_identifier}", identifier=other_identifier, confirm=True
    )
    assert create_project_result.ready, create_project_result.validation_errors
    project_refs.append(other_identifier)

    principal_id = await _other_principal_id(unrestricted_client)

    roles = await unrestricted_client.list_roles()
    role_name = next((r.name for r in roles.results if r.name == "Member"), None)
    if role_name is None:
        pytest.skip("Instance has no 'Member' role to assign")

    created = await unrestricted_client.create_membership(
        project=other_identifier, principal=principal_id, roles=[role_name], confirm=True
    )
    assert created.confirmed

    # denied_client can read test_project but not write it or other_identifier.
    with pytest.raises(PermissionDeniedError):
        await denied_client.update_membership(membership_id=created.result.id, roles=[role_name], confirm=True)
