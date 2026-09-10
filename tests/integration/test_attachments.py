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
    result = await client.work_package.create(
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
        await hidden_client.attachment.create(
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
    result = await client.work_package.create(
        project=test_project,
        type="Task",
        subject="[integration-test] attachment list-delete test",
        confirm=True,
    )
    assert result.ready
    wp_ids.append(result.work_package_id)

    rooted_client = _attachment_capable_client(client)
    await rooted_client.initialize()

    created = await rooted_client.attachment.create(
        work_package_id=result.work_package_id,
        file_path="tests/fixtures/spec.md",
        description="[integration-test] attachment",
        confirm=True,
    )
    assert created.ready
    attachment_id = created.attachment_id
    assert attachment_id is not None

    listed = await client.attachment.list_for_work_package(result.work_package_id)
    assert any(a.id == attachment_id for a in listed.results)

    fetched = await client.attachment.get(attachment_id)
    assert fetched.id == attachment_id

    preview = await client.attachment.delete(attachment_id=attachment_id)
    assert preview.state == "preview"

    deleted = await client.attachment.delete(attachment_id=attachment_id, confirm=True)
    assert deleted.state == "confirmed"

    listed_after = await client.attachment.list_for_work_package(result.work_package_id)
    assert not any(a.id == attachment_id for a in listed_after.results)


async def test_delete_attachment_denied_outside_write_allowlist(
    denied_client: OpenProjectClient, client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    result = await client.work_package.create(
        project=test_project,
        type="Task",
        subject="[integration-test] attachment delete-denied test",
        confirm=True,
    )
    assert result.ready
    wp_ids.append(result.work_package_id)

    rooted_client = _attachment_capable_client(client)
    await rooted_client.initialize()

    created = await rooted_client.attachment.create(
        work_package_id=result.work_package_id,
        file_path="tests/fixtures/spec.md",
        description="[integration-test] attachment denied",
        confirm=True,
    )
    assert created.ready
    attachment_id = created.attachment_id
    assert attachment_id is not None

    with pytest.raises(PermissionDeniedError):
        await denied_client.attachment.delete(attachment_id=attachment_id, confirm=True)

    # Clean up directly since the denied client couldn't remove it.
    await client.attachment.delete(attachment_id=attachment_id, confirm=True)


# --- get_attachment_content / include_images -----------------------------------


async def _upload(rooted_client: OpenProjectClient, work_package_id: int, file_path: str) -> int:
    created = await rooted_client.attachment.create(
        work_package_id=work_package_id,
        file_path=file_path,
        description="[integration-test] content",
        confirm=True,
    )
    assert created.ready
    assert created.attachment_id is not None
    return created.attachment_id


async def test_get_attachment_content_inlines_png_and_text(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    """Round-trips GET /attachments/{id}/content -- including OpenProject's
    redirect to its storage backend -- for an image and for a text file."""
    result = await client.work_package.create(
        project=test_project,
        type="Task",
        subject="[integration-test] attachment content",
        confirm=True,
    )
    assert result.ready
    wp_ids.append(result.work_package_id)

    rooted_client = _attachment_capable_client(client)
    await rooted_client.initialize()
    png_id = await _upload(rooted_client, result.work_package_id, "tests/fixtures/pixel.png")
    text_id = await _upload(rooted_client, result.work_package_id, "tests/fixtures/spec.md")
    try:
        with open("tests/fixtures/pixel.png", "rb") as fh:
            png_bytes = fh.read()
        image = await client.attachment.get_content(png_id)
        assert image.metadata.outcome == "image"
        assert image.metadata.content_type == "image/png"
        assert image.metadata.size_bytes == len(png_bytes)
        assert image.image_bytes == png_bytes

        with open("tests/fixtures/spec.md", encoding="utf-8") as fh:
            spec_text = fh.read()
        text = await client.attachment.get_content(text_id)
        assert text.metadata.outcome == "text"
        assert text.metadata.truncated is False
        assert text.text == spec_text

        # Text over the cap is cut, an image over the cap is refused whole.
        cut = await client.attachment.get_content(text_id, max_bytes=10)
        assert cut.metadata.outcome == "text"
        assert cut.metadata.truncated is True
        assert cut.text == spec_text.encode("utf-8")[:10].decode("utf-8", errors="replace")
        refused = await client.attachment.get_content(png_id, max_bytes=10)
        assert refused.metadata.outcome == "too_large"
        assert refused.image_bytes is None

        listing = await client.attachment.list_for_work_package_with_images(result.work_package_id)
        assert listing.list_result.images is not None
        by_id = {entry.attachment_id: entry.outcome for entry in listing.list_result.images}
        assert by_id[png_id] == "image"
        assert by_id[text_id] == "not_inline_supported"
        assert [o.metadata.attachment_id for o in listing.included] == [png_id]
        assert listing.included[0].image_bytes == png_bytes
    finally:
        await client.attachment.delete(attachment_id=png_id, confirm=True)
        await client.attachment.delete(attachment_id=text_id, confirm=True)


async def test_get_attachment_content_denied_outside_read_allowlist(
    client: OpenProjectClient, test_project: str, wp_ids: list[int]
) -> None:
    """`denied_client` only narrows the WRITE allowlist; reading content is a
    read, so the denial has to come from a read allowlist that does not
    contain the container's project. The metadata fetch itself succeeds (it is
    how the container is discovered) -- the scope check on its project link is
    what must refuse, before any content is requested."""
    read_denied_settings = dataclasses.replace(
        client.settings, read_projects=("no-such-project-for-integration-tests",)
    )
    read_denied_client = OpenProjectClient(read_denied_settings)
    await read_denied_client.initialize()

    result = await client.work_package.create(
        project=test_project,
        type="Task",
        subject="[integration-test] attachment content denied",
        confirm=True,
    )
    assert result.ready
    wp_ids.append(result.work_package_id)

    rooted_client = _attachment_capable_client(client)
    await rooted_client.initialize()
    png_id = await _upload(rooted_client, result.work_package_id, "tests/fixtures/pixel.png")
    try:
        with pytest.raises(PermissionDeniedError):
            await read_denied_client.attachment.get_content(png_id)
    finally:
        await client.attachment.delete(attachment_id=png_id, confirm=True)
