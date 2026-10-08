"""Application Service for the Meeting Sections domain.

Depends on `MeetingSectionApi` (its own domain Port) and `MeetingApi` (the
cross-domain Port precedent used throughout this batch -- a section has no
project of its own, only a parent Meeting). Reuses the `"meeting"` scope.

`get`/`update`/`delete` take a bare `section_id` -- same fetch-then-check
reasoning as Meeting Agenda Items: OpenProject's own global-namespace route
already does an authoritative
`MeetingSection.joins(meeting: :project).merge(Meeting.visible).find(id)`
server-side, so the fetched `meeting_id` is not a caller-supplied claim
needing independent cross-verification.

`backlog` is create-only: OpenProject documents a meeting having at most one
backlog section, effectively system-managed, and no evidence in the
representer suggests `update()` should ever flip it -- `update()` therefore
does not expose it as a parameter (see the docstring on `update()` below).

`list_for_meeting` is UNPAGINATED upstream -- limit/offset are applied
client-side via `paginate_client`, matching Meeting Agenda Items.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...config import Settings
from ...models import MeetingSectionListResult, MeetingSectionSummary, MeetingSectionWriteResult
from ..api_href import api_href as _api_href
from ..errors import NotFoundError
from ..pagination import clamp_limit, paginate_client
from ..policies import access, hidden_fields
from ..policies import scope as scope_policy
from ..ports.meeting_api import MeetingApi
from ..ports.meeting_section_api import MeetingSectionApi
from ..version_gate import call_version_gated
from ._write_outcome import _finalize_write, _WriteOutcome


class MeetingSectionService:
    def __init__(
        self,
        *,
        api: MeetingSectionApi,
        meeting_api: MeetingApi,
        settings: Settings,
        project_id_to_identifier: Mapping[int, str],
        api_prefix: str,
    ) -> None:
        self._api = api
        self._meeting_api = meeting_api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier
        self._api_prefix = api_prefix

    def _stamp(self, summary: MeetingSectionSummary) -> MeetingSectionSummary:
        return hidden_fields.apply_hidden_fields("meeting_section", summary, settings=self._settings)

    async def _ensure_meeting_allowed(self, meeting_id: int, *, write: bool) -> None:
        meeting = await call_version_gated(lambda: self._meeting_api.get(meeting_id), feature="Meetings", floor="17.4")
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
    ) -> MeetingSectionListResult:
        access.ensure_read_enabled("meeting", settings=self._settings)
        effective_limit = clamp_limit(
            limit,
            default_page_size=self._settings.default_page_size,
            max_page_size=self._settings.max_page_size,
            max_results=self._settings.max_results,
        )
        await self._ensure_meeting_allowed(meeting_id, write=False)
        records = await call_version_gated(
            lambda: self._api.list_for_meeting(meeting_id), feature="Meeting sections", floor="17.4"
        )
        summaries = [self._stamp(record.summary) for record in records]
        page, total, next_offset, truncated = paginate_client(offset=offset, limit=effective_limit, results=summaries)
        return MeetingSectionListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(page),
            next_offset=next_offset,
            truncated=truncated,
            results=page,
        )

    async def get(self, section_id: int) -> MeetingSectionSummary:
        access.ensure_read_enabled("meeting", settings=self._settings)
        record = await call_version_gated(lambda: self._api.get(section_id), feature="Meeting sections", floor="17.6")
        meeting_id = record.summary.meeting_id
        if meeting_id is None:
            # meeting_id is a mandatory belongs_to upstream and the global
            # route's own join already excludes orphans, so this should be
            # unreachable via the live API -- but a None here must never
            # silently skip the allowlist check (fail closed, not fail open).
            raise NotFoundError(f"OpenProject meeting section {section_id} has no parent meeting.")
        await self._ensure_meeting_allowed(meeting_id, write=False)
        return self._stamp(record.summary)

    async def create(
        self,
        *,
        meeting_id: int,
        title: str,
        position: int | None = None,
        backlog: bool | None = None,
        confirm: bool = False,
    ) -> MeetingSectionWriteResult:
        await self._ensure_meeting_allowed(meeting_id, write=True)
        payload: dict[str, Any] = {}
        links: dict[str, Any] = {}

        hidden_fields.ensure_field_writable("meeting_section", "title", settings=self._settings)
        payload["title"] = title
        if position is not None:
            hidden_fields.ensure_field_writable("meeting_section", "position", settings=self._settings)
            payload["position"] = position
        if backlog is not None:
            hidden_fields.ensure_field_writable("meeting_section", "backlog", settings=self._settings)
            payload["backlog"] = backlog
        hidden_fields.ensure_field_writable("meeting_section", "meeting", settings=self._settings)
        links["meeting"] = {"href": _api_href(f"meetings/{meeting_id}", api_prefix=self._api_prefix)}
        payload["_links"] = links

        async def _commit(p: dict[str, Any]) -> MeetingSectionSummary:
            record = await call_version_gated(lambda: self._api.create(p), feature="Meeting sections", floor="17.6")
            return self._stamp(record.summary)

        outcome = await _finalize_write(
            confirm=confirm,
            payload=payload,
            validation_errors={},
            identity={"section_id": None, "meeting_id": meeting_id},
            ensure_write_enabled=lambda: access.ensure_write_enabled("meeting", settings=self._settings),
            commit=_commit,
            committed_identity=lambda d: {"section_id": d.id, "meeting_id": d.meeting_id},
            rejected_message="",
            preview_message=(
                "OpenProject is ready to create this meeting section. Ask for confirmation, "
                "then call again with confirm=true."
            ),
            success_message="Meeting section created successfully.",
        )
        return self._to_write_result("create", outcome)

    async def update(
        self,
        *,
        section_id: int,
        title: str | None = None,
        position: int | None = None,
        confirm: bool = False,
    ) -> MeetingSectionWriteResult:
        """Update a meeting section's title/position.

        `backlog` cannot be changed after creation -- pass it only on create().
        """
        current = await call_version_gated(lambda: self._api.get(section_id), feature="Meeting sections", floor="17.6")
        meeting_id = current.summary.meeting_id
        if meeting_id is None:
            # See get()'s comment: fail closed rather than silently skip the
            # allowlist check if this were ever None.
            raise NotFoundError(f"OpenProject meeting section {section_id} has no parent meeting.")
        await self._ensure_meeting_allowed(meeting_id, write=True)
        payload: dict[str, Any] = {}
        if title is not None:
            hidden_fields.ensure_field_writable("meeting_section", "title", settings=self._settings)
            payload["title"] = title
        if position is not None:
            hidden_fields.ensure_field_writable("meeting_section", "position", settings=self._settings)
            payload["position"] = position

        async def _commit(p: dict[str, Any]) -> MeetingSectionSummary:
            record = await call_version_gated(
                lambda: self._api.update(section_id, p), feature="Meeting sections", floor="17.6"
            )
            return self._stamp(record.summary)

        outcome = await _finalize_write(
            confirm=confirm,
            payload=payload,
            validation_errors={},
            identity={"section_id": section_id, "meeting_id": meeting_id},
            ensure_write_enabled=lambda: access.ensure_write_enabled("meeting", settings=self._settings),
            commit=_commit,
            committed_identity=lambda d: {"section_id": d.id, "meeting_id": d.meeting_id},
            rejected_message="",
            preview_message="Ask for confirmation, then call again with confirm=true to update it.",
            success_message="Meeting section updated successfully.",
        )
        return self._to_write_result("update", outcome)

    async def delete(self, *, section_id: int, confirm: bool = False) -> MeetingSectionWriteResult:
        current = await call_version_gated(lambda: self._api.get(section_id), feature="Meeting sections", floor="17.6")
        meeting_id = current.summary.meeting_id
        if meeting_id is None:
            # See get()'s comment: fail closed rather than silently skip the
            # allowlist check if this were ever None.
            raise NotFoundError(f"OpenProject meeting section {section_id} has no parent meeting.")
        await self._ensure_meeting_allowed(meeting_id, write=True)
        section = self._stamp(current.summary)
        payload = {"id": section.id, "title": section.title}

        async def _commit(p: dict[str, Any]) -> MeetingSectionSummary:
            await call_version_gated(lambda: self._api.delete(section_id), feature="Meeting sections", floor="17.6")
            return section

        outcome = await _finalize_write(
            confirm=confirm,
            payload=payload,
            validation_errors={},
            identity={"section_id": section.id, "meeting_id": section.meeting_id},
            ensure_write_enabled=lambda: access.ensure_write_enabled("meeting", settings=self._settings),
            commit=_commit,
            committed_identity=lambda d: {"section_id": d.id, "meeting_id": d.meeting_id},
            rejected_message="",
            preview_message="OpenProject found the section. Ask for confirmation, then call again with confirm=true to delete it.",
            success_message="Meeting section deleted successfully.",
        )
        return self._to_write_result("delete", outcome)

    def _to_write_result(self, action: str, outcome: _WriteOutcome[MeetingSectionSummary]) -> MeetingSectionWriteResult:
        return MeetingSectionWriteResult(
            action=action,
            state=outcome.state,
            ready=outcome.ready,
            message=outcome.message,
            payload=outcome.payload,
            validation_errors=outcome.validation_errors,
            result=outcome.detail,
            **outcome.identity,
        )
