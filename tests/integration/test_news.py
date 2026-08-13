"""Integration tests for news CRUD operations."""

from __future__ import annotations

import uuid

import pytest

from openproject_ce_mcp.client import OpenProjectClient, PermissionDeniedError

pytestmark = pytest.mark.integration


async def test_list_news(client: OpenProjectClient, test_project: str, news_ids: list[int]) -> None:
    title = f"[integration-test] list {uuid.uuid4().hex[:8]}"
    create_result = await client.create_news(
        project=test_project,
        title=title,
        summary="Integration test summary for list_news",
        confirm=True,
    )
    assert create_result.ready, create_result.validation_errors
    news_ids.append(create_result.news_id)

    result = await client.list_news(project=test_project)
    assert result is not None
    assert result.count > 0
    assert any(item.title == title for item in result.results)


async def test_create_get_update_delete_news(client: OpenProjectClient, test_project: str, news_ids: list[int]) -> None:
    title = f"[integration-test] {uuid.uuid4().hex[:8]}"

    # Create
    result = await client.create_news(
        project=test_project,
        title=title,
        summary="Integration test summary",
        confirm=True,
    )
    assert result.ready, result.validation_errors
    news_id = result.news_id
    assert news_id > 0
    news_ids.append(news_id)

    # Read
    news = await client.get_news(news_id)
    assert news.title == title
    assert news.id == news_id

    # Update
    update_result = await client.update_news(
        news_id=news_id,
        title=f"{title} updated",
        confirm=True,
    )
    assert update_result.ready, update_result.validation_errors

    updated = await client.get_news(news_id)
    assert updated.title == f"{title} updated"

    # Delete
    delete_result = await client.delete_news(news_id=news_id, confirm=True)
    assert delete_result.ready and delete_result.state == "confirmed"
    news_ids.remove(news_id)


async def test_create_update_delete_news_denied_outside_write_allowlist(
    denied_client: OpenProjectClient, client: OpenProjectClient, test_project: str, news_ids: list[int]
) -> None:
    with pytest.raises(PermissionDeniedError):
        await denied_client.create_news(
            project=test_project, title=f"[integration-test] denied {uuid.uuid4().hex[:8]}", confirm=True
        )

    existing = await client.create_news(
        project=test_project, title=f"[integration-test] {uuid.uuid4().hex[:8]}", confirm=True
    )
    assert existing.ready
    news_ids.append(existing.news_id)

    with pytest.raises(PermissionDeniedError):
        await denied_client.update_news(news_id=existing.news_id, title="denied update", confirm=True)

    with pytest.raises(PermissionDeniedError):
        await denied_client.delete_news(news_id=existing.news_id, confirm=True)
