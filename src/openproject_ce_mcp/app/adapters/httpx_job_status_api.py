"""HTTP-backed JobStatusApi adapter.

No `httpx` import (depends on the `Transport` Protocol only). `trim_text`/
`id_from_href`/`link_title`/`web_url` are shared via `app/adapters/_text.py`.

`project_link` on the Record is the raw `payload._links.project` the Service
checks against `OPENPROJECT_READ_PROJECTS`, the same link `normalize_job_status`
reads for its `project` and `project_id` fields. For `copy_project` that link
is the copy TARGET, and the job writes it only when the copy succeeded.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ...models import JobStatusDetail
from ..ports.job_status_api import JobStatusRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import delimit_user_content as _delimit_user_content
from ._text import id_from_href as _id_from_href
from ._text import link_title as _link_title
from ._text import reject_path_traversal_segments as _reject_path_traversal_segments
from ._text import trim_text as _trim_text

# Used for the `message` field (value 1_200). Kept local rather than
# promoted to _text.py -- every other adapter needing this constant
# (Documents, News, Project, Version, Extended Metadata) keeps its own copy
# too, per this project's "don't unify what isn't a shared *function*"
# convention for simple numeric constants.
FORMATTABLE_LIMIT = 1_200


def _payload_links(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the links of a job status' free-form `payload`.

    `JobStatusRepresenter` renders only a `self` link at the top level; the
    one writer of payload links is `copy_project_job.rb`, which puts the
    target project there when the copy succeeded. A job that is still
    queued or running, or that failed, has no payload links.
    """
    inner = payload.get("payload")
    if isinstance(inner, dict):
        inner_links = inner.get("_links")
        if isinstance(inner_links, dict):
            return inner_links
    return {}


def normalize_job_status(payload: dict[str, Any]) -> JobStatusDetail:
    """Pure HAL->model translation (ADR: 'lives in the Domain API adapter').

    Excludes hidden-field masking -- that is a Service decision applied
    after this returns.

    No `url` field: a client-constructed web page path
    (`{base_url}/job_statuses/{job_id}`) is not a server-supplied href, so it
    is not built here, per the "no constructed output URLs" rule.

    No `percentage_complete`/`created_at`/`updated_at` fields either:
    `JobStatusRepresenter` (verified against the OpenProject 17.7 source) renders only
    `job_id`/`status`/`message`/`payload`/`_type` -- there is no progress
    concept or timestamp property anywhere in the job_status module. A prior
    version of this function read `percentageDone`/`progress`/`createdAt`/
    `updatedAt`, none of which the API ever sends -- all three were always
    None.
    """
    project_link = _payload_links(payload).get("project")
    return JobStatusDetail(
        id=_trim_text(payload.get("jobId"), limit=SUBJECT_LIMIT),
        type=_trim_text(payload.get("_type"), limit=SUBJECT_LIMIT),
        status=_trim_text(payload.get("status"), limit=SUBJECT_LIMIT),
        message=_delimit_user_content(_trim_text(payload.get("message"), limit=FORMATTABLE_LIMIT)),
        project_id=_id_from_href(project_link.get("href")) if isinstance(project_link, dict) else None,
        project=_link_title(project_link),
    )


class HttpxJobStatusApi:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    async def get(self, job_status_id: str) -> JobStatusRecord:
        safe_id = _reject_path_traversal_segments(job_status_id, field_name="job_status_id")
        payload = await self._transport.get_json(f"job_statuses/{quote(safe_id, safe='')}")
        return JobStatusRecord(
            summary=normalize_job_status(payload),
            # Passed through raw, unfiltered: classifying a link as missing,
            # malformed, or legitimately empty is the scope policy's job,
            # not the adapter's.
            project_link=_payload_links(payload).get("project"),
        )
