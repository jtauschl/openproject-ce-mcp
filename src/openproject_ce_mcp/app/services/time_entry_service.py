"""Application Service for the Time Entries domain (ADR 0001).

Depends on `TimeEntryApi`, `ProjectApi` (for the activity-fallback project
walk AND for `list_time_entries`'s numeric-user-id lookup, via `UserApi`),
`WorkPackageLookupApi`, `WorkPackageIdResolver`, `ProjectRefResolver`,
`ProjectIdResolver`, `PrincipalRefResolver`, and `CurrentUserLookup` --
NOT `WorkPackageProjectAllowedCheck` (unlike Relations): no Time Entries path
dereferences an already-known work-package link the way Relations' from/to
sides do. `list_all` only needs `resolve_work_package_id` to resolve a
caller-supplied reference to a numeric id (used for the post-normalize entity
match, matching the pre-migration original -- no allowlist check of its own
here); `create` fetches the work package itself via
`WorkPackageLookupApi.get(...)` and checks its OWN `_links.project` directly,
the same pattern `get`/`update`/`delete` use on the time entry's own project
link.

Uses the shared `app/services/_write_outcome.py` state machine (`_finalize_write`),
same as `GridService` -- both go through a `<domain>/form` endpoint with an
identical rejected/preview/committed shape. This is a distinct function from
client.py's flat, private `_finalize_write` helper, which stays in client.py
feeding the still-flat Work Package/Attachment methods; `_to_write_result`
below mirrors `GridService`'s identical mapper.

Read/write scope reuses `"work_package"` (not a dedicated `"time_entry"`
scope) -- verbatim behavior of client.py's `_ensure_read_enabled`/
`_ensure_write_enabled("work_package")` calls; tools.py's scope tables are
unchanged by this migration.

`normalize_time_entry`/`normalize_time_entry_activity` in the pre-migration
client.py were NOT settings-free (unlike `normalize_relation`) -- both called
`self._apply_hidden_fields(...)` on the whole normalized object, and
`normalize_time_entry` additionally called `self._visible_formattable_text_with_meta(...)`
(hide-aware) for the `comment` field. `_stamp`/`_stamp_activity` here apply
that masking AFTER the adapter's pure `normalize_time_entry_raw`/
`normalize_time_entry_activity_raw` extraction. `_stamp`'s `comment` handling
nulls `comment`/`comment_truncated`/`comment_length` together when hidden
(not just `comment`) -- leaving truncation metadata visible would indirectly
leak information about a field the caller isn't supposed to see at all.

The `log_own_time`-vs-`log_time` permission-gating asymmetry (GitHub issue
#10): OpenProject's `TimeEntries::CreateContract#allowed_to_log_own?` can
only validate `log_own_time` against a concrete WorkPackage/Meeting entity --
a project-only link falls through to requiring `log_time` instead, silently
denying a caller who only has `log_own_time` but is entitled to log time on
that specific work package. `_resolve_activity_id` threads `work_package_id`
through to `TimeEntryApi.fetch_activities_for_entity`, which sends the
`entity` link (not `project`) whenever a work package is already known --
this ordering must survive byte-for-byte; see that adapter's implementation.

`list_all`'s `user="me"` filter uses `CurrentUserLookup` (bound to
`self.get_current_user`, gates on the `"principal"` scope, returns the RAW
name) rather than `UserApi.get_user("me")` -- deliberately not
interchangeable (different scope gate, different name-truncation behavior).
A numeric `user` filters via `UserApi.get_user(user_ref)` instead.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from ...config import Settings
from ...models import (
    CurrentUser,
    TimeEntryActivityListResult,
    TimeEntryActivitySummary,
    TimeEntryListResult,
    TimeEntrySummary,
    TimeEntryWriteResult,
)
from ..api_href import api_href as _api_href
from ..errors import InvalidInputError, NotFoundError, OpenProjectServerError, PermissionDeniedError
from ..pagination import effective_limit, fetch_bounded_and_paginate
from ..policies import access, hidden_fields
from ..policies import scope as scope_policy
from ..ports.current_user import CurrentUserLookup
from ..ports.principal_ref import PrincipalRefResolver
from ..ports.project_api import ProjectApi
from ..ports.project_ref import ProjectIdResolver, ProjectRefResolver
from ..ports.time_entry_api import TimeEntryApi
from ..ports.user_api import UserApi
from ..ports.work_package_lookup_api import WorkPackageLookupApi
from ..ports.work_package_ref import WorkPackageIdResolver
from ..resolvers.project_query import fetch_project_page
from ._write_outcome import _finalize_write
from .project_scoped_list import SUBJECT_LIMIT
from .project_scoped_list import trim_text as _trim_text

_FALLBACK_ERRORS = (NotFoundError, PermissionDeniedError, OpenProjectServerError)


class TimeEntryService:
    def __init__(
        self,
        *,
        api: TimeEntryApi,
        project_api: ProjectApi,
        user_api: UserApi,
        work_package_lookup_api: WorkPackageLookupApi,
        settings: Settings,
        project_id_to_identifier: dict[int, str],
        resolve_work_package_id: WorkPackageIdResolver,
        resolve_project_ref: ProjectRefResolver,
        resolve_project_id: ProjectIdResolver,
        resolve_principal_id: PrincipalRefResolver,
        get_current_user: CurrentUserLookup,
        api_prefix: str,
    ) -> None:
        self._api = api
        self._project_api = project_api
        self._user_api = user_api
        self._work_package_lookup_api = work_package_lookup_api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier
        self._resolve_work_package_id = resolve_work_package_id
        self._resolve_project_ref = resolve_project_ref
        self._resolve_project_id = resolve_project_id
        self._resolve_principal_id = resolve_principal_id
        self._get_current_user = get_current_user
        self._api_prefix = api_prefix

    def _stamp(self, summary: TimeEntrySummary) -> TimeEntrySummary:
        if hidden_fields.field_hidden("time_entry", "comment", settings=self._settings):
            summary = dataclasses.replace(summary, comment=None, comment_truncated=False, comment_length=None)
        return hidden_fields.apply_hidden_fields("time_entry", summary, settings=self._settings)

    def _stamp_activity(self, summary: TimeEntryActivitySummary) -> TimeEntryActivitySummary:
        return hidden_fields.apply_hidden_fields("time_entry_activity", summary, settings=self._settings)

    def _normalize_activity_element(self, item: dict[str, Any]) -> TimeEntryActivitySummary:
        return self._stamp_activity(self._api.to_activity_record(item).summary)

    def _activities_from_form(self, form: dict[str, Any]) -> list[TimeEntryActivitySummary]:
        schema = form.get("_embedded", {}).get("schema", {})
        activity_field = schema.get("activity", {})
        allowed = activity_field.get("_embedded", {}).get("allowedValues", [])
        return [self._normalize_activity_element(item) for item in allowed if isinstance(item, dict)]

    async def list_activities(self) -> TimeEntryActivityListResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        payload = await self._api.fetch_activities()
        if payload is not None:
            elements = payload.get("_embedded", {}).get("elements", [])
            results = [self._normalize_activity_element(item) for item in elements if isinstance(item, dict)]
            if results:
                return TimeEntryActivityListResult(count=len(results), results=results)

        try:
            offset = 1
            while True:
                page_results, _total, next_offset, _truncated = await fetch_project_page(
                    api=self._project_api,
                    settings=self._settings,
                    project_id_to_identifier=self._project_id_to_identifier,
                    search=None,
                    offset=offset,
                    limit=self._settings.max_page_size,
                )
                for project in page_results:
                    try:
                        form = await self._api.fetch_activities_for_entity(project_id=project.id, work_package_id=None)
                    except _FALLBACK_ERRORS:
                        continue
                    results = self._activities_from_form(form)
                    if results:
                        return TimeEntryActivityListResult(count=len(results), results=results)
                if next_offset is None:
                    return TimeEntryActivityListResult(count=0, results=[])
                offset = next_offset
        except _FALLBACK_ERRORS:
            return TimeEntryActivityListResult(count=0, results=[])

    async def list_all(
        self,
        *,
        project: str | None = None,
        work_package_id: int | str | None = None,
        user: str | None = None,
        spent_on_from: str | None = None,
        spent_on_to: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> TimeEntryListResult:
        access.ensure_read_enabled("work_package", settings=self._settings)
        resolved_work_package_id: int | None = None
        if work_package_id is not None:
            resolved_work_package_id = await self._resolve_work_package_id(work_package_id)

        project_candidates: set[str] = set()
        if project is not None:
            project_payload = await self._resolve_project_ref(project)
            project_candidates = scope_policy.project_candidates(
                project_id_to_identifier=self._project_id_to_identifier,
                project_ref=project,
                payload=project_payload,
            )

        user_name: str | None = None
        if user is not None:
            if user.casefold() == "me":
                current_user: CurrentUser = await self._get_current_user()
                user_name = current_user.name
            elif user.isdigit():
                user_record = await self._user_api.get_user(user)
                user_name = user_record.summary.name
            else:
                user_name = user

        resolved_limit = effective_limit(limit, settings=self._settings)

        async def item_allowed(item: dict[str, Any]) -> bool:
            allowed = scope_policy.project_link_payload_allowed(
                item,
                link_key="project",
                settings=self._settings,
                project_id_to_identifier=self._project_id_to_identifier,
            )
            if not allowed:
                return False
            if not project_candidates:
                return True
            item_candidates = scope_policy.project_candidates(
                project_id_to_identifier=self._project_id_to_identifier,
                link=item.get("_links", {}).get("project"),
            )
            return not item_candidates.isdisjoint(project_candidates)

        def post_filter(results: list[TimeEntrySummary]) -> list[TimeEntrySummary]:
            filtered = results
            if resolved_work_package_id is not None:
                filtered = [
                    item
                    for item in filtered
                    if item.entity_type == "WorkPackage" and item.entity_id == resolved_work_package_id
                ]
            if user_name is not None:
                filtered = [item for item in filtered if (item.user or "").casefold() == user_name.casefold()]
            if spent_on_from is not None:
                filtered = [item for item in filtered if item.spent_on is not None and item.spent_on >= spent_on_from]
            if spent_on_to is not None:
                filtered = [item for item in filtered if item.spent_on is not None and item.spent_on <= spent_on_to]
            return filtered

        page, total, next_offset, truncated = await fetch_bounded_and_paginate(
            fetch_page=lambda o, ps: self._api.fetch_page(offset=o, page_size=ps),
            normalize=lambda raw: self._stamp(self._api.to_record(raw, text_limit=self._settings.text_limit).summary()),
            item_allowed=item_allowed,
            post_filter=post_filter,
            server_page_size=self._settings.max_page_size,
            offset=offset,
            limit=resolved_limit,
        )
        return TimeEntryListResult(
            offset=offset,
            limit=resolved_limit,
            total=total,
            count=len(page),
            next_offset=next_offset,
            truncated=truncated,
            results=page,
        )

    async def get(self, time_entry_id: int, *, text_limit: int | None = None) -> TimeEntrySummary:
        access.ensure_read_enabled("work_package", settings=self._settings)
        raw = await self._api.get_raw(time_entry_id)
        project_link = raw.get("_links", {}).get("project")
        scope_policy.ensure_project_link_allowed(
            project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        return self._stamp(self._api.to_record(raw, text_limit=text_limit).summary())

    async def _build_write_payload(
        self,
        *,
        project: str | None,
        work_package_id: int | None,
        user: str | None,
        activity: str | None,
        hours: str | None,
        spent_on: str | None,
        start_time: str | None,
        end_time: str | None,
        comment: str | None,
        ongoing: bool | None,
        activity_project_id: int | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        links: dict[str, dict[str, str]] = {}

        if hours is not None:
            hidden_fields.ensure_field_writable("time_entry", "hours", settings=self._settings)
            payload["hours"] = hours
        if spent_on is not None:
            hidden_fields.ensure_field_writable("time_entry", "spent_on", settings=self._settings)
            payload["spentOn"] = spent_on
        if start_time is not None:
            hidden_fields.ensure_field_writable("time_entry", "start_time", settings=self._settings)
            payload["startTime"] = start_time
        if end_time is not None:
            hidden_fields.ensure_field_writable("time_entry", "end_time", settings=self._settings)
            payload["endTime"] = end_time
        if comment is not None:
            hidden_fields.ensure_field_writable("time_entry", "comment", settings=self._settings)
            hidden_fields.ensure_field_writable("activity", "comment", settings=self._settings)
            payload["comment"] = {"format": "markdown", "raw": comment}
        if ongoing is not None:
            hidden_fields.ensure_field_writable("time_entry", "ongoing", settings=self._settings)
            payload["ongoing"] = ongoing
        if work_package_id is not None:
            hidden_fields.ensure_field_writable("time_entry", "entity", settings=self._settings)
            links["entity"] = {"href": _api_href(f"work_packages/{work_package_id}", api_prefix=self._api_prefix)}
        elif project is not None:
            hidden_fields.ensure_field_writable("time_entry", "project", settings=self._settings)
            project_id = await self._resolve_project_id(project)
            links["project"] = {"href": _api_href(f"projects/{project_id}", api_prefix=self._api_prefix)}
        if user is not None:
            hidden_fields.ensure_field_writable("time_entry", "user", settings=self._settings)
            user_id = await self._resolve_principal_id(user)
            links["user"] = {"href": _api_href(f"users/{user_id}", api_prefix=self._api_prefix)}
        if activity is not None:
            hidden_fields.ensure_field_writable("time_entry", "activity", settings=self._settings)
            activity_id = await self._resolve_activity_id(
                activity, project_id=activity_project_id, work_package_id=work_package_id
            )
            links["activity"] = {
                "href": _api_href(f"time_entries/activities/{activity_id}", api_prefix=self._api_prefix)
            }
        if links:
            payload["_links"] = links
        return payload

    async def _resolve_activity_id(
        self, activity_ref: str, *, project_id: int | None = None, work_package_id: int | None = None
    ) -> str:
        if activity_ref.isdigit():
            return activity_ref
        if project_id is not None:
            form = await self._api.fetch_activities_for_entity(project_id=project_id, work_package_id=work_package_id)
            activities = self._activities_from_form(form)
        else:
            activities = (await self.list_activities()).results
        matches = [str(item.id) for item in activities if (item.name or "").casefold() == activity_ref.casefold()]
        if not matches:
            raise InvalidInputError(f"OpenProject time entry activity '{activity_ref}' was not found.")
        if len(matches) > 1:
            raise InvalidInputError(
                f"OpenProject time entry activity '{activity_ref}' is ambiguous. Pass a numeric activity id."
            )
        return matches[0]

    async def create(
        self,
        *,
        project: str | None = None,
        work_package_id: int | str | None = None,
        user: str | None = None,
        activity: str,
        hours: str,
        spent_on: str,
        start_time: str | None = None,
        end_time: str | None = None,
        comment: str | None = None,
        ongoing: bool | None = None,
        confirm: bool = False,
    ) -> TimeEntryWriteResult:
        project_name: str | None = None
        activity_project_id: int | None = None
        work_package_numeric_id: int | None = None
        if project is not None:
            project_payload = await self._resolve_project_ref(project, write=True)
            project_name = _trim_text(project_payload.get("name"), limit=SUBJECT_LIMIT)
            activity_project_id = int(project_payload["id"])
        if work_package_id is not None:
            work_package_payload = await self._work_package_lookup_api.get(str(work_package_id))
            scope_policy.ensure_project_write_link_allowed(
                work_package_payload.get("_links", {}).get("project"),
                settings=self._settings,
                project_id_to_identifier=self._project_id_to_identifier,
            )
            work_package_numeric_id = int(work_package_payload["id"])
            work_package_project_link = work_package_payload.get("_links", {}).get("project")
            wp_project_title, wp_project_id = self._api.project_link_title_and_id(work_package_project_link)
            if project_name is None:
                project_name = wp_project_title
            if activity_project_id is None:
                activity_project_id = wp_project_id
        payload = await self._build_write_payload(
            project=project,
            work_package_id=work_package_numeric_id,
            user=user,
            activity=activity,
            hours=hours,
            spent_on=spent_on,
            start_time=start_time,
            end_time=end_time,
            comment=comment,
            ongoing=ongoing,
            activity_project_id=activity_project_id,
        )
        form = await self._api.validate_create(payload)
        parsed = self._api.parse_form_result(form)
        outcome = await _finalize_write(
            confirm=confirm,
            payload=parsed.payload,
            validation_errors=parsed.validation_errors,
            identity={"time_entry_id": None, "project": project_name},
            ensure_write_enabled=lambda: access.ensure_write_enabled("work_package", settings=self._settings),
            commit=self._api.create,
            committed_identity=lambda record: {
                "time_entry_id": record.summary().id,
                "project": record.summary().project,
            },
            rejected_message="OpenProject rejected the proposed time entry. Fix the validation errors before confirming.",
            preview_message="OpenProject validated the time entry. Ask for confirmation, then call again with confirm=true to create it.",
            success_message="Time entry created successfully.",
        )
        return self._to_write_result("create", outcome)

    async def update(
        self,
        *,
        time_entry_id: int,
        user: str | None = None,
        activity: str | None = None,
        hours: str | None = None,
        spent_on: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        comment: str | None = None,
        ongoing: bool | None = None,
        confirm: bool = False,
    ) -> TimeEntryWriteResult:
        current = await self._api.get_raw(time_entry_id)
        project_link = current.get("_links", {}).get("project")
        scope_policy.ensure_project_write_link_allowed(
            project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        project_name, project_id = self._api.project_link_title_and_id(project_link)
        payload = await self._build_write_payload(
            project=None,
            work_package_id=None,
            user=user,
            activity=activity,
            hours=hours,
            spent_on=spent_on,
            start_time=start_time,
            end_time=end_time,
            comment=comment,
            ongoing=ongoing,
            activity_project_id=project_id,
        )
        form = await self._api.validate_update(time_entry_id, payload)
        parsed = self._api.parse_form_result(form)
        outcome = await _finalize_write(
            confirm=confirm,
            payload=parsed.payload,
            validation_errors=parsed.validation_errors,
            identity={"time_entry_id": time_entry_id, "project": project_name},
            ensure_write_enabled=lambda: access.ensure_write_enabled("work_package", settings=self._settings),
            commit=lambda p: self._api.update(time_entry_id, p),
            committed_identity=lambda record: {
                "time_entry_id": record.summary().id,
                "project": record.summary().project,
            },
            rejected_message="OpenProject rejected the proposed time entry changes. Fix the validation errors before confirming.",
            preview_message="OpenProject validated the time entry. Ask for confirmation, then call again with confirm=true to update it.",
            success_message="Time entry updated successfully.",
        )
        return self._to_write_result("update", outcome)

    def _to_write_result(self, action: str, outcome: Any) -> TimeEntryWriteResult:
        return TimeEntryWriteResult(
            action=action,
            confirmed=outcome.confirmed,
            requires_confirmation=outcome.requires_confirmation,
            ready=outcome.ready,
            message=outcome.message,
            payload=outcome.payload,
            validation_errors=outcome.validation_errors,
            result=self._stamp(outcome.detail.summary()) if outcome.detail else None,
            **outcome.identity,
        )

    async def delete(self, *, time_entry_id: int, confirm: bool = False) -> TimeEntryWriteResult:
        current = await self._api.get_raw(time_entry_id)
        project_link = current.get("_links", {}).get("project")
        scope_policy.ensure_project_write_link_allowed(
            project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        detail = self._stamp(self._api.to_record(current, text_limit=self._settings.text_limit).summary())
        payload = {"id": detail.id, "hours": detail.hours, "spentOn": detail.spent_on}
        if not confirm:
            return TimeEntryWriteResult(
                action="delete",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject found the time entry. Ask for confirmation, then call again with confirm=true to delete it.",
                time_entry_id=detail.id,
                project=detail.project,
                payload=payload,
                validation_errors={},
                result=detail,
            )
        access.ensure_write_enabled("work_package", settings=self._settings)
        await self._api.delete(time_entry_id)
        return TimeEntryWriteResult(
            action="delete",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Time entry deleted successfully.",
            time_entry_id=detail.id,
            project=detail.project,
            payload=payload,
            validation_errors={},
            result=None,
        )
