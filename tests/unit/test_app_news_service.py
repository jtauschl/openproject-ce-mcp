from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import InvalidInputError, PermissionDeniedError
from openproject_ce_mcp.app.ports.news_api import NewsRecord
from openproject_ce_mcp.app.services.news_service import NewsService
from openproject_ce_mcp.models import NewsDetail, NewsSummary

BASE_URL = "https://op.example.com"


def _summary(
    news_id: int = 1,
    *,
    project_id: int = 6,
    project: str = "Demo Project",
    title: str = "New feature",
    description: str | None = "Short description",
) -> NewsSummary:
    return NewsSummary(
        id=news_id,
        title=title,
        summary="Short summary",
        description=description,
        project_id=project_id,
        project=project,
        author="Ada Lovelace",
        created_at="2026-01-01T00:00:00Z",
        can_update=True,
        can_delete=True,
        url=f"{BASE_URL}/news/{news_id}",
    )


def _detail(**kwargs: object) -> NewsDetail:
    summary = _summary(**kwargs)  # type: ignore[arg-type]
    return NewsDetail(**dataclasses.asdict(summary))


def _record(**kwargs: object) -> NewsRecord:
    summary = _summary(**kwargs)  # type: ignore[arg-type]
    return NewsRecord(
        summary=summary,
        to_detail=lambda: _detail(**kwargs),  # type: ignore[arg-type]
        project_link={"href": f"/api/v3/projects/{summary.project_id}"},
    )


class _FakeNewsApi:
    def __init__(self, records: list[NewsRecord] | None = None) -> None:
        self._records = {r.summary.id: r for r in (records or [_record()])}
        self.list_all_calls: list[int] = []
        self.get_calls: list[int] = []
        self.commit_create_calls: list[dict] = []
        self.commit_update_calls: list[tuple[int, dict]] = []
        self.delete_calls: list[int] = []
        self.commit_result_project: str = "Demo Project"

    async def list_all(self, *, page_size: int) -> list[NewsRecord]:
        self.list_all_calls.append(page_size)
        return list(self._records.values())

    async def get(self, news_id: int) -> NewsRecord:
        self.get_calls.append(news_id)
        if news_id not in self._records:
            raise AssertionError(f"no fake record for news_id {news_id}")
        return self._records[news_id]

    async def commit_create(self, payload: dict) -> NewsDetail:
        self.commit_create_calls.append(payload)
        return _detail(news_id=42, project=self.commit_result_project)

    async def commit_update(self, news_id: int, payload: dict) -> NewsDetail:
        self.commit_update_calls.append((news_id, payload))
        return _detail(news_id=news_id, project=self.commit_result_project)

    async def delete(self, news_id: int) -> None:
        self.delete_calls.append(news_id)


async def _resolve_project_ref(project_ref: str, *, write: bool = False, context=None) -> dict:
    return {"id": 6, "identifier": project_ref, "name": "Demo Project", "_links": {}}


def _service(
    api: _FakeNewsApi | None = None, *, settings=None, resolve_project_ref=_resolve_project_ref
) -> NewsService:
    api = api or _FakeNewsApi()
    return NewsService(
        api=api,
        settings=settings or make_settings(),
        project_id_to_identifier={},
        resolve_project_ref=resolve_project_ref,
    )


@pytest.mark.asyncio
async def test_list_returns_stamped_summaries() -> None:
    api = _FakeNewsApi()
    service = _service(api)

    result = await service.list()

    assert result.count == 1
    assert result.results[0].id == 1
    assert len(api.list_all_calls) == 1


@pytest.mark.asyncio
async def test_list_filters_by_project_candidate() -> None:
    api = _FakeNewsApi(
        records=[
            _record(news_id=1, project_id=6, project="Demo Project"),
            _record(news_id=2, project_id=7, project="Other Project"),
        ]
    )
    service = _service(api)

    result = await service.list(project="demo")

    assert [item.id for item in result.results] == [1]


@pytest.mark.asyncio
async def test_list_passes_write_false_to_resolve_project_ref() -> None:
    """list()'s project filter resolves via resolve_project_filter_candidates
    (project_scoped_list.py), which forwards straight to resolve_project_ref
    -- must ask for a READ-checked (write=False) resolution. Same shared
    helper/gap as ViewService.list()/DocumentService.list(), which each
    already have this test; NewsService (an earlier domain that originated
    this exact duplicated-then-extracted logic, per project_scoped_list.py's
    own module docstring) never got the equivalent test backfilled. Found
    during the Sprints migration's step-6 test-contract audit.
    """
    calls: list[bool] = []

    async def resolve_project_ref_tracking_write(project_ref: str, *, write: bool = False, context=None) -> dict:
        calls.append(write)
        return await _resolve_project_ref(project_ref, write=write, context=context)

    api = _FakeNewsApi()
    service = _service(api, resolve_project_ref=resolve_project_ref_tracking_write)

    await service.list(project="demo")

    assert calls == [False]


@pytest.mark.asyncio
async def test_list_filters_by_search_term_in_title_or_summary() -> None:
    api = _FakeNewsApi(records=[_record(news_id=1, title="Release notes"), _record(news_id=2, title="Unrelated")])
    service = _service(api)

    result = await service.list(search="release")

    assert [item.id for item in result.results] == [1]


@pytest.mark.asyncio
async def test_list_excludes_records_outside_read_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    api = _FakeNewsApi()
    service = _service(api, settings=settings)

    result = await service.list()

    assert result.results == []


@pytest.mark.asyncio
async def test_get_applies_hidden_field_masking() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"news": ("description",)})
    api = _FakeNewsApi()
    service = _service(api, settings=settings)

    result = await service.get(1)

    assert getattr(result, "_hidden_keys", frozenset()) == {"description"}
    assert api.get_calls == [1]


@pytest.mark.asyncio
async def test_get_description_hidden_by_news_scope_not_project_scope() -> None:
    """Regression test for the OPM-266 hotfix (commit 684edad): the OLD,
    buggy client.py normalize_news checked entity="project" instead of
    "news" for the description hide-check. That bug lived in the pre-
    migration flat client -- the new layered Service masks the ENTIRE
    description field via apply_hidden_fields("news", ...) regardless of
    which scope hid it, so this asserts the field only disappears under the
    news scope, never under a same-named project scope.
    """
    settings_project_hidden = dataclasses.replace(make_settings(), hide_project_fields=("description",))
    service_project_hidden = _service(settings=settings_project_hidden)
    result_project_hidden = await service_project_hidden.get(1)
    assert getattr(result_project_hidden, "_hidden_keys", frozenset()) == frozenset()

    settings_news_hidden = dataclasses.replace(make_settings(), hidden_fields={"news": ("description",)})
    service_news_hidden = _service(settings=settings_news_hidden)
    result_news_hidden = await service_news_hidden.get(1)
    assert getattr(result_news_hidden, "_hidden_keys", frozenset()) == {"description"}


@pytest.mark.asyncio
async def test_get_checks_project_read_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    api = _FakeNewsApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await service.get(1)


@pytest.mark.asyncio
async def test_get_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_project_read=False)
    api = _FakeNewsApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get(1)

    assert api.get_calls == []


@pytest.mark.asyncio
async def test_create_returns_preview_without_committing_or_calling_api() -> None:
    api = _FakeNewsApi()
    service = _service(api)

    result = await service.create(project="demo", title="New feature", confirm=False)

    assert result.requires_confirmation is True
    assert result.confirmed is False
    assert result.result is None
    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_commits_and_stamps_hidden_fields_when_confirmed() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"news": ("author",)})
    api = _FakeNewsApi()
    service = _service(api, settings=settings)

    result = await service.create(project="demo", title="New feature", confirm=True)

    assert result.confirmed is True
    assert len(api.commit_create_calls) == 1
    assert result.result is not None
    assert getattr(result.result, "_hidden_keys", frozenset()) == {"author"}


@pytest.mark.asyncio
async def test_create_rejects_when_hidden_field_is_being_written() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"news": ("title",)})
    api = _FakeNewsApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.create(project="demo", title="New feature", confirm=True)

    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_passes_write_true_to_resolve_project_ref() -> None:
    """create() must ask its injected resolve_project_ref for a WRITE-checked
    resolution (write=True), not a read-only one -- the actual write-
    allowlist enforcement for create() lives inside the real
    _get_project_payload/ProjectResolver.resolve_record (see
    project_resolver.py's `if write: ensure_project_write_allowed(...)`),
    not inside NewsService itself, so this only pins the contract at the
    seam; the enforcement itself is covered by test_project_resolution.py's
    "news-write_denied" policy-matrix case against the real client.
    """
    write_flags: list[bool] = []

    async def resolve_project_ref_tracking_write(project_ref: str, *, write: bool = False, context=None) -> dict:
        write_flags.append(write)
        return await _resolve_project_ref(project_ref, write=write, context=context)

    api = _FakeNewsApi()
    service = _service(api, resolve_project_ref=resolve_project_ref_tracking_write)

    await service.create(project="demo", title="New feature", confirm=True)

    assert write_flags == [True]


@pytest.mark.asyncio
async def test_update_commits_and_stamps_when_confirmed() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"news": ("author",)})
    api = _FakeNewsApi()
    service = _service(api, settings=settings)

    result = await service.update(news_id=1, title="Updated", confirm=True)

    assert result.confirmed is True
    assert api.commit_update_calls == [(1, {"title": "Updated"})]
    assert getattr(result.result, "_hidden_keys", frozenset()) == {"author"}


@pytest.mark.asyncio
async def test_update_checks_project_write_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("other",))
    api = _FakeNewsApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await service.update(news_id=1, title="Updated", confirm=False)


@pytest.mark.asyncio
async def test_delete_preview_carries_stamped_detail_not_none() -> None:
    """News differs from Memberships here: the ORIGINAL client.py delete_news
    passed preview_result=detail (not None) to _finalize_delete, so the
    preview branch's `result` must already carry the (masked) NewsDetail --
    unlike MembershipService.delete(), whose preview result is None.
    """
    api = _FakeNewsApi()
    service = _service(api)

    preview = await service.delete(news_id=1, confirm=False)

    assert preview.confirmed is False
    assert preview.requires_confirmation is True
    assert preview.result is not None
    assert preview.result.id == 1
    assert api.delete_calls == []


@pytest.mark.asyncio
async def test_delete_commits_and_stamps_result_when_confirmed() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"news": ("author",)})
    api = _FakeNewsApi()
    service = _service(api, settings=settings)

    committed = await service.delete(news_id=1, confirm=True)

    assert committed.confirmed is True
    assert api.delete_calls == [1]
    assert committed.result is not None
    assert getattr(committed.result, "_hidden_keys", frozenset()) == {"author"}


@pytest.mark.asyncio
async def test_delete_checks_project_write_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("other",))
    api = _FakeNewsApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await service.delete(news_id=1, confirm=False)
