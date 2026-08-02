"""Integration tests for work package CRUD operations."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from openproject_ce_mcp import tools
from openproject_ce_mcp.client import InvalidInputError, OpenProjectClient, PermissionDeniedError

from .conftest import disposable_project_identifier

pytestmark = pytest.mark.integration

_SUBJECT = "[integration-test] temp WP"
_SUBJECT_BULK = "[integration-test] bulk WP"


@dataclass
class _FakeAppContext:
    client: OpenProjectClient


class _FakeContext:
    """Minimal Context stand-in so a tools.py function can be exercised
    directly against a real client, the same shape tests/unit's mocked
    unit tests use (FakeAppContext/FakeContext in _tools_test_helpers.py),
    but wrapping a live client instead of a stub."""

    def __init__(self, client: OpenProjectClient) -> None:
        self.request_context = SimpleNamespace(lifespan_context=_FakeAppContext(client=client))


async def test_list_work_packages(client: OpenProjectClient, test_project: str) -> None:
    result = await client.list_work_packages(project=test_project)
    assert result is not None
    assert result.count >= 0


async def test_search_work_packages(client: OpenProjectClient) -> None:
    result = await client.search_work_packages(search="test")
    assert result is not None


async def test_list_my_open_work_packages(client: OpenProjectClient) -> None:
    result = await client.list_my_open_work_packages()
    assert result is not None


async def test_create_get_update_delete_work_package(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    # Create
    result = await client.create_work_package(
        project=test_project,
        type="Task",
        subject=_SUBJECT,
        confirm=True,
    )
    assert result.ready, result.validation_errors
    wp_id = result.work_package_id
    assert wp_id > 0
    wp_ids.append(wp_id)

    # Read
    wp = await client.get_work_package(wp_id)
    assert wp.subject == _SUBJECT
    assert wp.id == wp_id

    # Update
    update_result = await client.update_work_package(
        work_package_id=wp_id,
        subject=f"{_SUBJECT} updated",
        confirm=True,
    )
    assert update_result.ready, update_result.validation_errors

    updated = await client.get_work_package(wp_id)
    assert "updated" in updated.subject

    # Delete (cleanup fixture also deletes, but we verify delete works)
    delete_result = await client.delete_work_package(work_package_id=wp_id, confirm=True)
    assert delete_result.ready and delete_result.confirmed
    wp_ids.remove(wp_id)  # already deleted, don't try again in fixture


async def test_create_subtask(client: OpenProjectClient, test_project: str, wp_ids: list[int]) -> None:
    # Create parent
    parent = await client.create_work_package(
        project=test_project,
        type="Task",
        subject=f"{_SUBJECT} parent",
        confirm=True,
    )
    assert parent.ready
    wp_ids.append(parent.work_package_id)

    # Create subtask
    child = await client.create_subtask(
        parent_work_package_id=parent.work_package_id,
        type="Task",
        subject=f"{_SUBJECT} child",
        confirm=True,
    )
    assert child.ready
    wp_ids.append(child.work_package_id)

    wp = await client.get_work_package(child.work_package_id)
    assert wp.subject


async def test_create_work_package_rejects_assignee_supplied_by_name(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    """Live counterpart to the unit-level gap-fill test added during the
    write-path migration: assignee resolution on the write path
    accepts only "me" or a bare numeric user id, never a name search
    (deliberately narrower than the read-side assignee/assignee_me filters,
    which do accept names). Confirms the AssigneeRefResolver seam's narrower
    contract holds end-to-end against a live instance, not just against a
    mocked resolver."""
    with pytest.raises(InvalidInputError, match="assignee must be a positive integer user id or 'me'"):
        await client.create_work_package(
            project=test_project,
            type="Task",
            subject=f"{_SUBJECT} assignee-by-name",
            assignee="Definitely Not A Numeric Id",
            confirm=False,
        )


async def test_create_and_update_work_package_accept_assignee_me(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    """ "me" must still resolve correctly end-to-end (the one non-numeric value
    AssigneeRefResolver does accept) -- covers both create() and update()'s
    identical resolution path against a live instance."""
    result = await client.create_work_package(
        project=test_project,
        type="Task",
        subject=f"{_SUBJECT} assignee-me",
        assignee="me",
        confirm=True,
    )
    assert result.ready, result.validation_errors
    wp_ids.append(result.work_package_id)

    update_result = await client.update_work_package(
        work_package_id=result.work_package_id,
        assignee="me",
        confirm=True,
    )
    assert update_result.ready, update_result.validation_errors


async def test_create_and_update_work_package_accept_status_and_priority_by_name(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    """Gap-fill test, written before the flat _resolve_status_id/
    _resolve_priority_id are relocated into a StatusPriorityTypeResolver:
    name-based status/priority resolution on the work-package write path had
    no live coverage at all, only assignee-by-name did. Sources real
    status/priority names from list_statuses/list_priorities rather than
    hardcoding one, so this stays valid regardless of instance-specific
    workflow configuration. Run unchanged before and after the resolver
    relocation to prove no regression.

    create_work_package has no status= parameter (OpenProject assigns the
    workflow default status on create; status is settable on update_work_package
    only) -- priority-by-name is exercised on create, status-by-name on update,
    covering _resolve_priority_id and _resolve_status_id respectively."""
    priorities = await client.list_priorities()
    assert priorities.count > 0
    priority_name = priorities.results[0].name

    result = await client.create_work_package(
        project=test_project,
        type="Task",
        subject=f"{_SUBJECT} status-priority-by-name",
        priority=priority_name,
        confirm=True,
    )
    assert result.ready, result.validation_errors
    wp_ids.append(result.work_package_id)

    wp = await client.get_work_package(result.work_package_id)
    assert wp.priority == priority_name

    other_priority_name = next(
        (p.name for p in priorities.results if p.name != priority_name),
        priority_name,
    )
    statuses = await client.list_statuses()
    assert statuses.count > 0
    status_name = statuses.results[0].name

    update_result = await client.update_work_package(
        work_package_id=result.work_package_id,
        status=status_name,
        priority=other_priority_name,
        confirm=True,
    )
    assert update_result.ready, update_result.validation_errors

    updated = await client.get_work_package(result.work_package_id)
    assert updated.status == status_name
    assert updated.priority == other_priority_name


async def test_get_work_package_ancestors_tolerate_missing_display_id(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    """Regression: WorkPackageDetail.ancestors/children entries were typed as
    dict[str, str], but OpenProject only includes displayId on hierarchy links
    in 17.5+ semantic mode -- on a classic/pre-17.5 instance (or 17.5+ running
    in classic mode) display_id is None, and the MCP output schema used to
    reject that null outright, crashing get_work_package for any work package
    with ancestors. This test's own instance can be running with either
    semantic mode ON or OFF (both are valid configurations of this suite's
    Docker harness -- see docker/test/up.sh's SEED_SEMANTIC per service), so
    the actual regression being guarded against is "doesn't crash either
    way," not "display_id is always None": assert display_id is well-typed
    (None or str) rather than assuming one specific value."""
    parent = await client.create_work_package(
        project=test_project,
        type="Task",
        subject=f"{_SUBJECT} ancestors parent",
        confirm=True,
    )
    assert parent.ready
    wp_ids.append(parent.work_package_id)

    child = await client.create_subtask(
        parent_work_package_id=parent.work_package_id,
        type="Task",
        subject=f"{_SUBJECT} ancestors child",
        confirm=True,
    )
    assert child.ready
    wp_ids.append(child.work_package_id)

    wp = await client.get_work_package(child.work_package_id)
    assert wp.ancestors
    parent_href_fragment = f"/work_packages/{parent.work_package_id}"
    ancestor = next(a for a in wp.ancestors if a.get("href", "").endswith(parent_href_fragment))
    assert ancestor["display_id"] is None or isinstance(ancestor["display_id"], str)

    parent_wp = await client.get_work_package(parent.work_package_id)
    assert parent_wp.children
    child_href_fragment = f"/work_packages/{child.work_package_id}"
    child_link = next(c for c in parent_wp.children if c.get("href", "").endswith(child_href_fragment))
    assert child_link["display_id"] is None or isinstance(child_link["display_id"], str)


async def test_create_and_update_work_package_deny_reparent_into_write_restricted_parent(
    client: OpenProjectClient, test_project: str, wp_ids: list[int], project_refs: list[str]
) -> None:
    """Regression: create_work_package/update_work_package's
    parent_work_package_id reparent target was only resolved read-only,
    letting a caller with write access to test_project attach/move a work
    package under a parent in a project they could only read."""
    unrestricted_settings = dataclasses.replace(
        client.settings,
        read_projects=("*",),
        write_projects=("*",),
    )
    unrestricted_client = OpenProjectClient(unrestricted_settings)
    await unrestricted_client.initialize()

    other_identifier = disposable_project_identifier()
    create_project_result = await unrestricted_client.create_project(
        name=f"[integration-test] {other_identifier}", identifier=other_identifier, confirm=True
    )
    assert create_project_result.ready, create_project_result.validation_errors
    project_refs.append(other_identifier)

    other_parent = await unrestricted_client.create_work_package(
        project=other_identifier, type="Task", subject="[integration-test] write-restricted parent", confirm=True
    )
    assert other_parent.ready

    with pytest.raises(PermissionDeniedError):
        await client.create_work_package(
            project=test_project,
            type="Task",
            subject=f"{_SUBJECT} denied reparent on create",
            parent_work_package_id=other_parent.work_package_id,
            confirm=True,
        )

    existing = await client.create_work_package(
        project=test_project, type="Task", subject=f"{_SUBJECT} denied reparent on update", confirm=True
    )
    assert existing.ready
    wp_ids.append(existing.work_package_id)

    with pytest.raises(PermissionDeniedError):
        await client.update_work_package(
            work_package_id=existing.work_package_id,
            parent_work_package_id=other_parent.work_package_id,
            confirm=True,
        )


async def test_create_reparent_and_unparent_work_package(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    from openproject_ce_mcp.client import CLEAR_PARENT

    # Two candidate parents plus one child.
    parent_a = await client.create_work_package(
        project=test_project, type="Task", subject=f"{_SUBJECT} parent A", confirm=True
    )
    assert parent_a.ready
    wp_ids.append(parent_a.work_package_id)
    parent_b = await client.create_work_package(
        project=test_project, type="Task", subject=f"{_SUBJECT} parent B", confirm=True
    )
    assert parent_b.ready
    wp_ids.append(parent_b.work_package_id)

    # Create directly under parent A.
    child = await client.create_work_package(
        project=test_project,
        type="Task",
        subject=f"{_SUBJECT} reparent child",
        parent_work_package_id=parent_a.work_package_id,
        confirm=True,
    )
    assert child.ready, child.validation_errors
    wp_ids.append(child.work_package_id)
    assert (await client.get_work_package(child.work_package_id)).parent_id == parent_a.work_package_id

    # Re-parent to B.
    reparent = await client.update_work_package(
        work_package_id=child.work_package_id,
        parent_work_package_id=parent_b.work_package_id,
        confirm=True,
    )
    assert reparent.ready, reparent.validation_errors
    assert (await client.get_work_package(child.work_package_id)).parent_id == parent_b.work_package_id

    # Un-parent (make top-level).
    unparent = await client.update_work_package(
        work_package_id=child.work_package_id,
        parent_work_package_id=CLEAR_PARENT,
        confirm=True,
    )
    assert unparent.ready, unparent.validation_errors
    assert (await client.get_work_package(child.work_package_id)).parent_id is None


async def test_add_work_package_comment(client: OpenProjectClient, test_project: str, wp_ids: list[int]) -> None:
    result = await client.create_work_package(
        project=test_project,
        type="Task",
        subject=f"{_SUBJECT} comment-test",
        confirm=True,
    )
    assert result.ready
    wp_ids.append(result.work_package_id)

    comment = await client.add_work_package_comment(
        work_package_id=result.work_package_id,
        comment="Integration test comment",
        confirm=True,
    )
    assert comment is not None

    activities = await client.get_work_package_activities(result.work_package_id)
    assert activities.count > 0


async def test_get_work_package_activities_includes_creation_and_comment(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    """Dedicated test for get_work_package_activities itself (previously only
    ever exercised as a side-effect assertion inside other tests, e.g.
    test_add_work_package_comment above) -- checks the actual activity
    shape, not just a non-zero count."""
    result = await client.create_work_package(
        project=test_project,
        type="Task",
        subject=f"{_SUBJECT} get-activities-test",
        confirm=True,
    )
    assert result.ready
    wp_ids.append(result.work_package_id)

    # Work package creation itself generates at least one activity (a
    # "created" system journal entry) with no comment call needed.
    activities = await client.get_work_package_activities(result.work_package_id)
    assert activities.count >= 1
    created_activity = activities.results[0]
    assert created_activity.id > 0
    # The initial "created" activity's `user` field itself is None here (the
    # author instead shows up as an "Author set to ..." entry in `details`) --
    # not a bug, just this specific activity's real shape.
    assert created_activity.created_at is not None
    assert created_activity.details

    comment = await client.add_work_package_comment(
        work_package_id=result.work_package_id,
        comment="Integration test comment for get_work_package_activities",
        confirm=True,
    )
    assert comment.ready, comment.validation_errors

    # OpenProject can aggregate a fresh comment into the still-recent "created"
    # journal entry instead of always creating a new one (confirmed live: count
    # stayed the same here, with the existing entry's own `comment` field
    # populated instead) -- so >= growth, not exact +1, is the only safe assertion.
    after_comment = await client.get_work_package_activities(result.work_package_id)
    assert after_comment.count >= activities.count
    # get_work_package_activities returns newest-first (client.py's own
    # docstring), so the comment's own entry is results[0] -- UNLESS
    # OpenProject aggregated it into the existing "created" entry instead of
    # creating a new one (see the comment above), in which case that same
    # still-newest entry is still results[0], just with `comment` now
    # populated on it. Either way the newest entry is the one to check, never
    # results[-1] (the oldest), which only happened to hold the comment by
    # coincidence when aggregation kept the list at a single element.
    newest = after_comment.results[0]
    assert newest.comment is not None
    assert "Integration test comment for get_work_package_activities" in newest.comment


async def test_bulk_create_work_packages_rejects_unknown_item_field(
    client: OpenProjectClient, test_project: str
) -> None:
    """Regression: bulk_create_work_packages/bulk_update_work_packages
    accept an unrestricted items: list[dict] with no schema on each item's
    keys -- a misspelled or unsupported field was silently ignored instead
    of raising an error. This is a tools.py-layer validation (client.py has
    no knowledge of the item schema), so it's exercised through the tool
    function directly rather than client.bulk_create_work_packages."""
    ctx = _FakeContext(client)  # type: ignore[arg-type]
    items = [
        {"project": test_project, "type": "Task", "subject": "[integration-test] bulk unknown field", "bogus": "x"}
    ]
    with pytest.raises(ValueError, match="unsupported field"):
        await tools.bulk_create_work_packages(ctx, items=items, confirm=False)


async def test_bulk_create_work_packages(client: OpenProjectClient, test_project: str, wp_ids: list[int]) -> None:
    items = [
        {"project": test_project, "type": "Task", "subject": f"{_SUBJECT_BULK} 1"},
        {"project": test_project, "type": "Task", "subject": f"{_SUBJECT_BULK} 2"},
    ]
    result = await client.bulk_create_work_packages(items=items, confirm=True)
    assert result.total == 2

    for item in result.items:
        if item.success and item.result and item.result.work_package_id:
            wp_ids.append(item.result.work_package_id)

    assert result.succeeded >= 1  # at least one should succeed


async def test_bulk_create_work_packages_applies_duration_fields(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    # estimated_time/remaining_time/duration must actually be applied by
    # bulk_create_work_packages, not silently dropped.
    items = [
        {
            "project": test_project,
            "type": "Task",
            "subject": f"{_SUBJECT_BULK} duration",
            "estimated_time": "PT8H",
        },
    ]
    result = await client.bulk_create_work_packages(items=items, confirm=True)
    assert result.succeeded == 1
    item = result.items[0]
    assert item.result is not None and item.result.work_package_id is not None
    wp_ids.append(item.result.work_package_id)
    assert item.result.result is not None
    assert item.result.result.estimated_time == "PT8H"


async def test_list_work_package_watchers(client: OpenProjectClient, test_project: str, wp_ids: list[int]) -> None:
    result = await client.create_work_package(
        project=test_project,
        type="Task",
        subject=f"{_SUBJECT} watcher-test",
        confirm=True,
    )
    assert result.ready
    wp_ids.append(result.work_package_id)

    watchers = await client.list_work_package_watchers(result.work_package_id)
    assert watchers is not None


async def test_list_work_package_watchers_denies_anchor_outside_read_allowlist(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    """Regression: list_work_package_watchers fetched
    work_packages/{id}/watchers with no allowlist check on the anchor work
    package at all, leaking watcher names/emails for any work package id
    regardless of OPENPROJECT_READ_PROJECTS."""
    result = await client.create_work_package(
        project=test_project,
        type="Task",
        subject=f"{_SUBJECT} watcher-denial-test",
        confirm=True,
    )
    assert result.ready
    wp_ids.append(result.work_package_id)

    read_denied_settings = dataclasses.replace(
        client.settings, read_projects=("no-such-project-for-integration-tests",)
    )
    read_denied_client = OpenProjectClient(read_denied_settings)
    await read_denied_client.initialize()

    with pytest.raises(PermissionDeniedError):
        await read_denied_client.list_work_package_watchers(result.work_package_id)


async def test_add_and_remove_work_package_watcher(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    """Round-trips add_work_package_watcher/remove_work_package_watcher against
    the real POST/DELETE work_packages/{id}/watchers[/{user_id}] endpoints,
    watching/unwatching the work package as the current (token-owning) user."""
    result = await client.create_work_package(
        project=test_project,
        type="Task",
        subject=f"{_SUBJECT} watcher-add-remove-test",
        confirm=True,
    )
    assert result.ready
    wp_ids.append(result.work_package_id)

    me = await client.get_current_user()

    preview = await client.add_work_package_watcher(result.work_package_id, me.id)
    assert preview.requires_confirmation

    added = await client.add_work_package_watcher(result.work_package_id, me.id, confirm=True)
    assert added.confirmed
    assert added.watcher_user_id == me.id

    watchers_after_add = await client.list_work_package_watchers(result.work_package_id)
    assert any(w.id == me.id for w in watchers_after_add.results)

    removed = await client.remove_work_package_watcher(result.work_package_id, me.id, confirm=True)
    assert removed.confirmed

    watchers_after_remove = await client.list_work_package_watchers(result.work_package_id)
    assert not any(w.id == me.id for w in watchers_after_remove.results)


async def test_add_work_package_watcher_denied_outside_write_allowlist(
    denied_client: OpenProjectClient, client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    result = await client.create_work_package(
        project=test_project,
        type="Task",
        subject=f"{_SUBJECT} watcher-add-denied-test",
        confirm=True,
    )
    assert result.ready
    wp_ids.append(result.work_package_id)

    me = await client.get_current_user()

    with pytest.raises(PermissionDeniedError):
        await denied_client.add_work_package_watcher(result.work_package_id, me.id, confirm=True)


async def test_list_work_package_file_links_denies_anchor_outside_read_allowlist(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    """Regression: list_work_package_file_links fetched
    work_packages/{id}/file_links with no allowlist check on the anchor work
    package at all, leaking file link URLs/names for any work package id
    regardless of OPENPROJECT_READ_PROJECTS."""
    result = await client.create_work_package(
        project=test_project,
        type="Task",
        subject=f"{_SUBJECT} file-link-denial-test",
        confirm=True,
    )
    assert result.ready
    wp_ids.append(result.work_package_id)

    read_denied_settings = dataclasses.replace(
        client.settings, read_projects=("no-such-project-for-integration-tests",)
    )
    read_denied_client = OpenProjectClient(read_denied_settings)
    await read_denied_client.initialize()

    with pytest.raises(PermissionDeniedError):
        await read_denied_client.list_work_package_file_links(result.work_package_id)


async def test_get_work_packages_batch_partial_failure(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    """get_work_packages fans out one get_work_package call per id via
    asyncio.gather and tracks per-item success/failure, live, with a mix of
    a real id and one that must fail."""
    created = await client.create_work_package(
        project=test_project, type="Task", subject=f"{_SUBJECT} batch-get", confirm=True
    )
    assert created.ready
    wp_ids.append(created.work_package_id)

    bogus_id = 2**31 - 1  # exceeds any real work package id on a fresh test instance
    result = await client.get_work_packages(ids=[created.work_package_id, bogus_id])

    assert result.total == 2
    assert result.succeeded == 1
    assert result.failed == 1

    by_id = {item.id: item for item in result.results}
    assert by_id[created.work_package_id].success
    assert by_id[created.work_package_id].work_package is not None
    assert not by_id[bogus_id].success
    assert by_id[bogus_id].error is not None


async def test_bulk_update_work_packages_partial_failure(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    """bulk_update_work_packages loops update_work_package per item and
    tracks per-item success/failure -- bulk *create* has live coverage above,
    but bulk *update* (a distinct code path) did not until now."""
    first = await client.create_work_package(
        project=test_project, type="Task", subject=f"{_SUBJECT} bulk-update 1", confirm=True
    )
    assert first.ready
    wp_ids.append(first.work_package_id)
    second = await client.create_work_package(
        project=test_project, type="Task", subject=f"{_SUBJECT} bulk-update 2", confirm=True
    )
    assert second.ready
    wp_ids.append(second.work_package_id)

    bogus_id = 2**31 - 1
    items = [
        {"work_package_id": first.work_package_id, "subject": f"{_SUBJECT} bulk-update 1 changed"},
        {"work_package_id": second.work_package_id, "subject": f"{_SUBJECT} bulk-update 2 changed"},
        {"work_package_id": bogus_id, "subject": "should fail"},
    ]

    preview = await client.bulk_update_work_packages(items=items, confirm=False)
    # requires_confirmation is only set when every item validates cleanly
    # (`not confirm and failed == 0`) -- with one item already failing
    # validation in preview, there's nothing to confirm yet.
    assert not preview.requires_confirmation
    assert preview.succeeded == 2
    assert preview.failed == 1

    result = await client.bulk_update_work_packages(items=items, confirm=True)
    assert result.total == 3
    assert result.succeeded == 2
    assert result.failed == 1

    updated_first = await client.get_work_package(first.work_package_id)
    assert "changed" in updated_first.subject
    updated_second = await client.get_work_package(second.work_package_id)
    assert "changed" in updated_second.subject


async def test_get_project_work_package_context(client: OpenProjectClient, test_project: str) -> None:
    """Aggregation method: resolves the project, then fetches types,
    statuses, priorities, categories, and versions in parallel -- and, when
    a type is given, the create-form schema for that type too. No prior live
    coverage of either the untyped or typed path."""
    untyped = await client.get_project_work_package_context(project=test_project)
    assert untyped.available_types
    assert untyped.available_statuses
    assert untyped.available_priorities

    type_name = untyped.available_types[0].title
    typed = await client.get_project_work_package_context(project=test_project, type=type_name)
    assert typed.selected_type_name == type_name


async def test_get_work_package_hierarchy_filters_ancestors_and_children_outside_read_allowlist(
    client: OpenProjectClient, test_project: str, wp_ids: list[int], project_refs: list[str]
) -> None:
    """Baseline for the pre-migration behavior of `_filter_hierarchy_allowlist`
    (client.py:1706-1736): OpenProject's parent/child hierarchy is not
    project-constrained, so a linked work package's ancestor/child can belong
    to a project the caller isn't allowed to read. The anchor work package
    (`test_project`, inside `client`'s read allowlist) must still be
    returned, but a cross-project ancestor/child outside the allowlist must
    be dropped from `ancestors`/`children` rather than leaked.

    Written against the still-flat client.py before the Work Packages READ
    migration (domain-migration-runbook.md step 4's live-test-ordering rule)
    so the identical test proves no regression once `get_work_package`
    delegates to the new `WorkPackageService`."""
    unrestricted_settings = dataclasses.replace(
        client.settings,
        read_projects=("*",),
        write_projects=("*",),
    )
    unrestricted_client = OpenProjectClient(unrestricted_settings)
    await unrestricted_client.initialize()

    other_identifier = disposable_project_identifier()
    create_project_result = await unrestricted_client.create_project(
        name=f"[integration-test] {other_identifier}", identifier=other_identifier, confirm=True
    )
    assert create_project_result.ready, create_project_result.validation_errors
    project_refs.append(other_identifier)

    # Parent lives OUTSIDE test_project (in the other, unrestricted-only project).
    outside_parent = await unrestricted_client.create_work_package(
        project=other_identifier, type="Task", subject=f"{_SUBJECT} outside-scope parent", confirm=True
    )
    assert outside_parent.ready

    # Child lives INSIDE test_project (within `client`'s read allowlist), parented
    # to the outside-scope work package -- cross-project parenting is allowed by
    # OpenProject itself (create_work_package's own project scoping is
    # independent of parent_work_package_id's project), this test only concerns
    # what the READ path exposes. Uses the unrestricted client so the write
    # allowlist check on the cross-project parent link succeeds; `client`
    # itself only reads below.
    child = await unrestricted_client.create_work_package(
        project=test_project,
        type="Task",
        subject=f"{_SUBJECT} inside-scope child",
        parent_work_package_id=outside_parent.work_package_id,
        confirm=True,
    )
    assert child.ready, child.validation_errors
    wp_ids.append(child.work_package_id)

    # `client` (scoped to test_project only) reads the child: the anchor itself
    # is visible (its own project is in-scope), but the out-of-scope parent must
    # not appear in `ancestors`.
    wp = await client.get_work_package(child.work_package_id)
    assert wp.id == child.work_package_id
    outside_href_fragment = f"/work_packages/{outside_parent.work_package_id}"
    if wp.ancestors:
        assert not any(a.get("href", "").endswith(outside_href_fragment) for a in wp.ancestors)

    # The unrestricted client (read_projects=("*",)) must still see the real
    # ancestor -- proves the filtering above is allowlist-driven, not a
    # blanket/always-empty result.
    unrestricted_wp = await unrestricted_client.get_work_package(child.work_package_id)
    assert unrestricted_wp.ancestors
    assert any(a.get("href", "").endswith(outside_href_fragment) for a in unrestricted_wp.ancestors)
