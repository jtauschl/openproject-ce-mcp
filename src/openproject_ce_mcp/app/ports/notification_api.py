"""Notifications Domain API port (ADR 0001, OPM-318 eighth consumer).

List-only for reads (no single-item GET exists in client.py's original --
`normalize_notification` is only ever called from `list_notifications`), plus
two parameterless write actions with no request body: `mark_read` (one
notification) and `mark_all_read` (every currently-unread notification).

`NotificationRecord.summary` is a LAZY callable, not an eager field --
mirroring `ReminderRecord`'s precedent and the same Codex-found bug class it
exists to avoid: client.py's original `list_notifications` filters the RAW
elements by project/work-package allowlist first and normalizes only the
survivors (`elements = filtered` happens before `self.normalize_notification`
is ever called). An eager `summary` field would normalize every record up
front, including ones the Service is about to discard on a project it cannot
even read, and would raise a spurious `KeyError` on a filtered-out record
missing an unrelated field.

`project_link`/`resource_link` are carried as RAW link dicts, not
pre-extracted hrefs/ids, because the Service's allowlist check is a
three-way branch depending on which links are present at all (a project
link directly; no project link but a work-package resource link, resolved
via the work package itself; neither, which is genuinely personal/global and
passes through unchecked) -- matching client.py's original
`_notification_payload_allowed` exactly. `resource_link` is not narrowed to
"the work-package case" here, since distinguishing a work-package resource
link from any other kind is itself part of that branch, not something the
Port should pre-decide.

No `to_detail`: `NotificationSummary` IS the only normalized shape this
domain has (no separate Detail model exists in models.py), matching every
other OPM-318-consuming domain migrated this session.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from ...models import NotificationSummary


@dataclass(frozen=True)
class NotificationRecord:
    summary: Callable[[], NotificationSummary]
    project_link: dict[str, Any] | None
    resource_link: dict[str, Any] | None


@dataclass(frozen=True)
class NotificationPage:
    """`records` plus OpenProject's own reported `total` -- the Service needs
    the server-reported total (not just `len(records)`) when the scope
    allows all projects, matching client.py's original
    `int(payload.get("total", len(elements)))`; under a restrictive scope the
    Service instead uses its own post-filter count, exactly like the
    original's `total = len(filtered)`.

    `exhausted` (False if the server page still had more, unscanned results)
    drives the Service's re-scan-and-skip loop under a restrictive scope --
    same shape as `ProjectPage.exhausted` (app/ports/project_api.py), needed
    because a server page's allowed-subset can run out before the caller's
    own requested page size does, without the server collection itself
    being exhausted (found via an independent Codex review: a filtered-empty
    server page does not prove no further allowed notifications exist on
    later pages, so the Service must keep fetching rather than stopping).
    """

    records: list[NotificationRecord]
    total: int
    exhausted: bool


class NotificationApi(Protocol):
    """Narrow, Notifications-only Domain API port. NotificationService
    depends on this Protocol, never on HttpxNotificationApi concretely
    (enforced by the architecture-boundary test).
    """

    async def list_all(self, *, unread_only: bool, offset: int, limit: int) -> NotificationPage: ...
    async def mark_read(self, notification_id: int) -> None: ...
    async def mark_all_read(self) -> None: ...
