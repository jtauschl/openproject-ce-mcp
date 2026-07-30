from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import NotFoundError, PermissionDeniedError
from openproject_ce_mcp.app.ports.job_status_api import JobStatusRecord
from openproject_ce_mcp.app.ports.project_api import ProjectRecord
from openproject_ce_mcp.app.services.job_status_service import JobStatusService
from openproject_ce_mcp.models import JobStatusDetail, ProjectSummary
from openproject_ce_mcp.tools import _to_payload


def _detail(*, job_status_id: int = 77, project: str | None = "Demo", project_id: int | None = 6) -> JobStatusDetail:
    return JobStatusDetail(
        id=job_status_id,
        type="JobStatus",
        status="in_progress",
        message="Copy running",
        created_at="2026-03-20T10:00:00Z",
        updated_at="2026-03-20T10:05:00Z",
        percentage_complete=40,
        project_id=project_id,
        project=project,
        created_resource_type=None,
        created_resource_id=None,
        created_resource_name=None,
        links=["self", "project"],
        url="https://op.example.com/api/v3/job_statuses/77",
    )


class _FakeJobStatusApi:
    def __init__(self, record: JobStatusRecord | None = None) -> None:
        self._record = record or JobStatusRecord(
            summary=_detail(), project_link={"href": "/api/v3/projects/6", "title": "Demo"}, created_project_id=None
        )
        self.get_calls: list[int] = []

    async def get(self, job_status_id: int) -> JobStatusRecord:
        self.get_calls.append(job_status_id)
        return self._record


class _FakeProjectApi:
    def __init__(self, records: dict[str, ProjectRecord] | None = None, *, raises: Exception | None = None) -> None:
        self._records = records or {}
        self._raises = raises
        self.get_calls: list[str] = []

    async def get(self, project_ref: str, *, text_limit: int | None = None) -> ProjectRecord:
        self.get_calls.append(project_ref)
        if self._raises is not None:
            raise self._raises
        return self._records[project_ref]


def _project_record(*, project_id: int, identifier: str) -> ProjectRecord:
    summary = ProjectSummary(
        id=project_id, name=identifier.title(), identifier=identifier, active=True, description=None, url=""
    )
    return ProjectRecord(summary=summary, to_detail=lambda: None, payload={})  # type: ignore[arg-type]


def _service(
    api: _FakeJobStatusApi | None = None,
    *,
    settings=None,
    project_id_to_identifier=None,
    project_api: _FakeProjectApi | None = None,
) -> JobStatusService:
    api = api or _FakeJobStatusApi()
    return JobStatusService(
        api=api,
        settings=settings or make_settings(),
        project_id_to_identifier=project_id_to_identifier if project_id_to_identifier is not None else {6: "demo"},
        project_api=project_api or _FakeProjectApi(),
    )


@pytest.mark.asyncio
async def test_get_returns_summary() -> None:
    service = _service()

    job = await service.get(77)

    assert job.id == 77
    assert job.status == "in_progress"


@pytest.mark.asyncio
async def test_get_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_project_read=False)
    service = _service(settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get(77)


@pytest.mark.asyncio
async def test_get_denies_when_project_link_not_allowlisted() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other-project",))
    service = _service(settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get(77)


@pytest.mark.asyncio
async def test_get_allows_when_project_link_is_none_and_scope_is_wide_open() -> None:
    api = _FakeJobStatusApi(
        JobStatusRecord(summary=_detail(project=None, project_id=None), project_link=None, created_project_id=None)
    )
    service = _service(api)

    job = await service.get(77)

    assert job.id == 77


@pytest.mark.asyncio
async def test_get_denies_when_project_link_is_none_and_scope_is_restrictive() -> None:
    """Matches scope.ensure_project_link_allowed's documented behavior for a
    nullable link (see ViewService): under a restrictive read_projects, a job
    status with no project link at all is denied, not silently allowed."""
    api = _FakeJobStatusApi(
        JobStatusRecord(summary=_detail(project=None, project_id=None), project_link=None, created_project_id=None)
    )
    settings = dataclasses.replace(make_settings(), read_projects=("demo",))
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get(77)


@pytest.mark.asyncio
async def test_get_denies_when_only_source_project_link_present_and_not_allowlisted() -> None:
    """A job-status payload scoped exclusively via sourceProject (as in
    copy_project's response) must still be subject to
    OPENPROJECT_READ_PROJECTS. The Adapter populates JobStatusRecord.project_link
    via the same project-or-sourceProject fallback normalize_job_status uses
    for display fields, so this must be denied when "source-project" isn't
    allowlisted."""
    api = _FakeJobStatusApi(
        JobStatusRecord(
            summary=_detail(project="Source Project", project_id=9),
            project_link={"href": "/api/v3/projects/9", "title": "Source Project"},
            created_project_id=None,
        )
    )
    settings = dataclasses.replace(make_settings(), read_projects=("other-project",))
    service = _service(api, settings=settings, project_id_to_identifier={9: "source-project"})

    with pytest.raises(PermissionDeniedError):
        await service.get(77)


@pytest.mark.asyncio
async def test_get_allows_when_source_project_link_is_allowlisted() -> None:
    """Positive counterpart: once sourceProject's project IS allowlisted, the
    fallback-scoped job status is correctly allowed through."""
    api = _FakeJobStatusApi(
        JobStatusRecord(
            summary=_detail(project="Source Project", project_id=9),
            project_link={"href": "/api/v3/projects/9", "title": "Source Project"},
            created_project_id=None,
        )
    )
    settings = dataclasses.replace(make_settings(), read_projects=("source-project",))
    service = _service(api, settings=settings, project_id_to_identifier={9: "source-project"})

    job = await service.get(77)

    assert job.project == "Source Project"


@pytest.mark.asyncio
async def test_get_applies_hidden_field_masking() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"job_status": ("message",)})
    service = _service(settings=settings)

    job = await service.get(77)

    assert job._hidden_keys == frozenset({"message"})
    serialized = _to_payload(job)
    assert "message" not in serialized


@pytest.mark.asyncio
async def test_job_status_hidden_by_job_status_scope_not_view_scope() -> None:
    """Regression test for the entity="job_status" vs a same-named-neighbor
    hide-field bug class: masking must be keyed to "job_status", not
    silently reuse a differently-named neighbor's configured patterns."""
    settings = dataclasses.replace(make_settings(), hidden_fields={"view": ("message",)})
    service = _service(settings=settings)

    job = await service.get(77)

    assert not hasattr(job, "_hidden_keys")


@pytest.mark.asyncio
async def test_get_passes_job_status_id_through_to_api() -> None:
    api = _FakeJobStatusApi()
    service = _service(api)

    await service.get(123)

    assert api.get_calls == [123]


@pytest.mark.asyncio
async def test_get_remembers_copied_projects_real_identifier_in_the_shared_cache() -> None:
    """Regression test: a project created via copy_project was
    invisible to every link-shaped allowlist check until the process
    restarted, because project_id_to_identifier was never written through on
    the async copy-job-completion path (unlike create_project/update_project,
    which already handled this). A completed copy job's `_links.createdProject`
    is the only place the new project's numeric id becomes known; this
    resolves it to its REAL identifier (not just the job status response's
    own display title) and writes it through.

    Uses `created_project_id` (the presence of the `createdProject` link
    key), NOT `summary.created_resource_type` -- a Codex review caught that
    OpenProject's real `createdProject` payload shape carries no `type`
    field (only `href`/`title`), so a `created_resource_type == "Project"`
    check silently never fires. See `job_status_api.py`'s
    `created_project_id` docstring."""
    record = JobStatusRecord(summary=_detail(), project_link=None, created_project_id=99)
    api = _FakeJobStatusApi(record)
    project_id_to_identifier: dict[int, str] = {}
    project_api = _FakeProjectApi({"99": _project_record(project_id=99, identifier="demo-copy")})
    service = _service(api, project_id_to_identifier=project_id_to_identifier, project_api=project_api)

    await service.get(77)

    assert project_id_to_identifier[99] == "demo-copy"
    assert project_api.get_calls == ["99"]


@pytest.mark.asyncio
async def test_get_does_not_resolve_project_when_created_project_id_is_none() -> None:
    """A job whose createdProject link is absent (not a copy job, or the
    copy job hasn't completed yet) must not trigger the extra GET at all."""
    record = JobStatusRecord(summary=_detail(), project_link=None, created_project_id=None)
    api = _FakeJobStatusApi(record)
    project_api = _FakeProjectApi()
    service = _service(api, project_api=project_api)

    await service.get(77)

    assert project_api.get_calls == []


@pytest.mark.asyncio
async def test_get_tolerates_the_copied_project_being_unresolvable() -> None:
    """A race (the copied project was deleted, or scope tightened) right
    after the copy completed must not fail the job-status read itself --
    the caller is asking about the JOB, not the project."""
    record = JobStatusRecord(summary=_detail(), project_link=None, created_project_id=99)
    api = _FakeJobStatusApi(record)
    project_id_to_identifier: dict[int, str] = {}
    project_api = _FakeProjectApi(raises=NotFoundError("gone"))
    service = _service(api, project_id_to_identifier=project_id_to_identifier, project_api=project_api)

    job = await service.get(77)

    assert job.id == 77
    assert project_id_to_identifier == {}
