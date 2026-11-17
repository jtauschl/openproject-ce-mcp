"""Job Status Domain API port.

A single get-only method, no list/create/update/delete counterpart -- job
statuses are ephemeral background-job progress records (e.g. surfaced by
`copy_project`'s redirect-follow), not a resource with its own CRUD
lifecycle. No `summary`/`detail` split either: there is no list endpoint
whose rows would need a cheaper truncated shape to diverge from, so the
Record carries a single `JobStatusDetail` directly (matching the Query
Metadata bundle's five Records, each wrapping one Summary with no
`to_detail`).

`project_link` carries the RAW, unfiltered `_links` dict entry the Service's
allowlist check needs -- not just an extracted href/id, mirroring
`ViewRecord.project_link` and `SprintRecord.project_link`. This is the raw
*scoping* link (`payload._links.project`, the copy target of a finished
`copy_project` job), which is the link `summary.project`/`summary.project_id`
(the *display* fields of the response body) are read from. Typed `Any`, not `dict | None`: link
classification (missing vs. malformed vs. legitimately empty) is
`scope.classify_project_link`'s responsibility, so the adapter must pass the
raw value through unmodified.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ...models import JobStatusDetail


@dataclass(frozen=True)
class JobStatusRecord:
    summary: JobStatusDetail
    project_link: Any


class JobStatusApi(Protocol):
    """Narrow, Job-Status-only Domain API port. JobStatusService depends on
    this Protocol, never on HttpxJobStatusApi concretely (enforced by the
    architecture-boundary test).

    Read-only -- OpenProject's API exposes no create/update/delete for job
    statuses (they are server-managed background-job progress records).
    """

    async def get(self, job_status_id: str) -> JobStatusRecord: ...
