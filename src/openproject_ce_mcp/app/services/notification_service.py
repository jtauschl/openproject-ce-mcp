"""Application Service for the Notifications domain (ADR 0001).

Depends on the `NotificationApi` Protocol (never `HttpxNotificationApi`
concretely -- enforced by the architecture-boundary test) and on
`WorkPackageProjectAllowedCheck` -- the same seam Reminders' `list_all()`
uses, for the identical reason: `list_all()` fans out across N *different*
work packages (one per notification that has a work-package resource link
but no project link of its own), not a single anchor.

No `to_detail`, no Policy module: `NotificationSummary` is the only
normalized shape this domain has, and `list_all()`'s per-record allowlist
check is a three-way branch that itself does I/O (a conditional work-package
fetch) -- `app/policies/` is documented as pure, no I/O, so this belongs in
the Service, matching Reminders' precedent exactly:

- a project link present -> `scope.project_link_payload_allowed` (no I/O).
- no project link, but a work-package resource link -> resolve via the work
  package itself, using `WorkPackageProjectAllowedCheck` +
  `WorkPackageAllowedContext` (a request-scoped cache avoiding a redundant
  fetch if two notifications happen to reference the same work package),
  verbatim behavior of client.py's original `_notification_payload_allowed`.
- neither link present -> genuinely personal/global, passes through
  unchecked (verbatim behavior of client.py's original).

`mark_read()`/`mark_all_read()` each stay a single flat method (not the
shared `_write_outcome.py` state machine): neither goes through a
`<domain>/form` endpoint, and OpenProject's response carries no body to
report back as `result` -- `_finalize_write` assumes a form-produced
`payload`/`validation_errors` pair this domain's flat, bodyless POST doesn't
have. Both share the identical `NotificationMarkResult` shape, but that
alone is not the criterion the runbook uses (2+ write actions sharing a
`<domain>/form`-shaped result) -- matching Emoji Reactions'/Watchers'
single-flat-method precedent for the same reason.

Read/write scope uses `"personal"` (not `"work_package"` or a dedicated
`"notification"` scope) -- verbatim behavior of client.py's
`_ensure_read_enabled`/`_ensure_write_enabled("personal")` calls.

`mark_read()`/`mark_all_read()` both call `access.ensure_write_enabled("personal",
...)` unconditionally, BEFORE the `if not confirm:` preview return -- not gated
inside the confirmed branch like Document's update(). Verbatim port of
client.py's original `mark_notification_read`/`mark_all_notifications_read`
placement (`self._ensure_write_enabled("personal")` precedes the `if not
confirm:` check there too, confirmed against pre-migration history) --
preserved exactly, matching User Preferences' identical documented choice for
the same reason: a caller without personal-write can't even preview either
action today, and normalizing this to the Document-style ordering would
silently loosen that preview-time behavior.
"""

from __future__ import annotations

from ...config import Settings
from ...models import NotificationListResult, NotificationMarkResult, NotificationSummary
from ..pagination import effective_limit
from ..policies import access, hidden_fields
from ..policies import scope as scope_policy
from ..ports.notification_api import NotificationApi, NotificationRecord
from ..ports.work_package_ref import WorkPackageProjectAllowedCheck
from ..ports.work_package_resolution import WorkPackageAllowedContext


class NotificationService:
    def __init__(
        self,
        *,
        api: NotificationApi,
        settings: Settings,
        project_id_to_identifier: dict[int, str],
        work_package_project_allowed: WorkPackageProjectAllowedCheck,
    ) -> None:
        self._api = api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier
        self._work_package_project_allowed = work_package_project_allowed

    async def list_all(
        self, *, unread_only: bool = False, limit: int | None = None, offset: int = 1
    ) -> NotificationListResult:
        access.ensure_read_enabled("personal", settings=self._settings)
        resolved_limit = effective_limit(limit, settings=self._settings)
        if scope_policy.scope_allows_all(self._settings.read_projects):
            page = await self._api.list_all(unread_only=unread_only, offset=offset, limit=resolved_limit)
            # A missing project_link is fine under a wide-open scope
            # (resolved via the work-package branch or genuinely personal/
            # global, same as the restrictive path), but a structurally
            # malformed one is never legitimate -- filter it out even here,
            # without paying for the more expensive per-record allowlist
            # candidate-matching, which a wide-open scope doesn't need.
            records = [
                record
                for record in page.records
                if scope_policy.classify_project_link(record.project_link) is not scope_policy.LinkState.MALFORMED
            ]
            total = page.total
            truncated = total > offset * resolved_limit
        else:
            records, total, truncated = await self._rescan_and_skip(
                unread_only=unread_only, offset=offset, limit=resolved_limit
            )
        # .summary() is called only AFTER filtering -- matching client.py's
        # original "filter raw, normalize survivors" order (see
        # NotificationRecord's docstring for why this must stay lazy).
        results = [self._stamp(record.summary()) for record in records]
        return NotificationListResult(
            count=len(results),
            total=total,
            truncated=truncated,
            next_offset=offset + 1 if truncated else None,
            results=results,
        )

    async def _rescan_and_skip(
        self, *, unread_only: bool, offset: int, limit: int
    ) -> tuple[list[NotificationRecord], int, bool]:
        """Re-scan server pages from the start, skipping already-seen allowed
        matches, until `limit` allowed records are collected or the server
        collection is exhausted -- verbatim shape of
        `app/resolvers/project_query.fetch_project_page`'s identical
        re-scan-and-skip loop, needed for the same reason: a restrictive read
        scope means a server page's allowed subset can run dry before the
        caller's own requested page size does, without the server collection
        itself being exhausted. A filtered-empty server page does NOT prove no
        further allowed notifications exist on later pages, so a single page
        is never treated as conclusive.
        """
        skip_count = (offset - 1) * limit
        skipped = 0
        results: list[NotificationRecord] = []
        cache = WorkPackageAllowedContext()
        server_offset = 1
        server_page_size = self._settings.max_page_size
        truncated = False

        while len(results) < limit:
            page = await self._api.list_all(unread_only=unread_only, offset=server_offset, limit=server_page_size)
            if not page.records:
                break

            allowed_records = [record for record in page.records if await self._record_allowed(record, cache)]

            hit_limit_mid_page = False
            for record in allowed_records:
                if skipped < skip_count:
                    skipped += 1
                    continue
                results.append(record)
                if len(results) >= limit:
                    hit_limit_mid_page = True
                    break

            if hit_limit_mid_page:
                # This page had more allowed matches than needed -- stop without
                # checking server exhaustion: there's at least one more allowed
                # notification waiting, so treating this as "exhausted" would
                # wrongly hide it from a follow-up call. Report truncated=True
                # so the caller knows to request the next offset instead of
                # assuming this page is everything.
                truncated = True
                break

            if page.exhausted:
                break
            server_offset += 1

        return results, len(results), truncated

    async def _record_allowed(self, record: NotificationRecord, cache: WorkPackageAllowedContext) -> bool:
        if record.project_link is not None:
            return scope_policy.project_link_payload_allowed(
                {"_links": {"project": record.project_link}},
                link_key="project",
                settings=self._settings,
                project_id_to_identifier=self._project_id_to_identifier,
            )
        resource_href = record.resource_link.get("href") if isinstance(record.resource_link, dict) else None
        if isinstance(resource_href, str) and "work_packages/" in resource_href:
            # Work-package-linked notification without its own resolvable
            # project link -- resolve via the work package itself instead of
            # trusting the absent link (same helper/cache pattern as
            # list_relations/list_reminders).
            return await self._work_package_project_allowed(resource_href, context=cache)
        return True  # no project link and no work-package resource link: genuinely personal/global

    def _stamp(self, summary: NotificationSummary) -> NotificationSummary:
        return hidden_fields.apply_hidden_fields("notification", summary, settings=self._settings)

    async def mark_read(self, notification_id: int, *, confirm: bool = False) -> NotificationMarkResult:
        access.ensure_write_enabled("personal", settings=self._settings)
        if not confirm:
            # No OpenProject dry-run endpoint exists for this action -- this
            # is a client-side preview only: ready=True means the request is
            # valid and will be sent once confirmed, not that OpenProject has
            # already validated it.
            return NotificationMarkResult(
                action="mark_read",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message=(
                    f"Ask for confirmation, then call again with confirm=true to mark "
                    f"notification {notification_id} read."
                ),
                notification_id=notification_id,
            )
        await self._api.mark_read(notification_id)
        return NotificationMarkResult(
            action="mark_read",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message=f"Notification {notification_id} marked read.",
            notification_id=notification_id,
        )

    async def mark_all_read(self, *, confirm: bool = False) -> NotificationMarkResult:
        access.ensure_write_enabled("personal", settings=self._settings)
        if not confirm:
            return NotificationMarkResult(
                action="mark_all_read",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message=(
                    "Marks all currently unread notifications read. Ask for confirmation, "
                    "then call again with confirm=true to apply it."
                ),
                notification_id=None,
            )
        await self._api.mark_all_read()
        return NotificationMarkResult(
            action="mark_all_read",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="All unread notifications marked read.",
            notification_id=None,
        )
