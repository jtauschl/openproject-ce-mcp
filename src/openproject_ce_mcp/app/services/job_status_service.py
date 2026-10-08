"""Application Service for the Job Status domain.

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

A project created via `copy_project` becomes known to the allowlist when the
completed job's response, which links the new project, passes through the
learning transport (see services.project_directory_service).
"""

from __future__ import annotations

from collections.abc import Mapping

from ...config import Settings
from ...models import JobStatusDetail
from ..policies import access, hidden_fields
from ..policies import scope as scope_policy
from ..ports.job_status_api import JobStatusApi


class JobStatusService:
    def __init__(
        self,
        *,
        api: JobStatusApi,
        settings: Settings,
        project_id_to_identifier: Mapping[int, str],
    ) -> None:
        self._api = api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier

    async def get(self, job_status_id: str) -> JobStatusDetail:
        access.ensure_read_enabled("project", settings=self._settings)
        record = await self._api.get(job_status_id)
        scope_policy.ensure_project_link_allowed_if_present(
            record.project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        return hidden_fields.apply_hidden_fields("job_status", record.summary, settings=self._settings)
