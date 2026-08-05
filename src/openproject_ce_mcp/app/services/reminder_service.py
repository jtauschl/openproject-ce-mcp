"""Application Service for the Reminders domain.

Depends on the `ReminderApi` Protocol (never `HttpxReminderApi` concretely --
enforced by the architecture-boundary test), on `WorkPackageLookupApi`
directly, on `WorkPackageIdResolver`, and on `WorkPackageProjectAllowedCheck`
-- the widest seam surface of any domain in this migration,
because each of its four methods scopes differently:

- `list()` fans out across N *different* work packages (one per reminder,
  not a single anchor) -- uses `WorkPackageProjectAllowedCheck` +
  `WorkPackageAllowedContext` (a request-scoped cache avoiding a redundant
  fetch if two reminders happen to share a work package), verbatim behavior
  of client.py's original per-record filter. This does NOT belong in a
  Policy module (`app/policies/` is documented as pure, no I/O) since the
  check itself does I/O (a conditional work-package fetch).
- `create()` takes a genuine caller-supplied work-package reference -- uses
  `WorkPackageIdResolver(ref, write=True)`, replacing client.py's hand-rolled
  `_work_package_ref` + manual `_get` + `_ensure_project_write_link_allowed`
  chain, the same replacement Watchers' add()/remove() made.
- `update()`/`delete()` both need the reminder's OWN `remindable` link first
  (an id already concrete once the reminder is fetched, not a caller-supplied
  reference) -- uses `WorkPackageLookupApi.get_by_href()` + a direct
  `scope_policy.ensure_project_write_link_allowed` call, the same shape as
  Emoji Reactions' `toggle()` (fail-closed raise on a missing/malformed link,
  not a bool-returning check to re-wrap).

No shared `_write_outcome.py` state machine: `create()`/`update()` return the
same `ReminderWriteResult` shape, but neither goes through a `<domain>/form`
endpoint the way Grid/News/Board do -- `_finalize_write` assumes a
form-produced `payload`/`validation_errors` pair, which this domain's flat
POST/PATCH payload construction doesn't have. `delete()` stays its own flat
method (single write action, no sibling delete-shaped write to share with).

Read/write scope reuses `"work_package"` (not a dedicated `"reminder"`
scope) -- verbatim behavior of client.py's `_ensure_read_enabled`/
`_ensure_write_enabled("work_package")` calls.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...models import ReminderListResult, ReminderSummary, ReminderWriteResult
from ..errors import InvalidInputError, PermissionDeniedError
from ..pagination import clamp_limit, fetch_bounded_and_paginate
from ..policies import access, hidden_fields
from ..policies import scope as scope_policy
from ..ports.reminder_api import ReminderApi
from ..ports.work_package_lookup_api import WorkPackageLookupApi
from ..ports.work_package_ref import WorkPackageIdResolver, WorkPackageProjectAllowedCheck
from ..ports.work_package_resolution import WorkPackageAllowedContext


class ReminderService:
    def __init__(
        self,
        *,
        api: ReminderApi,
        work_package_lookup_api: WorkPackageLookupApi,
        settings: Settings,
        project_id_to_identifier: dict[int, str],
        resolve_work_package_id: WorkPackageIdResolver,
        work_package_project_allowed: WorkPackageProjectAllowedCheck,
    ) -> None:
        self._api = api
        self._work_package_lookup_api = work_package_lookup_api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier
        self._resolve_work_package_id = resolve_work_package_id
        self._work_package_project_allowed = work_package_project_allowed

    def _stamp(self, summary: ReminderSummary) -> ReminderSummary:
        return hidden_fields.apply_hidden_fields("reminder", summary, settings=self._settings)

    async def list_all(self, *, offset: int = 1, limit: int | None = None) -> ReminderListResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        effective_limit = clamp_limit(
            limit,
            default_page_size=self._settings.default_page_size,
            max_page_size=self._settings.max_page_size,
            max_results=self._settings.max_results,
        )
        if not self._settings.read_projects:
            # deny-all: skip the network call entirely
            return ReminderListResult(
                offset=offset, limit=effective_limit, total=0, count=0, next_offset=None, truncated=False, results=[]
            )
        allowlisted = not scope_policy.scope_allows_all(self._settings.read_projects)
        cache = WorkPackageAllowedContext()

        async def item_allowed(raw: dict[str, Any]) -> bool:
            if not allowlisted:
                return True
            record = self._api.to_record(raw)
            href = record.remindable_link.get("href") if isinstance(record.remindable_link, dict) else None
            if not href:
                return False  # can't verify -> fail closed
            return await self._work_package_project_allowed(href, context=cache)

        # Reminders is really offset-paginated server-side (verified against
        # OpenProject's own API implementation: ReminderCollectionRepresenter
        # subclasses OffsetPaginatedCollection) -- a single unparameterized
        # GET silently returned only the server's default page, and walking
        # the complete collection on every call (the prior paginate_all
        # approach) never reduced server load. Scan just enough pages to
        # fill the requested window instead, same early-stopping pattern as
        # Relations (OPM-373 Phase 5, OPM-379/F5). .summary() (LAZY, see
        # ReminderRecord's own docstring) is called only AFTER filtering,
        # inside `normalize`, matching client.py's original "filter raw,
        # normalize survivors" order.
        raw_items, total, next_offset, truncated = await fetch_bounded_and_paginate(
            fetch_page=lambda o, ps: self._api.fetch_page(offset=o, page_size=ps),
            normalize=lambda raw: self._stamp(self._api.to_record(raw).summary()),
            item_allowed=item_allowed,
            server_page_size=self._settings.max_page_size,
            offset=offset,
            limit=effective_limit,
        )
        return ReminderListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=total,
            next_offset=next_offset,
            truncated=truncated,
            results=raw_items,
        )

    async def create(
        self,
        *,
        work_package_id: int | str,
        remind_at: str,
        note: str | None = None,
        confirm: bool = False,
    ) -> ReminderWriteResult:
        resolved_id = await self._resolve_work_package_id(work_package_id, write=True)
        hidden_fields.ensure_field_writable("reminder", "remind_at", settings=self._settings)
        payload: dict = {"remindAt": remind_at}
        if note is not None:
            hidden_fields.ensure_field_writable("reminder", "note", settings=self._settings)
            payload["note"] = note

        if not confirm:
            return ReminderWriteResult(
                action="create",
                state="preview",
                ready=True,
                message="OpenProject is ready to create this reminder. Ask for confirmation, then call again with confirm=true.",
                reminder_id=None,
                payload=payload,
                validation_errors={},
                result=None,
            )
        access.ensure_write_enabled("work_package", settings=self._settings)
        # One active reminder per work package/user: a second create returns
        # 409, surfaced as InvalidInputError with the API's "update or
        # delete" message.
        record = await self._api.create(resolved_id, payload)
        result = self._stamp(record.summary())
        return ReminderWriteResult(
            action="create",
            state="confirmed",
            ready=True,
            message="Reminder created successfully.",
            reminder_id=result.id,
            payload=payload,
            validation_errors={},
            result=result,
        )

    async def _ensure_reminder_project_write_allowed(self, reminder_id: int) -> None:
        """Fetch only the reminder's `remindable` link (not the full record --
        see `ReminderApi.get_remindable_link`'s docstring for why), derive its
        work package, and check the write allowlist against that work
        package's own project link.

        Fail closed: an unresolvable remindable link must not be bypassed,
        even under a fully open READ_PROJECTS=*/WRITE_PROJECTS=* scope --
        verbatim behavior of client.py's original.
        """
        remindable = await self._api.get_remindable_link(reminder_id)
        href = remindable.get("href") if isinstance(remindable, dict) else None
        if not isinstance(href, str) or not href:
            raise PermissionDeniedError(
                "OpenProject writes to this reminder are disabled by OPENPROJECT_WRITE_PROJECTS."
            )
        work_package = await self._work_package_lookup_api.get_by_href(href)
        scope_policy.ensure_project_write_link_allowed(
            work_package.get("_links", {}).get("project"),
            settings=self._settings,
            project_id_to_identifier=self._project_id_to_identifier,
        )

    async def update(
        self,
        *,
        reminder_id: int,
        remind_at: str | None = None,
        note: str | None = None,
        confirm: bool = False,
    ) -> ReminderWriteResult:
        await self._ensure_reminder_project_write_allowed(reminder_id)
        payload: dict = {}
        if remind_at is not None:
            hidden_fields.ensure_field_writable("reminder", "remind_at", settings=self._settings)
            payload["remindAt"] = remind_at
        if note is not None:
            hidden_fields.ensure_field_writable("reminder", "note", settings=self._settings)
            payload["note"] = note
        if not payload:
            raise InvalidInputError("At least one field (remind_at or note) is required.")

        if not confirm:
            return ReminderWriteResult(
                action="update",
                state="preview",
                ready=True,
                message="OpenProject is ready to update this reminder. Ask for confirmation, then call again with confirm=true.",
                reminder_id=reminder_id,
                payload=payload,
                validation_errors={},
                result=None,
            )
        access.ensure_write_enabled("work_package", settings=self._settings)
        record = await self._api.update(reminder_id, payload)
        result = self._stamp(record.summary())
        return ReminderWriteResult(
            action="update",
            state="confirmed",
            ready=True,
            message="Reminder updated successfully.",
            reminder_id=result.id,
            payload=payload,
            validation_errors={},
            result=result,
        )

    async def delete(self, *, reminder_id: int, confirm: bool = False) -> ReminderWriteResult:
        await self._ensure_reminder_project_write_allowed(reminder_id)

        if not confirm:
            return ReminderWriteResult(
                action="delete",
                state="preview",
                ready=True,
                message="OpenProject is ready to delete this reminder. Ask for confirmation, then call again with confirm=true.",
                reminder_id=reminder_id,
                payload={},
                validation_errors={},
                result=None,
            )
        access.ensure_write_enabled("work_package", settings=self._settings)
        await self._api.delete(reminder_id)
        return ReminderWriteResult(
            action="delete",
            state="confirmed",
            ready=True,
            message="Reminder deleted successfully.",
            reminder_id=reminder_id,
            payload={},
            validation_errors={},
            result=None,
        )
