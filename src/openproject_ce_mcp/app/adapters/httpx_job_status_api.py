"""HTTP-backed JobStatusApi adapter.

No `httpx` import (depends on the `Transport` Protocol only). `trim_text`/
`id_from_href`/`link_title`/`web_url` are shared via `app/adapters/_text.py`.

`project_link` on the Record deliberately uses the SAME `project-or-
sourceProject` fallback as `normalize_job_status`'s own `project`/
`project_id` fields (`links.get("project") or links.get("sourceProject")`).
A job-status payload scoped only via `sourceProject` (e.g. `copy_project`'s
response, referencing the source project of a copy operation) must still be
subject to `OPENPROJECT_READ_PROJECTS`, so the scoping link the Service
checks uses the identical fallback as the display fields.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ...models import JobStatusDetail
from ..ports.job_status_api import JobStatusRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import id_from_href as _id_from_href
from ._text import link_title as _link_title
from ._text import reject_path_traversal_segments as _reject_path_traversal_segments
from ._text import slug_from_href as _slug_from_href
from ._text import trim_text as _trim_text

# Used for the `message` field (value 1_200). Kept local rather than
# promoted to _text.py -- every other adapter needing this constant
# (Documents, News, Project, Version, Extended Metadata) keeps its own copy
# too, per this project's "don't unify what isn't a shared *function*"
# convention for simple numeric constants.
FORMATTABLE_LIMIT = 1_200


def _job_status_inner_links(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a job status response's real resource links.

    OpenProject's JobStatusRepresenter only puts a self link at the
    top-level `_links` -- any project/sourceProject/createdProject link a
    specific job (e.g. copy_project) exposes lives one level down, inside
    the job-specific `payload` object's own `_links` (verified live against
    17.4: top-level `_links` is `{"self": ...}` only). Falls back to the
    top-level links for robustness in case some other job type's payload
    is shaped differently or absent.
    """
    inner = payload.get("payload")
    if isinstance(inner, dict):
        inner_links = inner.get("_links")
        if isinstance(inner_links, dict) and inner_links:
            return inner_links
    links = payload.get("_links", {})
    return links if isinstance(links, dict) else {}


def normalize_job_status(payload: dict[str, Any]) -> JobStatusDetail:
    """Pure HAL->model translation (ADR: 'lives in the Domain API adapter').

    Excludes hidden-field masking -- that is a Service decision applied
    after this returns.

    No `url` field: a client-constructed web page path
    (`{base_url}/job_statuses/{job_id}`) is not a server-supplied href, so it
    is not built here, per the "no constructed output URLs" rule.

    No `percentage_complete`/`created_at`/`updated_at` fields either:
    `JobStatusRepresenter` (verified against op-sources 17.7) renders only
    `job_id`/`status`/`message`/`payload`/`_type` -- there is no progress
    concept or timestamp property anywhere in the job_status module. A prior
    version of this function read `percentageDone`/`progress`/`createdAt`/
    `updatedAt`, none of which the API ever sends -- all three were always
    None.
    """
    top_level_links = payload.get("_links", {})
    links = _job_status_inner_links(payload)
    project_link = links.get("project") or links.get("sourceProject")
    resource_link = links.get("createdProject") or links.get("createdResource") or links.get("result")
    # Job status ids are UUID strings (payload["jobId"]) on every supported
    # version -- there is no top-level "id" field.
    job_id = _trim_text(payload.get("jobId") or payload.get("id"), limit=SUBJECT_LIMIT) or _slug_from_href(
        top_level_links.get("self", {}).get("href")
    )
    return JobStatusDetail(
        id=job_id,
        type=_trim_text(payload.get("_type"), limit=SUBJECT_LIMIT),
        status=_trim_text(
            payload.get("status") or payload.get("jobStatus") or payload.get("state"), limit=SUBJECT_LIMIT
        ),
        message=_trim_text(payload.get("message") or payload.get("error"), limit=FORMATTABLE_LIMIT),
        project_id=_id_from_href(project_link.get("href")) if isinstance(project_link, dict) else None,
        project=_link_title(project_link),
        created_resource_type=_trim_text(resource_link.get("type"), limit=SUBJECT_LIMIT)
        if isinstance(resource_link, dict)
        else None,
        created_resource_id=_id_from_href(resource_link.get("href")) if isinstance(resource_link, dict) else None,
        created_resource_name=_link_title(resource_link),
    )


class HttpxJobStatusApi:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    async def get(self, job_status_id: str) -> JobStatusRecord:
        safe_id = _reject_path_traversal_segments(job_status_id, field_name="job_status_id")
        payload = await self._transport.get_json(f"job_statuses/{quote(safe_id, safe='')}")
        links = _job_status_inner_links(payload)
        # Select by absence, not truthiness: a falsy-but-present "project"
        # value (e.g. {}, "", []) is a malformed link, distinct from a
        # genuinely absent one, and must reach the scope policy as such
        # rather than being replaced by "sourceProject".
        project_link = links.get("project")
        if project_link is None:
            project_link = links.get("sourceProject")
        created_project_link = links.get("createdProject")
        created_project_id = (
            _id_from_href(created_project_link.get("href")) if isinstance(created_project_link, dict) else None
        )
        return JobStatusRecord(
            summary=normalize_job_status(payload),
            # Passed through raw, unfiltered: classifying a link as missing,
            # malformed, or legitimately empty is the scope policy's job,
            # not the adapter's.
            project_link=project_link,
            created_project_id=created_project_id,
        )
