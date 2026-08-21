"""Application Service for the Meeting Outcomes domain (OpenProject 17.6+).

Depends on `MeetingOutcomeApi` (its own domain Port), `MeetingAgendaItemApi`
and `MeetingApi` (two cross-domain Port dependencies -- an outcome has no
project of its own, only a grandparent Meeting reached via its parent
Agenda Item). Reuses the `"meeting"` scope.

`get`/`update`/`delete` take a bare `outcome_id` -- OpenProject's own
global-namespace route already does an authoritative
`MeetingOutcome.joins(meeting_agenda_item: { meeting: :project }).merge(
Meeting.visible).find(id)` server-side (verified against source), so the
fetched `meeting_agenda_item_id` is not a caller-supplied claim needing
independent cross-verification -- this resolves the domain's explicit
bypass-check requirement.

`list_for_agenda_item` requires walking agenda_item -> meeting first (the
underlying route needs both ids in its path) -- `_ensure_via_agenda_item`
does this walk once and returns the resolved `meeting_id`, used by both the
allowlist check and the list call's path. UNPAGINATED upstream -- limit/
offset applied client-side via `paginate_client`.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...models import MeetingOutcomeListResult, MeetingOutcomeSummary, MeetingOutcomeWriteResult
from ..api_href import api_href as _api_href
from ..errors import NotFoundError
from ..pagination import clamp_limit, paginate_client
from ..policies import access, hidden_fields
from ..policies import scope as scope_policy
from ..ports.meeting_agenda_item_api import MeetingAgendaItemApi
from ..ports.meeting_api import MeetingApi
from ..ports.meeting_outcome_api import MeetingOutcomeApi


class MeetingOutcomeService:
    def __init__(
        self,
        *,
        api: MeetingOutcomeApi,
        meeting_agenda_item_api: MeetingAgendaItemApi,
        meeting_api: MeetingApi,
        settings: Settings,
        project_id_to_identifier: dict[int, str],
        api_prefix: str,
    ) -> None:
        self._api = api
        self._meeting_agenda_item_api = meeting_agenda_item_api
        self._meeting_api = meeting_api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier
        self._api_prefix = api_prefix

    def _stamp(self, summary: MeetingOutcomeSummary) -> MeetingOutcomeSummary:
        return hidden_fields.apply_hidden_fields("meeting_outcome", summary, settings=self._settings)

    async def _ensure_via_agenda_item(self, agenda_item_id: int, *, write: bool) -> int:
        """Fetch agenda item -> extract meeting_id -> fetch meeting -> check
        allowlist against the meeting's project. Returns meeting_id (needed
        by list_for_agenda_item's two-id path)."""
        agenda_item = await self._meeting_agenda_item_api.get(agenda_item_id)
        meeting_id = agenda_item.summary.meeting_id
        if meeting_id is None:
            raise NotFoundError(f"OpenProject meeting agenda item {agenda_item_id} has no parent meeting.")
        meeting = await self._meeting_api.get(meeting_id)
        if write:
            scope_policy.ensure_project_write_link_allowed(
                meeting.project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
            )
        else:
            scope_policy.ensure_project_link_allowed(
                meeting.project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
            )
        return meeting_id

    async def list_for_agenda_item(
        self, agenda_item_id: int, *, offset: int = 1, limit: int | None = None, text_limit: int | None = None
    ) -> MeetingOutcomeListResult:
        access.ensure_read_enabled("meeting", settings=self._settings)
        effective_limit = clamp_limit(
            limit,
            default_page_size=self._settings.default_page_size,
            max_page_size=self._settings.max_page_size,
            max_results=self._settings.max_results,
        )
        meeting_id = await self._ensure_via_agenda_item(agenda_item_id, write=False)
        records = await self._api.list_for_agenda_item(meeting_id, agenda_item_id, text_limit=text_limit)
        summaries = [self._stamp(record.summary) for record in records]
        page, total, next_offset, truncated = paginate_client(offset=offset, limit=effective_limit, results=summaries)
        return MeetingOutcomeListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(page),
            next_offset=next_offset,
            truncated=truncated,
            results=page,
        )

    async def _ensure_outcome_allowed(
        self, outcome_id: int, meeting_agenda_item_id: int | None, *, write: bool
    ) -> None:
        if meeting_agenda_item_id is None:
            # meeting_agenda_item_id is a mandatory belongs_to upstream
            # (validates presence: true) and the global route's own join
            # already excludes orphans, so this should be unreachable via
            # the live API -- but a None here must never silently skip the
            # allowlist check (fail closed, not fail open).
            raise NotFoundError(f"OpenProject meeting outcome {outcome_id} has no parent agenda item.")
        await self._ensure_via_agenda_item(meeting_agenda_item_id, write=write)

    async def get(self, outcome_id: int) -> MeetingOutcomeSummary:
        access.ensure_read_enabled("meeting", settings=self._settings)
        record = await self._api.get(outcome_id)
        await self._ensure_outcome_allowed(outcome_id, record.summary.meeting_agenda_item_id, write=False)
        return self._stamp(record.summary)

    async def _build_write_payload(
        self,
        *,
        agenda_item_id: int | None,
        kind: str | None,
        notes: str | None,
        work_package_id: int | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        links: dict[str, Any] = {}

        if kind is not None:
            hidden_fields.ensure_field_writable("meeting_outcome", "kind", settings=self._settings)
            payload["kind"] = kind
        if notes is not None:
            hidden_fields.ensure_field_writable("meeting_outcome", "notes", settings=self._settings)
            payload["notes"] = {"format": "markdown", "raw": notes}

        if agenda_item_id is not None:
            hidden_fields.ensure_field_writable("meeting_outcome", "meeting_agenda_item", settings=self._settings)
            links["agendaItem"] = {
                "href": _api_href(f"meeting_agenda_items/{agenda_item_id}", api_prefix=self._api_prefix)
            }
        if work_package_id is not None:
            hidden_fields.ensure_field_writable("meeting_outcome", "work_package", settings=self._settings)
            links["workPackage"] = {"href": _api_href(f"work_packages/{work_package_id}", api_prefix=self._api_prefix)}

        if links:
            payload["_links"] = links
        return payload

    async def create(
        self,
        *,
        agenda_item_id: int,
        kind: str,
        notes: str | None = None,
        work_package_id: int | None = None,
        confirm: bool = False,
    ) -> MeetingOutcomeWriteResult:
        await self._ensure_via_agenda_item(agenda_item_id, write=True)
        payload = await self._build_write_payload(
            agenda_item_id=agenda_item_id, kind=kind, notes=notes, work_package_id=work_package_id
        )
        if not confirm:
            return MeetingOutcomeWriteResult(
                action="create",
                state="preview",
                ready=True,
                message=(
                    "OpenProject is ready to create this meeting outcome. Ask for confirmation, "
                    "then call again with confirm=true."
                ),
                outcome_id=None,
                meeting_agenda_item_id=agenda_item_id,
                payload=payload,
                validation_errors={},
                result=None,
            )

        access.ensure_write_enabled("meeting", settings=self._settings)
        record = await self._api.create(payload)
        result = self._stamp(record.summary)
        return MeetingOutcomeWriteResult(
            action="create",
            state="confirmed",
            ready=True,
            message="Meeting outcome created successfully.",
            outcome_id=result.id,
            meeting_agenda_item_id=result.meeting_agenda_item_id,
            payload=payload,
            validation_errors={},
            result=result,
        )

    async def update(
        self,
        *,
        outcome_id: int,
        kind: str | None = None,
        notes: str | None = None,
        work_package_id: int | None = None,
        confirm: bool = False,
    ) -> MeetingOutcomeWriteResult:
        current = await self._api.get(outcome_id)
        agenda_item_id = current.summary.meeting_agenda_item_id
        await self._ensure_outcome_allowed(outcome_id, agenda_item_id, write=True)
        payload = await self._build_write_payload(
            agenda_item_id=None, kind=kind, notes=notes, work_package_id=work_package_id
        )
        if not confirm:
            return MeetingOutcomeWriteResult(
                action="update",
                state="preview",
                ready=True,
                message="Ask for confirmation, then call again with confirm=true to update it.",
                outcome_id=outcome_id,
                meeting_agenda_item_id=agenda_item_id,
                payload=payload,
                validation_errors={},
                result=None,
            )

        access.ensure_write_enabled("meeting", settings=self._settings)
        record = await self._api.update(outcome_id, payload)
        result = self._stamp(record.summary)
        return MeetingOutcomeWriteResult(
            action="update",
            state="confirmed",
            ready=True,
            message="Meeting outcome updated successfully.",
            outcome_id=result.id,
            meeting_agenda_item_id=result.meeting_agenda_item_id,
            payload=payload,
            validation_errors={},
            result=result,
        )

    async def delete(self, *, outcome_id: int, confirm: bool = False) -> MeetingOutcomeWriteResult:
        current = await self._api.get(outcome_id)
        agenda_item_id = current.summary.meeting_agenda_item_id
        await self._ensure_outcome_allowed(outcome_id, agenda_item_id, write=True)
        outcome = self._stamp(current.summary)
        payload = {"id": outcome.id, "kind": outcome.kind}

        if not confirm:
            return MeetingOutcomeWriteResult(
                action="delete",
                state="preview",
                ready=True,
                message="OpenProject found the outcome. Ask for confirmation, then call again with confirm=true to delete it.",
                outcome_id=outcome.id,
                meeting_agenda_item_id=outcome.meeting_agenda_item_id,
                payload=payload,
                validation_errors={},
                result=None,
            )

        access.ensure_write_enabled("meeting", settings=self._settings)
        await self._api.delete(outcome_id)
        return MeetingOutcomeWriteResult(
            action="delete",
            state="confirmed",
            ready=True,
            message="Meeting outcome deleted successfully.",
            outcome_id=outcome.id,
            meeting_agenda_item_id=outcome.meeting_agenda_item_id,
            payload=payload,
            validation_errors={},
            result=outcome,
        )
