"""Integration tests for project read operations."""

from __future__ import annotations

import dataclasses

import pytest

from openproject_ce_mcp.client import NotFoundError, OpenProjectClient, PermissionDeniedError

from .conftest import disposable_project_identifier

pytestmark = pytest.mark.integration


async def test_list_projects(client: OpenProjectClient) -> None:
    result = await client.project.list()
    assert result.count > 0
    assert result.results[0].name


async def test_get_project(client: OpenProjectClient, test_project: str) -> None:
    project = await client.project.get(test_project)
    # OpenProject identifiers are always lowercase server-side (docker/test/
    # seed.rb creates the project as "tst" even when OPENPROJECT_TEST_PROJECT
    # is "TST", per that script's own comment) -- compare case-insensitively,
    # not as an exact match.
    assert project.identifier is not None
    assert project.identifier.casefold() == test_project.casefold()
    assert project.name


async def test_get_project_admin_context(client: OpenProjectClient, test_project: str) -> None:
    ctx = await client.project_admin.get_admin_context(test_project)
    assert ctx is not None
    assert ctx.project is not None
    assert ctx.project.identifier is not None
    assert ctx.project.identifier.casefold() == test_project.casefold()


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

    identifier = disposable_project_identifier()
    create_result = await unrestricted_client.create_project(
        name=f"[integration-test] {identifier}", identifier=identifier, confirm=True
    )
    assert create_result.ready, create_result.validation_errors
    project_refs.append(identifier)

    ctx = await client.project_admin.get_admin_context(test_project)

    candidate_identifiers = {ref.identifier for ref in ctx.available_parent_projects}
    assert identifier not in candidate_identifiers


_WILDCARDS = pytest.mark.parametrize("wildcard", ["_", "%"], ids=["underscore", "percent"])


async def _create_named_projects(client: OpenProjectClient, project_refs: list[str], names: list[str]) -> None:
    for name in names:
        identifier = disposable_project_identifier()
        created = await client.create_project(name=name, identifier=identifier, confirm=True)
        assert created.ready, created.validation_errors
        project_refs.append(identifier)


@_WILDCARDS
async def test_project_search_treats_like_wildcards_as_literal_text(
    start_scoped_client, project_refs: list[str], wildcard: str
) -> None:
    client = await start_scoped_client(read_projects=("*",), write_projects=("*",))
    suffix = disposable_project_identifier()
    literal_name = f"[integration-test] a{wildcard}b {suffix}"
    await _create_named_projects(client, project_refs, [literal_name, f"[integration-test] axb {suffix}"])

    found = await client.project.list(search=f"a{wildcard}b {suffix}")

    assert [project.name for project in found.results] == [literal_name]


@_WILDCARDS
async def test_a_name_that_only_a_wildcard_would_match_is_not_resolved_to_that_project(
    start_scoped_client, project_refs: list[str], wildcard: str
) -> None:
    client = await start_scoped_client(read_projects=("*",), write_projects=("*",))
    suffix = disposable_project_identifier()
    await _create_named_projects(client, project_refs, [f"[integration-test] axb {suffix}"])

    with pytest.raises(NotFoundError):
        await client.project.get(f"[integration-test] a{wildcard}b {suffix}")


async def test_get_project_configuration(client: OpenProjectClient, test_project: str) -> None:
    # The project configuration endpoint was added in 17.4; older instances 404.
    try:
        config = await client.project.get_configuration(test_project)
    except NotFoundError:
        pytest.skip("project configuration endpoint requires OpenProject 17.4+")
    assert config is not None
    assert config.project_name


async def test_list_types_scoped_to_project(client: OpenProjectClient, test_project: str) -> None:
    result = await client.status_priority_type.list_types(project=test_project)
    assert result.count > 0


async def test_list_categories(client: OpenProjectClient, test_project: str) -> None:
    result = await client.category.list(test_project)
    assert result is not None
    if result.count == 0:
        pytest.skip("no existing category in the test project (no create_category API to seed one)")
    # docker/test/seed.rb always seeds a "Seed Category" (no create_category
    # API exists to seed one through a test-time call instead).
    assert result.results[0].name


async def test_get_my_project_access(client: OpenProjectClient, test_project: str) -> None:
    access = await client.get_my_project_access(test_project)
    assert access is not None
    me = await client.current_user.get_current_user()
    assert access.current_user_id == me.id


async def test_list_principals(client: OpenProjectClient) -> None:
    me = await client.current_user.get_current_user()
    assert me.name
    # The collection has no defined order and leftovers of earlier tests can push the current user off the first
    # page, so the user is looked up by name instead of expected on page one.
    result = await client.principal.list_principals(search=me.name)
    assert result.count > 0
    assert any(p.id == me.id for p in result.results)


async def test_list_principals_paginates_beyond_a_single_page(client: OpenProjectClient) -> None:
    unfiltered = await client.principal.list_principals(limit=100)
    if unfiltered.total < 2:
        pytest.skip("Not enough principals on this instance to prove pagination")

    first_page = await client.principal.list_principals(limit=1)
    assert first_page.count == 1
    assert first_page.truncated
    assert first_page.next_offset == 2

    second_page = await client.principal.list_principals(limit=1, offset=2)
    assert second_page.count == 1
    assert second_page.results[0].id != first_page.results[0].id


async def test_add_and_remove_project_favorite(client: OpenProjectClient, test_project: str) -> None:
    """Round-trips add_project_favorite/remove_project_favorite against the
    real POST/DELETE workspaces/{id}/favorite endpoints. Restores the
    pre-test favorite state (unfavorited) regardless of outcome so this test
    leaves no persistent side effect on the disposable test project."""
    add_preview = await client.add_project_favorite(project=test_project)
    assert add_preview.state == "preview"

    try:
        try:
            added = await client.add_project_favorite(project=test_project, confirm=True)
        except NotFoundError as exc:
            # _run_version_gated raises this with a specific message when the
            # endpoint itself doesn't exist yet (favorites require OpenProject
            # 17.0+) -- distinct from a genuine 404 on a real resource, which
            # this test isn't exercising.
            if "requires OpenProject" in str(exc):
                pytest.skip(str(exc))
            raise
        assert added.state == "confirmed"
        assert added.action == "favorite"

        remove_preview = await client.remove_project_favorite(project=test_project)
        assert remove_preview.state == "preview"

        removed = await client.remove_project_favorite(project=test_project, confirm=True)
        assert removed.state == "confirmed"
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

    target_identifier = disposable_project_identifier()
    create_result = await unrestricted_client.create_project(
        name=f"[integration-test] {target_identifier}", identifier=target_identifier, confirm=True
    )
    assert create_result.ready, create_result.validation_errors
    project_refs.append(target_identifier)

    with pytest.raises(PermissionDeniedError):
        await client.update_project(project_ref=test_project, parent=target_identifier, confirm=True)


async def test_a_renamed_project_is_not_admitted_by_its_former_identifier(
    start_scoped_client, project_refs: list[str]
) -> None:
    """From 17.3 OpenProject resolves a project's former identifier to the
    renamed project; only its id, current identifier and name may match."""
    unrestricted = await start_scoped_client(read_projects=("*",), write_projects=("*",))
    former = disposable_project_identifier()
    current = disposable_project_identifier()
    # The name must not contain the former identifier, or the name fallback
    # would find the project on versions without former-identifier lookup.
    created = await unrestricted.project.create(
        name="[integration-test] renamed project", identifier=former, confirm=True
    )
    assert created.ready, created.validation_errors
    assert created.project_id is not None
    project_refs.append(str(created.project_id))
    renamed = await unrestricted.project.update(project_ref=former, identifier=current, confirm=True)
    assert renamed.ready, renamed.validation_errors
    try:
        resolved = await unrestricted.project.get(former)
    except NotFoundError:
        pytest.skip("former project identifiers resolve only from OpenProject 17.3")
    assert (resolved.id, resolved.identifier) == (created.project_id, current)

    read_by_former = await start_scoped_client(read_projects=(former,), write_projects=(former,))
    for project_ref in (former, current, str(created.project_id)):
        with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
            await read_by_former.project.get(project_ref)

    write_by_former = await start_scoped_client(read_projects=("*",), write_projects=(former,))
    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await write_by_former.project.update(project_ref=former, name="[integration-test] denied", confirm=False)

    for pattern in (current, str(created.project_id)):
        allowed = await start_scoped_client(read_projects=(pattern,), write_projects=(pattern,))
        assert (await allowed.project.get(former)).id == created.project_id
        preview = await allowed.project.update(project_ref=former, name="[integration-test] allowed", confirm=False)
        assert preview.project_id == created.project_id
