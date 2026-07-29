from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import InvalidInputError, PermissionDeniedError
from openproject_ce_mcp.app.ports.document_api import DocumentRecord
from openproject_ce_mcp.app.services.document_service import DocumentService
from openproject_ce_mcp.models import DocumentDetail, DocumentSummary

BASE_URL = "https://op.example.com"


def _summary(
    document_id: int = 1,
    *,
    project_id: int = 6,
    project: str = "Demo Project",
    title: str = "Architecture",
    description: str | None = "Short description",
) -> DocumentSummary:
    return DocumentSummary(
        id=document_id,
        title=title,
        project_id=project_id,
        project=project,
        description=description,
        created_at="2026-01-01T00:00:00Z",
        attachment_count=0,
        can_update=True,
        url=f"{BASE_URL}/documents/{document_id}",
    )


def _detail(**kwargs: object) -> DocumentDetail:
    summary = _summary(**kwargs)  # type: ignore[arg-type]
    return DocumentDetail(
        id=summary.id,
        title=summary.title,
        project_id=summary.project_id,
        project=summary.project,
        description=summary.description,
        created_at=summary.created_at,
        attachment_count=summary.attachment_count,
        attachments_url=None,
        can_update=summary.can_update,
        url=summary.url,
    )


def _record(**kwargs: object) -> DocumentRecord:
    summary = _summary(**kwargs)  # type: ignore[arg-type]
    return DocumentRecord(
        summary=summary,
        to_detail=lambda: _detail(**kwargs),  # type: ignore[arg-type]
        project_link={"href": f"/api/v3/projects/{summary.project_id}"},
    )


class _FakeDocumentApi:
    def __init__(self, records: list[DocumentRecord] | None = None) -> None:
        self._records = {r.summary.id: r for r in (records or [_record()])}
        self.list_all_calls: list[int] = []
        self.get_calls: list[int] = []
        self.commit_update_calls: list[tuple[int, dict]] = []
        self.commit_result_project: str = "Demo Project"

    async def list_all(self, *, offset: int, page_size: int) -> tuple[list[DocumentRecord], int]:
        self.list_all_calls.append(page_size)
        records = list(self._records.values())
        return records, len(records)

    async def get(self, document_id: int) -> DocumentRecord:
        self.get_calls.append(document_id)
        if document_id not in self._records:
            raise AssertionError(f"no fake record for document_id {document_id}")
        return self._records[document_id]

    async def commit_update(self, document_id: int, payload: dict) -> DocumentDetail:
        self.commit_update_calls.append((document_id, payload))
        return _detail(document_id=document_id, project=self.commit_result_project)


async def _resolve_project_ref(project_ref: str, *, write: bool = False, context=None) -> dict:
    return {"id": 6, "identifier": project_ref, "name": "Demo Project", "_links": {}}


def _service(
    api: _FakeDocumentApi | None = None, *, settings=None, resolve_project_ref=_resolve_project_ref
) -> DocumentService:
    api = api or _FakeDocumentApi()
    return DocumentService(
        api=api,
        settings=settings or make_settings(),
        project_id_to_identifier={},
        resolve_project_ref=resolve_project_ref,
    )


@pytest.mark.asyncio
async def test_list_returns_stamped_summaries() -> None:
    api = _FakeDocumentApi()
    service = _service(api)

    result = await service.list()

    assert result.count == 1
    assert result.results[0].id == 1
    assert len(api.list_all_calls) == 1


@pytest.mark.asyncio
async def test_list_filters_by_project_candidate() -> None:
    api = _FakeDocumentApi(
        records=[
            _record(document_id=1, project_id=6, project="Demo Project"),
            _record(document_id=2, project_id=7, project="Other Project"),
        ]
    )
    service = _service(api)

    result = await service.list(project="demo")

    assert [item.id for item in result.results] == [1]


@pytest.mark.asyncio
async def test_list_passes_write_false_to_resolve_project_ref() -> None:
    """list()'s project filter resolves via resolve_project_filter_candidates
    (project_scoped_list.py), which forwards straight to resolve_project_ref
    -- must ask for a READ-checked (write=False) resolution. Found missing
    during the Views domain's step-6 self-audit; ViewService.list() has the
    identical gap (same shared helper), fixed alongside this one.
    """
    calls: list[bool] = []

    async def resolve_project_ref_tracking_write(project_ref: str, *, write: bool = False, context=None) -> dict:
        calls.append(write)
        return await _resolve_project_ref(project_ref, write=write, context=context)

    api = _FakeDocumentApi()
    service = _service(api, resolve_project_ref=resolve_project_ref_tracking_write)

    await service.list(project="demo")

    assert calls == [False]


@pytest.mark.asyncio
async def test_list_filters_by_search_term_in_title_only() -> None:
    """Documents' post_filter (client.py's pre-migration list_documents) only
    ever searches `item.title`, unlike News which also matches `.summary` --
    DocumentSummary has no separate `summary` field at all. Verified against
    the current source rather than copied from News' equivalent test.
    """
    api = _FakeDocumentApi(
        records=[_record(document_id=1, title="Release notes"), _record(document_id=2, title="Unrelated")]
    )
    service = _service(api)

    result = await service.list(search="release")

    assert [item.id for item in result.results] == [1]


@pytest.mark.asyncio
async def test_list_excludes_records_outside_read_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    api = _FakeDocumentApi()
    service = _service(api, settings=settings)

    result = await service.list()

    assert result.results == []


@pytest.mark.asyncio
async def test_get_applies_hidden_field_masking() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"document": ("description",)})
    api = _FakeDocumentApi()
    service = _service(api, settings=settings)

    result = await service.get(1)

    assert getattr(result, "_hidden_keys", frozenset()) == {"description"}
    assert api.get_calls == [1]


@pytest.mark.asyncio
async def test_get_description_hidden_by_document_scope_not_project_scope() -> None:
    """Regression test for the entity="document" vs "project" hide-field bug
    (same bug class as the OPM-266 News hotfix, commit 9bc9a4a). Re-anchored
    here at the Service layer -- the pre-migration version of this test lived
    in tests/unit/test_text_and_shape_utils.py and called
    client.normalize_document/normalize_document_detail, which no longer
    exist after the migration.
    """
    settings_project_hidden = dataclasses.replace(make_settings(), hide_project_fields=("description",))
    service_project_hidden = _service(settings=settings_project_hidden)
    result_project_hidden = await service_project_hidden.get(1)
    assert getattr(result_project_hidden, "_hidden_keys", frozenset()) == frozenset()

    settings_document_hidden = dataclasses.replace(make_settings(), hidden_fields={"document": ("description",)})
    service_document_hidden = _service(settings=settings_document_hidden)
    result_document_hidden = await service_document_hidden.get(1)
    assert getattr(result_document_hidden, "_hidden_keys", frozenset()) == {"description"}


@pytest.mark.asyncio
async def test_get_checks_project_read_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    api = _FakeDocumentApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await service.get(1)


@pytest.mark.asyncio
async def test_get_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_project_read=False)
    api = _FakeDocumentApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get(1)

    assert api.get_calls == []


@pytest.mark.asyncio
async def test_update_returns_preview_without_committing_when_not_confirmed() -> None:
    api = _FakeDocumentApi()
    service = _service(api)

    result = await service.update(document_id=1, title="Updated", confirm=False)

    assert result.requires_confirmation is True
    assert result.confirmed is False
    assert result.result is None
    assert api.commit_update_calls == []


@pytest.mark.asyncio
async def test_update_commits_and_stamps_hidden_fields_when_confirmed() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"document": ("description",)})
    api = _FakeDocumentApi()
    service = _service(api, settings=settings)

    result = await service.update(document_id=1, title="Updated", confirm=True)

    assert result.confirmed is True
    assert api.commit_update_calls == [(1, {"title": "Updated"})]
    assert result.result is not None
    assert getattr(result.result, "_hidden_keys", frozenset()) == {"description"}


@pytest.mark.asyncio
async def test_update_checks_project_write_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("other",))
    api = _FakeDocumentApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await service.update(document_id=1, title="Updated", confirm=False)

    assert api.commit_update_calls == []


@pytest.mark.asyncio
async def test_update_rejects_when_hidden_field_is_being_written() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"document": ("title",)})
    api = _FakeDocumentApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.update(document_id=1, title="Updated", confirm=True)

    assert api.commit_update_calls == []


@pytest.mark.asyncio
async def test_update_does_not_call_resolve_project_ref() -> None:
    """update() takes no `project` parameter at all -- the project scope is
    derived entirely from the ALREADY-FETCHED document's own `_links.project`
    (checked via scope_policy.ensure_project_write_link_allowed directly),
    unlike News' create()/update() which resolve a `project` ref to build/
    validate the payload's `_links.project`. Documents has no such seam to
    test for a write=True flag -- asserting resolve_project_ref is never
    called IS the correct coverage here, not an oversight relative to News'
    test_create_passes_write_true_to_resolve_project_ref.
    """
    calls: list[str] = []

    async def resolve_project_ref_tracking_calls(project_ref: str, *, write: bool = False, context=None) -> dict:
        calls.append(project_ref)
        return await _resolve_project_ref(project_ref, write=write, context=context)

    api = _FakeDocumentApi()
    service = _service(api, resolve_project_ref=resolve_project_ref_tracking_calls)

    await service.update(document_id=1, title="Updated", confirm=True)

    assert calls == []
