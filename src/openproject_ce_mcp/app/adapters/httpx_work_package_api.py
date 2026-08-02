"""HTTP-backed WorkPackageApi adapter -- covers the full domain.

Write-path methods (`validate_create`/`validate_update`/`parse_form`/
`commit_create`/`commit_update`/`delete`/`post_comment`) are thin HTTP
translations added alongside the READ slice below, once the write-path
migration landed -- straightforward `Transport.{post_json,patch_json,delete}`
calls, no domain logic (schema-option resolution, custom-field matching, the
auto-percentage/auto-remaining-time derivation) lives here; all of that is a
`WorkPackageService` concern (see `app/ports/work_package_api.py`'s module
docstring).

No `httpx` import (depends on the `Transport` Protocol only). Owns the pure
normalize_* HAL->model translation functions, matching the Projects/Versions
domains' convention: normalize_* live in the adapter, not the port, and are
NOT hidden-field-aware (masking is a Service concern, applied after these
return -- see `app/services/work_package_service.py`'s `_stamp`).

`list()` deliberately returns raw, unnormalized elements (`WorkPackagePage`)
rather than pre-built `WorkPackageRecord`s -- see `app/ports/work_package_api.py`'s
module docstring for why: allowlist filtering must happen BEFORE
normalization for this domain, unlike Projects. `to_record()` is exposed as a
separate Protocol method so the Service can normalize only the elements that
survive its own allowlist filter, then call it again for `get()`'s single
payload.

`_trim_text`/`_link_title`/`_id_from_href`/`_delimit_user_content`/
`_origin_from_url`/`_reject_path_traversal_segments`/`SUBJECT_LIMIT` are
shared via `app/adapters/_text.py`. `_normalize_text`/`_trim_text_with_meta`/
`_extract_formattable_text_with_meta` (+ `FORMATTABLE_LIMIT`) are local,
verbatim-copied from `httpx_project_api.py` -- per `_text.py`'s own module
docstring, these differ behaviorally across adapters (a genuinely different
extraction, not just a truncation-limit divergence) and are not unified.
`work_package_ref()` (path-safe reference encoding) is imported from
`app/ports/work_package_ref.py` rather than re-implemented here: adapters may
import from ports (see `tests/test_architecture_boundaries.py`'s layer rules),
and it is already the exact, path-traversal-safe encoding
`HttpxWorkPackageLookupApi`/`WorkPackageResolver` use today -- a third local
copy would be needless duplication where reuse is clean.
"""

from __future__ import annotations

import json
from typing import Any

from ...models import SortCriterion, WorkPackageDetail, WorkPackageSummary
from ..ports.work_package_api import WorkPackageFormResult, WorkPackagePage, WorkPackageRecord
from ..ports.work_package_ref import work_package_ref as _work_package_ref_encode
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import delimit_user_content as _delimit_user_content
from ._text import id_from_href as _id_from_href
from ._text import link_title as _link_title
from ._text import link_to_web_url as _shared_link_to_web_url
from ._text import normalize_form_validation_errors as _normalize_form_validation_errors
from ._text import origin_from_url as _origin_from_url
from ._text import trim_text as _trim_text
from ._text import web_url as _shared_web_url

FORMATTABLE_LIMIT = 1_200
WORK_PACKAGE_CHILDREN_LIMIT = 50
WORK_PACKAGE_ANCESTORS_LIMIT = 20


def _normalize_text(value: Any, *, preserve_newlines: bool) -> str:
    if not preserve_newlines:
        return " ".join(str(value).split())
    lines = str(value).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    normalized: list[str] = []
    blank_run = 0
    for line in lines:
        stripped = " ".join(line.split())
        if stripped:
            blank_run = 0
            normalized.append(stripped)
        else:
            blank_run += 1
            if blank_run <= 1:
                normalized.append("")
    while normalized and normalized[0] == "":
        normalized.pop(0)
    while normalized and normalized[-1] == "":
        normalized.pop()
    return "\n".join(normalized)


def _trim_text_with_meta(
    value: Any, *, limit: int | None, preserve_newlines: bool = False
) -> tuple[str | None, bool, int | None]:
    if value is None:
        return None, False, None
    text = _normalize_text(value, preserve_newlines=preserve_newlines)
    if not text:
        return None, False, None
    full_length = len(text)
    if limit is None or full_length <= limit:
        return text, False, full_length
    return text[: limit - 1].rstrip() + "…", True, full_length


def _extract_formattable_text_with_meta(
    value: Any, *, limit: int | None = FORMATTABLE_LIMIT, preserve_newlines: bool = False
) -> tuple[str | None, bool, int | None]:
    raw = value.get("raw") or value.get("html") if isinstance(value, dict) else value
    return _trim_text_with_meta(raw, limit=limit, preserve_newlines=preserve_newlines)


def _work_package_dates(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    """(start_date, due_date) for a work package, accounting for milestones.

    OpenProject's work_package_representer.rb (`date_property :date`, `getter:
    default_date_getter(:due_date)`, `skip_render: !milestone?`) omits
    `startDate`/`dueDate` entirely for milestone-type work packages and
    instead reports the single day under a separate `date` key, itself
    reading the underlying `due_date` value -- verified against
    lib/api/v3/work_packages/work_package_representer.rb. Without this, every
    milestone work package normalizes to start_date=None, due_date=None even
    when it has a real date set.
    """
    start_date = payload.get("startDate")
    due_date = payload.get("dueDate")
    if start_date is None and due_date is None and payload.get("date") is not None:
        milestone_date = payload["date"]
        return milestone_date, milestone_date
    return start_date, due_date


def normalize_work_package_summary(
    payload: dict[str, Any], *, base_url: str, text_limit: int | None
) -> WorkPackageSummary:
    """Pure HAL->model translation. Verbatim port of client.py's
    normalize_work_package_summary, minus the _apply_hidden_fields call and
    the hidden-field-aware text extraction -- hidden-field masking (including
    zeroing description_truncated/description_length/has_description when
    the description field itself is hidden) is a Service concern, applied
    after this returns (see WorkPackageService._stamp).

    ``text_limit`` is an explicit parameter here (client.py's original read
    `self.settings.text_limit` implicitly) since the adapter has no Settings
    access -- the Service passes `settings.text_limit` through, matching
    `normalize_project`'s equivalent parameter.
    """
    links = payload.get("_links", {})
    description, truncated, length = _extract_formattable_text_with_meta(payload.get("description"), limit=text_limit)
    start_date, due_date = _work_package_dates(payload)
    return WorkPackageSummary(
        id=int(payload["id"]),
        display_id=payload.get("displayId"),
        subject=_trim_text(payload.get("subject"), limit=SUBJECT_LIMIT) or f"Work package {payload['id']}",
        type=_link_title(links.get("type")),
        status=_link_title(links.get("status")),
        priority=_link_title(links.get("priority")),
        project_phase=_link_title(links.get("projectPhase")),
        assignee=_link_title(links.get("assignee")),
        responsible=_link_title(links.get("responsible")),
        project=_link_title(links.get("project")),
        version=_link_title(links.get("version")),
        sprint=_link_title(links.get("sprint")),
        start_date=start_date,
        due_date=due_date,
        description=_delimit_user_content(description),
        has_description=description is not None,
        url=_shared_web_url(f"work_packages/{payload['id']}", base_url=base_url),
        description_truncated=truncated,
        description_length=length,
        estimated_time=payload.get("estimatedTime"),
        derived_estimated_time=payload.get("derivedEstimatedTime"),
        spent_time=payload.get("spentTime"),
        remaining_time=payload.get("remainingTime"),
        derived_remaining_time=payload.get("derivedRemainingTime"),
        duration=payload.get("duration"),
        parent_id=_id_from_href(links.get("parent", {}).get("href")),
        # Hierarchy links carry displayId from 17.5 (semantic mode); absent on
        # older/classic instances (verified against the 17.2 representer,
        # which has no displayId on the parent link), where this stays None.
        parent_display_id=links.get("parent", {}).get("displayId"),
        created_at=payload.get("createdAt"),
        updated_at=payload.get("updatedAt"),
        author=_link_title(links.get("author")),
        category=_link_title(links.get("category")),
        schedule_manually=payload.get("scheduleManually"),
        ignore_non_working_days=payload.get("ignoreNonWorkingDays"),
        derived_start_date=payload.get("derivedStartDate"),
        derived_due_date=payload.get("derivedDueDate"),
        percentage_done=payload.get("percentageDone"),
        derived_percentage_done=payload.get("derivedPercentageDone"),
        readonly=payload.get("readonly"),
    )


def normalize_work_package_detail(
    payload: dict[str, Any],
    *,
    base_url: str,
    origin: str,
    text_limit: int | None = FORMATTABLE_LIMIT,
    summary: WorkPackageSummary | None = None,
) -> WorkPackageDetail:
    """Single-work-package read. ``text_limit=None`` (used by get()) returns the
    full description uncapped; the FORMATTABLE_LIMIT default keeps
    write-preview-style callers capped (once a write path exists). Verbatim
    port of client.py's normalize_work_package_detail, minus hidden-field
    masking (Service concern).

    `summary` lets a caller that already built a `WorkPackageSummary` for the
    same payload pass it in to avoid a second full normalization -- callers
    with only the raw payload omit it and get the summary computed here.
    `description` is still independently re-extracted regardless
    (`preserve_newlines=True`, a genuinely different extraction than the
    summary's, not just a different truncation limit).
    """
    if summary is None:
        summary = normalize_work_package_summary(payload, base_url=base_url, text_limit=text_limit)
    links = payload.get("_links", {})
    description, truncated, length = _extract_formattable_text_with_meta(
        payload.get("description"), limit=text_limit, preserve_newlines=True
    )

    children_raw = links.get("children", [])
    children = None
    children_truncated = False
    if children_raw:
        children = [
            {"href": c.get("href"), "title": c.get("title"), "display_id": c.get("displayId")}
            for c in children_raw[:WORK_PACKAGE_CHILDREN_LIMIT]
        ]
        children_truncated = len(children_raw) > WORK_PACKAGE_CHILDREN_LIMIT

    ancestors_raw = links.get("ancestors", [])
    ancestors = None
    ancestors_truncated = False
    if ancestors_raw:
        ancestors = [
            {"href": a.get("href"), "title": a.get("title"), "display_id": a.get("displayId")}
            for a in ancestors_raw[:WORK_PACKAGE_ANCESTORS_LIMIT]
        ]
        ancestors_truncated = len(ancestors_raw) > WORK_PACKAGE_ANCESTORS_LIMIT

    start_date, due_date = _work_package_dates(payload)
    return WorkPackageDetail(
        id=summary.id,
        display_id=summary.display_id,
        subject=summary.subject,
        type=summary.type,
        status=summary.status,
        priority=summary.priority,
        project_phase=summary.project_phase,
        assignee=summary.assignee,
        responsible=summary.responsible,
        project=summary.project,
        version=summary.version,
        sprint=summary.sprint,
        parent_id=summary.parent_id,
        parent_display_id=summary.parent_display_id,
        start_date=start_date,
        due_date=due_date,
        lock_version=payload.get("lockVersion"),
        description=_delimit_user_content(description),
        url=summary.url,
        activities_url=_shared_link_to_web_url(
            links.get("activities", {}).get("href"), base_url=base_url, origin=origin
        ),
        relations_url=_shared_link_to_web_url(links.get("relations", {}).get("href"), base_url=base_url, origin=origin),
        description_truncated=truncated,
        description_length=length,
        estimated_time=summary.estimated_time,
        derived_estimated_time=summary.derived_estimated_time,
        spent_time=summary.spent_time,
        remaining_time=summary.remaining_time,
        derived_remaining_time=summary.derived_remaining_time,
        duration=summary.duration,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
        author=summary.author,
        category=summary.category,
        children=children,
        children_truncated=children_truncated,
        ancestors=ancestors,
        ancestors_truncated=ancestors_truncated,
        schedule_manually=summary.schedule_manually,
        ignore_non_working_days=summary.ignore_non_working_days,
        derived_start_date=summary.derived_start_date,
        derived_due_date=summary.derived_due_date,
        percentage_done=summary.percentage_done,
        derived_percentage_done=summary.derived_percentage_done,
        readonly=summary.readonly,
    )


class HttpxWorkPackageApi:
    def __init__(self, transport: Transport, *, base_url: str, api_prefix: str = "/api/v3/") -> None:
        self._transport = transport
        self._base_url = base_url
        self._origin = _origin_from_url(base_url)
        self._api_prefix = api_prefix

    def to_record(self, payload: dict[str, Any], *, text_limit: int | None) -> WorkPackageRecord:
        base_url = self._base_url
        origin = self._origin
        summary = normalize_work_package_summary(payload, base_url=base_url, text_limit=text_limit)
        return WorkPackageRecord(
            summary=summary,
            # Lazy: list()/search() callers never read this -- only get()'s
            # single-item path needs the full detail normalization.
            to_detail=lambda: normalize_work_package_detail(
                payload, base_url=base_url, origin=origin, text_limit=text_limit, summary=summary
            ),
            payload=payload,
        )

    async def list(
        self,
        *,
        filters: list[dict[str, Any]],
        offset: int,
        limit: int,
        sort_by: list[SortCriterion] | None,
        group_by: str | None,
    ) -> WorkPackagePage:
        params: dict[str, str] = {
            "offset": str(offset),
            "pageSize": str(limit),
            "filters": json.dumps(filters, separators=(",", ":")),
        }
        if sort_by:
            sort_criteria = [[criterion.field, criterion.direction] for criterion in sort_by]
            params["sortBy"] = json.dumps(sort_criteria, separators=(",", ":"))
        if group_by:
            params["groupBy"] = group_by
        payload = await self._transport.get_json("work_packages", params=params)
        raw_elements = [item for item in payload.get("_embedded", {}).get("elements", []) if isinstance(item, dict)]
        server_total = int(payload.get("total", len(raw_elements)))
        return WorkPackagePage(raw_elements=raw_elements, server_total=server_total)

    async def get(self, work_package_ref: str, *, text_limit: int | None = None) -> WorkPackageRecord:
        safe_ref = _work_package_ref_encode(work_package_ref)
        payload = await self._transport.get_json(f"work_packages/{safe_ref}")
        return self.to_record(payload, text_limit=text_limit)

    async def validate_create(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._transport.post_json(f"projects/{project_id}/work_packages/form", json_body=payload)

    async def validate_update(self, work_package_ref: str, payload: dict[str, Any]) -> dict[str, Any]:
        safe_ref = _work_package_ref_encode(work_package_ref)
        return await self._transport.post_json(f"work_packages/{safe_ref}/form", json_body=payload)

    def parse_form(self, form: dict[str, Any]) -> WorkPackageFormResult:
        embedded = form.get("_embedded", {})
        return WorkPackageFormResult(
            payload=embedded.get("payload", {}),
            validation_errors=_normalize_form_validation_errors(embedded.get("validationErrors")),
            schema=embedded.get("schema", {}),
        )

    async def commit_create(self, payload: dict[str, Any], *, text_limit: int | None) -> WorkPackageRecord:
        response = await self._transport.post_json("work_packages", json_body=payload)
        return self.to_record(response, text_limit=text_limit)

    async def commit_update(
        self, work_package_ref: str, payload: dict[str, Any], *, text_limit: int | None
    ) -> WorkPackageRecord:
        safe_ref = _work_package_ref_encode(work_package_ref)
        response = await self._transport.patch_json(f"work_packages/{safe_ref}", json_body=payload)
        return self.to_record(response, text_limit=text_limit)

    async def delete(self, work_package_ref: str) -> None:
        safe_ref = _work_package_ref_encode(work_package_ref)
        await self._transport.delete(f"work_packages/{safe_ref}")

    async def post_comment(
        self, work_package_ref: str, *, comment: str, internal: bool, notify: bool
    ) -> dict[str, Any]:
        safe_ref = _work_package_ref_encode(work_package_ref)
        return await self._transport.post_json(
            f"work_packages/{safe_ref}/activities",
            params={"notify": str(notify).lower()},
            json_body={"comment": {"raw": comment}, "internal": internal},
        )
