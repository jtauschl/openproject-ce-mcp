"""Integration tests for work package attachment write operations."""

from __future__ import annotations

import dataclasses
import os

import pytest

from openproject_ce_mcp.client import InvalidInputError, OpenProjectClient, PermissionDeniedError

pytestmark = pytest.mark.integration


async def test_create_attachment_rejects_hidden_file_name_field(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    """Regression: create_work_package_attachment's file_name field bypassed
    the hidden-fields guard on writes (only the optional description field
    was covered)."""
    result = await client.create_work_package(
        project=test_project,
        type="Task",
        subject="[integration-test] attachment hidden field",
        confirm=True,
    )
    assert result.ready
    wp_ids.append(result.work_package_id)

    hidden_settings = dataclasses.replace(client.settings, hidden_fields={"attachment": ("file_name",)})
    hidden_client = OpenProjectClient(hidden_settings)
    await hidden_client.initialize()

    with pytest.raises(InvalidInputError, match="OPENPROJECT_HIDE_ATTACHMENT_FIELDS"):
        await hidden_client.create_work_package_attachment(
            work_package_id=result.work_package_id,
            file_path="/nonexistent/path/does-not-matter.txt",
            confirm=False,
        )


def _attachment_capable_client(client: OpenProjectClient) -> OpenProjectClient:
    """create_work_package_attachment requires OPENPROJECT_ATTACHMENT_ROOT to be
    set before it will read real file bytes off disk; the shared `client`
    fixture doesn't set one, so build a copy that does, rooted at the repo's
    working directory (file_path is then given relative to that root, mirroring
    the unit test pattern in tests/test_client.py)."""
    rooted_settings = dataclasses.replace(client.settings, attachment_root=os.getcwd())
    return OpenProjectClient(rooted_settings)


async def test_list_work_package_attachments_and_delete_attachment(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    """Round-trips list_work_package_attachments (GET
    work_packages/{id}/attachments) and delete_attachment (GET+DELETE
    attachments/{id}) against a real uploaded attachment."""
    result = await client.create_work_package(
        project=test_project,
        type="Task",
        subject="[integration-test] attachment list-delete test",
        confirm=True,
    )
    assert result.ready
    wp_ids.append(result.work_package_id)

    rooted_client = _attachment_capable_client(client)
    await rooted_client.initialize()

    created = await rooted_client.create_work_package_attachment(
        work_package_id=result.work_package_id,
        file_path="tests/fixtures/spec.md",
        description="[integration-test] attachment",
        confirm=True,
    )
    assert created.ready
    attachment_id = created.attachment_id
    assert attachment_id is not None

    listed = await client.list_work_package_attachments(result.work_package_id)
    assert any(a.id == attachment_id for a in listed.results)

    fetched = await client.get_attachment(attachment_id)
    assert fetched.id == attachment_id

    preview = await client.delete_attachment(attachment_id=attachment_id)
    assert preview.requires_confirmation

    deleted = await client.delete_attachment(attachment_id=attachment_id, confirm=True)
    assert deleted.confirmed

    listed_after = await client.list_work_package_attachments(result.work_package_id)
    assert not any(a.id == attachment_id for a in listed_after.results)


async def test_delete_attachment_denied_outside_write_allowlist(
    denied_client: OpenProjectClient, client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    result = await client.create_work_package(
        project=test_project,
        type="Task",
        subject="[integration-test] attachment delete-denied test",
        confirm=True,
    )
    assert result.ready
    wp_ids.append(result.work_package_id)

    rooted_client = _attachment_capable_client(client)
    await rooted_client.initialize()

    created = await rooted_client.create_work_package_attachment(
        work_package_id=result.work_package_id,
        file_path="tests/fixtures/spec.md",
        description="[integration-test] attachment denied",
        confirm=True,
    )
    assert created.ready
    attachment_id = created.attachment_id
    assert attachment_id is not None

    with pytest.raises(PermissionDeniedError):
        await denied_client.delete_attachment(attachment_id=attachment_id, confirm=True)

    # Clean up directly since the denied client couldn't remove it.
    await client.delete_attachment(attachment_id=attachment_id, confirm=True)
