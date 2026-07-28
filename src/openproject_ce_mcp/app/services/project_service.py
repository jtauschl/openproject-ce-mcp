"""Application Services for the Projects domain (ADR 0001).

Depends on the ProjectApi Protocol, never HttpxProjectApi concretely (enforced by
the architecture-boundary test). Two classes in one file (ProjectService and
ProjectAdminService), sharing the same ProjectApi/ProjectResolver dependencies --
splitting into a second file would mostly relocate, not reduce, complexity.

get_my_project_access and get_project_work_package_context are NOT here: they
combine Projects with the still-flat Memberships/Work-Package-schema domains, and
a Service must not depend on another Service. They stay as client.py-level
orchestration that calls into ProjectService/ProjectResolver for the project-
identity part only.

`_WriteOutcome`/`_finalize_write` are shared via `app/services/_write_outcome.py`
(unified once a 3rd domain needed the identical state machine).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from urllib.parse import unquote

from ...config import Settings
from ...models import (
    FavoriteWriteResult,
    ProjectAdminContext,
    ProjectConfiguration,
    ProjectCopyResult,
    ProjectDetail,
    ProjectListResult,
    ProjectPhase,
    ProjectPhaseDefinition,
    ProjectPhaseDefinitionListResult,
    ProjectRef,
    ProjectSummary,
    ProjectWriteResult,
)
from ..api_href import api_href
from ..errors import InvalidInputError, NotFoundError
from ..pagination import clamp_limit
from ..policies import access, hidden_fields
from ..policies import project_policy as project_policy_module
from ..policies.scope import ensure_project_link_allowed, id_from_href, payload_allowed
from ..ports.project_api import ProjectApi
from ..resolvers.project_query import fetch_project_page
from ..resolvers.project_resolver import ProjectResolver
from ._write_outcome import _finalize_write, _WriteOutcome

SUBJECT_LIMIT = 255


# Duplicated from httpx_project_api.py's helpers of the same name (ADR 0001
# deliberate duplication) -- Services must not import Adapters. These are
# generic string/href utilities, not HAL->model mapping (which stays adapter-
# only), needed here for job-status-URL parsing (copy()), status-href
# matching (_resolve_status_href), and name trimming (set_favorite()). Unify
# only once every domain has migrated.
#
# id_from_href is NOT duplicated here -- it now lives in
# app/policies/scope.py (imported above), since it crossed this project's
# "3+ identical copies" threshold within app/ itself during the File Links
# migration's step-6 self-audit (OPM-296): this module's own copy,
# scope.py's own private copy, and file_link_service.py's new copy.
def _trim_text(value: Any, *, limit: int) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _slug_from_href(href: str | None) -> str | None:
    if not href:
        return None
    parts = href.rstrip("/").split("/")
    try:
        slug = parts[-1]
        return unquote(slug) or None
    except IndexError:
        return None


# "Clear this field" sentinel for `parent` (unassign via _links.parent =
# {"href": null}), distinguishing it from `None` ("leave unchanged"). Lives
# here (not client.py's own CLEAR) because Services must not import from
# client.py; client.py's create_project/update_project/copy_project wrappers
# translate their own CLEAR into this one at the call boundary.
CLEAR_PARENT = object()


def _stamp_project(value: Any, *, settings: Settings) -> Any:
    # The adapter computes description_truncated/description_length AND
    # status_explanation_truncated/status_explanation_length before hidden-field
    # masking exists (masking is a Service concern, per ADR 0001) --
    # apply_hidden_fields only drops the field key itself, so without this, a
    # hidden field's length/truncation state would still leak through its
    # sibling metadata fields. Zero both pairs out here, mirroring
    # VersionService._stamp and client.py's hide-aware
    # _visible_formattable_text_with_meta. Shared by ProjectService AND
    # ProjectAdminService (the embedded ProjectSummary in ProjectAdminContext.project
    # needs the identical treatment, not just a bare apply_hidden_fields call).
    if isinstance(value, ProjectSummary):
        if hidden_fields.field_hidden("project", "description", settings=settings):
            value = replace(value, description_truncated=False, description_length=None)
        if hidden_fields.field_hidden("project", "status_explanation", settings=settings):
            value = replace(value, status_explanation_truncated=False, status_explanation_length=None)
    return hidden_fields.apply_hidden_fields("project", value, settings=settings)


class ProjectService:
    def __init__(
        self,
        *,
        api: ProjectApi,
        settings: Settings,
        project_id_to_identifier: dict[int, str],
        resolver: ProjectResolver,
        base_url: str,
        api_prefix: str,
    ) -> None:
        self._api = api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier
        self._resolver = resolver
        self._base_url = base_url
        self._api_prefix = api_prefix

    def _stamp(self, value: Any) -> Any:
        return _stamp_project(value, settings=self._settings)

    def _remember_identifier(self, outcome: _WriteOutcome[ProjectDetail]) -> None:
        """Keep project_id_to_identifier in sync with a just-committed create/update.

        This dict is otherwise populated exactly once, by client.py's
        initialize() at server startup -- a project created or renamed
        through this same server afterward was invisible to every
        link-shaped allowlist check (ensure_project_link_allowed, used by
        every already-migrated Service plus every still-flat client.py
        domain that scopes by a work-package-style `_links.project` link,
        which carries no identifier field) until the process restarted.
        """
        if not outcome.confirmed or outcome.detail is None:
            return
        identifier = outcome.detail.identifier
        if identifier:
            self._project_id_to_identifier[outcome.detail.id] = identifier

    async def list(self, *, search: str | None = None, offset: int = 1, limit: int | None = None) -> ProjectListResult:
        effective_limit = clamp_limit(
            limit,
            default_page_size=self._settings.default_page_size,
            max_page_size=self._settings.max_page_size,
            max_results=self._settings.max_results,
        )
        page_results, total, next_offset, truncated = await fetch_project_page(
            api=self._api,
            settings=self._settings,
            project_id_to_identifier=self._project_id_to_identifier,
            search=search,
            offset=offset,
            limit=effective_limit,
            text_limit=self._settings.text_limit,
        )
        stamped = [self._stamp(item) for item in page_results]
        return ProjectListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(stamped),
            next_offset=next_offset,
            truncated=truncated,
            results=stamped,
        )

    async def get(self, project_ref: str, *, text_limit: int | None = None) -> ProjectDetail:
        # Default (text_limit=None) returns the full description/status_explanation
        # uncapped, like get_work_package: opening a single project means you want
        # to read it, so nothing is cut unless the caller asks for a smaller cap.
        access.ensure_read_enabled("project", settings=self._settings)
        record = await self._resolver.resolve_record(project_ref, write=False, text_limit=text_limit)
        return self._stamp(record.to_detail())

    async def get_configuration(self, project_ref: str) -> ProjectConfiguration:
        access.ensure_read_enabled("project", settings=self._settings)
        record = await self._resolver.resolve_record(project_ref, write=False)
        project = self._stamp(record.summary)
        configuration = await self._api.get_configuration(project.id)
        return hidden_fields.apply_hidden_fields(
            "project_configuration",
            self._normalize_configuration(configuration, project=project),
            settings=self._settings,
        )

    async def list_phase_definitions(self) -> ProjectPhaseDefinitionListResult:
        access.ensure_read_enabled("project", settings=self._settings)
        results = [
            hidden_fields.apply_hidden_fields("project_phase_definition", item, settings=self._settings)
            for item in await self._api.list_phase_definitions()
        ]
        return ProjectPhaseDefinitionListResult(count=len(results), results=results)

    async def get_phase_definition(self, phase_definition_id: int) -> ProjectPhaseDefinition:
        access.ensure_read_enabled("project", settings=self._settings)
        definition = await self._api.get_phase_definition(phase_definition_id)
        return hidden_fields.apply_hidden_fields("project_phase_definition", definition, settings=self._settings)

    async def get_phase(self, phase_id: int) -> ProjectPhase:
        access.ensure_read_enabled("project", settings=self._settings)
        record = await self._api.get_phase(phase_id)
        # Always checked (fail-closed on a missing link too), matching client.py's
        # unconditional self._ensure_project_link_allowed(payload.get("_links",
        # {}).get("project")) -- a phase with no project link must not be
        # readable under a non-wildcard scope, not silently allowed through.
        ensure_project_link_allowed(
            record.project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
        )
        return hidden_fields.apply_hidden_fields("project_phase", record.phase, settings=self._settings)

    async def create(
        self,
        *,
        name: str,
        identifier: str,
        description: str | None = None,
        public: bool | None = None,
        active: bool | None = None,
        status: str | None = None,
        status_explanation: str | None = None,
        parent: str | object | None = None,
        confirm: bool = False,
    ) -> ProjectWriteResult:
        project_policy_module.ensure_project_create_target_allowed(
            identifier=identifier,
            name=name,
            settings=self._settings,
            project_id_to_identifier=self._project_id_to_identifier,
        )
        payload = await self._build_write_payload(
            name=name,
            identifier=identifier,
            description=description,
            public=public,
            active=active,
            status=status,
            status_explanation=status_explanation,
            parent=parent,
            project_id=None,
        )
        form = await self._api.create_form(payload)
        outcome = await _finalize_write(
            confirm=confirm,
            payload=form.payload,
            validation_errors=form.validation_errors,
            identity={"project_id": None, "project": None},
            ensure_write_enabled=lambda: access.ensure_write_enabled("project", settings=self._settings),
            commit=self._api.commit_create,
            committed_identity=lambda d: {"project_id": d.id, "project": d.name},
            rejected_message="OpenProject rejected the proposed project changes. Fix the validation errors before confirming.",
            preview_message="OpenProject validated the project. Ask for confirmation, then call again with confirm=true to create it.",
            success_message="Project created successfully.",
        )
        self._remember_identifier(outcome)
        return self._to_write_result("create", outcome)

    async def update(
        self,
        *,
        project_ref: str,
        name: str | None = None,
        identifier: str | None = None,
        description: str | None = None,
        public: bool | None = None,
        active: bool | None = None,
        status: str | None = None,
        status_explanation: str | None = None,
        parent: str | object | None = None,
        confirm: bool = False,
    ) -> ProjectWriteResult:
        record = await self._resolver.resolve_record(project_ref, write=True)
        project = record.summary
        payload = await self._build_write_payload(
            name=name,
            identifier=identifier,
            description=description,
            public=public,
            active=active,
            status=status,
            status_explanation=status_explanation,
            parent=parent,
            project_id=project.id,
        )
        form = await self._api.update_form(project.id, payload)
        outcome = await _finalize_write(
            confirm=confirm,
            payload=form.payload,
            validation_errors=form.validation_errors,
            identity={"project_id": project.id, "project": project.name},
            ensure_write_enabled=lambda: access.ensure_write_enabled("project", settings=self._settings),
            commit=lambda p: self._api.commit_update(project.id, p),
            committed_identity=lambda d: {"project_id": d.id, "project": d.name},
            rejected_message="OpenProject rejected the proposed project changes. Fix the validation errors before confirming.",
            preview_message="OpenProject validated the project change. Ask for confirmation, then call again with confirm=true to write it.",
            success_message="Project updated successfully.",
        )
        self._remember_identifier(outcome)
        return self._to_write_result("update", outcome)

    async def delete(self, *, project_ref: str, confirm: bool = False) -> ProjectWriteResult:
        record = await self._resolver.resolve_record(project_ref, write=True)
        project = self._stamp(record.summary)
        payload = {"id": project.id, "identifier": project.identifier, "name": project.name}

        if not confirm:
            return ProjectWriteResult(
                action="delete",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject found the project. Ask for confirmation, then call again with confirm=true to delete it.",
                project_id=project.id,
                project=project.name,
                payload=payload,
                validation_errors={},
                result=None,
            )

        access.ensure_write_enabled("project", settings=self._settings)
        await self._api.delete(project.id)
        return ProjectWriteResult(
            action="delete",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Project deleted successfully.",
            project_id=project.id,
            project=project.name,
            payload=payload,
            validation_errors={},
            result=project,
        )

    async def copy(
        self,
        *,
        source_project: str,
        name: str,
        identifier: str,
        description: str | None = None,
        public: bool | None = None,
        active: bool | None = None,
        status: str | None = None,
        status_explanation: str | None = None,
        parent: str | object | None = None,
        confirm: bool = False,
    ) -> ProjectCopyResult:
        source_record = await self._resolver.resolve_record(source_project, write=True)
        # Also validate the destination so a copy cannot create a project outside
        # the read/write allowlist (the source being allowed is not sufficient).
        project_policy_module.ensure_project_create_target_allowed(
            identifier=identifier,
            name=name,
            settings=self._settings,
            project_id_to_identifier=self._project_id_to_identifier,
        )
        project = source_record.summary
        payload = await self._build_write_payload(
            name=name,
            identifier=identifier,
            description=description,
            public=public,
            active=active,
            status=status,
            status_explanation=status_explanation,
            parent=parent,
            project_id=None,
        )
        form = await self._api.copy_form(project.id, payload)
        ready = not form.validation_errors
        if not confirm:
            return ProjectCopyResult(
                action="copy",
                confirmed=False,
                requires_confirmation=True,
                ready=ready,
                message=(
                    "OpenProject validated the project copy. Ask for confirmation, then call again with confirm=true to start the copy job."
                    if ready
                    else "OpenProject rejected the project copy payload. Fix the validation errors and try again."
                ),
                source_project_id=project.id,
                source_project=project.name,
                payload=form.payload,
                validation_errors=form.validation_errors,
                job_status_id=None,
                job_status_url=None,
            )
        if form.validation_errors:
            return ProjectCopyResult(
                action="copy",
                confirmed=False,
                requires_confirmation=False,
                ready=False,
                message="OpenProject rejected the project copy payload. Fix the validation errors and try again.",
                source_project_id=project.id,
                source_project=project.name,
                payload=form.payload,
                validation_errors=form.validation_errors,
                job_status_id=None,
                job_status_url=None,
            )
        access.ensure_write_enabled("project", settings=self._settings)
        job_status_url = await self._api.commit_copy(project.id, form.payload)
        return ProjectCopyResult(
            action="copy",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Project copy job started successfully.",
            source_project_id=project.id,
            source_project=project.name,
            payload=form.payload,
            validation_errors={},
            job_status_id=id_from_href(job_status_url),
            job_status_url=job_status_url,
        )

    async def set_favorite(self, project_ref: str, *, favorite: bool, confirm: bool) -> FavoriteWriteResult:
        # Use the workspaces endpoint (the project-favorite path is deprecated).
        payload = await self._resolver.resolve(project_ref, write=True)
        project_id = int(payload["id"])
        project_name = _trim_text(payload.get("name"), limit=SUBJECT_LIMIT)
        action = "favorite" if favorite else "unfavorite"
        if not confirm:
            verb = "mark as favorite" if favorite else "remove from favorites"
            return FavoriteWriteResult(
                action=action,
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message=f"OpenProject is ready to {verb}. Ask for confirmation, then call again with confirm=true.",
                project_id=project_id,
                project=project_name,
            )
        access.ensure_write_enabled("project", settings=self._settings)
        # The workspaces favorite endpoint exists only from 17.0; on older
        # instances a 404 is translated into a clear version hint. Kept in the
        # Service (not the adapter) -- the adapter stays a dumb HTTP translator.
        try:
            await self._api.set_favorite(project_id, favorite=favorite)
        except NotFoundError as exc:
            raise NotFoundError(
                "Project favorites requires OpenProject 17.0 or newer; this instance appears to be older."
            ) from exc
        return FavoriteWriteResult(
            action=action,
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message=f"Project {'added to' if favorite else 'removed from'} favorites.",
            project_id=project_id,
            project=project_name,
        )

    async def _build_write_payload(
        self,
        *,
        name: str | None,
        identifier: str | None,
        description: str | None,
        public: bool | None,
        active: bool | None,
        status: str | None,
        status_explanation: str | None,
        parent: str | object | None,
        project_id: int | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        links: dict[str, dict[str, str | None]] = {}
        schema_result = await self._api.get_schema(project_id=project_id, draft_payload=payload)
        schema = schema_result.schema

        if name is not None:
            hidden_fields.ensure_field_writable("project", "name", settings=self._settings)
            payload["name"] = name
        if identifier is not None:
            hidden_fields.ensure_field_writable("project", "identifier", settings=self._settings)
            payload["identifier"] = identifier
        if description is not None:
            hidden_fields.ensure_field_writable("project", "description", settings=self._settings)
            payload["description"] = {"format": "markdown", "raw": description}
        if public is not None:
            hidden_fields.ensure_field_writable("project", "public", settings=self._settings)
            payload["public"] = public
        if active is not None:
            hidden_fields.ensure_field_writable("project", "active", settings=self._settings)
            payload["active"] = active
        if status_explanation is not None:
            hidden_fields.ensure_field_writable("project", "status_explanation", settings=self._settings)
            payload["statusExplanation"] = {"format": "markdown", "raw": status_explanation}
        if status is not None:
            hidden_fields.ensure_field_writable("project", "status", settings=self._settings)
            links["status"] = {"href": self._resolve_status_href(schema, status)}
        if parent is CLEAR_PARENT:
            hidden_fields.ensure_field_writable("project", "parent", settings=self._settings)
            links["parent"] = {"href": None}
        elif parent is not None:
            hidden_fields.ensure_field_writable("project", "parent", settings=self._settings)
            assert isinstance(parent, str)
            # write=True: reparenting must be authorized on the new parent
            # too, not just on the project being updated -- otherwise a
            # caller with write access to project A could attach it under
            # project B they can only read, the same gap update_board's
            # reparent-target fix already closed for boards.
            parent_id = await self._resolver.resolve_id(parent, write=True)
            links["parent"] = {"href": self._api_href(f"projects/{parent_id}")}
        if links:
            payload["_links"] = links
        return payload

    def _resolve_status_href(self, schema: dict[str, Any], raw_value: str) -> str:
        field = schema.get("status")
        if not isinstance(field, dict):
            raise InvalidInputError("OpenProject schema does not expose the project status field.")
        for item in field.get("_links", {}).get("allowedValues", []):
            if not isinstance(item, dict):
                continue
            href = item.get("href")
            title = _trim_text(item.get("title"), limit=SUBJECT_LIMIT)
            item_id = _slug_from_href(href)
            if (raw_value.casefold() == (title or "").casefold() or raw_value == item_id) and href:
                return href
        raise InvalidInputError(f"OpenProject project status '{raw_value}' is not allowed.")

    def _api_href(self, relative_path: str) -> str:
        return api_href(relative_path, api_prefix=self._api_prefix)

    def _to_write_result(self, action: str, outcome: _WriteOutcome[ProjectDetail]) -> ProjectWriteResult:
        return ProjectWriteResult(
            action=action,
            confirmed=outcome.confirmed,
            requires_confirmation=outcome.requires_confirmation,
            ready=outcome.ready,
            message=outcome.message,
            payload=outcome.payload,
            validation_errors=outcome.validation_errors,
            result=self._stamp(outcome.detail) if outcome.detail else None,
            **outcome.identity,
        )

    def _normalize_configuration(self, payload: dict[str, Any], *, project: ProjectSummary) -> ProjectConfiguration:
        return ProjectConfiguration(
            project_id=project.id,
            project_name=project.name,
            maximum_attachment_file_size=payload.get("maximumAttachmentFileSize"),
            maximum_api_v3_page_size=payload.get("maximumAPIV3PageSize"),
            per_page_options=[int(item) for item in payload.get("perPageOptions", []) if isinstance(item, int)],
            duration_format=_trim_text(payload.get("durationFormat"), limit=SUBJECT_LIMIT),
            hours_per_day=payload.get("hoursPerDay"),
            days_per_month=payload.get("daysPerMonth"),
            active_feature_flags=sorted(
                str(item) for item in payload.get("activeFeatureFlags", []) if str(item).strip()
            ),
            available_features=sorted(str(item) for item in payload.get("availableFeatures", []) if str(item).strip()),
            trialling_features=sorted(str(item) for item in payload.get("triallingFeatures", []) if str(item).strip()),
            enabled_internal_comments=payload.get("enabledInternalComments"),
            url=f"{self._base_url.rstrip('/')}/api/v3/projects/{project.id}/configuration",
        )


class ProjectAdminService:
    def __init__(
        self,
        *,
        api: ProjectApi,
        settings: Settings,
        project_id_to_identifier: dict[int, str],
        resolver: ProjectResolver,
        base_url: str,
    ) -> None:
        self._api = api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier
        self._resolver = resolver
        self._base_url = base_url

    async def get_admin_context(self, project_ref: str) -> ProjectAdminContext:
        access.ensure_read_enabled("project", settings=self._settings)
        record = await self._resolver.resolve_record(project_ref, write=False)
        project = _stamp_project(record.summary, settings=self._settings)
        schema_result = await self._api.get_schema(project_id=project.id, draft_payload={"name": project.name})
        schema = schema_result.schema
        fields = schema_result.fields
        status_field = next((field for field in fields if field.key == "status"), None)
        available_statuses = status_field.allowed_values if status_field else []
        parent_candidates = await self._api.list_available_parent_projects(project.id, schema=schema)

        def _parent_ref_allowed(ref: ProjectRef) -> bool:
            return payload_allowed(
                lambda: project_policy_module.ensure_project_read_allowed(
                    {"id": ref.id, "identifier": ref.identifier, "name": ref.name},
                    settings=self._settings,
                    project_id_to_identifier=self._project_id_to_identifier,
                )
            )

        # Fail closed: a parent-project candidate outside READ_PROJECTS must not
        # leak its name/identifier through this picklist just because it's a
        # valid parent target (verbatim port of client.py's
        # `[item for item in elements if self._project_payload_allowed(item)]`).
        available_parent_projects = [ref for ref in parent_candidates if _parent_ref_allowed(ref)]
        # Non-writable/internal schema entries (id, timestamps, lockVersion, ...)
        # aren't useful to an agent discovering what it can set here.
        writable_fields = [field for field in fields if field.writable]
        return hidden_fields.apply_hidden_fields(
            "project_admin_context",
            ProjectAdminContext(
                project=project,
                available_statuses=available_statuses,
                available_parent_projects=available_parent_projects,
                fields=writable_fields,
            ),
            settings=self._settings,
        )
