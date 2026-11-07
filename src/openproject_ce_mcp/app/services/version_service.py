"""Application Service for the Versions domain.

Depends on the VersionApi Protocol, never HttpxVersionApi concretely (enforced by
the architecture-boundary test). `_WriteOutcome`/`_finalize_write` are shared via
`app/services/_write_outcome.py` (unified once a 3rd domain needed the identical
state machine -- see that module's docstring).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from ...config import Settings
from ...models import ProjectListResult, VersionDetail, VersionListResult, VersionSummary, VersionWriteResult
from ..api_href import api_href as _api_href
from ..pagination import clamp_limit
from ..policies import access, hidden_fields
from ..policies import scope as scope_policy
from ..ports.project_api import ProjectApi
from ..ports.project_ref import ProjectRefResolver
from ..ports.project_resolution import ProjectResolutionContext
from ..ports.version_api import VersionApi
from ..resolvers.project_query import fetch_allowed_project_page
from ..resolvers.version_query import fetch_version_page
from . import _stored_text_edit
from ._write_outcome import _finalize_write, _WriteOutcome
from .project_service import _stamp_project


class VersionService:
    def __init__(
        self,
        *,
        api: VersionApi,
        settings: Settings,
        project_id_to_identifier: Mapping[int, str],
        resolve_project_ref: ProjectRefResolver,
        api_prefix: str,
        project_api: ProjectApi,
    ) -> None:
        self._api = api
        self._project_api = project_api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier
        self._resolve_project_ref = resolve_project_ref
        self._api_prefix = api_prefix

    def _stamp(self, value: Any) -> Any:
        # The adapter computes description_truncated/description_length before
        # hidden-field masking exists (masking is a Service concern, per ADR
        # 0001) -- apply_hidden_fields only drops the "description" key itself,
        # so without this, a hidden description's length/truncation state would
        # still leak through those two sibling fields. Zero them out here,
        # mirroring the identical treatment for Project/WorkPackage/TimeEntry.
        if isinstance(value, VersionSummary) and hidden_fields.field_hidden(
            "version", "description", settings=self._settings
        ):
            value = replace(value, description_truncated=False, description_length=None)
        return hidden_fields.apply_hidden_fields("version", value, settings=self._settings)

    async def list(
        self,
        *,
        project: str | None = None,
        search: str | None = None,
        offset: int = 1,
        limit: int | None = None,
        context: ProjectResolutionContext | None = None,
    ) -> VersionListResult:
        access.ensure_read_enabled("version", settings=self._settings)
        # limit must be clamped HERE, matching the original _resolve_limit contract
        # (min(requested, max_page_size, max_results)) -- fetch_version_page clamps
        # its own internal copy for the actual pagination math, but that clamped
        # value must also be what gets reported back in the returned envelope.
        effective_limit = clamp_limit(
            limit,
            default_page_size=self._settings.default_page_size,
            max_page_size=self._settings.max_page_size,
            max_results=self._settings.max_results,
        )
        # ADR: each Application Service call creates its own resolution context at
        # the entry boundary if the caller didn't supply one. VersionResolver calls
        # fetch_version_page() directly, threading its OWN context across its OWN
        # page-walk -- so no current internal caller actually passes a context into
        # this method; the parameter is kept for signature compatibility and for
        # any future caller that might chain a list() call into a larger
        # multi-resolution operation. Either way, this line guarantees list()'s own
        # resolve call is never left uncached-and-unscoped.
        resolution_context = context or ProjectResolutionContext(self._resolve_project_ref)
        page_results, total, next_offset, truncated = await fetch_version_page(
            api=self._api,
            resolve_project_ref=self._resolve_project_ref,
            settings=self._settings,
            project_id_to_identifier=self._project_id_to_identifier,
            project=project,
            search=search,
            offset=offset,
            limit=effective_limit,
            context=resolution_context,
            # List-row context: capped at settings.text_limit (default 500), same
            # convention as list_projects/list_work_packages.
            text_limit=self._settings.text_limit,
        )
        stamped = [self._stamp(item) for item in page_results]
        return VersionListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(stamped),
            next_offset=next_offset,
            truncated=truncated,
            results=stamped,
        )

    async def get(self, version_id: int, *, text_limit: int | None = None) -> VersionDetail:
        # Default (text_limit=None) returns the full description uncapped, like
        # get_work_package/get_project: opening a single version means you want
        # to read it, so nothing is cut unless the caller asks for a smaller cap.
        access.ensure_read_enabled("version", settings=self._settings)
        record = await self._api.get(version_id, text_limit=text_limit)
        scope_policy.ensure_defining_project_link_allowed(
            record.defining_project_link,
            settings=self._settings,
            project_id_to_identifier=self._project_id_to_identifier,
        )
        return self._stamp(record.to_detail())

    async def list_projects(self, version_id: int, *, offset: int = 1, limit: int | None = None) -> ProjectListResult:
        """The projects a version is shared with, kept to those the read scope covers.

        The version is judged first: a version defined outside the read scope names no project at all.
        """
        access.ensure_read_enabled("version", settings=self._settings)
        access.ensure_read_enabled("project", settings=self._settings)
        record = await self._api.get(version_id)
        scope_policy.ensure_defining_project_link_allowed(
            record.defining_project_link,
            settings=self._settings,
            project_id_to_identifier=self._project_id_to_identifier,
        )
        effective_limit = clamp_limit(
            limit,
            default_page_size=self._settings.default_page_size,
            max_page_size=self._settings.max_page_size,
            max_results=self._settings.max_results,
        )
        page_results, total, next_offset, truncated = await fetch_allowed_project_page(
            fetch_page=lambda server_offset, server_page_size: self._project_api.list_for_version(
                version_id,
                server_offset=server_offset,
                server_page_size=server_page_size,
                text_limit=self._settings.text_limit,
            ),
            settings=self._settings,
            offset=offset,
            limit=effective_limit,
        )
        stamped = [
            _stamp_project(
                record.summary, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
            )
            for record in page_results
        ]
        return ProjectListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(stamped),
            next_offset=next_offset,
            truncated=truncated,
            results=stamped,
        )

    async def create(
        self,
        *,
        project: str,
        name: str,
        description: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        status: str | None = None,
        sharing: str | None = None,
        confirm: bool = False,
    ) -> VersionWriteResult:
        project_payload = await self._resolve_project_ref(project, write=True)
        payload = self._build_write_payload(
            project_id=str(project_payload["id"]),
            name=name,
            description=description,
            start_date=start_date,
            end_date=end_date,
            status=status,
            sharing=sharing,
        )
        form = await self._api.create_form(payload)
        outcome = await _finalize_write(
            confirm=confirm,
            entity="version",
            settings=self._settings,
            payload=form.payload,
            validation_errors=form.validation_errors,
            identity={"version_id": None, "project": project_payload.get("name")},
            ensure_write_enabled=lambda: access.ensure_write_enabled("version", settings=self._settings),
            commit=self._api.commit_create,
            committed_identity=lambda d: {"version_id": d.id, "project": d.defining_project},
            rejected_message="OpenProject rejected the proposed version changes. Fix the validation errors before confirming.",
            preview_message="OpenProject validated the version. Ask for confirmation, then call again with confirm=true to create it.",
            success_message="Version created successfully.",
        )
        return self._to_write_result("create", outcome)

    async def update(
        self,
        *,
        version_id: int,
        name: str | None = None,
        description: str | None = None,
        description_append: str | None = None,
        description_replace: Mapping[str, str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        status: str | None = None,
        sharing: str | None = None,
        confirm: bool = False,
    ) -> VersionWriteResult:
        current = await self._api.get(version_id)
        scope_policy.ensure_defining_project_write_link_allowed(
            current.defining_project_link,
            settings=self._settings,
            project_id_to_identifier=self._project_id_to_identifier,
        )
        description, sentence = _stored_text_edit.edit_stored_field(
            "version",
            "description",
            (current.payload.get("description") or {}).get("raw"),
            description,
            description_append,
            description_replace,
            settings=self._settings,
        )
        payload = self._build_write_payload(
            project_id=None,
            name=name,
            description=description,
            start_date=start_date,
            end_date=end_date,
            status=status,
            sharing=sharing,
        )
        form = await self._api.update_form(version_id, payload)
        outcome = await _finalize_write(
            confirm=confirm,
            entity="version",
            settings=self._settings,
            payload=form.payload,
            validation_errors=form.validation_errors,
            identity={"version_id": version_id, "project": current.summary.defining_project},
            ensure_write_enabled=lambda: access.ensure_write_enabled("version", settings=self._settings),
            commit=lambda p: self._api.commit_update(version_id, p),
            committed_identity=lambda d: {"version_id": d.id, "project": d.defining_project},
            rejected_message="OpenProject rejected the proposed version changes. Fix the validation errors before confirming.",
            preview_message=_stored_text_edit.with_sentence(
                "OpenProject validated the version change. Ask for confirmation, then call again with confirm=true to write it.",
                sentence,
            ),
            success_message=_stored_text_edit.with_sentence("Version updated successfully.", sentence),
        )
        return self._to_write_result("update", outcome)

    async def delete(self, *, version_id: int, confirm: bool = False) -> VersionWriteResult:
        current = await self._api.get(version_id)
        scope_policy.ensure_defining_project_write_link_allowed(
            current.defining_project_link,
            settings=self._settings,
            project_id_to_identifier=self._project_id_to_identifier,
        )
        detail = self._stamp(current.to_detail())
        payload = {"id": detail.id, "name": detail.name}

        async def _commit(p: dict[str, Any]) -> VersionDetail:
            await self._api.delete(version_id)
            return detail

        outcome = await _finalize_write(
            entity="version",
            settings=self._settings,
            confirm=confirm,
            payload=payload,
            validation_errors={},
            identity={"version_id": detail.id, "project": detail.defining_project},
            ensure_write_enabled=lambda: access.ensure_write_enabled("version", settings=self._settings),
            commit=_commit,
            committed_identity=lambda d: {"version_id": d.id, "project": d.defining_project},
            rejected_message="",
            preview_message="OpenProject found the version. Ask for confirmation, then call again with confirm=true to delete it.",
            success_message="Version deleted successfully.",
        )
        return self._to_write_result("delete", outcome)

    def _build_write_payload(
        self,
        *,
        project_id: str | None,
        name: str | None = None,
        description: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        status: str | None = None,
        sharing: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        links: dict[str, dict[str, str]] = {}

        if name is not None:
            hidden_fields.ensure_field_writable("version", "name", settings=self._settings)
            payload["name"] = name
        if description is not None:
            hidden_fields.ensure_field_writable("version", "description", settings=self._settings)
            payload["description"] = {"format": "plain", "raw": description}
        if start_date is not None:
            hidden_fields.ensure_field_writable("version", "start_date", settings=self._settings)
            payload["startDate"] = start_date
        if end_date is not None:
            hidden_fields.ensure_field_writable("version", "end_date", settings=self._settings)
            payload["endDate"] = end_date
        if status is not None:
            hidden_fields.ensure_field_writable("version", "status", settings=self._settings)
            payload["status"] = status
        if sharing is not None:
            hidden_fields.ensure_field_writable("version", "sharing", settings=self._settings)
            payload["sharing"] = sharing
        if project_id is not None:
            hidden_fields.ensure_field_writable("version", "defining_project", settings=self._settings)
            links["definingProject"] = {"href": _api_href(f"projects/{project_id}", api_prefix=self._api_prefix)}
        if links:
            payload["_links"] = links
        return payload

    def _to_write_result(self, action: str, outcome: _WriteOutcome[VersionDetail]) -> VersionWriteResult:
        return VersionWriteResult(
            action=action,
            state=outcome.state,
            ready=outcome.ready,
            message=outcome.message,
            payload=outcome.payload,
            validation_errors=outcome.validation_errors,
            result=self._stamp(outcome.detail) if outcome.detail else None,
            **outcome.identity,
        )
