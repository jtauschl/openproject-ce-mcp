"""Application Service for the Meetings domain.

Depends on the `MeetingApi` Protocol (never `HttpxMeetingApi` concretely --
enforced by the architecture-boundary test), plus `ProjectRefResolver`,
`ProjectIdResolver` (kept for symmetry with other write-capable domains, not
currently used by any method below), and `PrincipalRefResolver` (participant
resolution). Meetings get their own dedicated `"meeting"` read/write scope
(the domain is large and distinct enough to warrant its own toggle, following
Boards' precedent), shared by all five sub-resources in this batch.

A Meeting always belongs to exactly one project -- `create()` requires
`project`, unlike Boards' optional-project "global board" case.

`create()`/`update()` use the shared `_write_outcome.py` state machine
(`_finalize_write`), matching Boards'/Time Entries'/Grids' form-based shape
(2+ write actions sharing an identical preview/commit/reject contract).
`delete()` has no form step at all (verified: `Endpoints::Delete.new(model:
Meeting).mount` is a direct DELETE, same as every other domain's delete()),
so it stays a flat inline preview/commit method, mirroring
`BoardService.delete()`.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...models import MeetingListResult, MeetingSummary, MeetingWriteResult
from ..api_href import api_href as _api_href
from ..pagination import clamp_limit, paginate_server, scan_records_and_paginate
from ..policies import access, hidden_fields
from ..policies import scope as scope_policy
from ..ports.meeting_api import MeetingApi
from ..ports.principal_ref import PrincipalRefResolver
from ..ports.project_ref import ProjectIdResolver, ProjectRefResolver
from ._write_outcome import _finalize_write, _WriteOutcome


class MeetingService:
    def __init__(
        self,
        *,
        api: MeetingApi,
        settings: Settings,
        project_id_to_identifier: dict[int, str],
        resolve_project_ref: ProjectRefResolver,
        resolve_project_id: ProjectIdResolver,
        resolve_principal_id: PrincipalRefResolver,
        api_prefix: str,
    ) -> None:
        self._api = api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier
        self._resolve_project_ref = resolve_project_ref
        self._resolve_project_id = resolve_project_id
        self._resolve_principal_id = resolve_principal_id
        self._api_prefix = api_prefix

    def _stamp(self, summary: MeetingSummary) -> MeetingSummary:
        return hidden_fields.apply_hidden_fields("meeting", summary, settings=self._settings)

    async def list_all(
        self,
        *,
        project: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> MeetingListResult:
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

        # Server-side project_id filter already restricts results to one
        # project, but the allowlist itself must still be enforced -- an open
        # read scope with no project filter could return meetings from
        # disallowed projects, so a restrictive scope (or no project filter at
        # all) still needs the client-side scan below.
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
            return MeetingListResult(
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
        return MeetingListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(results),
            next_offset=next_offset,
            truncated=truncated,
            results=results,
        )

    async def get(self, meeting_id: int) -> MeetingSummary:
        access.ensure_read_enabled("meeting", settings=self._settings)
        record = await self._api.get(meeting_id)
        scope_policy.ensure_project_link_allowed(
            record.project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        return self._stamp(record.summary)

    async def _build_write_payload(
        self,
        *,
        project: str | None,
        title: str | None,
        location: str | None,
        start_time: str | None,
        duration: str | None,
        state: str | None,
        sharing: str | None,
        notify: bool | None,
        participant_user_refs: list[str] | None,
        lock_version: int | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        links: dict[str, Any] = {}

        if title is not None:
            hidden_fields.ensure_field_writable("meeting", "title", settings=self._settings)
            payload["title"] = title
        if location is not None:
            hidden_fields.ensure_field_writable("meeting", "location", settings=self._settings)
            payload["location"] = location
        if start_time is not None:
            hidden_fields.ensure_field_writable("meeting", "start_time", settings=self._settings)
            payload["startTime"] = start_time
        if duration is not None:
            hidden_fields.ensure_field_writable("meeting", "duration", settings=self._settings)
            payload["duration"] = duration
        if state is not None:
            hidden_fields.ensure_field_writable("meeting", "state", settings=self._settings)
            payload["state"] = state
        if sharing is not None:
            hidden_fields.ensure_field_writable("meeting", "sharing", settings=self._settings)
            payload["sharing"] = sharing
        if notify is not None:
            hidden_fields.ensure_field_writable("meeting", "notify", settings=self._settings)
            payload["notify"] = notify
        if lock_version is not None:
            hidden_fields.ensure_field_writable("meeting", "lock_version", settings=self._settings)
            payload["lockVersion"] = lock_version

        if project is not None:
            hidden_fields.ensure_field_writable("meeting", "project", settings=self._settings)
            project_payload = await self._resolve_project_ref(project, write=False)
            links["project"] = {"href": _api_href(f"projects/{project_payload['id']}", api_prefix=self._api_prefix)}
        if participant_user_refs is not None:
            hidden_fields.ensure_field_writable("meeting", "participants", settings=self._settings)
            participant_hrefs = []
            for ref in participant_user_refs:
                user_id = await self._resolve_principal_id(ref)
                participant_hrefs.append({"href": _api_href(f"users/{user_id}", api_prefix=self._api_prefix)})
            links["participants"] = participant_hrefs

        if links:
            payload["_links"] = links
        return payload

    async def create(
        self,
        *,
        project: str,
        title: str,
        location: str | None = None,
        start_time: str | None = None,
        duration: str | None = None,
        state: str | None = None,
        sharing: str | None = None,
        notify: bool | None = None,
        participant_user_refs: list[str] | None = None,
        confirm: bool = False,
    ) -> MeetingWriteResult:
        project_payload = await self._resolve_project_ref(project, write=True)
        payload = await self._build_write_payload(
            project=project,
            title=title,
            location=location,
            start_time=start_time,
            duration=duration,
            state=state,
            sharing=sharing,
            notify=notify,
            participant_user_refs=participant_user_refs,
            lock_version=None,
        )
        form = await self._api.create_form(payload)
        identity_project = form.payload.get("_links", {}).get("project", {}).get("title") or project_payload.get("name")
        outcome = await _finalize_write(
            confirm=confirm,
            payload=form.payload,
            validation_errors=form.validation_errors,
            identity={"meeting_id": None, "project": identity_project},
            ensure_write_enabled=lambda: access.ensure_write_enabled("meeting", settings=self._settings),
            commit=self._api.commit_create,
            committed_identity=lambda record: {"meeting_id": record.summary.id, "project": record.summary.project},
            rejected_message="OpenProject rejected the proposed meeting. Fix the validation errors before confirming.",
            preview_message="OpenProject validated the meeting. Ask for confirmation, then call again with confirm=true to create it.",
            success_message="Meeting created successfully.",
        )
        return self._to_write_result("create", outcome)

    async def update(
        self,
        *,
        meeting_id: int,
        title: str | None = None,
        location: str | None = None,
        start_time: str | None = None,
        duration: str | None = None,
        state: str | None = None,
        sharing: str | None = None,
        notify: bool | None = None,
        participant_user_refs: list[str] | None = None,
        lock_version: int | None = None,
        confirm: bool = False,
    ) -> MeetingWriteResult:
        current = await self._api.get(meeting_id)
        scope_policy.ensure_project_write_link_allowed(
            current.project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        payload = await self._build_write_payload(
            project=None,
            title=title,
            location=location,
            start_time=start_time,
            duration=duration,
            state=state,
            sharing=sharing,
            notify=notify,
            participant_user_refs=participant_user_refs,
            lock_version=lock_version,
        )
        form = await self._api.update_form(meeting_id, payload)
        identity_project = form.payload.get("_links", {}).get("project", {}).get("title") or current.summary.project
        outcome = await _finalize_write(
            confirm=confirm,
            payload=form.payload,
            validation_errors=form.validation_errors,
            identity={"meeting_id": meeting_id, "project": identity_project},
            ensure_write_enabled=lambda: access.ensure_write_enabled("meeting", settings=self._settings),
            commit=lambda p: self._api.commit_update(meeting_id, p),
            committed_identity=lambda record: {"meeting_id": record.summary.id, "project": record.summary.project},
            rejected_message="OpenProject rejected the proposed meeting changes. Fix the validation errors before confirming.",
            preview_message="OpenProject validated the meeting update. Ask for confirmation, then call again with confirm=true to write it.",
            success_message="Meeting updated successfully.",
        )
        return self._to_write_result("update", outcome)

    async def delete(self, *, meeting_id: int, confirm: bool = False) -> MeetingWriteResult:
        current = await self._api.get(meeting_id)
        scope_policy.ensure_project_write_link_allowed(
            current.project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        meeting = self._stamp(current.summary)
        payload = {"id": meeting.id, "title": meeting.title}

        if not confirm:
            return MeetingWriteResult(
                action="delete",
                state="preview",
                ready=True,
                message="OpenProject found the meeting. Ask for confirmation, then call again with confirm=true to delete it.",
                meeting_id=meeting.id,
                project=meeting.project,
                payload=payload,
                validation_errors={},
                result=None,
            )

        access.ensure_write_enabled("meeting", settings=self._settings)
        await self._api.delete(meeting_id)
        return MeetingWriteResult(
            action="delete",
            state="confirmed",
            ready=True,
            message="Meeting deleted successfully.",
            meeting_id=meeting.id,
            project=meeting.project,
            payload=payload,
            validation_errors={},
            result=meeting,
        )

    def _to_write_result(self, action: str, outcome: _WriteOutcome[Any]) -> MeetingWriteResult:
        return MeetingWriteResult(
            action=action,
            state=outcome.state,
            ready=outcome.ready,
            message=outcome.message,
            payload=outcome.payload,
            validation_errors=outcome.validation_errors,
            result=self._stamp(outcome.detail.summary) if outcome.detail else None,
            **outcome.identity,
        )
