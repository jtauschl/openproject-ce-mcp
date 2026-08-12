"""Application Service for Recurring Meetings + virtual Occurrences.

Depends on `RecurringMeetingApi` (its own domain Port, occurrences included)
and `ProjectRefResolver`. Reuses the `"meeting"` scope.

`create()`/`update()`/`delete()` are flat inline preview/commit (no form
endpoint exists for this domain -- verified against source). A Recurring
Meeting always belongs to exactly one project, same as Meeting.

`init_occurrence()`/`cancel_occurrence()` fetch the parent RecurringMeeting
first to run the allowlist check against ITS project link -- an occurrence
has no project of its own. `init_occurrence`'s write-gate maps to source's
`authorize_in_project(:create_meetings, ...)`; `cancel_occurrence`'s maps to
`authorize_in_project(:edit_meetings, ...)` -- both collapse onto this MCP's
single `"meeting"` write scope (this MCP does not split OpenProject's
per-action meeting permissions into separate scopes, matching how Work
Packages' create/update/delete all share one `"work_package"` write scope
despite OpenProject itself having separate permissions).

`cancel_occurrence()` on a not-yet-materialized occurrence silently creates a
new, PERMANENT cancelled Meeting server-side with no id returned in the
response (see `app/ports/recurring_meeting_api.py`'s docstring) -- this is
flagged explicitly here and in the tool docstring/integration tests, not
hidden behind a innocuous-looking "cancel" name.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...models import (
    MeetingSummary,
    RecurringMeetingListResult,
    RecurringMeetingOccurrenceListResult,
    RecurringMeetingOccurrenceSummary,
    RecurringMeetingOccurrenceWriteResult,
    RecurringMeetingSummary,
    RecurringMeetingWriteResult,
)
from ..api_href import api_href as _api_href
from ..pagination import clamp_limit, paginate_server, scan_records_and_paginate
from ..policies import access, hidden_fields
from ..policies import scope as scope_policy
from ..ports.project_ref import ProjectRefResolver
from ..ports.recurring_meeting_api import RecurringMeetingApi


class RecurringMeetingService:
    def __init__(
        self,
        *,
        api: RecurringMeetingApi,
        settings: Settings,
        project_id_to_identifier: dict[int, str],
        resolve_project_ref: ProjectRefResolver,
        api_prefix: str,
    ) -> None:
        self._api = api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier
        self._resolve_project_ref = resolve_project_ref
        self._api_prefix = api_prefix

    def _stamp(self, summary: RecurringMeetingSummary) -> RecurringMeetingSummary:
        return hidden_fields.apply_hidden_fields("recurring_meeting", summary, settings=self._settings)

    def _stamp_occurrence(self, summary: RecurringMeetingOccurrenceSummary) -> RecurringMeetingOccurrenceSummary:
        return hidden_fields.apply_hidden_fields("recurring_meeting", summary, settings=self._settings)

    async def list_all(
        self, *, project: str | None = None, offset: int = 1, limit: int | None = None
    ) -> RecurringMeetingListResult:
        access.ensure_read_enabled("meeting", settings=self._settings)
        effective_limit = clamp_limit(
            limit,
            default_page_size=self._settings.default_page_size,
            max_page_size=self._settings.max_page_size,
            max_results=self._settings.max_results,
        )

        resolved_project_id: int | None = None
        if project is not None:
            project_payload = await self._resolve_project_ref(project)
            resolved_project_id = int(project_payload["id"])

        use_client_side_filtering = resolved_project_id is None or not scope_policy.scope_allows_all(
            self._settings.read_projects
        )

        if use_client_side_filtering:

            def _record_allowed(record: Any) -> bool:
                return scope_policy.payload_allowed(
                    lambda: scope_policy.ensure_project_link_allowed(
                        record.project_link,
                        settings=self._settings,
                        project_id_to_identifier=self._project_id_to_identifier,
                    )
                )

            raw_items, truncated = await scan_records_and_paginate(
                lambda o, lim: self._api.list_page(offset=o, limit=lim, project_id=resolved_project_id),
                item_allowed=_record_allowed,
                server_page_size=self._settings.max_page_size,
                offset=offset,
                limit=effective_limit,
                key=lambda r: r.summary.id,
            )
            results = [self._stamp(record.summary) for record in raw_items]
            total = len(results)
            return RecurringMeetingListResult(
                offset=offset,
                limit=effective_limit,
                total=total,
                count=total,
                next_offset=offset + 1 if truncated else None,
                truncated=truncated,
                results=results,
            )

        records, total = await self._api.list_page(offset=offset, limit=effective_limit, project_id=resolved_project_id)
        results = [self._stamp(record.summary) for record in records]
        next_offset, truncated = paginate_server(offset=offset, limit=effective_limit, total=total)
        return RecurringMeetingListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(results),
            next_offset=next_offset,
            truncated=truncated,
            results=results,
        )

    async def get(self, recurring_meeting_id: int) -> RecurringMeetingSummary:
        access.ensure_read_enabled("meeting", settings=self._settings)
        record = await self._api.get(recurring_meeting_id)
        scope_policy.ensure_project_link_allowed(
            record.project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        return self._stamp(record.summary)

    async def _build_write_payload(
        self,
        *,
        project: str | None,
        title: str | None,
        frequency: str | None,
        start_time: str | None,
        interval: int | None,
        end_after: str | None,
        end_date: str | None,
        iterations: int | None,
        monthly_day: int | None,
        monthly_ordinal: str | None,
        monthly_weekday: str | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        links: dict[str, Any] = {}

        if title is not None:
            hidden_fields.ensure_field_writable("recurring_meeting", "title", settings=self._settings)
            payload["title"] = title
        if frequency is not None:
            hidden_fields.ensure_field_writable("recurring_meeting", "frequency", settings=self._settings)
            payload["frequency"] = frequency
        if start_time is not None:
            hidden_fields.ensure_field_writable("recurring_meeting", "start_time", settings=self._settings)
            payload["startTime"] = start_time
        if interval is not None:
            hidden_fields.ensure_field_writable("recurring_meeting", "interval", settings=self._settings)
            payload["interval"] = interval
        if end_after is not None:
            hidden_fields.ensure_field_writable("recurring_meeting", "end_after", settings=self._settings)
            payload["endAfter"] = end_after
        if end_date is not None:
            hidden_fields.ensure_field_writable("recurring_meeting", "end_date", settings=self._settings)
            payload["endDate"] = end_date
        if iterations is not None:
            hidden_fields.ensure_field_writable("recurring_meeting", "iterations", settings=self._settings)
            payload["iterations"] = iterations
        if monthly_day is not None:
            hidden_fields.ensure_field_writable("recurring_meeting", "monthly_day", settings=self._settings)
            payload["monthlyDay"] = monthly_day
        if monthly_ordinal is not None:
            hidden_fields.ensure_field_writable("recurring_meeting", "monthly_ordinal", settings=self._settings)
            payload["monthlyOrdinal"] = monthly_ordinal
        if monthly_weekday is not None:
            hidden_fields.ensure_field_writable("recurring_meeting", "monthly_weekday", settings=self._settings)
            payload["monthlyWeekday"] = monthly_weekday

        if project is not None:
            hidden_fields.ensure_field_writable("recurring_meeting", "project", settings=self._settings)
            project_payload = await self._resolve_project_ref(project, write=False)
            links["project"] = {"href": _api_href(f"projects/{project_payload['id']}", api_prefix=self._api_prefix)}

        if links:
            payload["_links"] = links
        return payload

    async def create(
        self,
        *,
        project: str,
        title: str,
        frequency: str,
        start_time: str,
        interval: int | None = None,
        end_after: str | None = None,
        end_date: str | None = None,
        iterations: int | None = None,
        monthly_day: int | None = None,
        monthly_ordinal: str | None = None,
        monthly_weekday: str | None = None,
        confirm: bool = False,
    ) -> RecurringMeetingWriteResult:
        project_payload = await self._resolve_project_ref(project, write=True)
        payload = await self._build_write_payload(
            project=project,
            title=title,
            frequency=frequency,
            start_time=start_time,
            interval=interval,
            end_after=end_after,
            end_date=end_date,
            iterations=iterations,
            monthly_day=monthly_day,
            monthly_ordinal=monthly_ordinal,
            monthly_weekday=monthly_weekday,
        )
        identity_project = payload.get("_links", {}).get("project", {}).get("title") or project_payload.get("name")

        if not confirm:
            return RecurringMeetingWriteResult(
                action="create",
                state="preview",
                ready=True,
                message=(
                    "OpenProject is ready to create this recurring meeting. Ask for confirmation, "
                    "then call again with confirm=true."
                ),
                recurring_meeting_id=None,
                project=identity_project,
                payload=payload,
                validation_errors={},
                result=None,
            )

        access.ensure_write_enabled("meeting", settings=self._settings)
        record = await self._api.create(payload)
        result = self._stamp(record.summary)
        return RecurringMeetingWriteResult(
            action="create",
            state="confirmed",
            ready=True,
            message="Recurring meeting created successfully.",
            recurring_meeting_id=result.id,
            project=result.project,
            payload=payload,
            validation_errors={},
            result=result,
        )

    async def update(
        self,
        *,
        recurring_meeting_id: int,
        title: str | None = None,
        frequency: str | None = None,
        start_time: str | None = None,
        interval: int | None = None,
        end_after: str | None = None,
        end_date: str | None = None,
        iterations: int | None = None,
        confirm: bool = False,
    ) -> RecurringMeetingWriteResult:
        current = await self._api.get(recurring_meeting_id)
        scope_policy.ensure_project_write_link_allowed(
            current.project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        payload = await self._build_write_payload(
            project=None,
            title=title,
            frequency=frequency,
            start_time=start_time,
            interval=interval,
            end_after=end_after,
            end_date=end_date,
            iterations=iterations,
            monthly_day=None,
            monthly_ordinal=None,
            monthly_weekday=None,
        )

        if not confirm:
            return RecurringMeetingWriteResult(
                action="update",
                state="preview",
                ready=True,
                message="Ask for confirmation, then call again with confirm=true to update it.",
                recurring_meeting_id=recurring_meeting_id,
                project=current.summary.project,
                payload=payload,
                validation_errors={},
                result=None,
            )

        access.ensure_write_enabled("meeting", settings=self._settings)
        record = await self._api.update(recurring_meeting_id, payload)
        result = self._stamp(record.summary)
        return RecurringMeetingWriteResult(
            action="update",
            state="confirmed",
            ready=True,
            message="Recurring meeting updated successfully.",
            recurring_meeting_id=result.id,
            project=result.project,
            payload=payload,
            validation_errors={},
            result=result,
        )

    async def delete(self, *, recurring_meeting_id: int, confirm: bool = False) -> RecurringMeetingWriteResult:
        current = await self._api.get(recurring_meeting_id)
        scope_policy.ensure_project_write_link_allowed(
            current.project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        recurring_meeting = self._stamp(current.summary)
        payload = {"id": recurring_meeting.id, "title": recurring_meeting.title}

        if not confirm:
            return RecurringMeetingWriteResult(
                action="delete",
                state="preview",
                ready=True,
                message=(
                    "OpenProject found the recurring meeting. Ask for confirmation, then call again "
                    "with confirm=true to delete it."
                ),
                recurring_meeting_id=recurring_meeting.id,
                project=recurring_meeting.project,
                payload=payload,
                validation_errors={},
                result=None,
            )

        access.ensure_write_enabled("meeting", settings=self._settings)
        await self._api.delete(recurring_meeting_id)
        return RecurringMeetingWriteResult(
            action="delete",
            state="confirmed",
            ready=True,
            message="Recurring meeting deleted successfully.",
            recurring_meeting_id=recurring_meeting.id,
            project=recurring_meeting.project,
            payload=payload,
            validation_errors={},
            result=recurring_meeting,
        )

    async def list_occurrences(
        self, recurring_meeting_id: int, *, filter: str = "upcoming", limit: int | None = None
    ) -> RecurringMeetingOccurrenceListResult:
        access.ensure_read_enabled("meeting", settings=self._settings)
        current = await self._api.get(recurring_meeting_id)
        scope_policy.ensure_project_link_allowed(
            current.project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        records = await self._api.list_occurrences(recurring_meeting_id, filter=filter, limit=limit)
        results = [self._stamp_occurrence(record.summary) for record in records]
        return RecurringMeetingOccurrenceListResult(
            recurring_meeting_id=recurring_meeting_id,
            filter=filter,
            count=len(results),
            results=results,
        )

    async def _ensure_recurring_meeting_write_allowed(self, recurring_meeting_id: int) -> Any:
        current = await self._api.get(recurring_meeting_id)
        scope_policy.ensure_project_write_link_allowed(
            current.project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        return current

    async def init_occurrence(
        self, *, recurring_meeting_id: int, start_time: str, confirm: bool = False
    ) -> RecurringMeetingOccurrenceWriteResult:
        await self._ensure_recurring_meeting_write_allowed(recurring_meeting_id)
        payload = {"recurring_meeting_id": recurring_meeting_id, "start_time": start_time}

        if not confirm:
            return RecurringMeetingOccurrenceWriteResult(
                action="init",
                state="preview",
                ready=True,
                message=(
                    "OpenProject is ready to materialize this occurrence into a real meeting. "
                    "Ask for confirmation, then call again with confirm=true."
                ),
                recurring_meeting_id=recurring_meeting_id,
                start_time=start_time,
                payload=payload,
                validation_errors={},
                result=None,
            )

        access.ensure_write_enabled("meeting", settings=self._settings)
        meeting: MeetingSummary = await self._api.init_occurrence(recurring_meeting_id, start_time=start_time)
        return RecurringMeetingOccurrenceWriteResult(
            action="init",
            state="confirmed",
            ready=True,
            message="Occurrence materialized into a real meeting successfully.",
            recurring_meeting_id=recurring_meeting_id,
            start_time=start_time,
            payload=payload,
            validation_errors={},
            result=hidden_fields.apply_hidden_fields("meeting", meeting, settings=self._settings),
        )

    async def cancel_occurrence(
        self, *, recurring_meeting_id: int, start_time: str, confirm: bool = False
    ) -> RecurringMeetingOccurrenceWriteResult:
        await self._ensure_recurring_meeting_write_allowed(recurring_meeting_id)
        payload = {"recurring_meeting_id": recurring_meeting_id, "start_time": start_time}

        if not confirm:
            return RecurringMeetingOccurrenceWriteResult(
                action="cancel",
                state="preview",
                ready=True,
                message=(
                    "Ask for confirmation, then call again with confirm=true to cancel it. If this "
                    "occurrence has not yet been materialized, OpenProject will create a new, "
                    "permanently cancelled meeting -- this call returns no id for it."
                ),
                recurring_meeting_id=recurring_meeting_id,
                start_time=start_time,
                payload=payload,
                validation_errors={},
                result=None,
            )

        access.ensure_write_enabled("meeting", settings=self._settings)
        await self._api.cancel_occurrence(recurring_meeting_id, start_time=start_time)
        return RecurringMeetingOccurrenceWriteResult(
            action="cancel",
            state="confirmed",
            ready=True,
            message="Occurrence cancelled successfully.",
            recurring_meeting_id=recurring_meeting_id,
            start_time=start_time,
            payload=payload,
            validation_errors={},
            result=None,
        )
