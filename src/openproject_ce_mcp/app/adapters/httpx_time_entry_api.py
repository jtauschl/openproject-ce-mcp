"""HTTP-backed TimeEntryApi adapter.

No `httpx` import (depends on the `Transport` Protocol only, matching every
other adapter). `trim_text`/`id_from_href`/`link_title`/`delimit_user_content`/
`web_url`/`SUBJECT_LIMIT`/`normalize_form_validation_errors`/`_normalize_text`/
`_trim_text_with_meta`/`_extract_formattable_text_with_meta` come from
`app/adapters/_text.py`. `normalize_form_validation_errors` is the exact
three-branch shape `create_time_entry`/`update_time_entry` use, shared with
Grids' identical situation. This adapter's `comment` field never needs
`preserve_newlines=True`, so it relies on the shared helper's `False` default.

Unlike `normalize_relation`, `normalize_time_entry_raw`/
`normalize_time_entry_activity_raw` here do NOT call a hide-aware,
settings-dependent extraction or apply hidden-field masking inline -- these
functions do ONLY the pure HAL extraction. `comment` is still
trimmed/delimited (matching the untrusted-user-content handling every other
domain applies, via the same `raw`-or-`html` fallback, whitespace-collapse,
and ellipsis-truncation shape as `httpx_project_api.py`'s
`_extract_formattable_text_with_meta`), but with NO hidden-field awareness at
all. `TimeEntryService._stamp`/`_stamp_activity` apply the
`"time_entry"`/`"time_entry_activity"` hidden-field masking afterwards (see
that module's docstring for the comment-specific metadata-clearing rationale).

`fetch_activities_for_entity` lets the transport call raise normally on
error -- it must NOT convert failures to `None`/empty here, since one of its
two callers (`TimeEntryService._resolve_activity_id`) needs a real error to
propagate, not be silently swallowed (see time_entry_api.py's module
docstring for the full rationale, and GitHub issue #10's log_own_time
entity-vs-project-link distinction, described below).
"""

from __future__ import annotations

from typing import Any

from ...models import TimeEntryActivitySummary, TimeEntrySummary
from ..api_href import api_href as _api_href
from ..errors import NotFoundError, OpenProjectServerError, PermissionDeniedError
from ..ports.time_entry_api import TimeEntryActivityRecord, TimeEntryFormResult, TimeEntryRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import delimit_user_content as _delimit_user_content
from ._text import extract_formattable_text_with_meta as _extract_formattable_text_with_meta
from ._text import id_from_href as _id_from_href
from ._text import link_title as _link_title
from ._text import normalize_form_validation_errors as normalize_validation_errors
from ._text import trim_text as _trim_text


def normalize_time_entry_raw(payload: dict[str, Any], *, text_limit: int | None) -> TimeEntrySummary:
    """Pure HAL extraction, no hidden-field awareness (see module docstring).

    ``text_limit=None`` returns the full comment uncapped (get_time_entry);
    the caller passes settings.text_limit for list rows.
    """
    links = payload.get("_links", {})
    project_link = links.get("project")
    entity_link = links.get("entity")
    trimmed, truncated, full_length = _extract_formattable_text_with_meta(payload.get("comment"), limit=text_limit)
    return TimeEntrySummary(
        id=int(payload["id"]),
        project=_link_title(project_link),
        entity_type=_trim_text(payload.get("entityType"), limit=SUBJECT_LIMIT),
        entity_id=_id_from_href(entity_link.get("href")) if isinstance(entity_link, dict) else None,
        entity_name=_link_title(entity_link),
        user=_link_title(links.get("user")),
        activity=_link_title(links.get("activity")),
        hours=_trim_text(payload.get("hours"), limit=SUBJECT_LIMIT),
        spent_on=_trim_text(payload.get("spentOn"), limit=SUBJECT_LIMIT),
        start_time=_trim_text(payload.get("startTime"), limit=SUBJECT_LIMIT),
        end_time=_trim_text(payload.get("endTime"), limit=SUBJECT_LIMIT),
        ongoing=bool(payload.get("ongoing")),
        comment=_delimit_user_content(trimmed),
        comment_truncated=truncated,
        comment_length=full_length,
        created_at=payload.get("createdAt"),
        updated_at=payload.get("updatedAt"),
    )


def normalize_time_entry_activity_raw(payload: dict[str, Any]) -> TimeEntryActivitySummary:
    activity_id = int(payload["id"])
    projects = [_link_title(item) for item in payload.get("_links", {}).get("projects", []) if isinstance(item, dict)]
    return TimeEntryActivitySummary(
        id=activity_id,
        name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or f"Activity {activity_id}",
        position=payload.get("position"),
        is_default=bool(payload.get("default")),
        projects=[item for item in projects if item],
    )


class HttpxTimeEntryApi:
    def __init__(self, transport: Transport, *, api_prefix: str = "/api/v3/") -> None:
        self._transport = transport
        self._api_prefix = api_prefix

    def to_record(self, payload: dict[str, Any], *, text_limit: int | None) -> TimeEntryRecord:
        return TimeEntryRecord(summary=lambda: normalize_time_entry_raw(payload, text_limit=text_limit))

    def to_activity_record(self, payload: dict[str, Any]) -> TimeEntryActivityRecord:
        return TimeEntryActivityRecord(summary=normalize_time_entry_activity_raw(payload))

    def parse_form_result(self, form: dict[str, Any]) -> TimeEntryFormResult:
        embedded = form.get("_embedded", {})
        return TimeEntryFormResult(
            payload=embedded.get("payload", {}),
            validation_errors=normalize_validation_errors(embedded.get("validationErrors")),
        )

    def project_link_title_and_id(self, link: Any) -> tuple[str | None, int | None]:
        title = _link_title(link)
        href = link.get("href") if isinstance(link, dict) else None
        return title, _id_from_href(href)

    async def fetch_page(self, *, offset: int, page_size: int) -> dict[str, Any]:
        params = {"offset": str(offset), "pageSize": str(page_size)}
        return await self._transport.get_json("time_entries", params=params)

    async def get_raw(self, time_entry_id: int) -> dict[str, Any]:
        return await self._transport.get_json(f"time_entries/{time_entry_id}")

    async def validate_create(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._transport.post_json("time_entries/form", json_body=payload)

    async def validate_update(self, time_entry_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._transport.post_json(f"time_entries/{time_entry_id}/form", json_body=payload)

    async def create(self, payload: dict[str, Any]) -> TimeEntryRecord:
        response = await self._transport.post_json("time_entries", json_body=payload)
        return self.to_record(response, text_limit=None)

    async def update(self, time_entry_id: int, payload: dict[str, Any]) -> TimeEntryRecord:
        response = await self._transport.patch_json(f"time_entries/{time_entry_id}", json_body=payload)
        return self.to_record(response, text_limit=None)

    async def delete(self, time_entry_id: int) -> None:
        await self._transport.delete(f"time_entries/{time_entry_id}")

    async def fetch_activities(self) -> dict[str, Any] | None:
        # Only ONE call context uses this (list_activities()'s best-effort
        # first attempt, which treats a failure identically to an empty
        # result) -- unlike fetch_activities_for_entity, catching here is
        # safe and keeps that call site simple. See module docstring.
        try:
            return await self._transport.get_json("time_entries/activities")
        except (NotFoundError, PermissionDeniedError, OpenProjectServerError):
            return None

    async def fetch_activities_for_entity(self, *, project_id: int, work_package_id: int | None) -> dict[str, Any]:
        # OpenProject's CreateContract#allowed_to_log_own? can only validate the
        # log_own_time permission against a concrete WorkPackage/Meeting entity
        # (case model.entity ... else false) -- a project-only link makes it fall
        # through to requiring log_time instead, denying a caller who only has
        # log_own_time even though they're entitled to log their own time on this
        # work package. Send the entity link whenever the work package is already
        # known, matching what the real create/update payload sends (GitHub #10).
        links: dict[str, dict[str, str]] = (
            {"entity": {"href": _api_href(f"work_packages/{work_package_id}", api_prefix=self._api_prefix)}}
            if work_package_id is not None
            else {"project": {"href": _api_href(f"projects/{project_id}", api_prefix=self._api_prefix)}}
        )
        return await self._transport.post_json("time_entries/form", json_body={"_links": links})
