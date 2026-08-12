"""Application Service for the Meeting Agenda Items domain.

Depends on `MeetingAgendaItemApi` (its own domain Port), `MeetingApi` (a
second, cross-domain Port -- the precedent this project already established
for WorkPackageService->ActivityApi/FileLinkService->WorkPackageLookupApi:
an agenda item has no project of its own, only a parent Meeting, so its
allowlist check walks through the parent), and `WorkPackageIdResolver`
(resolving an optional `work_package_id` write-target reference). Reuses the
`"meeting"` scope, not a dedicated `"meeting_agenda_item"` scope -- all five
sub-resources in this batch share one scope pair.

`get`/`update`/`delete` take a bare `agenda_item_id` (matching the global
`meeting_agenda_items/{id}` route shape) -- each fetches the record first via
`api.get()`, extracts `meeting_id` from the returned summary, then checks the
allowlist against the PARENT MEETING's project (fetched via `meeting_api`).
This is safe fetch-then-check, NOT the Wiki-Page-Links-style two-argument
"verify caller-supplied parent" pattern: OpenProject's own global-namespace
route already does an authoritative
`MeetingAgendaItem.joins(meeting: :project).merge(Meeting.visible).find(id)`
server-side (verified against source), so the fetched `meeting_id` is not a
caller-supplied claim needing independent cross-verification -- there is no
caller-supplied parent id on these bare-id calls at all.

`list_for_meeting`/`list_for_work_package` are UNPAGINATED upstream (verified:
neither underlying route accepts offset/pageSize) -- limit/offset are applied
client-side via `paginate_client`, not `scan_records_and_paginate`/
`paginate_all` (both assume a re-fetchable paged fetcher, which doesn't
exist here).
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...models import MeetingAgendaItemListResult, MeetingAgendaItemSummary, MeetingAgendaItemWriteResult
from ..api_href import api_href as _api_href
from ..pagination import clamp_limit, paginate_client
from ..policies import access, hidden_fields
from ..policies import scope as scope_policy
from ..ports.meeting_agenda_item_api import MeetingAgendaItemApi
from ..ports.meeting_api import MeetingApi
from ..ports.work_package_ref import WorkPackageIdResolver


class MeetingAgendaItemService:
    def __init__(
        self,
        *,
        api: MeetingAgendaItemApi,
        meeting_api: MeetingApi,
        settings: Settings,
        project_id_to_identifier: dict[int, str],
        resolve_work_package_id: WorkPackageIdResolver,
        api_prefix: str,
    ) -> None:
        self._api = api
        self._meeting_api = meeting_api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier
        self._resolve_work_package_id = resolve_work_package_id
        self._api_prefix = api_prefix

    def _stamp(self, summary: MeetingAgendaItemSummary) -> MeetingAgendaItemSummary:
        return hidden_fields.apply_hidden_fields("meeting_agenda_item", summary, settings=self._settings)

    async def _ensure_meeting_allowed(self, meeting_id: int, *, write: bool) -> None:
        meeting = await self._meeting_api.get(meeting_id)
        if write:
            scope_policy.ensure_project_write_link_allowed(
                meeting.project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
            )
        else:
            scope_policy.ensure_project_link_allowed(
                meeting.project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
            )

    async def list_for_meeting(
        self, meeting_id: int, *, offset: int = 1, limit: int | None = None
    ) -> MeetingAgendaItemListResult:
        access.ensure_read_enabled("meeting", settings=self._settings)
        effective_limit = clamp_limit(
            limit,
            default_page_size=self._settings.default_page_size,
            max_page_size=self._settings.max_page_size,
            max_results=self._settings.max_results,
        )
        await self._ensure_meeting_allowed(meeting_id, write=False)
        records = await self._api.list_for_meeting(meeting_id)
        summaries = [self._stamp(record.summary) for record in records]
        page, total, next_offset, truncated = paginate_client(offset=offset, limit=effective_limit, results=summaries)
        return MeetingAgendaItemListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(page),
            next_offset=next_offset,
            truncated=truncated,
            results=page,
        )

    async def list_for_work_package(
        self, work_package_id: int | str, *, offset: int = 1, limit: int | None = None
    ) -> MeetingAgendaItemListResult:
        access.ensure_read_enabled("meeting", settings=self._settings)
        effective_limit = clamp_limit(
            limit,
            default_page_size=self._settings.default_page_size,
            max_page_size=self._settings.max_page_size,
            max_results=self._settings.max_results,
        )
        resolved_id = await self._resolve_work_package_id(work_package_id, write=False)
        records = await self._api.list_for_work_package(resolved_id)
        summaries = [self._stamp(record.summary) for record in records]
        page, total, next_offset, truncated = paginate_client(offset=offset, limit=effective_limit, results=summaries)
        return MeetingAgendaItemListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(page),
            next_offset=next_offset,
            truncated=truncated,
            results=page,
        )

    async def get(self, agenda_item_id: int) -> MeetingAgendaItemSummary:
        access.ensure_read_enabled("meeting", settings=self._settings)
        record = await self._api.get(agenda_item_id)
        meeting_id = record.summary.meeting_id
        if meeting_id is not None:
            await self._ensure_meeting_allowed(meeting_id, write=False)
        return self._stamp(record.summary)

    async def _build_write_payload(
        self,
        *,
        meeting_id: int | None,
        title: str | None,
        notes: str | None,
        duration_in_minutes: int | None,
        item_type: str | None,
        work_package_id: int | None,
        meeting_section_id: int | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        links: dict[str, Any] = {}

        if title is not None:
            hidden_fields.ensure_field_writable("meeting_agenda_item", "title", settings=self._settings)
            payload["title"] = title
        if notes is not None:
            hidden_fields.ensure_field_writable("meeting_agenda_item", "notes", settings=self._settings)
            payload["notes"] = {"format": "markdown", "raw": notes}
        if duration_in_minutes is not None:
            hidden_fields.ensure_field_writable("meeting_agenda_item", "duration_in_minutes", settings=self._settings)
            payload["durationInMinutes"] = duration_in_minutes
        if item_type is not None:
            hidden_fields.ensure_field_writable("meeting_agenda_item", "item_type", settings=self._settings)
            payload["itemType"] = item_type

        if meeting_id is not None:
            hidden_fields.ensure_field_writable("meeting_agenda_item", "meeting", settings=self._settings)
            links["meeting"] = {"href": _api_href(f"meetings/{meeting_id}", api_prefix=self._api_prefix)}
        if work_package_id is not None:
            hidden_fields.ensure_field_writable("meeting_agenda_item", "work_package", settings=self._settings)
            links["workPackage"] = {"href": _api_href(f"work_packages/{work_package_id}", api_prefix=self._api_prefix)}
        if meeting_section_id is not None:
            hidden_fields.ensure_field_writable("meeting_agenda_item", "meeting_section", settings=self._settings)
            links["section"] = {
                "href": _api_href(f"meeting_sections/{meeting_section_id}", api_prefix=self._api_prefix)
            }

        if links:
            payload["_links"] = links
        return payload

    async def create(
        self,
        *,
        meeting_id: int,
        title: str,
        notes: str | None = None,
        duration_in_minutes: int | None = None,
        item_type: str | None = None,
        work_package_id: int | str | None = None,
        meeting_section_id: int | None = None,
        confirm: bool = False,
    ) -> MeetingAgendaItemWriteResult:
        await self._ensure_meeting_allowed(meeting_id, write=True)
        resolved_work_package_id: int | None = None
        if work_package_id is not None:
            resolved_work_package_id = await self._resolve_work_package_id(work_package_id, write=False)
        payload = await self._build_write_payload(
            meeting_id=meeting_id,
            title=title,
            notes=notes,
            duration_in_minutes=duration_in_minutes,
            item_type=item_type,
            work_package_id=resolved_work_package_id,
            meeting_section_id=meeting_section_id,
        )
        if not confirm:
            return MeetingAgendaItemWriteResult(
                action="create",
                state="preview",
                ready=True,
                message=(
                    "OpenProject is ready to create this meeting agenda item. Ask for confirmation, "
                    "then call again with confirm=true."
                ),
                agenda_item_id=None,
                meeting_id=meeting_id,
                payload=payload,
                validation_errors={},
                result=None,
            )

        access.ensure_write_enabled("meeting", settings=self._settings)
        record = await self._api.create(payload)
        result = self._stamp(record.summary)
        return MeetingAgendaItemWriteResult(
            action="create",
            state="confirmed",
            ready=True,
            message="Meeting agenda item created successfully.",
            agenda_item_id=result.id,
            meeting_id=result.meeting_id,
            payload=payload,
            validation_errors={},
            result=result,
        )

    async def update(
        self,
        *,
        agenda_item_id: int,
        title: str | None = None,
        notes: str | None = None,
        duration_in_minutes: int | None = None,
        item_type: str | None = None,
        work_package_id: int | str | None = None,
        meeting_section_id: int | None = None,
        confirm: bool = False,
    ) -> MeetingAgendaItemWriteResult:
        current = await self._api.get(agenda_item_id)
        meeting_id = current.summary.meeting_id
        if meeting_id is not None:
            await self._ensure_meeting_allowed(meeting_id, write=True)
        resolved_work_package_id: int | None = None
        if work_package_id is not None:
            resolved_work_package_id = await self._resolve_work_package_id(work_package_id, write=False)
        payload = await self._build_write_payload(
            meeting_id=None,
            title=title,
            notes=notes,
            duration_in_minutes=duration_in_minutes,
            item_type=item_type,
            work_package_id=resolved_work_package_id,
            meeting_section_id=meeting_section_id,
        )
        if not confirm:
            return MeetingAgendaItemWriteResult(
                action="update",
                state="preview",
                ready=True,
                message="Ask for confirmation, then call again with confirm=true to update it.",
                agenda_item_id=agenda_item_id,
                meeting_id=meeting_id,
                payload=payload,
                validation_errors={},
                result=None,
            )

        access.ensure_write_enabled("meeting", settings=self._settings)
        record = await self._api.update(agenda_item_id, payload)
        result = self._stamp(record.summary)
        return MeetingAgendaItemWriteResult(
            action="update",
            state="confirmed",
            ready=True,
            message="Meeting agenda item updated successfully.",
            agenda_item_id=result.id,
            meeting_id=result.meeting_id,
            payload=payload,
            validation_errors={},
            result=result,
        )

    async def delete(self, *, agenda_item_id: int, confirm: bool = False) -> MeetingAgendaItemWriteResult:
        current = await self._api.get(agenda_item_id)
        meeting_id = current.summary.meeting_id
        if meeting_id is not None:
            await self._ensure_meeting_allowed(meeting_id, write=True)
        item = self._stamp(current.summary)
        payload = {"id": item.id, "title": item.title}

        if not confirm:
            return MeetingAgendaItemWriteResult(
                action="delete",
                state="preview",
                ready=True,
                message="OpenProject found the agenda item. Ask for confirmation, then call again with confirm=true to delete it.",
                agenda_item_id=item.id,
                meeting_id=item.meeting_id,
                payload=payload,
                validation_errors={},
                result=None,
            )

        access.ensure_write_enabled("meeting", settings=self._settings)
        await self._api.delete(agenda_item_id)
        return MeetingAgendaItemWriteResult(
            action="delete",
            state="confirmed",
            ready=True,
            message="Meeting agenda item deleted successfully.",
            agenda_item_id=item.id,
            meeting_id=item.meeting_id,
            payload=payload,
            validation_errors={},
            result=item,
        )
