"""Job Status Domain API port (20th migrated domain, OPM-311).

A single get-only method, no list/create/update/delete counterpart -- job
statuses are ephemeral background-job progress records (e.g. surfaced by
`copy_project`'s 302-redirect-follow), not a resource with its own CRUD
lifecycle. No `summary`/`detail` split either: there is no list endpoint
whose rows would need a cheaper truncated shape to diverge from, so the
Record carries a single `JobStatusDetail` directly (matching the Query
Metadata bundle's five Records, each wrapping one Summary with no
`to_detail`).

`project_link` carries the RAW, unfiltered `_links` dict entry the Service's
allowlist check needs -- not just an extracted href/id, mirroring
`ViewRecord.project_link` and `SprintRecord.project_link`. This is the raw
*scoping* link (which of `_links["project"]`/`_links["sourceProject"]` was
actually used to resolve scope), which is a separate concern from
`summary.project`/`summary.project_id` (the *display* fields
`normalize_job_status` populates from the same `project-or-sourceProject`
fallback for the response body). Typed `Any`, not `dict | None` (OPM-359):
the adapter must NOT coerce a non-dict value to `None` before the Service's
`scope.classify_project_link` sees it -- doing so would make a genuinely
malformed link indistinguishable from a legitimately absent one.

`created_project_id` is a THIRD, narrower concern: whether the job's
`_links["createdProject"]` key specifically is present (a copy_project
job's completion signal), as opposed to the generic
`createdResource`/`result` fallback keys `summary.created_resource_type`/
`created_resource_id` are populated from. `summary.created_resource_type`
cannot be used for this -- OpenProject's real `createdProject` payload
shape carries only `href`/`title`, no `type` field (confirmed against
`test_projects.py`'s `createdProject` fixture), so `created_resource_type`
stays `None` even for a genuine completed project copy. Only the
*presence of the `createdProject` key itself* reliably signals "this job
created a project."
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ...models import JobStatusDetail


@dataclass(frozen=True)
class JobStatusRecord:
    summary: JobStatusDetail
    project_link: Any
    created_project_id: int | None


class JobStatusApi(Protocol):
    """Narrow, Job-Status-only Domain API port. JobStatusService depends on
    this Protocol, never on HttpxJobStatusApi concretely (enforced by the
    architecture-boundary test).

    Read-only -- OpenProject's API exposes no create/update/delete for job
    statuses (they are server-managed background-job progress records).
    """

    async def get(self, job_status_id: str) -> JobStatusRecord: ...
