"""HTTP-backed NotificationApi adapter.

No `httpx` import (depends on the `Transport` Protocol only, matching every
other adapter). `trim_text`/`link_title`/`id_from_href`/`SUBJECT_LIMIT` come
from `app/adapters/_text.py`, used by `normalize_notification` for
`trim_text` (subject/reason truncation), `link_title` (project/reason link
titles), and `id_from_href` (project/work-package ids from their links).

`mark_read`/`mark_all_read` use `Transport.request_raw`, not `post_json`:
both endpoints return 204/200/201 with no JSON body to parse.
`HttpxTransport._request` already raises via `raise_for_status` on any
status >= 400 before `request_raw` returns, so a successful return already
means success -- no separate status-code check is needed in this adapter.
"""

from __future__ import annotations

import json
from typing import Any

from ...models import NotificationSummary
from ..ports.notification_api import NotificationPage, NotificationRecord
from ..transport.protocol import Transport
from ._text import SUBJECT_LIMIT
from ._text import id_from_href as _id_from_href
from ._text import link_title as _link_title
from ._text import trim_text as _trim_text


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
    read_ian = payload.get("readIAN")
    if read_ian is None:
        read_ian = bool(payload.get("read"))
    # reason is a top-level string property (an enum-like identifier, e.g.
    # "mentioned"/"assigned"), not a link -- notification_representer.rb has
    # no `_links.reason` at all.
    reason = _trim_text(payload.get("reason"), limit=SUBJECT_LIMIT)
    return NotificationSummary(
        id=notification_id,
        subject=_link_title(resource_link) or f"Notification {notification_id}",
        reason=reason,
        read=bool(read_ian),
        project_id=_id_from_href(project_link.get("href")) if isinstance(project_link, dict) else None,
        project_name=_link_title(project_link),
        work_package_id=work_package_id,
        work_package_subject=work_package_subject,
        created_at=payload.get("createdAt") or "",
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
        )

    async def list_all(self, *, unread_only: bool, offset: int, limit: int) -> NotificationPage:
        params: dict[str, str] = {"offset": str(offset), "pageSize": str(limit)}
        if unread_only:
            params["filters"] = json.dumps([{"readIAN": {"operator": "=", "values": ["f"]}}], separators=(",", ":"))
        payload = await self._transport.get_json("notifications", params=params)
        elements = payload.get("_embedded", {}).get("elements", [])
        records = [self._record(item) for item in elements if isinstance(item, dict)]
        total = int(payload.get("total", len(records)))
        exhausted = offset * limit >= total
        return NotificationPage(records=records, total=total, exhausted=exhausted)

    async def mark_read(self, notification_id: int) -> None:
        # An empty dict, not None -- a bodyless POST here sends no Content-Type
        # header at all (httpx only sets one when `json` is non-None), and
        # OpenProject's Grape endpoint rejects that with 406 "Missing
        # content-type header" even though the POST itself carries no data
        # (same class of bug as UserApi.commit_lock).
        await self._transport.request_raw("POST", f"notifications/{notification_id}/read_ian", json_body={})

    async def mark_all_read(self) -> None:
        await self._transport.request_raw("POST", "notifications/read_ian", json_body={})
