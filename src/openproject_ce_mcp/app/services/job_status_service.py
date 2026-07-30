"""Application Service for the Job Status domain (20th migrated domain).

Depends on the JobStatusApi Protocol, never HttpxJobStatusApi concretely
(enforced by the architecture-boundary test). No dedicated policy file: like
Views, there is only ever one scoping concern to check (the `project`-or-
`sourceProject` link), and that link is NULLABLE (a job status need not
reference any project -- OpenProject's own JobStatusRepresenter has no
guaranteed project link at all, only a self link plus an arbitrary payload).
Uses `scope.ensure_project_link_allowed_if_present` (the OPTIONAL-project-
link contract): a missing link is a legitimate, common state here (most jobs
aren't project-copy jobs), allowed under a wide-open scope and denied under
a restrictive one, same rationale as `ViewService.get` -- while a
structurally malformed link is always rejected regardless of scope.

Read-only, single get method -- OpenProject exposes no create/update/delete
for job statuses. `access.ensure_read_enabled("project", ...)` is the gate --
job statuses share the "project" read scope, there is no dedicated
`OPENPROJECT_ENABLE_JOB_STATUS_*` flag.

The allowlist check here relies on the Adapter's `JobStatusRecord.project_link`
using the same `project-or-sourceProject` fallback that `normalize_job_status`
uses to populate the response's own `project`/`project_id` display fields --
a payload scoped only via `sourceProject` (e.g. `copy_project`'s response)
must still be subject to `OPENPROJECT_READ_PROJECTS`, so the allowlist check
stays consistent with what the response body reports.

A project created via `copy_project` is only known by numeric id once the
async copy job completes, which `copy_project` itself never observes (it
returns immediately after starting the job) -- until that id is written
through to the shared `project_id_to_identifier` cache, the new project
would be invisible to every link-shaped allowlist check. `get()` closes this
gap: when `record.created_project_id` is set (the job's
`_links.createdProject` key is present), it resolves the new project by id
via `ProjectApi.get()` (an extra GET, only on this one code path) and writes
its REAL identifier through to the shared cache -- not just the job status
response's own `created_resource_name` display title, which the allowlist
matcher (`scope.project_candidates`) already tries as a fallback and would
add no coverage beyond. Uses `created_project_id`, NOT
`summary.created_resource_type == "Project"`: OpenProject's real
`createdProject` payload shape carries no `type` field (only `href`/`title`),
so that check would never fire; see `job_status_api.py`'s
`created_project_id` docstring for the full explanation.
"""

from __future__ import annotations

from ...config import Settings
from ...models import JobStatusDetail
from ..errors import NotFoundError, PermissionDeniedError
from ..policies import access, hidden_fields
from ..policies import scope as scope_policy
from ..ports.job_status_api import JobStatusApi
from ..ports.project_api import ProjectApi


class JobStatusService:
    def __init__(
        self,
        *,
        api: JobStatusApi,
        settings: Settings,
        project_id_to_identifier: dict[int, str],
        project_api: ProjectApi,
    ) -> None:
        self._api = api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier
        self._project_api = project_api

    async def get(self, job_status_id: str) -> JobStatusDetail:
        access.ensure_read_enabled("project", settings=self._settings)
        record = await self._api.get(job_status_id)
        scope_policy.ensure_project_link_allowed_if_present(
            record.project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        if record.created_project_id is not None:
            await self._remember_copied_project_identifier(record.created_project_id)
        return hidden_fields.apply_hidden_fields("job_status", record.summary, settings=self._settings)

    async def _remember_copied_project_identifier(self, project_id: int) -> None:
        # Best-effort: a race (the project was deleted right after the copy
        # completed, or the caller's own scope no longer covers it) must not
        # fail the job-status read itself -- the caller is asking about the
        # JOB, not the project. Do NOT swallow other errors (e.g. a
        # transient 5xx) the same way -- see _work_package_project_allowed's
        # identical distinction elsewhere in this codebase.
        try:
            new_project = await self._project_api.get(str(project_id))
        except (NotFoundError, PermissionDeniedError):
            return
        identifier = new_project.summary.identifier
        if identifier:
            self._project_id_to_identifier[project_id] = identifier
