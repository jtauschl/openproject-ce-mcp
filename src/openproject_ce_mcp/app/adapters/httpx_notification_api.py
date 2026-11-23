"""HTTP-backed NotificationApi adapter.

No `httpx` import (depends on the `Transport` Protocol only, matching every
other adapter). `trim_text`/`link_title`/`id_from_href`/`SUBJECT_LIMIT` come
from `app/adapters/_text.py`, used by `normalize_notification` for
`trim_text` (subject/reason truncation), `link_title` (project/reason link
titles), and `id_from_href` (project/work-package ids from their links).

`mark_all_read`'s `project` filter matches the work package's own project
only; subprojects are not included.

`mark_read`/`mark_all_read` use `Transport.request_raw`, not `post_json`:
both endpoints return 204/200/201 with no JSON body to parse.
`HttpxTransport._request` already raises via `raise_for_status` on any
status >= 400 before `request_raw` returns, so a successful return already
means success -- no separate status-code check is needed in this adapter.
"""

from __future__ import annotations

import json
from typing import Any

from ...models import NotificationDetail, NotificationDetailValue, NotificationSummary
from ..pagination import page_is_last
from ..ports.notification_api import NotificationPage, NotificationRecord
from ..transport.protocol import Transport
from ._text import FORMATTABLE_LIMIT, SUBJECT_LIMIT, unnamed
from ._text import delimit_user_content as _delimit_user_content
from ._text import id_from_href as _id_from_href
from ._text import link_title as _link_title
from ._text import trim_text as _trim_text

_UNREAD_IN_APP_FILTER: dict[str, Any] = {"readIAN": {"operator": "=", "values": ["f"]}}
_READ_IN_APP_FILTER: dict[str, Any] = {"readIAN": {"operator": "=", "values": ["t"]}}


def _filters_param(filters: list[dict[str, Any]]) -> str:
    return json.dumps(filters, separators=(",", ":"))


def normalize_notification(payload: dict[str, Any]) -> NotificationSummary:
    """Pure HAL->model translation (ADR: 'lives in the Domain API adapter').

    Excludes hidden-field masking -- that is a Service-layer concern applied
    after this returns (same pattern as every other normalize_*).
    """
    notification_id = int(payload["id"])
    links = payload.get("_links", {})
    project_link = links.get("project")
    resource_link = links.get("resource")
    resource_href = resource_link.get("href") if isinstance(resource_link, dict) else None
    work_package_id: int | None = None
    work_package_subject: str | None = None
    if isinstance(resource_href, str) and "work_packages/" in resource_href:
        work_package_id = _id_from_href(resource_href)
        work_package_subject = _link_title(resource_link)
    # reason is a top-level string property (an enum-like identifier, e.g.
    # "mentioned"/"assigned"), not a link -- notification_representer.rb has
    # no `_links.reason` at all.
    reason = _trim_text(payload.get("reason"), limit=SUBJECT_LIMIT)
    return NotificationSummary(
        id=notification_id,
        subject=_link_title(resource_link) or unnamed("notification"),
        reason=reason,
        read=bool(payload.get("readIAN")),
        project_id=_id_from_href(project_link.get("href")) if isinstance(project_link, dict) else None,
        project_name=_link_title(project_link),
        work_package_id=work_package_id,
        work_package_subject=work_package_subject,
        created_at=payload.get("createdAt") or "",
    )


def normalize_notification_detail(payload: dict[str, Any]) -> NotificationDetail:
    """The summary plus the embedded detail values and the activity the notification points at.

    A detail value is a date of the work package or the note of a reminder; the note is user text and is
    delimited as such. Which values may be shown is a Service decision.
    """
    summary = normalize_notification(payload)
    raw_details = payload.get("_embedded", {}).get("details", [])
    details = [
        NotificationDetailValue(
            property=str(item["property"]),
            value=_delimit_user_content(_trim_text(item.get("value"), limit=FORMATTABLE_LIMIT))
            if item.get("property") == "note"
            else _trim_text(item.get("value"), limit=SUBJECT_LIMIT),
        )
        for item in raw_details
        if isinstance(item, dict) and isinstance(item.get("property"), str)
    ]
    activity_link = payload.get("_links", {}).get("activity")
    return NotificationDetail(
        **vars(summary),
        details=details,
        activity_id=_id_from_href(activity_link.get("href")) if isinstance(activity_link, dict) else None,
    )


class HttpxNotificationApi:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def _record(self, payload: dict[str, Any]) -> NotificationRecord:
        # `summary` is lazy (see NotificationRecord's docstring): list_all()'s
        # caller filters records by project_link/resource_link BEFORE ever
        # reading .summary ("filter raw, normalize survivors" order) -- an
        # eager field here would normalize (and potentially KeyError on)
        # records the Service is about to discard on a project it cannot
        # even read.
        links = payload.get("_links", {})
        return NotificationRecord(
            summary=lambda: normalize_notification(payload),
            project_link=links.get("project"),
            resource_link=links.get("resource"),
            detail=lambda: normalize_notification_detail(payload),
        )

    async def list_all(self, *, unread_only: bool, offset: int, limit: int) -> NotificationPage:
        params: dict[str, str] = {"offset": str(offset), "pageSize": str(limit)}
        if unread_only:
            params["filters"] = _filters_param([_UNREAD_IN_APP_FILTER])
        payload = await self._transport.get_json("notifications", params=params)
        elements = payload.get("_embedded", {}).get("elements", [])
        records = [self._record(item) for item in elements if isinstance(item, dict)]
        total = int(payload.get("total", len(records)))
        exhausted = page_is_last(payload, offset=offset, requested_page_size=limit, total=total)
        return NotificationPage(records=records, total=total, exhausted=exhausted)

    async def mark_read(self, notification_id: int) -> None:
        await self._post_state(f"notifications/{notification_id}/read_ian")

    async def mark_unread(self, notification_id: int) -> None:
        await self._post_state(f"notifications/{notification_id}/unread_ian")

    async def _post_state(self, path: str, *, filters: list[dict[str, Any]] | None = None) -> None:
        # An empty dict, not None -- a bodyless POST here sends no Content-Type
        # header at all (httpx only sets one when `json` is non-None), and
        # OpenProject's Grape endpoint rejects that with 406 "Missing
        # content-type header" even though the POST itself carries no data
        # (same class of bug as UserApi.commit_lock).
        params = {"filters": _filters_param(filters)} if filters is not None else None
        await self._transport.request_raw("POST", path, params=params, json_body={})

    async def get(self, notification_id: int) -> NotificationRecord:
        return self._record(await self._transport.get_json(f"notifications/{notification_id}"))

    async def mark_all_read(self, *, project_ids: frozenset[int] | None) -> None:
        await self._post_state("notifications/read_ian", filters=_bulk_filters(_UNREAD_IN_APP_FILTER, project_ids))

    async def mark_all_unread(self, *, project_ids: frozenset[int] | None) -> None:
        await self._post_state("notifications/unread_ian", filters=_bulk_filters(_READ_IN_APP_FILTER, project_ids))


def _bulk_filters(state_filter: dict[str, Any], project_ids: frozenset[int] | None) -> list[dict[str, Any]]:
    # Unfiltered, a bulk route sets the state and updated_at on every visible notification, so each call would
    # rewrite those already in the target state and move their updatedAt. OpenProject's own mark-all also touches
    # only the ones that change.
    filters: list[dict[str, Any]] = [state_filter]
    if project_ids is not None:
        if not project_ids:
            # An empty "=" list is not "no project": refuse rather than rely on how OpenProject reads it.
            raise ValueError("project_ids must name at least one project")
        filters.append(
            {"project": {"operator": "=", "values": [str(project_id) for project_id in sorted(project_ids)]}}
        )
    return filters
