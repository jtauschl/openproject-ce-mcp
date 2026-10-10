from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import PermissionDeniedError
from openproject_ce_mcp.app.ports.job_status_api import JobStatusRecord
from openproject_ce_mcp.app.services.job_status_service import JobStatusService
from openproject_ce_mcp.models import JobStatusDetail
from openproject_ce_mcp.presentation import _to_payload


def _detail(*, job_status_id: int = 77, project: str | None = "Demo", project_id: int | None = 6) -> JobStatusDetail:
    return JobStatusDetail(
        id=job_status_id,
        type="JobStatus",
        status="in_progress",
        message="Copy running",
        project_id=project_id,
        project=project,
        created_resource_type=None,
        created_resource_id=None,
        created_resource_name=None,
    )


class _FakeJobStatusApi:
    def __init__(self, record: JobStatusRecord | None = None) -> None:
        self._record = record or JobStatusRecord(
            summary=_detail(), project_link={"href": "/api/v3/projects/6", "title": "Demo"}
        )
        self.get_calls: list[int] = []

    async def get(self, job_status_id: int) -> JobStatusRecord:
        self.get_calls.append(job_status_id)
        return self._record


def _service(
    api: _FakeJobStatusApi | None = None,
    *,
    settings=None,
    project_id_to_identifier=None,
) -> JobStatusService:
    api = api or _FakeJobStatusApi()
    return JobStatusService(
        api=api,
        settings=settings or make_settings(),
        project_id_to_identifier=project_id_to_identifier if project_id_to_identifier is not None else {6: "demo"},
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
    api = _FakeJobStatusApi(JobStatusRecord(summary=_detail(project=None, project_id=None), project_link=None))
    service = _service(api)

    job = await service.get(77)

    assert job.id == 77


@pytest.mark.asyncio
async def test_get_denies_when_project_link_is_none_and_scope_is_restrictive() -> None:
    """Matches scope.ensure_project_link_allowed's documented behavior for a
    nullable link (see ViewService): under a restrictive read_projects, a job
    status with no project link at all is denied, not silently allowed."""
    api = _FakeJobStatusApi(JobStatusRecord(summary=_detail(project=None, project_id=None), project_link=None))
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


@pytest.mark.parametrize("read_projects", [("*",), ("demo",)])
@pytest.mark.asyncio
async def test_get_allows_the_canonical_project_link_of_a_copy_job(read_projects) -> None:
    settings = dataclasses.replace(make_settings(), read_projects=read_projects)

    result = await _service(settings=settings).get(77)

    assert result.project_id == 6


@pytest.mark.parametrize(
    "href", ["https://evil.example.com/api/v3/projects/6", "/api/v3/users/6", "/api/v3/projects/6/copy"]
)
@pytest.mark.parametrize("read_projects", [("*",), ("demo",), ("6",)])
@pytest.mark.asyncio
async def test_get_denies_a_job_whose_project_link_is_no_project_link_of_this_instance(
    href: str, read_projects
) -> None:
    api = _FakeJobStatusApi(JobStatusRecord(summary=_detail(), project_link={"href": href, "title": "Demo"}))
    settings = dataclasses.replace(make_settings(), read_projects=read_projects)

    with pytest.raises(PermissionDeniedError):
        await _service(api, settings=settings).get(77)
