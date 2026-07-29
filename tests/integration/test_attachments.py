"""Integration tests for work package attachment write operations."""

from __future__ import annotations

import dataclasses

import pytest

from openproject_ce_mcp.client import InvalidInputError, OpenProjectClient

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
