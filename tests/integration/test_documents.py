"""Integration tests for document read/update operations.

Documents is PATCH-only in the OpenProject v3 API: no POST create / DELETE
endpoint exists, so unlike news/versions/memberships this file has no
create-then-cleanup fixture. get_document/update_document are exercised
against a pre-existing document in the test project, sourced via
list_documents -- if the test project has none, that test is skipped rather
than failed, since there's no API to seed one.
"""

from __future__ import annotations

import pytest

from openproject_ce_mcp.client import OpenProjectClient

pytestmark = pytest.mark.integration


async def test_list_documents(client: OpenProjectClient, test_project: str) -> None:
    result = await client.list_documents(project=test_project)
    assert result is not None
    assert result.count >= 0


async def test_get_and_update_document(client: OpenProjectClient, test_project: str) -> None:
    existing = await client.list_documents(project=test_project)
    if existing.count == 0:
        pytest.skip("no existing document in the test project to read/update (no create_document API to seed one)")

    document_id = existing.results[0].id

    document = await client.get_document(document_id)
    assert document.id == document_id

    update_result = await client.update_document(
        document_id=document_id,
        description=document.description,
        confirm=True,
    )
    assert update_result.ready, update_result.validation_errors
