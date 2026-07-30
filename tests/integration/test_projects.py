"""Integration tests for project read operations."""

from __future__ import annotations

import dataclasses
import uuid

import pytest

from openproject_ce_mcp.client import NotFoundError, OpenProjectClient, PermissionDeniedError

pytestmark = pytest.mark.integration


async def test_list_projects(client: OpenProjectClient) -> None:
    result = await client.list_projects()
    assert result.count > 0
    assert result.results[0].name


async def test_get_project(client: OpenProjectClient, test_project: str) -> None:
    project = await client.get_project(test_project)
    assert project.identifier == test_project
    assert project.name


async def test_get_project_admin_context(client: OpenProjectClient, test_project: str) -> None:
    ctx = await client.get_project_admin_context(test_project)
    assert ctx is not None


async def test_get_project_admin_context_filters_parent_candidates_by_read_allowlist(
    client: OpenProjectClient, test_project: str, project_refs: list[str]
) -> None:
    """available_parent_projects must be filtered by OPENPROJECT_READ_PROJECTS,
    not just by what OpenProject itself considers a valid parent candidate --
    otherwise a project outside the allowlist would leak its name/identifier
    through this picklist. The fixture's client is
    restricted to read_projects=(test_project,), so a freshly created,
    differently-named project must NOT appear as a parent candidate.

    Creating that second project requires its own, unrestricted client:
    the fixture's client's read_projects/write_projects are both scoped to
    (test_project,) alone, so create_project's own allowlist check would
    reject a differently-named project before this test ever reaches the
    available_parent_projects assertion it's meant to exercise.
    """
    unrestricted_settings = dataclasses.replace(
        client.settings,
        read_projects=("*",),
        write_projects=("*",),
    )
    unrestricted_client = OpenProjectClient(unrestricted_settings)
    await unrestricted_client.initialize()

    identifier = f"integration-test-{uuid.uuid4().hex[:8]}"
    create_result = await unrestricted_client.create_project(
        name=f"[integration-test] {identifier}", identifier=identifier, confirm=True
    )
    assert create_result.ready, create_result.validation_errors
    project_refs.append(identifier)

    ctx = await client.get_project_admin_context(test_project)

    candidate_identifiers = {ref.identifier for ref in ctx.available_parent_projects}
    assert identifier not in candidate_identifiers


async def test_get_project_configuration(client: OpenProjectClient, test_project: str) -> None:
    # The project configuration endpoint was added in 17.4; older instances 404.
    try:
        config = await client.get_project_configuration(test_project)
    except NotFoundError:
        pytest.skip("project configuration endpoint requires OpenProject 17.4+")
    assert config is not None


async def test_list_types_scoped_to_project(client: OpenProjectClient, test_project: str) -> None:
    result = await client.list_types(project=test_project)
    assert result.count > 0


async def test_list_categories(client: OpenProjectClient, test_project: str) -> None:
    result = await client.list_categories(test_project)
    assert result is not None


async def test_get_my_project_access(client: OpenProjectClient, test_project: str) -> None:
    access = await client.get_my_project_access(test_project)
    assert access is not None


async def test_list_principals(client: OpenProjectClient) -> None:
    result = await client.list_principals()
    assert result.count >= 0  # may be empty on minimal instance


async def test_add_and_remove_project_favorite(client: OpenProjectClient, test_project: str) -> None:
    """Round-trips add_project_favorite/remove_project_favorite against the
    real POST/DELETE workspaces/{id}/favorite endpoints. Restores the
    pre-test favorite state (unfavorited) regardless of outcome so this test
    leaves no persistent side effect on the disposable test project."""
    add_preview = await client.add_project_favorite(project=test_project)
    assert add_preview.requires_confirmation

    try:
        added = await client.add_project_favorite(project=test_project, confirm=True)
        assert added.confirmed
        assert added.action == "favorite"

        remove_preview = await client.remove_project_favorite(project=test_project)
        assert remove_preview.requires_confirmation

        removed = await client.remove_project_favorite(project=test_project, confirm=True)
        assert removed.confirmed
        assert removed.action == "unfavorite"
    finally:
        # Best-effort restore to unfavorited in case an assertion above failed
        # mid-sequence, so the test project's favorite state doesn't leak
        # into other tests/runs.
        try:
            await client.remove_project_favorite(project=test_project, confirm=True)
        except Exception:
            pass


async def test_add_project_favorite_denied_outside_write_allowlist(
    denied_client: OpenProjectClient, test_project: str
) -> None:
    with pytest.raises(PermissionDeniedError):
        await denied_client.add_project_favorite(project=test_project, confirm=True)


async def test_update_project_denies_reparent_into_write_restricted_project(
    client: OpenProjectClient, test_project: str, project_refs: list[str]
) -> None:
    """Regression: update_project's reparent target was only resolved
    read-only, letting a caller reparent a project they can write into
    under a different project they could only read -- the same gap
    update_board's reparent-target fix already closed for boards."""
    unrestricted_settings = dataclasses.replace(
        client.settings,
        read_projects=("*",),
        write_projects=("*",),
    )
    unrestricted_client = OpenProjectClient(unrestricted_settings)
    await unrestricted_client.initialize()

    target_identifier = f"integration-test-{uuid.uuid4().hex[:8]}"
    create_result = await unrestricted_client.create_project(
        name=f"[integration-test] {target_identifier}", identifier=target_identifier, confirm=True
    )
    assert create_result.ready, create_result.validation_errors
    project_refs.append(target_identifier)

    with pytest.raises(PermissionDeniedError):
        await client.update_project(project_ref=test_project, parent=target_identifier, confirm=True)
