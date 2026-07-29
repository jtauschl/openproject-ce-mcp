"""Integration tests for work package CRUD operations."""

from __future__ import annotations

import dataclasses
import uuid
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from openproject_ce_mcp import tools
from openproject_ce_mcp.client import OpenProjectClient, PermissionDeniedError

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


async def test_get_work_package_ancestors_tolerate_missing_display_id(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    """Regression: WorkPackageDetail.ancestors/children entries were typed as
    dict[str, str], but OpenProject only includes displayId on hierarchy
    links in 17.5+ semantic mode -- on a classic/pre-17.5 instance (like this
    one, seeded with classic identifiers) display_id is None, and the MCP
    output schema used to reject that null outright, crashing get_work_package
    for any work package with ancestors."""
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
    assert ancestor["display_id"] is None  # classic instance: no displayId on hierarchy links

    parent_wp = await client.get_work_package(parent.work_package_id)
    assert parent_wp.children
    child_href_fragment = f"/work_packages/{child.work_package_id}"
    child_link = next(c for c in parent_wp.children if c.get("href", "").endswith(child_href_fragment))
    assert child_link["display_id"] is None


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

    other_identifier = f"integration-test-{uuid.uuid4().hex[:8]}"
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
    # estimated_time/remaining_time/duration used to be silently dropped by
    # bulk_create_work_packages instead of applied.
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
