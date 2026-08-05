"""Application Service for the Notifications domain.

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

`_rescan_and_skip`'s restrictive-scope path resolves each server page's
work-package hrefs concurrently via `WorkPackageProjectAllowedBulkCheck`
(`_resolve_page_allowed`, OPM-379/F3) instead of one `WorkPackageProjectAllowedCheck`
call per record -- the skip-counting/`limit + 1`-lookahead consumption logic
itself is unchanged, it now just reads pre-resolved `bool | Exception`
outcomes. The same change also fixed an independent bug (OPM-379/F3
Korrektur 6c): `_rescan_and_skip` previously set `truncated=True` as soon as
`len(results) >= limit` was reached mid-page, without the `limit + 1`
lookahead every sibling scan helper already uses to confirm a genuine next
match exists -- a false positive whenever a page happened to end exactly at
the limit-th allowed record.

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
from ..ports.work_package_ref import WorkPackageProjectAllowedBulkCheck, WorkPackageProjectAllowedCheck
from ..ports.work_package_resolution import WorkPackageAllowedContext


class NotificationService:
    def __init__(
        self,
        *,
        api: NotificationApi,
        settings: Settings,
        project_id_to_identifier: dict[int, str],
        work_package_project_allowed: WorkPackageProjectAllowedCheck,
        work_package_project_allowed_bulk: WorkPackageProjectAllowedBulkCheck,
    ) -> None:
        self._api = api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier
        self._work_package_project_allowed = work_package_project_allowed
        self._work_package_project_allowed_bulk = work_package_project_allowed_bulk

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
        matches, until `limit + 1` allowed records are collected (or the
        server collection is genuinely exhausted) -- same re-scan-and-skip
        shape as `app/resolvers/project_query.fetch_project_page`, needed for
        the same reason: a restrictive read scope means a server page's
        allowed subset can run dry before the caller's own requested page
        size does, without the server collection itself being exhausted. A
        filtered-empty server page does NOT prove no further allowed
        notifications exist on later pages, so a single page is never treated
        as conclusive.

        Collects one extra (`limit + 1`) allowed record before deciding
        `truncated`, matching every sibling scan helper
        (`fetch_bounded_and_paginate`/`scan_and_paginate`/
        `scan_records_and_paginate`) -- an earlier version of this method
        stopped and set `truncated=True` as soon as `len(results) >= limit`
        was reached mid-page, WITHOUT checking whether a genuine next match
        existed beyond that window (a false-positive `next_offset`/
        `truncated` promise whenever the page happened to end exactly at the
        limit-th allowed record). Fixed here in the same change that
        page-batches the allowlist checks (OPM-379/F3 Korrektur 6c).

        Per-page allowlist resolution is now batched (OPM-379/F3): every raw
        record's candidate work-package href is collected up front and
        resolved in one bulk call via `_work_package_project_allowed_bulk`,
        instead of awaiting `_record_allowed` one record at a time -- the
        skip-counting/limit+1-lookahead consumption loop below is otherwise
        structurally unchanged, it just reads pre-resolved outcomes.
        """
        skip_count = (offset - 1) * limit
        skipped = 0
        results: list[NotificationRecord] = []
        cache = WorkPackageAllowedContext()
        server_offset = 1
        server_page_size = self._settings.max_page_size

        while len(results) <= limit:
            page = await self._api.list_all(unread_only=unread_only, offset=server_offset, limit=server_page_size)
            if not page.records:
                break

            outcomes = await self._resolve_page_allowed(page.records, cache=cache)

            for record, outcome in zip(page.records, outcomes, strict=True):
                if isinstance(outcome, Exception):
                    # Every record reached by this loop iteration -- skip
                    # window or not -- WOULD have been awaited by the old
                    # one-at-a-time control flow too (the skip counter only
                    # skips already-confirmed ALLOWED records, it does not
                    # skip the check itself; and the loop only stops once the
                    # (limit+1)-th allowed record is actually found and
                    # appended, via the `break` below -- not merely once
                    # `len(results) == limit`). So a speculative failure here
                    # always raises; only outcomes for records the loop never
                    # reaches at all (a later record on this page, once the
                    # break already fired) are silently discarded, same as
                    # `fetch_bounded_and_paginate`/`_scan_and_paginate`.
                    raise outcome
                if not outcome:
                    continue
                if skipped < skip_count:
                    skipped += 1
                    continue
                results.append(record)
                if len(results) > limit:
                    # The (limit + 1)-th allowed record proves at least one
                    # more match exists beyond the requested page -- stop
                    # immediately, without checking the rest of this page or
                    # server exhaustion.
                    break

            if len(results) > limit:
                break
            if page.exhausted:
                break
            server_offset += 1

        truncated = len(results) > limit
        if truncated:
            results = results[:limit]
        return results, len(results), truncated

    async def _resolve_page_allowed(
        self, records: list[NotificationRecord], *, cache: WorkPackageAllowedContext
    ) -> list[bool | Exception]:
        """Page-batching allowlist resolution (OPM-379/F3): collect every
        record's candidate work-package href (records with their own
        `project_link`, or neither kind of link, need no I/O and are resolved
        synchronously) and resolve the rest concurrently in one bulk call --
        same three-way branch client.py's original `_notification_payload_allowed`
        used (and this Service's own pre-F3 `_record_allowed` verbatim-ported),
        just resolving a whole page's work-package hrefs together instead of
        one record at a time.
        """
        hrefs: list[str] = []
        for record in records:
            if record.project_link is not None:
                continue
            resource_href = record.resource_link.get("href") if isinstance(record.resource_link, dict) else None
            if isinstance(resource_href, str) and "work_packages/" in resource_href:
                hrefs.append(resource_href)
        bulk_outcomes = await self._work_package_project_allowed_bulk(hrefs, context=cache) if hrefs else {}

        results: list[bool | Exception] = []
        for record in records:
            if record.project_link is not None:
                results.append(
                    scope_policy.project_link_payload_allowed(
                        {"_links": {"project": record.project_link}},
                        link_key="project",
                        settings=self._settings,
                        project_id_to_identifier=self._project_id_to_identifier,
                    )
                )
                continue
            resource_href = record.resource_link.get("href") if isinstance(record.resource_link, dict) else None
            if isinstance(resource_href, str) and "work_packages/" in resource_href:
                results.append(bulk_outcomes[resource_href])
                continue
            results.append(True)  # no project link and no work-package resource link: genuinely personal/global
        return results

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
                state="preview",
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
            state="confirmed",
            ready=True,
            message=f"Notification {notification_id} marked read.",
            notification_id=notification_id,
        )

    async def mark_all_read(self, *, confirm: bool = False) -> NotificationMarkResult:
        access.ensure_write_enabled("personal", settings=self._settings)
        if not confirm:
            return NotificationMarkResult(
                action="mark_all_read",
                state="preview",
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
            state="confirmed",
            ready=True,
            message="All unread notifications marked read.",
            notification_id=None,
        )
