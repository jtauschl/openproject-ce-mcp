from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import PermissionDeniedError
from openproject_ce_mcp.app.ports.post_api import PostRecord
from openproject_ce_mcp.app.services.post_service import PostService
from openproject_ce_mcp.models import PostDetail

BASE_URL = "https://op.example.com"


def _detail(post_id: int = 30, *, project_id: int = 6, project: str = "Demo Project") -> PostDetail:
    return PostDetail(
        id=post_id,
        subject="Welcome to the forum",
        project_id=project_id,
        project=project,
    )


def _record(post_id: int = 30, *, project_id: int = 6, project: str = "Demo Project") -> PostRecord:
    return PostRecord(
        detail=_detail(post_id, project_id=project_id, project=project),
        project_link={"href": f"/api/v3/projects/{project_id}", "title": project},
    )


class _FakePostApi:
    def __init__(self, records: dict[int, PostRecord] | None = None) -> None:
        self._records = records or {30: _record()}
        self.get_calls: list[int] = []

    async def get(self, post_id: int) -> PostRecord:
        self.get_calls.append(post_id)
        if post_id not in self._records:
            raise AssertionError(f"no fake record for post_id {post_id}")
        return self._records[post_id]


def _service(api: _FakePostApi | None = None, *, settings=None) -> PostService:
    api = api or _FakePostApi()
    return PostService(
        api=api,
        settings=settings or make_settings(),
        project_id_to_identifier={},
    )


@pytest.mark.asyncio
async def test_get_returns_stamped_detail() -> None:
    api = _FakePostApi()
    service = _service(api)

    result = await service.get(30)

    assert result.id == 30
    assert api.get_calls == [30]


@pytest.mark.asyncio
async def test_get_applies_hidden_field_masking() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"post": ("subject",)})
    api = _FakePostApi()
    service = _service(api, settings=settings)

    result = await service.get(30)

    assert getattr(result, "_hidden_keys", frozenset()) == {"subject"}


@pytest.mark.asyncio
async def test_get_subject_hidden_by_post_scope_not_project_scope() -> None:
    """Regression test for the entity="post" vs "project" hide-field bug
    (same bug class as the News hotfix and Wiki Pages' own copy of this
    test). Masking must key off the domain's own entity string, not a
    same-named neighbor."""
    settings_project_hidden = dataclasses.replace(make_settings(), hide_project_fields=("subject",))
    service_project_hidden = _service(settings=settings_project_hidden)
    result_project_hidden = await service_project_hidden.get(30)
    assert getattr(result_project_hidden, "_hidden_keys", frozenset()) == frozenset()

    settings_post_hidden = dataclasses.replace(make_settings(), hidden_fields={"post": ("subject",)})
    service_post_hidden = _service(settings=settings_post_hidden)
    result_post_hidden = await service_post_hidden.get(30)
    assert getattr(result_post_hidden, "_hidden_keys", frozenset()) == {"subject"}


@pytest.mark.asyncio
async def test_get_checks_project_read_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    api = _FakePostApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await service.get(30)


@pytest.mark.asyncio
async def test_get_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_project_read=False)
    api = _FakePostApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get(30)

    assert api.get_calls == []
