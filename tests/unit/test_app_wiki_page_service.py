from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import PermissionDeniedError
from openproject_ce_mcp.app.ports.wiki_page_api import WikiPageRecord
from openproject_ce_mcp.app.services.wiki_page_service import WikiPageService
from openproject_ce_mcp.models import WikiPageDetail

BASE_URL = "https://op.example.com"


def _detail(wiki_page_id: int = 20, *, project_id: int = 6, project: str = "Demo Project") -> WikiPageDetail:
    return WikiPageDetail(
        id=wiki_page_id,
        title="Wiki Page",
        project_id=project_id,
        project=project,
        content="<user-content>Wiki page content</user-content>",
        attachments_url=None,
        url=f"{BASE_URL}/wiki_pages/{wiki_page_id}",
    )


def _record(wiki_page_id: int = 20, *, project_id: int = 6, project: str = "Demo Project") -> WikiPageRecord:
    return WikiPageRecord(
        detail=_detail(wiki_page_id, project_id=project_id, project=project),
        project_link={"href": f"/api/v3/projects/{project_id}", "title": project},
    )


class _FakeWikiPageApi:
    def __init__(self, records: dict[int, WikiPageRecord] | None = None) -> None:
        self._records = records or {20: _record()}
        self.get_calls: list[int] = []

    async def get(self, wiki_page_id: int) -> WikiPageRecord:
        self.get_calls.append(wiki_page_id)
        if wiki_page_id not in self._records:
            raise AssertionError(f"no fake record for wiki_page_id {wiki_page_id}")
        return self._records[wiki_page_id]


def _service(api: _FakeWikiPageApi | None = None, *, settings=None) -> WikiPageService:
    api = api or _FakeWikiPageApi()
    return WikiPageService(
        api=api,
        settings=settings or make_settings(),
        project_id_to_identifier={},
    )


@pytest.mark.asyncio
async def test_get_returns_stamped_detail() -> None:
    api = _FakeWikiPageApi()
    service = _service(api)

    result = await service.get(20)

    assert result.id == 20
    assert api.get_calls == [20]


@pytest.mark.asyncio
async def test_get_applies_hidden_field_masking() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"wiki_page": ("content",)})
    api = _FakeWikiPageApi()
    service = _service(api, settings=settings)

    result = await service.get(20)

    assert getattr(result, "_hidden_keys", frozenset()) == {"content"}


@pytest.mark.asyncio
async def test_get_content_hidden_by_wiki_page_scope_not_project_scope() -> None:
    """Regression test for the entity="wiki_page" vs "project" hide-field bug
    (same bug class as the News hotfix). This is the single most
    important test in this file -- masking must key off the domain's own
    entity string, not a same-named neighbor.
    """
    settings_project_hidden = dataclasses.replace(make_settings(), hide_project_fields=("content",))
    service_project_hidden = _service(settings=settings_project_hidden)
    result_project_hidden = await service_project_hidden.get(20)
    assert getattr(result_project_hidden, "_hidden_keys", frozenset()) == frozenset()

    settings_wiki_page_hidden = dataclasses.replace(make_settings(), hidden_fields={"wiki_page": ("content",)})
    service_wiki_page_hidden = _service(settings=settings_wiki_page_hidden)
    result_wiki_page_hidden = await service_wiki_page_hidden.get(20)
    assert getattr(result_wiki_page_hidden, "_hidden_keys", frozenset()) == {"content"}


@pytest.mark.asyncio
async def test_get_checks_project_read_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    api = _FakeWikiPageApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await service.get(20)


@pytest.mark.asyncio
async def test_get_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_project_read=False)
    api = _FakeWikiPageApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get(20)

    assert api.get_calls == []
