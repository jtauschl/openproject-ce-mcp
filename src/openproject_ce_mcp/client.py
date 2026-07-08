from __future__ import annotations

import json
import logging
import mimetypes
from collections.abc import Awaitable
from dataclasses import fields as dataclass_fields
from dataclasses import is_dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urljoin, urlparse

import httpx

from . import __version__
from .config import HIDE_FIELD_ENV_BY_ENTITY, Settings
from .models import (
    ActionListResult,
    ActionSummary,
    ActivityListResult,
    ActivitySummary,
    ActivityWriteResult,
    AttachmentListResult,
    AttachmentSummary,
    AttachmentWriteResult,
    BoardDetail,
    BoardFilter,
    BoardListResult,
    BoardSummary,
    BoardWriteResult,
    BulkWorkPackageItemResult,
    BulkWorkPackageWriteResult,
    CapabilityListResult,
    CapabilitySummary,
    CategoryListResult,
    CategorySummary,
    CurrentUser,
    CustomOptionSummary,
    DocumentDetail,
    DocumentListResult,
    DocumentSummary,
    DocumentWriteResult,
    EmojiReactionListResult,
    EmojiReactionSummary,
    FavoriteWriteResult,
    FileLinkListResult,
    FileLinkSummary,
    FileLinkWriteResult,
    GridListResult,
    GridSummary,
    GridWriteResult,
    GroupDetail,
    GroupListResult,
    GroupSummary,
    GroupWriteResult,
    HelpTextListResult,
    HelpTextSummary,
    InstanceConfiguration,
    JobStatusDetail,
    MembershipListResult,
    MembershipSummary,
    MembershipWriteResult,
    NewsDetail,
    NewsListResult,
    NewsSummary,
    NewsWriteResult,
    NonWorkingDay,
    NonWorkingDayListResult,
    NotificationListResult,
    NotificationSummary,
    OptionValue,
    PrincipalListResult,
    PrincipalSummary,
    PriorityListResult,
    PrioritySummary,
    ProjectAccessSummary,
    ProjectAdminContext,
    ProjectConfiguration,
    ProjectCopyResult,
    ProjectFieldSchema,
    ProjectListResult,
    ProjectPhase,
    ProjectPhaseDefinition,
    ProjectPhaseDefinitionListResult,
    ProjectSummary,
    ProjectWorkPackageContext,
    ProjectWriteResult,
    QueryColumnSummary,
    QueryFilterInstanceSchemaListResult,
    QueryFilterInstanceSchemaSummary,
    QueryFilterSummary,
    QueryOperatorSummary,
    QuerySortBySummary,
    RelationListResult,
    RelationSummary,
    RelationUpdateResult,
    RelationWriteResult,
    ReminderListResult,
    ReminderSummary,
    ReminderWriteResult,
    RenderedText,
    RoleListResult,
    RoleSummary,
    StatusListResult,
    StatusSummary,
    TimeEntryActivityListResult,
    TimeEntryActivitySummary,
    TimeEntryListResult,
    TimeEntrySummary,
    TimeEntryWriteResult,
    TypeListResult,
    TypeSummary,
    UserDetail,
    UserListResult,
    UserPreferences,
    UserPreferencesWriteResult,
    UserSummary,
    UserWriteResult,
    VersionDetail,
    VersionListResult,
    VersionSummary,
    VersionWriteResult,
    ViewDetail,
    ViewListResult,
    ViewSummary,
    WatcherListResult,
    WatcherSummary,
    WatcherWriteResult,
    WikiPageDetail,
    WorkingDay,
    WorkingDayListResult,
    WorkPackageDetail,
    WorkPackageFieldSchema,
    WorkPackageListResult,
    WorkPackageSummary,
    WorkPackageWriteResult,
)

LOGGER = logging.getLogger(__name__)

# Text caps below trim formattable fields (descriptions, comments) *before* they
# are serialized back to the MCP client. They exist to protect the AGENT'S CONTEXT
# WINDOW — not to save memory or bandwidth: the full text has already been fetched
# from OpenProject and lives in this process; trimming only bounds how much lands
# in the model's limited read context. Single-item reads (get_work_package,
# get_work_package_activities) return their full text because one item is cheap;
# only list/search results are capped, because many rows at full length flood the
# context. That list-preview cap is configurable via OPENPROJECT_TEXT_LIMIT
# (settings.text_limit, default 500) — see normalize_work_package_summary.
FORMATTABLE_LIMIT = 1_200
SUBJECT_LIMIT = 255

# Sentinel for update_work_package: distinguishes "clear the parent" (make the work
# package top-level via _links.parent = {"href": null}) from "leave unchanged" (None).
# A dedicated object avoids colliding with numeric ids or the _resolve_work_package_id
# path, and cannot be confused with any valid parent reference.
CLEAR_PARENT = object()

# Sentinel for create/update_work_package: distinguishes "clear the version"
# (unassign via _links.version = {"href": null}) from "leave unchanged" (None). Same
# rationale as CLEAR_PARENT — it must bypass version-name resolution.
CLEAR_VERSION = object()


class OpenProjectError(Exception):
    """Base error for safe OpenProject failures."""


class AuthenticationError(OpenProjectError):
    """Authentication failed."""


class PermissionDeniedError(OpenProjectError):
    """Access to the resource was denied."""


class NotFoundError(OpenProjectError):
    """The requested resource does not exist."""


class InvalidInputError(OpenProjectError):
    """A provided tool or request input is invalid."""


class OpenProjectServerError(OpenProjectError):
    """OpenProject returned an unexpected failure."""


class TransportError(OpenProjectError):
    """The request could not reach OpenProject safely."""


class OpenProjectClient:
    """Small OpenProject API client with optional guarded write support."""

    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings
        self._origin = _origin_from_url(settings.base_url)
        self._api_prefix = urlparse(settings.api_base_url).path.rstrip("/") + "/"
        self._project_id_to_identifier: dict[int, str] = {}
        self._http = httpx.AsyncClient(
            base_url=f"{settings.api_base_url.rstrip('/')}/",
            headers={
                "Accept": "application/hal+json, application/json",
                "Authorization": f"Basic {__import__('base64').b64encode(f'apikey:{settings.api_token}'.encode()).decode()}",
                "User-Agent": f"openproject-ce-mcp/{__version__}",
            },
            timeout=httpx.Timeout(settings.timeout),
            verify=settings.verify_ssl,
            follow_redirects=True,
            transport=transport,
        )

    async def initialize(self) -> None:
        if not self.settings.allowed_projects or _scope_allows_all(self.settings.allowed_projects):
            return
        try:
            payload = await self._get("projects", params={"pageSize": "500"})
            for item in payload.get("_embedded", {}).get("elements", []):
                proj_id = item.get("id")
                proj_identifier = item.get("identifier")
                proj_name = item.get("name") or ""
                if not isinstance(proj_id, int) or not isinstance(proj_identifier, str):
                    continue
                candidates: set[str] = {
                    proj_identifier.casefold(),
                    str(proj_id),
                    proj_name.casefold(),
                    proj_name.casefold().replace(" ", "-"),
                }
                if _scope_matches_candidates(self.settings.allowed_projects, candidates):
                    self._project_id_to_identifier[proj_id] = proj_identifier
        except Exception:
            pass

    async def aclose(self) -> None:
        await self._http.aclose()

    async def list_projects(
        self,
        *,
        search: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> ProjectListResult:
        self._ensure_read_enabled("project")
        effective_limit = self._resolve_limit(limit)
        filters: list[dict[str, Any]] = []
        if search:
            filters.append({"name_and_identifier": {"operator": "~", "values": [search]}})
        payload = await self._get(
            "projects",
            params={
                "offset": str(offset),
                "pageSize": str(effective_limit),
                "filters": _json_param(filters),
            },
        )
        raw_projects = payload.get("_embedded", {}).get("elements", [])
        projects = [project for project in raw_projects if project.get("_type") == "Project"]
        projects = [project for project in projects if self._project_payload_allowed(project)]
        results = [self.normalize_project(project) for project in projects]
        server_total = int(payload.get("total", len(results)))
        total = len(results)
        return ProjectListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=total,
            next_offset=_next_offset(offset, effective_limit, server_total),
            truncated=server_total > offset * effective_limit,
            results=results,
        )

    async def get_project(self, project_ref: str) -> ProjectSummary:
        self._ensure_read_enabled("project")
        payload = await self._get(f"projects/{quote(project_ref, safe='')}")
        if payload.get("_type") != "Project":
            raise NotFoundError("OpenProject project not found.")
        self._ensure_project_allowed(project_ref, payload=payload)
        return self.normalize_project(payload)

    async def get_project_admin_context(self, project_ref: str) -> ProjectAdminContext:
        self._ensure_read_enabled("project")
        payload = await self._get(f"projects/{quote(project_ref, safe='')}")
        self._ensure_project_allowed(project_ref, payload=payload)
        project = self.normalize_project(payload)
        form = await self._post(f"projects/{project.id}/form", json_body={"name": project.name})
        schema = form.get("_embedded", {}).get("schema", {})
        fields = [
            self._normalize_project_field_schema(key, entry) for key, entry in schema.items() if isinstance(entry, dict)
        ]
        status_field = next((field for field in fields if field.key == "status"), None)
        available_statuses = status_field.allowed_values if status_field else []
        available_parent_projects = await self._list_available_parent_projects(project.id, schema=schema)
        return self._apply_hidden_fields(
            "project_admin_context",
            ProjectAdminContext(
                project=project,
                available_statuses=available_statuses,
                available_parent_projects=available_parent_projects,
                fields=fields,
                project_links=sorted(payload.get("_links", {}).keys()),
            ),
        )

    async def get_project_configuration(self, project_ref: str) -> ProjectConfiguration:
        self._ensure_read_enabled("project")
        payload = await self._get(f"projects/{quote(project_ref, safe='')}")
        self._ensure_project_allowed(project_ref, payload=payload)
        project = self.normalize_project(payload)
        configuration = await self._get(f"projects/{project.id}/configuration")
        return self.normalize_project_configuration(configuration, project=project)

    async def create_project(
        self,
        *,
        name: str,
        identifier: str,
        description: str | None = None,
        public: bool | None = None,
        active: bool | None = None,
        status: str | None = None,
        status_explanation: str | None = None,
        parent: str | None = None,
        confirm: bool = False,
    ) -> ProjectWriteResult:
        self._ensure_project_write_candidate_allowed(identifier=identifier, name=name)
        payload = await self._build_project_write_payload(
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
        form = await self._post("projects/form", json_body=payload)
        return await self._finalize_project_write(
            action="create",
            confirm=confirm,
            form=form,
            write_path="projects",
            preview_message="OpenProject validated the project. Ask for confirmation, then call again with confirm=true to create it.",
            success_message="Project created successfully.",
        )

    async def update_project(
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
        parent: str | None = None,
        confirm: bool = False,
    ) -> ProjectWriteResult:
        current = await self._get(f"projects/{quote(project_ref, safe='')}")
        self._ensure_project_write_allowed(project_ref, payload=current)
        project = self.normalize_project(current)
        payload = await self._build_project_write_payload(
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
        form = await self._post(f"projects/{project.id}/form", json_body=payload)
        return await self._finalize_project_write(
            action="update",
            confirm=confirm,
            form=form,
            write_path=f"projects/{project.id}",
            write_method="PATCH",
            project_id=project.id,
            project_name=project.name,
            success_message="Project updated successfully.",
        )

    async def delete_project(
        self,
        *,
        project_ref: str,
        confirm: bool = False,
    ) -> ProjectWriteResult:
        payload_current = await self._get(f"projects/{quote(project_ref, safe='')}")
        self._ensure_project_write_allowed(project_ref, payload=payload_current)
        project = self.normalize_project(payload_current)
        payload = {"id": project.id, "identifier": project.identifier, "name": project.name}
        if self._preview_mode(confirm, delete=True):
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
        self._ensure_write_enabled("project")
        await self._delete(f"projects/{project.id}")
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

    async def copy_project(
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
        parent: str | None = None,
        confirm: bool = False,
    ) -> ProjectCopyResult:
        source_payload = await self._get(f"projects/{quote(source_project, safe='')}")
        self._ensure_project_write_allowed(source_project, payload=source_payload)
        # Also validate the destination so a copy cannot create a project outside
        # the read/write allowlist (the source being allowed is not sufficient).
        self._ensure_project_write_candidate_allowed(identifier=identifier, name=name)
        project = self.normalize_project(source_payload)
        payload = await self._build_project_write_payload(
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
        form = await self._post(f"projects/{project.id}/copy/form", json_body=payload)
        form_payload = form.get("_embedded", {}).get("payload", payload)
        validation_errors = _normalize_validation_errors(form.get("_embedded", {}).get("validationErrors"))
        ready = not validation_errors
        if self._preview_mode(confirm):
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
                payload=form_payload,
                validation_errors=validation_errors,
                job_status_id=None,
                job_status_url=None,
            )
        if validation_errors:
            return ProjectCopyResult(
                action="copy",
                confirmed=False,
                requires_confirmation=False,
                ready=False,
                message="OpenProject rejected the project copy payload. Fix the validation errors and try again.",
                source_project_id=project.id,
                source_project=project.name,
                payload=form_payload,
                validation_errors=validation_errors,
                job_status_id=None,
                job_status_url=None,
            )
        self._ensure_write_enabled("project")
        response = await self._request("POST", f"projects/{project.id}/copy", json_body=form_payload)
        redirect = response.history[0] if response.history else response
        job_status_url = self._link_to_web_url(redirect.headers.get("Location"))
        return ProjectCopyResult(
            action="copy",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Project copy job started successfully.",
            source_project_id=project.id,
            source_project=project.name,
            payload=form_payload,
            validation_errors={},
            job_status_id=_id_from_href(job_status_url),
            job_status_url=job_status_url,
        )

    async def get_job_status(self, job_status_id: int) -> JobStatusDetail:
        self._ensure_read_enabled("project")
        payload = await self._get(f"job_statuses/{job_status_id}")
        project_link = payload.get("_links", {}).get("project")
        if isinstance(project_link, dict):
            self._ensure_project_link_allowed(project_link)
        return self.normalize_job_status(payload)

    async def list_roles(self) -> RoleListResult:
        self._ensure_read_enabled("role")
        payload = await self._get("roles")
        roles = [self.normalize_role(item) for item in payload.get("_embedded", {}).get("elements", [])]
        return RoleListResult(count=len(roles), results=roles)

    async def list_principals(
        self,
        *,
        search: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> PrincipalListResult:
        self._ensure_read_enabled("principal")
        effective_limit = self._resolve_limit(limit)
        filters: list[dict[str, Any]] = []
        if search:
            filters.append({"name": {"operator": "~", "values": [search]}})
        payload = await self._get(
            "principals",
            params={
                "offset": str(offset),
                "pageSize": str(effective_limit),
                "filters": _json_param(filters),
            },
        )
        results = [self.normalize_principal(item) for item in payload.get("_embedded", {}).get("elements", [])]
        total = int(payload.get("total", len(results)))
        return PrincipalListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(results),
            next_offset=_next_offset(offset, effective_limit, total),
            truncated=total > offset * effective_limit,
            results=results,
        )

    async def list_users(
        self,
        *,
        search: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> UserListResult:
        self._ensure_read_enabled("membership")
        effective_limit = self._resolve_limit(limit)
        payload = await self._get(
            "users",
            params={
                "offset": str(offset),
                "pageSize": str(effective_limit),
            },
        )
        results = [
            self.normalize_user(item)
            for item in payload.get("_embedded", {}).get("elements", [])
            if isinstance(item, dict)
        ]
        if search is not None:
            search_key = search.casefold()
            results = [
                item
                for item in results
                if search_key in (item.name or "").casefold()
                or search_key in (item.login or "").casefold()
                or search_key in (item.email or "").casefold()
            ]
        total = int(payload.get("total", len(results)))
        return UserListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(results),
            next_offset=_next_offset(offset, effective_limit, total),
            truncated=total > offset * effective_limit,
            results=results,
        )

    async def get_user(self, user_ref: str) -> UserDetail:
        self._ensure_read_enabled("membership")
        payload = await self._get(f"users/{quote(user_ref, safe='')}")
        return self.normalize_user_detail(payload)

    async def list_groups(
        self,
        *,
        search: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> GroupListResult:
        self._ensure_read_enabled("membership")
        effective_limit = self._resolve_limit(limit)
        payload = await self._get(
            "groups",
            params={
                "offset": str(offset),
                "pageSize": str(effective_limit),
            },
        )
        results = [
            self.normalize_group(item)
            for item in payload.get("_embedded", {}).get("elements", [])
            if isinstance(item, dict)
        ]
        if search is not None:
            search_key = search.casefold()
            results = [item for item in results if search_key in (item.name or "").casefold()]
        total = int(payload.get("total", len(results)))
        return GroupListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(results),
            next_offset=_next_offset(offset, effective_limit, total),
            truncated=total > offset * effective_limit,
            results=results,
        )

    async def get_group(self, group_id: int) -> GroupDetail:
        self._ensure_read_enabled("membership")
        payload = await self._get(f"groups/{group_id}")
        return self.normalize_group_detail(payload)

    async def list_actions(
        self,
        *,
        offset: int = 1,
        limit: int | None = None,
    ) -> ActionListResult:
        self._ensure_read_enabled("membership")
        effective_limit = self._resolve_limit(limit)
        payload = await self._get(
            "actions",
            params={
                "offset": str(offset),
                "pageSize": str(effective_limit),
            },
        )
        results = [
            self.normalize_action(item)
            for item in payload.get("_embedded", {}).get("elements", [])
            if isinstance(item, dict)
        ]
        total = int(payload.get("total", len(results)))
        return ActionListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(results),
            next_offset=_next_offset(offset, effective_limit, total),
            truncated=total > offset * effective_limit,
            results=results,
        )

    async def list_capabilities(
        self,
        *,
        project: str | None = None,
        capability_id: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> CapabilityListResult:
        self._ensure_read_enabled("membership")
        if project is None and capability_id is None:
            raise InvalidInputError("At least one of project or capability_id is required for capabilities.")
        effective_limit = self._resolve_limit(limit)
        filters: list[dict[str, Any]] = []
        if capability_id is not None:
            filters.append({"id": {"operator": "=", "values": [capability_id]}})
        if project is not None:
            project_id = await self._resolve_project_id(project)
            filters.append({"context": {"operator": "=", "values": [f"p{project_id}"]}})
        payload = await self._get(
            "capabilities",
            params={
                "offset": str(offset),
                "pageSize": str(effective_limit),
                "filters": _json_param(filters),
            },
        )
        results = [
            self.normalize_capability(item)
            for item in payload.get("_embedded", {}).get("elements", [])
            if isinstance(item, dict)
        ]
        total = int(payload.get("total", len(results)))
        return CapabilityListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(results),
            next_offset=_next_offset(offset, effective_limit, total),
            truncated=total > offset * effective_limit,
            results=results,
        )

    async def get_query_filter(self, filter_id: str) -> QueryFilterSummary:
        self._ensure_read_enabled("board")
        payload = await self._get(f"queries/filters/{quote(filter_id, safe='')}")
        return self.normalize_query_filter(payload)

    async def get_query_column(self, column_id: str) -> QueryColumnSummary:
        self._ensure_read_enabled("board")
        payload = await self._get(f"queries/columns/{quote(column_id, safe='')}")
        return self.normalize_query_column(payload)

    async def get_query_operator(self, operator_id: str) -> QueryOperatorSummary:
        self._ensure_read_enabled("board")
        payload = await self._get(f"queries/operators/{quote(operator_id, safe='')}")
        return self.normalize_query_operator(payload)

    async def get_query_sort_by(self, sort_by_id: str) -> QuerySortBySummary:
        self._ensure_read_enabled("board")
        payload = await self._get(f"queries/sort_bys/{quote(sort_by_id, safe='')}")
        return self.normalize_query_sort_by(payload)

    async def list_query_filter_instance_schemas(
        self,
        *,
        project: str | None = None,
    ) -> QueryFilterInstanceSchemaListResult:
        self._ensure_read_enabled("board")
        path = "queries/filter_instance_schemas"
        if project is not None:
            project_id = await self._resolve_project_id(project)
            path = f"projects/{project_id}/queries/filter_instance_schemas"
        payload = await self._get(path)
        results = [
            self.normalize_query_filter_instance_schema(item)
            for item in payload.get("_embedded", {}).get("elements", [])
            if isinstance(item, dict)
        ]
        return QueryFilterInstanceSchemaListResult(count=len(results), results=results)

    async def get_query_filter_instance_schema(self, schema_id: str) -> QueryFilterInstanceSchemaSummary:
        self._ensure_read_enabled("board")
        payload = await self._get(f"queries/filter_instance_schemas/{quote(schema_id, safe='')}")
        return self.normalize_query_filter_instance_schema(payload)

    async def list_project_memberships(self, project_ref: str) -> MembershipListResult:
        self._ensure_read_enabled("membership")
        project_payload = await self._get(f"projects/{quote(project_ref, safe='')}")
        self._ensure_project_allowed(project_ref, payload=project_payload)
        href = project_payload.get("_links", {}).get("memberships", {}).get("href")
        if not href:
            return MembershipListResult(count=0, results=[])
        payload = await self._get(self._link_to_api_path(href))
        memberships = [self.normalize_membership(item) for item in payload.get("_embedded", {}).get("elements", [])]
        return MembershipListResult(count=len(memberships), results=memberships)

    async def get_membership(self, membership_id: int) -> MembershipSummary:
        self._ensure_read_enabled("membership")
        payload = await self._get(f"memberships/{membership_id}")
        self._ensure_project_link_allowed(payload.get("_links", {}).get("project"))
        return self.normalize_membership(payload)

    async def create_membership(
        self,
        *,
        project: str,
        principal: str,
        roles: list[str],
        notification_message: str | None = None,
        confirm: bool = False,
    ) -> MembershipWriteResult:
        project_payload = await self._get_project_payload(project, write=True)
        self._ensure_field_writable("membership", "project_name")
        self._ensure_field_writable("membership", "principal_name")
        self._ensure_field_writable("membership", "role_names")
        project_id = str(project_payload["id"])
        principal_id = await self._resolve_principal_id(principal)
        role_hrefs = await self._resolve_role_hrefs(roles)
        payload: dict[str, Any] = {
            "_links": {
                "project": {"href": self._api_href(f"projects/{project_id}")},
                "principal": {"href": self._api_href(f"users/{principal_id}")},
                "roles": [{"href": href} for href in role_hrefs],
            }
        }
        if notification_message is not None:
            payload["_meta"] = {"notificationMessage": {"format": "markdown", "raw": notification_message}}
        form = await self._post("memberships/form", json_body=payload)
        return await self._finalize_membership_write(
            action="create",
            confirm=confirm,
            form=form,
            write_path="memberships",
            project_name=_trim_text(project_payload.get("name"), limit=SUBJECT_LIMIT),
            preview_message="OpenProject validated the membership. Ask for confirmation, then call again with confirm=true to create it.",
            success_message="Membership created successfully.",
        )

    async def update_membership(
        self,
        *,
        membership_id: int,
        roles: list[str],
        notification_message: str | None = None,
        confirm: bool = False,
    ) -> MembershipWriteResult:
        current = await self._get(f"memberships/{membership_id}")
        self._ensure_project_write_link_allowed(current.get("_links", {}).get("project"))
        self._ensure_field_writable("membership", "role_names")
        role_hrefs = await self._resolve_role_hrefs(roles)
        payload: dict[str, Any] = {
            "_links": {
                "roles": [{"href": href} for href in role_hrefs],
            }
        }
        if notification_message is not None:
            payload["_meta"] = {"notificationMessage": {"format": "markdown", "raw": notification_message}}
        form = await self._post(f"memberships/{membership_id}/form", json_body=payload)
        return await self._finalize_membership_write(
            action="update",
            confirm=confirm,
            form=form,
            write_path=f"memberships/{membership_id}",
            write_method="PATCH",
            membership_id=membership_id,
            project_name=_link_title(current.get("_links", {}).get("project")),
            success_message="Membership updated successfully.",
        )

    async def delete_membership(
        self,
        *,
        membership_id: int,
        confirm: bool = False,
    ) -> MembershipWriteResult:
        current = await self._get(f"memberships/{membership_id}")
        self._ensure_project_write_link_allowed(current.get("_links", {}).get("project"))
        membership = self.normalize_membership(current)
        payload = {
            "id": membership.id,
            "principal": membership.principal_name,
            "roles": membership.role_names,
        }
        if self._preview_mode(confirm, delete=True):
            return MembershipWriteResult(
                action="delete",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject found the membership. Ask for confirmation, then call again with confirm=true to delete it.",
                membership_id=membership.id,
                project=membership.project_name,
                payload=payload,
                validation_errors={},
                result=None,
            )
        self._ensure_write_enabled("membership")
        await self._delete(f"memberships/{membership_id}")
        return MembershipWriteResult(
            action="delete",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Membership deleted successfully.",
            membership_id=membership.id,
            project=membership.project_name,
            payload=payload,
            validation_errors={},
            result=membership,
        )

    async def get_my_project_access(self, project_ref: str) -> ProjectAccessSummary:
        self._ensure_read_enabled("project")
        self._ensure_read_enabled("membership")
        self._ensure_read_enabled("principal")
        current_user = await self.get_current_user()
        project_payload = await self._get(f"projects/{quote(project_ref, safe='')}")
        self._ensure_project_allowed(project_ref, payload=project_payload)
        project_summary = self.normalize_project(project_payload)
        memberships = await self.list_project_memberships(project_ref)
        my_membership = next((item for item in memberships.results if item.principal_id == current_user.id), None)
        project_links = sorted(project_payload.get("_links", {}).keys())
        inferred_is_project_admin = any(
            name.casefold() == "project admin" for name in (my_membership.role_names if my_membership else [])
        )
        inferred_can_edit_project = (
            "update" in project_links or "updateImmediately" in project_links or inferred_is_project_admin
        )
        inferred_can_manage_memberships = bool(
            my_membership
            and (my_membership.can_update or my_membership.can_update_immediately or inferred_is_project_admin)
        )
        return self._apply_hidden_fields(
            "project_access",
            ProjectAccessSummary(
                project_id=project_summary.id,
                project_name=project_summary.name,
                project_identifier=project_summary.identifier,
                current_user_id=current_user.id,
                current_user_name=current_user.name,
                membership=my_membership,
                project_links=project_links,
                inferred_is_project_admin=inferred_is_project_admin,
                inferred_can_edit_project=inferred_can_edit_project,
                inferred_can_manage_memberships=inferred_can_manage_memberships,
                inference_basis="Derived from project HATEOAS links and the current user's project membership roles.",
            ),
        )

    async def get_instance_configuration(self) -> InstanceConfiguration:
        self._ensure_read_enabled("project")
        payload = await self._get("configuration")
        return self.normalize_instance_configuration(payload)

    async def list_project_phase_definitions(self) -> ProjectPhaseDefinitionListResult:
        self._ensure_read_enabled("project")
        payload = await self._get("project_phase_definitions")
        elements = payload.get("_embedded", {}).get("elements", [])
        results = [
            self.normalize_project_phase_definition(item)
            for item in elements
            if isinstance(item, dict) and item.get("_type") == "ProjectPhaseDefinition"
        ]
        return ProjectPhaseDefinitionListResult(count=len(results), results=results)

    async def get_project_phase_definition(self, phase_definition_id: int) -> ProjectPhaseDefinition:
        self._ensure_read_enabled("project")
        payload = await self._get(f"project_phase_definitions/{phase_definition_id}")
        return self.normalize_project_phase_definition(payload)

    async def get_project_phase(self, phase_id: int) -> ProjectPhase:
        self._ensure_read_enabled("project")
        payload = await self._get(f"project_phases/{phase_id}")
        self._ensure_project_link_allowed(payload.get("_links", {}).get("project"))
        return self.normalize_project_phase(payload)

    async def list_views(
        self,
        *,
        project: str | None = None,
        view_type: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> ViewListResult:
        self._ensure_read_enabled("project")
        effective_limit = self._resolve_limit(limit)
        payload = await self._get(
            "views",
            params={
                "offset": "1",
                "pageSize": str(self.settings.max_results),
            },
        )
        results = [
            self.normalize_view(item)
            for item in payload.get("_embedded", {}).get("elements", [])
            if isinstance(item, dict) and self._view_payload_allowed(item)
        ]
        if project is not None:
            project_payload = await self._get(f"projects/{quote(project, safe='')}")
            self._ensure_project_allowed(project, payload=project_payload)
            project_candidates = {
                str(project_payload["id"]).casefold(),
                (_trim_text(project_payload.get("identifier"), limit=SUBJECT_LIMIT) or "").casefold(),
                (_trim_text(project_payload.get("name"), limit=SUBJECT_LIMIT) or "").casefold(),
            }
            results = [
                item
                for item in results
                if not project_candidates.isdisjoint(
                    {
                        str(item.project_id).casefold() if item.project_id is not None else "",
                        (item.project or "").casefold(),
                    }
                )
            ]
        if view_type is not None:
            results = [item for item in results if (item.type or "").casefold() == view_type.casefold()]

        total = len(results)
        start = (offset - 1) * effective_limit
        end = start + effective_limit
        page = results[start:end]
        return ViewListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(page),
            next_offset=offset + 1 if end < total else None,
            truncated=end < total,
            results=page,
        )

    async def get_view(self, view_id: int) -> ViewDetail:
        self._ensure_read_enabled("project")
        payload = await self._get(f"views/{view_id}")
        self._ensure_view_payload_allowed(payload)
        return self.normalize_view_detail(payload)

    async def list_documents(
        self,
        *,
        project: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> DocumentListResult:
        self._ensure_read_enabled("project")
        effective_limit = self._resolve_limit(limit)
        payload = await self._get(
            "documents",
            params={
                "offset": "1",
                "pageSize": str(self.settings.max_results),
            },
        )
        results = [
            self.normalize_document(item)
            for item in payload.get("_embedded", {}).get("elements", [])
            if isinstance(item, dict) and self._document_payload_allowed(item)
        ]

        if project is not None:
            project_payload = await self._get(f"projects/{quote(project, safe='')}")
            self._ensure_project_allowed(project, payload=project_payload)
            project_candidates = {
                str(project_payload["id"]).casefold(),
                (_trim_text(project_payload.get("identifier"), limit=SUBJECT_LIMIT) or "").casefold(),
                (_trim_text(project_payload.get("name"), limit=SUBJECT_LIMIT) or "").casefold(),
            }
            results = [
                item
                for item in results
                if not project_candidates.isdisjoint(
                    {
                        str(item.project_id).casefold() if item.project_id is not None else "",
                        (item.project or "").casefold(),
                    }
                )
            ]

        total = len(results)
        start = (offset - 1) * effective_limit
        end = start + effective_limit
        page = results[start:end]
        return DocumentListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(page),
            next_offset=offset + 1 if end < total else None,
            truncated=end < total,
            results=page,
        )

    async def get_document(self, document_id: int) -> DocumentDetail:
        self._ensure_read_enabled("project")
        payload = await self._get(f"documents/{document_id}")
        self._ensure_document_payload_allowed(payload)
        return self.normalize_document_detail(payload)

    async def update_document(
        self,
        *,
        document_id: int,
        title: str | None = None,
        description: str | None = None,
        confirm: bool = False,
    ) -> DocumentWriteResult:
        current = await self._get(f"documents/{document_id}")
        self._ensure_document_write_payload_allowed(current)
        payload: dict[str, Any] = {}
        if title is not None:
            self._ensure_field_writable("document", "title")
            payload["title"] = title
        if description is not None:
            self._ensure_field_writable("document", "description")
            payload["description"] = {"format": "markdown", "raw": description}
        detail = self.normalize_document_detail(current)
        if self._preview_mode(confirm):
            return DocumentWriteResult(
                action="update",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject is ready to update this document. Ask for confirmation, then call again with confirm=true.",
                document_id=detail.id,
                project=detail.project,
                payload=payload,
                validation_errors={},
                result=None,
            )
        self._ensure_write_enabled("project")
        response = await self._patch(f"documents/{document_id}", json_body=payload)
        result = self.normalize_document_detail(response)
        return DocumentWriteResult(
            action="update",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Document updated successfully.",
            document_id=result.id,
            project=result.project,
            payload=payload,
            validation_errors={},
            result=result,
        )

    async def list_news(
        self,
        *,
        project: str | None = None,
        search: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> NewsListResult:
        self._ensure_read_enabled("project")
        effective_limit = self._resolve_limit(limit)
        payload = await self._get(
            "news",
            params={
                "offset": "1",
                "pageSize": str(self.settings.max_results),
            },
        )
        results = [
            self.normalize_news(item)
            for item in payload.get("_embedded", {}).get("elements", [])
            if isinstance(item, dict) and self._news_payload_allowed(item)
        ]

        if project is not None:
            project_payload = await self._get(f"projects/{quote(project, safe='')}")
            self._ensure_project_allowed(project, payload=project_payload)
            project_candidates = {
                str(project_payload["id"]).casefold(),
                (_trim_text(project_payload.get("identifier"), limit=SUBJECT_LIMIT) or "").casefold(),
                (_trim_text(project_payload.get("name"), limit=SUBJECT_LIMIT) or "").casefold(),
            }
            results = [
                item
                for item in results
                if not project_candidates.isdisjoint(
                    {
                        str(item.project_id).casefold() if item.project_id is not None else "",
                        (item.project or "").casefold(),
                    }
                )
            ]

        if search is not None:
            search_key = search.casefold()
            results = [
                item
                for item in results
                if search_key in (item.title or "").casefold() or search_key in (item.summary or "").casefold()
            ]

        total = len(results)
        start = (offset - 1) * effective_limit
        end = start + effective_limit
        page = results[start:end]
        return NewsListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(page),
            next_offset=offset + 1 if end < total else None,
            truncated=end < total,
            results=page,
        )

    async def get_news(self, news_id: int) -> NewsDetail:
        self._ensure_read_enabled("project")
        payload = await self._get(f"news/{news_id}")
        self._ensure_news_payload_allowed(payload)
        return self.normalize_news_detail(payload)

    async def create_news(
        self,
        *,
        project: str,
        title: str,
        summary: str | None = None,
        description: str | None = None,
        confirm: bool = False,
    ) -> NewsWriteResult:
        project_payload = await self._get(f"projects/{quote(project, safe='')}")
        self._ensure_project_write_allowed(project, payload=project_payload)
        project_id = str(project_payload["id"])
        self._ensure_field_writable("news", "title")
        payload: dict[str, Any] = {
            "title": title,
            "_links": {"project": {"href": self._api_href(f"projects/{project_id}")}},
        }
        if summary is not None:
            self._ensure_field_writable("news", "summary")
            payload["summary"] = summary
        if description is not None:
            self._ensure_field_writable("news", "description")
            payload["description"] = {"format": "markdown", "raw": description}
        if self._preview_mode(confirm):
            return NewsWriteResult(
                action="create",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject is ready to create this news entry. Ask for confirmation, then call again with confirm=true.",
                news_id=None,
                project=_trim_text(project_payload.get("name"), limit=SUBJECT_LIMIT),
                payload=payload,
                validation_errors={},
                result=None,
            )
        self._ensure_write_enabled("project")
        response = await self._post("news", json_body=payload)
        result = self.normalize_news_detail(response)
        return NewsWriteResult(
            action="create",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="News created successfully.",
            news_id=result.id,
            project=result.project,
            payload=payload,
            validation_errors={},
            result=result,
        )

    async def update_news(
        self,
        *,
        news_id: int,
        title: str | None = None,
        summary: str | None = None,
        description: str | None = None,
        confirm: bool = False,
    ) -> NewsWriteResult:
        current = await self._get(f"news/{news_id}")
        self._ensure_news_write_payload_allowed(current)
        detail = self.normalize_news_detail(current)
        payload: dict[str, Any] = {}
        if title is not None:
            self._ensure_field_writable("news", "title")
            payload["title"] = title
        if summary is not None:
            self._ensure_field_writable("news", "summary")
            payload["summary"] = summary
        if description is not None:
            self._ensure_field_writable("news", "description")
            payload["description"] = {"format": "markdown", "raw": description}
        if self._preview_mode(confirm):
            return NewsWriteResult(
                action="update",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject is ready to update this news entry. Ask for confirmation, then call again with confirm=true.",
                news_id=detail.id,
                project=detail.project,
                payload=payload,
                validation_errors={},
                result=None,
            )
        self._ensure_write_enabled("project")
        response = await self._patch(f"news/{news_id}", json_body=payload)
        result = self.normalize_news_detail(response)
        return NewsWriteResult(
            action="update",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="News updated successfully.",
            news_id=result.id,
            project=result.project,
            payload=payload,
            validation_errors={},
            result=result,
        )

    async def delete_news(
        self,
        *,
        news_id: int,
        confirm: bool = False,
    ) -> NewsWriteResult:
        current = await self._get(f"news/{news_id}")
        self._ensure_news_write_payload_allowed(current)
        detail = self.normalize_news_detail(current)
        payload = {"id": detail.id, "title": detail.title}
        if self._preview_mode(confirm, delete=True):
            return NewsWriteResult(
                action="delete",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject found the news entry. Ask for confirmation, then call again with confirm=true to delete it.",
                news_id=detail.id,
                project=detail.project,
                payload=payload,
                validation_errors={},
                result=detail,
            )
        self._ensure_write_enabled("project")
        await self._delete(f"news/{news_id}")
        return NewsWriteResult(
            action="delete",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="News deleted successfully.",
            news_id=detail.id,
            project=detail.project,
            payload=payload,
            validation_errors={},
            result=detail,
        )

    async def get_wiki_page(self, wiki_page_id: int) -> WikiPageDetail:
        self._ensure_read_enabled("project")
        payload = await self._get(f"wiki_pages/{wiki_page_id}")
        self._ensure_project_link_allowed(payload.get("_links", {}).get("project"))
        return self.normalize_wiki_page(payload)

    async def list_categories(self, project_ref: str) -> CategoryListResult:
        self._ensure_read_enabled("project")
        project_payload = await self._get(f"projects/{quote(project_ref, safe='')}")
        self._ensure_project_allowed(project_ref, payload=project_payload)
        project_id = int(project_payload["id"])
        payload = await self._get(f"projects/{project_id}/categories")
        project_name = _trim_text(project_payload.get("name"), limit=SUBJECT_LIMIT)
        results = [
            self.normalize_category(item, project_id=project_id, project_name=project_name)
            for item in payload.get("_embedded", {}).get("elements", [])
            if isinstance(item, dict)
        ]
        return CategoryListResult(count=len(results), results=results)

    async def get_category(self, *, project_ref: str, category_id: int) -> CategorySummary:
        categories = await self.list_categories(project_ref)
        for category in categories.results:
            if category.id == category_id:
                return category
        raise NotFoundError("OpenProject category not found in this project.")

    async def list_work_package_attachments(self, work_package_id: int | str) -> AttachmentListResult:
        self._ensure_read_enabled("work_package")
        work_package_id = self._work_package_ref(work_package_id)
        work_package = await self.get_work_package(work_package_id)
        payload = await self._get(f"work_packages/{work_package_id}/attachments")
        results = [
            self.normalize_attachment(item)
            for item in payload.get("_embedded", {}).get("elements", [])
            if isinstance(item, dict)
        ]
        results = [
            item for item in results if item.container_type == "WorkPackage" and item.container_id == work_package.id
        ]
        return AttachmentListResult(count=len(results), results=results)

    async def get_attachment(self, attachment_id: int) -> AttachmentSummary:
        self._ensure_read_enabled("work_package")
        payload = await self._get(f"attachments/{attachment_id}")
        attachment = self.normalize_attachment(payload)
        await self._ensure_attachment_container_allowed(payload)
        return attachment

    async def create_work_package_attachment(
        self,
        *,
        work_package_id: int | str,
        file_path: str,
        description: str | None = None,
        confirm: bool = False,
    ) -> AttachmentWriteResult:
        work_package_id = self._work_package_ref(work_package_id)
        work_package_payload = await self._get(f"work_packages/{work_package_id}")
        self._ensure_project_write_link_allowed(work_package_payload.get("_links", {}).get("project"))
        file_info = self._prepare_attachment_file(file_path, include_bytes=confirm)
        await self._validate_attachment_size(file_info["file_size"])
        if self._preview_mode(confirm):
            return AttachmentWriteResult(
                action="create",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject is ready to upload this attachment. Ask for confirmation, then call again with confirm=true.",
                attachment_id=None,
                work_package_id=work_package_id,
                payload={
                    "fileName": file_info["file_name"],
                    "fileSize": file_info["file_size"],
                    "description": description,
                },
                validation_errors={},
                result=None,
            )

        self._ensure_write_enabled("work_package")
        response = await self._post_multipart(
            f"work_packages/{work_package_id}/attachments",
            metadata={
                "fileName": file_info["file_name"],
                **({"description": {"format": "markdown", "raw": description}} if description is not None else {}),
            },
            file_name=file_info["file_name"],
            file_bytes=file_info["file_bytes"],
            content_type=file_info["content_type"],
        )
        result = self.normalize_attachment(response)
        return AttachmentWriteResult(
            action="create",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Attachment uploaded successfully.",
            attachment_id=result.id,
            work_package_id=work_package_id,
            payload={
                "fileName": file_info["file_name"],
                "fileSize": file_info["file_size"],
                "description": description,
            },
            validation_errors={},
            result=result,
        )

    async def delete_attachment(
        self,
        *,
        attachment_id: int,
        confirm: bool = False,
    ) -> AttachmentWriteResult:
        payload = await self._get(f"attachments/{attachment_id}")
        attachment = self.normalize_attachment(payload)
        work_package_id = await self._ensure_attachment_container_allowed(payload, write=True)
        preview_payload = {
            "id": attachment.id,
            "title": attachment.title,
            "fileName": attachment.file_name,
            "fileSize": attachment.file_size,
        }
        if self._preview_mode(confirm, delete=True):
            return AttachmentWriteResult(
                action="delete",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject found the attachment. Ask for confirmation, then call again with confirm=true to delete it.",
                attachment_id=attachment.id,
                work_package_id=work_package_id,
                payload=preview_payload,
                validation_errors={},
                result=attachment,
            )

        self._ensure_write_enabled("work_package")
        await self._delete(f"attachments/{attachment_id}")
        return AttachmentWriteResult(
            action="delete",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Attachment deleted successfully.",
            attachment_id=attachment.id,
            work_package_id=work_package_id,
            payload=preview_payload,
            validation_errors={},
            result=None,
        )

    async def list_time_entry_activities(self) -> TimeEntryActivityListResult:
        self._ensure_read_enabled("work_package")
        # Try the global endpoint first; fall back to a project-scoped form if it is not available.
        try:
            payload = await self._get("time_entries/activities")
            elements = payload.get("_embedded", {}).get("elements", [])
            results = [self.normalize_time_entry_activity(item) for item in elements if isinstance(item, dict)]
            if results:
                return TimeEntryActivityListResult(count=len(results), results=results)
        except (NotFoundError, PermissionDeniedError, OpenProjectServerError):
            pass
        # Global endpoint not available or returned no results — derive activities from the
        # time_entries form schema by scanning visible projects until one exposes activities.
        try:
            offset = 1
            while True:
                projects = await self.list_projects(offset=offset, limit=self.settings.max_page_size)
                for project in projects.results:
                    try:
                        results = await self._time_entry_activities_from_project(project.id)
                    except (NotFoundError, PermissionDeniedError, OpenProjectServerError):
                        continue
                    if results:
                        return TimeEntryActivityListResult(count=len(results), results=results)
                if projects.next_offset is None:
                    break
                offset = projects.next_offset
            return TimeEntryActivityListResult(count=0, results=[])
        except (NotFoundError, PermissionDeniedError, OpenProjectServerError):
            return TimeEntryActivityListResult(count=0, results=[])

    async def list_time_entries(
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
        self._ensure_read_enabled("work_package")
        if work_package_id is not None:
            work_package_id = await self._resolve_work_package_id(work_package_id)
        if project is not None:
            project_payload = await self._get_project_payload(project)
            project_candidates = {
                project.casefold(),
                str(project_payload["id"]).casefold(),
                (_trim_text(project_payload.get("identifier"), limit=SUBJECT_LIMIT) or "").casefold(),
                (_trim_text(project_payload.get("name"), limit=SUBJECT_LIMIT) or "").casefold(),
            }
        else:
            project_candidates = set()

        user_name = None
        if user is not None:
            if user.casefold() == "me":
                user_name = (await self.get_current_user()).name
            elif user.isdigit():
                user_payload = await self._get(f"users/{user}")
                user_name = _trim_text(user_payload.get("name"), limit=SUBJECT_LIMIT)
            else:
                user_name = user

        effective_limit = self._resolve_limit(limit)
        payload = await self._get(
            "time_entries",
            params={
                "offset": "1",
                "pageSize": str(self.settings.max_results),
            },
        )
        raw_entries = [
            item
            for item in payload.get("_embedded", {}).get("elements", [])
            if isinstance(item, dict) and self._time_entry_payload_allowed(item)
        ]
        if project_candidates:
            raw_entries = [
                item
                for item in raw_entries
                if self._link_matches_project_refs(item.get("_links", {}).get("project"), project_candidates)
            ]
        results = [self.normalize_time_entry(item) for item in raw_entries]
        if work_package_id is not None:
            results = [
                item for item in results if item.entity_type == "WorkPackage" and item.entity_id == work_package_id
            ]
        if user_name is not None:
            results = [item for item in results if (item.user or "").casefold() == (user_name or "").casefold()]
        if spent_on_from is not None:
            results = [item for item in results if item.spent_on is not None and item.spent_on >= spent_on_from]
        if spent_on_to is not None:
            results = [item for item in results if item.spent_on is not None and item.spent_on <= spent_on_to]

        total = len(results)
        start = (offset - 1) * effective_limit
        end = start + effective_limit
        page = results[start:end]
        return TimeEntryListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(page),
            next_offset=offset + 1 if end < total else None,
            truncated=end < total,
            results=page,
        )

    async def get_time_entry(self, time_entry_id: int) -> TimeEntrySummary:
        self._ensure_read_enabled("work_package")
        payload = await self._get(f"time_entries/{time_entry_id}")
        project_link = payload.get("_links", {}).get("project")
        self._ensure_project_link_allowed(project_link)
        return self.normalize_time_entry(payload)

    async def create_time_entry(
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
        if work_package_id is not None:
            work_package_id = self._work_package_ref(work_package_id)
        project_name = None
        activity_project_id = None
        # The entity HAL link needs the numeric id (hrefs don't resolve displayId);
        # read it back from the fetched work package rather than reusing the ref.
        work_package_numeric_id = None
        if project is not None:
            project_payload = await self._get_project_payload(project, write=True)
            project_name = _trim_text(project_payload.get("name"), limit=SUBJECT_LIMIT)
            activity_project_id = int(project_payload["id"])
        if work_package_id is not None:
            work_package_payload = await self._get(f"work_packages/{work_package_id}")
            self._ensure_project_write_link_allowed(work_package_payload.get("_links", {}).get("project"))
            work_package_numeric_id = int(work_package_payload["id"])
            if project_name is None:
                project_name = _link_title(work_package_payload.get("_links", {}).get("project"))
            if activity_project_id is None:
                activity_project_id = _id_from_href(
                    work_package_payload.get("_links", {}).get("project", {}).get("href")
                )
        payload = await self._build_time_entry_write_payload(
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
        if self._preview_mode(confirm):
            return TimeEntryWriteResult(
                action="create",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject is ready to create this time entry. Ask for confirmation, then call again with confirm=true.",
                time_entry_id=None,
                project=project_name,
                payload=payload,
                validation_errors={},
                result=None,
            )
        self._ensure_write_enabled("work_package")
        response = await self._post("time_entries", json_body=payload)
        result = self.normalize_time_entry(response)
        return TimeEntryWriteResult(
            action="create",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Time entry created successfully.",
            time_entry_id=result.id,
            project=result.project,
            payload=payload,
            validation_errors={},
            result=result,
        )

    async def update_time_entry(
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
        current = await self._get(f"time_entries/{time_entry_id}")
        self._ensure_project_write_link_allowed(current.get("_links", {}).get("project"))
        project_id = _id_from_href(current.get("_links", {}).get("project", {}).get("href"))
        payload = await self._build_time_entry_write_payload(
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
        if self._preview_mode(confirm):
            return TimeEntryWriteResult(
                action="update",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject is ready to update this time entry. Ask for confirmation, then call again with confirm=true.",
                time_entry_id=time_entry_id,
                project=_link_title(current.get("_links", {}).get("project")),
                payload=payload,
                validation_errors={},
                result=None,
            )
        self._ensure_write_enabled("work_package")
        response = await self._patch(f"time_entries/{time_entry_id}", json_body=payload)
        result = self.normalize_time_entry(response)
        return TimeEntryWriteResult(
            action="update",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Time entry updated successfully.",
            time_entry_id=result.id,
            project=result.project,
            payload=payload,
            validation_errors={},
            result=result,
        )

    async def delete_time_entry(
        self,
        *,
        time_entry_id: int,
        confirm: bool = False,
    ) -> TimeEntryWriteResult:
        current = await self._get(f"time_entries/{time_entry_id}")
        self._ensure_project_write_link_allowed(current.get("_links", {}).get("project"))
        detail = self.normalize_time_entry(current)
        payload = {"id": detail.id, "hours": detail.hours, "spentOn": detail.spent_on}
        if self._preview_mode(confirm, delete=True):
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
        self._ensure_write_enabled("work_package")
        await self._delete(f"time_entries/{time_entry_id}")
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

    async def get_project_work_package_context(
        self,
        *,
        project: str,
        type: str | None = None,
    ) -> ProjectWorkPackageContext:
        self._ensure_read_enabled("project")
        self._ensure_read_enabled("work_package")
        self._ensure_read_enabled("version")
        project_payload = await self._get(f"projects/{quote(project, safe='')}")
        self._ensure_project_allowed(project, payload=project_payload)
        project_id = int(project_payload["id"])
        types_payload = await self._get(f"projects/{project_id}/types")
        available_types = [
            self._normalize_option_value(item) for item in types_payload.get("_embedded", {}).get("elements", [])
        ]

        selected_type_id: int | None = None
        selected_type_name: str | None = None
        fields: list[WorkPackageFieldSchema] = []
        custom_fields: list[WorkPackageFieldSchema] = []
        available_statuses: list[OptionValue] = [
            self._normalize_option_value(item)
            for item in (await self._get("statuses")).get("_embedded", {}).get("elements", [])
        ]
        available_priorities: list[OptionValue] = [
            self._normalize_option_value(item)
            for item in (await self._get("priorities")).get("_embedded", {}).get("elements", [])
        ]
        available_categories: list[OptionValue] = [
            self._normalize_option_value(item)
            for item in (await self._get(f"projects/{project_id}/categories")).get("_embedded", {}).get("elements", [])
        ]
        available_project_phases: list[OptionValue] = []
        versions = await self.list_versions(project=str(project_id), offset=1, limit=self.settings.max_results)

        if type is not None:
            selected_type_id = int(await self._resolve_type_id(type, project=str(project_id)))
            selected_type_name = next((item.title for item in available_types if item.id == selected_type_id), type)
            form = await self._post(
                f"projects/{project_id}/work_packages/form",
                json_body={"_links": {"type": {"href": self._api_href(f"types/{selected_type_id}")}}},
            )
            schema = form.get("_embedded", {}).get("schema", {})
            fields = [
                self._normalize_field_schema(key, entry)
                for key, entry in schema.items()
                if isinstance(entry, dict) and entry.get("writable") is True
            ]
            custom_fields = [
                field
                for field in fields
                if field.key.startswith("customField") and not self._custom_field_hidden(field.name, field.key)
            ]
            fields = [
                field
                for field in fields
                if not (field.key.startswith("customField") and self._custom_field_hidden(field.name, field.key))
            ]
            status_field = next((field for field in fields if field.key == "status"), None)
            priority_field = next((field for field in fields if field.key == "priority"), None)
            category_field = next((field for field in fields if field.key == "category"), None)
            project_phase_field = next((field for field in fields if field.key == "projectPhase"), None)
            if status_field and status_field.allowed_values:
                available_statuses = status_field.allowed_values
            if priority_field and priority_field.allowed_values:
                available_priorities = priority_field.allowed_values
            if category_field:
                available_categories = category_field.allowed_values
            if project_phase_field:
                available_project_phases = project_phase_field.allowed_values

        return ProjectWorkPackageContext(
            project_id=project_id,
            project_name=_trim_text(project_payload.get("name"), limit=SUBJECT_LIMIT) or f"Project {project_id}",
            project_identifier=project_payload.get("identifier"),
            selected_type_id=selected_type_id,
            selected_type_name=selected_type_name,
            available_types=available_types,
            available_statuses=available_statuses,
            available_priorities=available_priorities,
            available_categories=available_categories,
            available_project_phases=available_project_phases,
            available_versions=versions.results,
            fields=fields,
            custom_fields=custom_fields,
        )

    async def search_work_packages(
        self,
        *,
        query: str,
        project: str | None = None,
        status: str | None = None,
        open_only: bool = False,
        assignee_me: bool = False,
        offset: int = 1,
        limit: int | None = None,
    ) -> WorkPackageListResult:
        self._ensure_read_enabled("work_package")
        effective_limit = self._resolve_limit(limit)
        filters: list[dict[str, Any]] = [{"subject_or_id": {"operator": "**", "values": [query]}}]
        project_id: int | None = None
        if project is not None:
            project_payload = await self._get_project_payload(project)
            project_id = int(project_payload["id"])
            filters.append({"project_id": {"operator": "=", "values": [str(project_id)]}})
        if status:
            status_id = await self._resolve_status_id(status)
            filters.append({"status_id": {"operator": "=", "values": [status_id]}})
        if open_only:
            filters.append({"status_id": {"operator": "o", "values": []}})
        if assignee_me:
            current_user = await self.get_current_user()
            filters.append({"assignee": {"operator": "=", "values": [str(current_user.id)]}})
        return await self._list_work_package_collection(
            project_id=project_id,
            filters=filters,
            offset=offset,
            limit=effective_limit,
        )

    async def list_work_packages(
        self,
        *,
        project: str | None = None,
        type: str | None = None,
        version: str | None = None,
        version_status: str | None = None,
        open_only: bool = False,
        assignee_me: bool = False,
        has_description: bool | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> WorkPackageListResult:
        self._ensure_read_enabled("work_package")
        effective_limit = self._resolve_limit(limit)
        filters: list[dict[str, Any]] = []
        project_id: int | None = None
        if project is not None:
            project_payload = await self._get_project_payload(project)
            project_id = int(project_payload["id"])
            filters.append({"project_id": {"operator": "=", "values": [str(project_id)]}})
        elif self.settings.allowed_projects and not _scope_allows_all(self.settings.allowed_projects):
            # No explicit project given but read scope is restricted — add a server-side
            # project filter so the API only returns WPs from the allowed projects.
            allowed_ids = [str(pid) for pid in self._project_id_to_identifier]
            if allowed_ids:
                filters.append({"project_id": {"operator": "=", "values": allowed_ids}})
        if open_only:
            filters.append({"status_id": {"operator": "o", "values": []}})
        if assignee_me:
            current_user = await self.get_current_user()
            filters.append({"assignee": {"operator": "=", "values": [str(current_user.id)]}})
        if type:
            type_id = await self._resolve_type_id(type, project=project)
            filters.append({"type": {"operator": "=", "values": [type_id]}})
        if version:
            version_id = await self._resolve_version_id(version, project=project)
            filters.append({"version": {"operator": "=", "values": [version_id]}})
        if version_status:
            # Filter by the status of a work package's assigned version. The
            # version filter supports operators o/c/l for open/closed/locked.
            status_operator = {"open": "o", "closed": "c", "locked": "l"}[version_status]
            filters.append({"version": {"operator": status_operator, "values": []}})
        if has_description is not None:
            filters.append({"description": {"operator": "*" if has_description else "!*", "values": []}})
        return await self._list_work_package_collection(
            project_id=project_id,
            filters=filters,
            offset=offset,
            limit=effective_limit,
        )

    async def _list_work_package_collection(
        self,
        *,
        project_id: int | None,
        filters: list[dict[str, Any]],
        offset: int,
        limit: int,
    ) -> WorkPackageListResult:
        payload = await self._get(
            "work_packages",
            params={
                "offset": str(offset),
                "pageSize": str(limit),
                "filters": _json_param(filters),
            },
        )
        raw_items = [
            item
            for item in payload.get("_embedded", {}).get("elements", [])
            if isinstance(item, dict) and self._work_package_payload_allowed(item)
        ]
        results = [self.normalize_work_package_summary(item) for item in raw_items]
        server_total = int(payload.get("total", len(results)))
        total = len(results)
        return WorkPackageListResult(
            offset=offset,
            limit=limit,
            total=total,
            count=total,
            next_offset=_next_offset(offset, limit, server_total),
            truncated=server_total > offset * limit,
            results=results,
        )

    async def get_work_package(self, work_package_id: int | str, *, text_limit: int | None = None) -> WorkPackageDetail:
        self._ensure_read_enabled("work_package")
        work_package_id = self._work_package_ref(work_package_id)
        payload = await self._get(f"work_packages/{work_package_id}")
        self._ensure_project_link_allowed(payload.get("_links", {}).get("project"))
        # Default (text_limit=None) returns the full description uncapped: opening
        # a single work package means you want to read/edit it, so nothing is cut.
        return self.normalize_work_package_detail(payload, text_limit=text_limit)

    async def create_work_package(
        self,
        *,
        project: str,
        type: str,
        subject: str,
        description: str | None = None,
        version: str | object | None = None,
        project_phase: str | None = None,
        assignee: str | None = None,
        responsible: str | None = None,
        priority: str | None = None,
        category: str | None = None,
        custom_fields: dict[str, Any] | None = None,
        parent_work_package_id: int | str | None = None,
        start_date: str | None = None,
        due_date: str | None = None,
        confirm: bool = False,
    ) -> WorkPackageWriteResult:
        project_payload = await self._get(f"projects/{quote(project, safe='')}")
        self._ensure_project_write_allowed(project, payload=project_payload)
        project_id = str(project_payload["id"])
        if parent_work_package_id is not None:
            # parent goes into a HAL link href, which resolves only by numeric id.
            parent_work_package_id = await self._resolve_work_package_id(parent_work_package_id)
        payload = await self._build_write_payload(
            project=project_id,
            type=type,
            subject=subject,
            description=description,
            version=version,
            project_phase=project_phase,
            assignee=assignee,
            responsible=responsible,
            priority=priority,
            category=category,
            custom_fields=custom_fields,
            parent_work_package_id=parent_work_package_id,
            start_date=start_date,
            due_date=due_date,
        )
        form = await self._post(f"projects/{project_id}/work_packages/form", json_body=payload)
        return await self._finalize_work_package_write(
            action="create",
            confirm=confirm,
            form=form,
            write_path="work_packages",
            project_name=project_payload.get("name"),
        )

    async def create_subtask(
        self,
        *,
        parent_work_package_id: int | str,
        type: str,
        subject: str,
        description: str | None = None,
        version: str | object | None = None,
        project_phase: str | None = None,
        assignee: str | None = None,
        responsible: str | None = None,
        priority: str | None = None,
        category: str | None = None,
        custom_fields: dict[str, Any] | None = None,
        start_date: str | None = None,
        due_date: str | None = None,
        confirm: bool = False,
    ) -> WorkPackageWriteResult:
        parent_ref = self._work_package_ref(parent_work_package_id)
        parent = await self._get(f"work_packages/{parent_ref}")
        # The parent link needs the numeric id (HAL hrefs don't resolve displayId);
        # read it back from the fetched parent rather than reusing the semantic ref.
        parent_numeric_id = int(parent["id"])
        project_id = _id_from_href(parent.get("_links", {}).get("project", {}).get("href"))
        if project_id is None:
            raise OpenProjectServerError("OpenProject work package is missing a project link.")
        self._ensure_project_write_link_allowed(parent.get("_links", {}).get("project"))

        payload = await self._build_write_payload(
            project=str(project_id),
            type=type,
            subject=subject,
            description=description,
            version=version,
            project_phase=project_phase,
            assignee=assignee,
            responsible=responsible,
            priority=priority,
            category=category,
            custom_fields=custom_fields,
            parent_work_package_id=parent_numeric_id,
            start_date=start_date,
            due_date=due_date,
        )
        form = await self._post(f"projects/{project_id}/work_packages/form", json_body=payload)
        return await self._finalize_work_package_write(
            action="create",
            confirm=confirm,
            form=form,
            write_path="work_packages",
            project_name=_link_title(parent.get("_links", {}).get("project")),
            preview_message="OpenProject validated the subtask. Ask for confirmation, then call again with confirm=true to create it.",
            success_message="Subtask created successfully.",
        )

    async def update_work_package(
        self,
        *,
        work_package_id: int | str,
        subject: str | None = None,
        description: str | None = None,
        type: str | None = None,
        version: str | object | None = None,
        project_phase: str | None = None,
        status: str | None = None,
        assignee: str | None = None,
        responsible: str | None = None,
        priority: str | None = None,
        category: str | None = None,
        custom_fields: dict[str, Any] | None = None,
        parent_work_package_id: int | str | object | None = None,
        start_date: str | None = None,
        due_date: str | None = None,
        confirm: bool = False,
    ) -> WorkPackageWriteResult:
        work_package_id = self._work_package_ref(work_package_id)
        if parent_work_package_id is not None and parent_work_package_id is not CLEAR_PARENT:
            # parent goes into a HAL link href, which resolves only by numeric id.
            # CLEAR_PARENT is a sentinel (un-parent) and must pass through unresolved.
            parent_work_package_id = await self._resolve_work_package_id(parent_work_package_id)
        current = await self._get(f"work_packages/{work_package_id}")
        project_id = _id_from_href(current.get("_links", {}).get("project", {}).get("href"))
        if project_id is None:
            raise OpenProjectServerError("OpenProject work package is missing a project link.")
        self._ensure_project_write_link_allowed(current.get("_links", {}).get("project"))

        lock_version = current.get("lockVersion")
        payload = await self._build_write_payload(
            project=str(project_id),
            type=type,
            subject=subject,
            description=description,
            version=version,
            project_phase=project_phase,
            status=status,
            assignee=assignee,
            responsible=responsible,
            priority=priority,
            category=category,
            custom_fields=custom_fields,
            parent_work_package_id=parent_work_package_id,
            start_date=start_date,
            due_date=due_date,
            work_package_id=work_package_id,
            lock_version=lock_version,
        )
        payload["lockVersion"] = lock_version
        form = await self._post(f"work_packages/{work_package_id}/form", json_body=payload)
        return await self._finalize_work_package_write(
            action="update",
            confirm=confirm,
            form=form,
            write_path=f"work_packages/{work_package_id}",
            write_method="PATCH",
            work_package_id=work_package_id,
            project_name=_link_title(current.get("_links", {}).get("project")),
        )

    async def bulk_create_work_packages(
        self,
        *,
        items: list[dict[str, Any]],
        confirm: bool = False,
    ) -> BulkWorkPackageWriteResult:
        item_results: list[BulkWorkPackageItemResult] = []
        for i, item in enumerate(items):
            try:
                result = await self.create_work_package(
                    project=item["project"],
                    type=item["type"],
                    subject=item["subject"],
                    description=item.get("description"),
                    version=item.get("version"),
                    project_phase=item.get("project_phase"),
                    assignee=item.get("assignee"),
                    responsible=item.get("responsible"),
                    priority=item.get("priority"),
                    category=item.get("category"),
                    custom_fields=item.get("custom_fields"),
                    parent_work_package_id=item.get("parent_work_package_id"),
                    start_date=item.get("start_date"),
                    due_date=item.get("due_date"),
                    confirm=confirm,
                )
                if not result.ready:
                    item_results.append(
                        BulkWorkPackageItemResult(index=i, success=False, error=result.message, result=result)
                    )
                else:
                    item_results.append(BulkWorkPackageItemResult(index=i, success=True, error=None, result=result))
            except Exception as exc:
                item_results.append(BulkWorkPackageItemResult(index=i, success=False, error=str(exc), result=None))

        succeeded = sum(1 for r in item_results if r.success)
        failed = len(item_results) - succeeded
        requires_confirmation = not confirm and failed == 0
        if confirm:
            message = (
                f"{succeeded} of {len(items)} work packages created successfully."
                if failed == 0
                else f"{succeeded} created, {failed} failed."
            )
        else:
            message = (
                f"Validated {succeeded} of {len(items)} work packages. Call again with confirm=true to create them."
                if failed == 0
                else f"{succeeded} validated, {failed} failed validation."
            )
        return BulkWorkPackageWriteResult(
            action="bulk_create",
            confirmed=confirm and failed == 0,
            requires_confirmation=requires_confirmation,
            total=len(items),
            succeeded=succeeded,
            failed=failed,
            message=message,
            items=item_results,
        )

    async def bulk_update_work_packages(
        self,
        *,
        items: list[dict[str, Any]],
        confirm: bool = False,
    ) -> BulkWorkPackageWriteResult:
        item_results: list[BulkWorkPackageItemResult] = []
        for i, item in enumerate(items):
            try:
                result = await self.update_work_package(
                    work_package_id=item["work_package_id"],
                    subject=item.get("subject"),
                    description=item.get("description"),
                    type=item.get("type"),
                    version=item.get("version"),
                    project_phase=item.get("project_phase"),
                    status=item.get("status"),
                    assignee=item.get("assignee"),
                    responsible=item.get("responsible"),
                    priority=item.get("priority"),
                    category=item.get("category"),
                    custom_fields=item.get("custom_fields"),
                    parent_work_package_id=item.get("parent_work_package_id"),
                    start_date=item.get("start_date"),
                    due_date=item.get("due_date"),
                    confirm=confirm,
                )
                if not result.ready:
                    item_results.append(
                        BulkWorkPackageItemResult(index=i, success=False, error=result.message, result=result)
                    )
                else:
                    item_results.append(BulkWorkPackageItemResult(index=i, success=True, error=None, result=result))
            except Exception as exc:
                item_results.append(BulkWorkPackageItemResult(index=i, success=False, error=str(exc), result=None))

        succeeded = sum(1 for r in item_results if r.success)
        failed = len(item_results) - succeeded
        requires_confirmation = not confirm and failed == 0
        if confirm:
            message = (
                f"{succeeded} of {len(items)} work packages updated successfully."
                if failed == 0
                else f"{succeeded} updated, {failed} failed."
            )
        else:
            message = (
                f"Validated {succeeded} of {len(items)} work packages. Call again with confirm=true to update them."
                if failed == 0
                else f"{succeeded} validated, {failed} failed validation."
            )
        return BulkWorkPackageWriteResult(
            action="bulk_update",
            confirmed=confirm and failed == 0,
            requires_confirmation=requires_confirmation,
            total=len(items),
            succeeded=succeeded,
            failed=failed,
            message=message,
            items=item_results,
        )

    async def add_work_package_comment(
        self,
        *,
        work_package_id: int | str,
        comment: str,
        internal: bool = False,
        notify: bool = False,
        confirm: bool = False,
    ) -> ActivityWriteResult:
        if comment is not None:
            self._ensure_field_writable("activity", "comment")
        work_package_id = self._work_package_ref(work_package_id)
        work_package = await self._get(f"work_packages/{work_package_id}")
        self._ensure_project_write_link_allowed(work_package.get("_links", {}).get("project"))
        payload = {
            "comment": {"raw": comment},
            "internal": internal,
            "notify": notify,
        }

        if self._preview_mode(confirm):
            return ActivityWriteResult(
                action="comment",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject is ready to add this comment. Ask for confirmation, then call again with confirm=true.",
                work_package_id=work_package_id,
                payload=payload,
                validation_errors={},
                result=None,
            )

        self._ensure_write_enabled("work_package")
        activity = await self._post(
            f"work_packages/{work_package_id}/activities",
            params={"notify": str(notify).lower()},
            json_body={
                "comment": {"raw": comment},
                "internal": internal,
            },
        )
        return ActivityWriteResult(
            action="comment",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Comment added successfully.",
            work_package_id=work_package_id,
            payload=payload,
            validation_errors={},
            result=self.normalize_activity(activity),
        )

    async def create_work_package_relation(
        self,
        *,
        work_package_id: int | str,
        related_to_work_package_id: int | str,
        relation_type: str,
        description: str | None = None,
        lag: int | None = None,
        confirm: bool = False,
    ) -> RelationWriteResult:
        work_package_id = self._work_package_ref(work_package_id)
        # The target goes into a HAL link href, which OpenProject resolves only by
        # numeric id (not displayId), so resolve a semantic ref to its numeric id.
        related_numeric_id = await self._resolve_work_package_id(related_to_work_package_id)
        work_package = await self._get(f"work_packages/{work_package_id}")
        self._ensure_project_write_link_allowed(work_package.get("_links", {}).get("project"))
        # Reuse the numeric id from the fetch above rather than a second GET.
        source_numeric_id = int(work_package["id"])
        payload: dict[str, Any] = {
            "type": relation_type,
            "_links": {"to": {"href": self._api_href(f"work_packages/{related_numeric_id}")}},
        }
        if description is not None:
            self._ensure_field_writable("relation", "description")
            payload["description"] = description
        if lag is not None:
            payload["lag"] = lag

        preview_payload = payload | {"to_work_package_id": related_numeric_id}
        if self._preview_mode(confirm):
            return RelationWriteResult(
                action="create",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject is ready to create this relation. Ask for confirmation, then call again with confirm=true.",
                relation_id=None,
                work_package_id=source_numeric_id,
                payload=preview_payload,
                validation_errors={},
                result=None,
            )

        self._ensure_write_enabled("work_package")
        relation = await self._post(f"work_packages/{work_package_id}/relations", json_body=payload)
        normalized = self.normalize_relation(relation)
        return RelationWriteResult(
            action="create",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Relation created successfully.",
            relation_id=normalized.id,
            work_package_id=source_numeric_id,
            payload=preview_payload,
            validation_errors={},
            result=normalized,
        )

    async def delete_work_package(
        self,
        *,
        work_package_id: int | str,
        confirm: bool = False,
    ) -> WorkPackageWriteResult:
        work_package_id = self._work_package_ref(work_package_id)
        current = await self._get(f"work_packages/{work_package_id}")
        self._ensure_project_write_link_allowed(current.get("_links", {}).get("project"))
        detail = self.normalize_work_package_detail(current)

        if self._preview_mode(confirm, delete=True):
            return WorkPackageWriteResult(
                action="delete",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject is ready to delete this work package. Ask for confirmation, then call again with confirm=true.",
                work_package_id=detail.id,
                project=detail.project,
                payload={
                    "id": detail.id,
                    "subject": detail.subject,
                    "lockVersion": detail.lock_version,
                },
                validation_errors={},
                result=detail,
            )

        self._ensure_write_enabled("work_package")
        await self._delete(f"work_packages/{work_package_id}")
        return WorkPackageWriteResult(
            action="delete",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Work package deleted successfully.",
            work_package_id=detail.id,
            project=detail.project,
            payload={
                "id": detail.id,
                "subject": detail.subject,
                "lockVersion": detail.lock_version,
            },
            validation_errors={},
            result=None,
        )

    async def delete_relation(
        self,
        *,
        relation_id: int,
        confirm: bool = False,
    ) -> RelationWriteResult:
        relation = await self._get(f"relations/{relation_id}")
        source = relation.get("_links", {}).get("from")
        if not isinstance(source, dict) or not source.get("href"):
            raise OpenProjectServerError("OpenProject relation is missing its source work package link.")
        work_package = await self._get(self._link_to_api_path(source["href"]))
        self._ensure_project_write_link_allowed(work_package.get("_links", {}).get("project"))
        normalized = self.normalize_relation(relation)

        payload = {
            "id": normalized.id,
            "type": normalized.type,
            "from_id": normalized.from_id,
            "to_id": normalized.to_id,
        }
        if self._preview_mode(confirm, delete=True):
            return RelationWriteResult(
                action="delete",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject is ready to delete this relation. Ask for confirmation, then call again with confirm=true.",
                relation_id=normalized.id,
                work_package_id=normalized.from_id,
                payload=payload,
                validation_errors={},
                result=normalized,
            )

        self._ensure_write_enabled("work_package")
        await self._delete(f"relations/{relation_id}")
        return RelationWriteResult(
            action="delete",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Relation deleted successfully.",
            relation_id=normalized.id,
            work_package_id=normalized.from_id,
            payload=payload,
            validation_errors={},
            result=None,
        )

    async def list_my_open_work_packages(
        self,
        *,
        offset: int = 1,
        limit: int | None = None,
    ) -> WorkPackageListResult:
        self._ensure_read_enabled("work_package")
        current_user = await self.get_current_user()
        effective_limit = self._resolve_limit(limit)
        payload = await self._get(
            "work_packages",
            params={
                "offset": str(offset),
                "pageSize": str(effective_limit),
                "filters": _json_param(
                    [
                        {"assignee": {"operator": "=", "values": [str(current_user.id)]}},
                        {"status_id": {"operator": "o", "values": []}},
                    ]
                ),
            },
        )
        raw_items = [
            item
            for item in payload.get("_embedded", {}).get("elements", [])
            if isinstance(item, dict) and self._work_package_payload_allowed(item)
        ]
        results = [self.normalize_work_package_summary(item) for item in raw_items]
        server_total = int(payload.get("total", len(results)))
        total = len(results)
        return WorkPackageListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=total,
            next_offset=_next_offset(offset, effective_limit, server_total),
            truncated=server_total > offset * effective_limit,
            results=results,
        )

    async def list_versions(
        self,
        *,
        project: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> VersionListResult:
        self._ensure_read_enabled("version")
        effective_limit = self._resolve_limit(limit)
        params: dict[str, str] = {"offset": str(offset), "pageSize": str(effective_limit)}
        project_already_verified = False
        if project:
            # GET /api/v3/versions has no project filter; use the project-scoped endpoint.
            # Access to the project is verified by _get_project_payload, so per-item
            # allowlist checks are redundant and would fail because the definingProject
            # link only carries the title (display name), not the identifier.
            project_payload = await self._get_project_payload(project)
            project_id = int(project_payload["id"])
            payload = await self._get(f"projects/{project_id}/versions", params=params)
            project_already_verified = True
        else:
            payload = await self._get("versions", params=params)
        raw_items = [
            item
            for item in payload.get("_embedded", {}).get("elements", [])
            if isinstance(item, dict) and (project_already_verified or self._version_payload_allowed(item))
        ]
        results = [self.normalize_version(item) for item in raw_items]
        server_total = int(payload.get("total", len(results)))
        total = len(results)
        return VersionListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=total,
            next_offset=_next_offset(offset, effective_limit, server_total),
            truncated=server_total > offset * effective_limit,
            results=results,
        )

    async def get_version(self, version_id: int) -> VersionDetail:
        self._ensure_read_enabled("version")
        payload = await self._get(f"versions/{version_id}")
        self._ensure_project_link_allowed(payload.get("_links", {}).get("definingProject"))
        return self.normalize_version_detail(payload)

    async def create_version(
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
        project_payload = await self._get(f"projects/{quote(project, safe='')}")
        self._ensure_project_write_allowed(project, payload=project_payload)
        payload = self._build_version_write_payload(
            project_id=str(project_payload["id"]),
            name=name,
            description=description,
            start_date=start_date,
            end_date=end_date,
            status=status,
            sharing=sharing,
        )
        form = await self._post("versions/form", json_body=payload)
        return await self._finalize_version_write(
            action="create",
            confirm=confirm,
            form=form,
            write_path="versions",
            project_name=project_payload.get("name"),
            preview_message="OpenProject validated the version. Ask for confirmation, then call again with confirm=true to create it.",
            success_message="Version created successfully.",
        )

    async def update_version(
        self,
        *,
        version_id: int,
        name: str | None = None,
        description: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        status: str | None = None,
        sharing: str | None = None,
        confirm: bool = False,
    ) -> VersionWriteResult:
        current = await self._get(f"versions/{version_id}")
        defining_project = current.get("_links", {}).get("definingProject")
        project_name = _link_title(defining_project)
        self._ensure_project_write_link_allowed(defining_project)
        payload = self._build_version_write_payload(
            project_id=None,
            name=name,
            description=description,
            start_date=start_date,
            end_date=end_date,
            status=status,
            sharing=sharing,
        )
        form = await self._post(f"versions/{version_id}/form", json_body=payload)
        return await self._finalize_version_write(
            action="update",
            confirm=confirm,
            form=form,
            write_path=f"versions/{version_id}",
            write_method="PATCH",
            version_id=version_id,
            project_name=project_name,
            success_message="Version updated successfully.",
        )

    async def delete_version(
        self,
        *,
        version_id: int,
        confirm: bool = False,
    ) -> VersionWriteResult:
        current = await self._get(f"versions/{version_id}")
        defining_project = current.get("_links", {}).get("definingProject")
        self._ensure_project_write_link_allowed(defining_project)
        detail = self.normalize_version_detail(current)
        payload = {"id": detail.id, "name": detail.name}

        if self._preview_mode(confirm, delete=True):
            return VersionWriteResult(
                action="delete",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject found the version. Ask for confirmation, then call again with confirm=true to delete it.",
                version_id=detail.id,
                project=detail.defining_project,
                payload=payload,
                validation_errors={},
                result=None,
            )

        self._ensure_write_enabled("version")
        await self._delete(f"versions/{version_id}")
        return VersionWriteResult(
            action="delete",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Version deleted successfully.",
            version_id=detail.id,
            project=detail.defining_project,
            payload=payload,
            validation_errors={},
            result=detail,
        )

    async def list_boards(
        self,
        *,
        project: str | None = None,
        search: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> BoardListResult:
        self._ensure_read_enabled("board")
        effective_limit = self._resolve_limit(limit)
        use_client_side_filtering = project is not None or bool(search) or bool(self.settings.allowed_projects)
        if use_client_side_filtering:
            project_candidates: set[str] = set()
            if project is not None:
                project_payload = await self._get_project_payload(project)
                project_candidates = {
                    project.casefold(),
                    str(project_payload["id"]).casefold(),
                    (_trim_text(project_payload.get("identifier"), limit=SUBJECT_LIMIT) or "").casefold(),
                    (_trim_text(project_payload.get("name"), limit=SUBJECT_LIMIT) or "").casefold(),
                }
            payload = await self._get(
                "queries",
                params={
                    "offset": "1",
                    "pageSize": str(self.settings.max_results),
                },
            )
            raw_queries = payload.get("_embedded", {}).get("elements", [])
            filtered = [self.normalize_board(item) for item in raw_queries if self._board_payload_allowed(item)]
            if project is not None:
                filtered = [item for item in filtered if self._board_matches_project(item, project_candidates)]
            if search:
                search_key = search.casefold()
                filtered = [item for item in filtered if search_key in (item.name or "").casefold()]
            total = len(filtered)
            start = (offset - 1) * effective_limit
            end = start + effective_limit
            results = filtered[start:end]
            return BoardListResult(
                offset=offset,
                limit=effective_limit,
                total=total,
                count=len(results),
                next_offset=offset + 1 if end < total else None,
                truncated=end < total,
                results=results,
            )

        payload = await self._get(
            "queries",
            params={
                "offset": str(offset),
                "pageSize": str(effective_limit),
            },
        )
        results = [self.normalize_board(item) for item in payload.get("_embedded", {}).get("elements", [])]
        total = int(payload.get("total", len(results)))
        return BoardListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(results),
            next_offset=_next_offset(offset, effective_limit, total),
            truncated=total > offset * effective_limit,
            results=results,
        )

    async def get_board(self, board_id: int) -> BoardDetail:
        self._ensure_read_enabled("board")
        payload = await self._get(f"queries/{board_id}")
        self._ensure_board_payload_allowed(payload)
        return self.normalize_board_detail(payload)

    async def create_board(
        self,
        *,
        name: str,
        project: str | None = None,
        public: bool | None = None,
        starred: bool | None = None,
        hidden: bool | None = None,
        include_subprojects: bool | None = None,
        show_hierarchies: bool | None = None,
        timeline_visible: bool | None = None,
        group_by: str | None = None,
        columns: list[str] | None = None,
        sort_by: list[str] | None = None,
        highlighted_attributes: list[str] | None = None,
        filters: list[dict[str, Any]] | None = None,
        confirm: bool = False,
    ) -> BoardWriteResult:
        if project is not None:
            await self._get_project_payload(project, write=True)
        elif self.settings.project_write_scope_configured:
            raise PermissionDeniedError(
                "Project-scoped board writes require a project when OPENPROJECT_ALLOWED_PROJECTS_WRITE is set."
            )
        payload = await self._build_board_write_payload(
            name=name,
            project=project,
            public=public,
            starred=starred,
            hidden=hidden,
            include_subprojects=include_subprojects,
            show_hierarchies=show_hierarchies,
            timeline_visible=timeline_visible,
            group_by=group_by,
            columns=columns,
            sort_by=sort_by,
            highlighted_attributes=highlighted_attributes,
            filters=filters,
        )
        form = await self._post("queries/form", json_body=payload)
        return await self._finalize_board_write(
            action="create",
            confirm=confirm,
            form=form,
            write_path="queries",
            project_name=_link_title(form.get("_embedded", {}).get("payload", {}).get("_links", {}).get("project")),
            preview_message="OpenProject validated the board. Ask for confirmation, then call again with confirm=true to create it.",
            success_message="Board created successfully.",
        )

    async def update_board(
        self,
        *,
        board_id: int,
        name: str | None = None,
        project: str | None = None,
        public: bool | None = None,
        starred: bool | None = None,
        hidden: bool | None = None,
        include_subprojects: bool | None = None,
        show_hierarchies: bool | None = None,
        timeline_visible: bool | None = None,
        group_by: str | None = None,
        columns: list[str] | None = None,
        sort_by: list[str] | None = None,
        highlighted_attributes: list[str] | None = None,
        filters: list[dict[str, Any]] | None = None,
        confirm: bool = False,
    ) -> BoardWriteResult:
        current = await self._get(f"queries/{board_id}")
        self._ensure_board_write_payload_allowed(current)
        self._ensure_board_payload_allowed(current)
        payload = await self._build_board_write_payload(
            name=name,
            project=project,
            public=public,
            starred=starred,
            hidden=hidden,
            include_subprojects=include_subprojects,
            show_hierarchies=show_hierarchies,
            timeline_visible=timeline_visible,
            group_by=group_by,
            columns=columns,
            sort_by=sort_by,
            highlighted_attributes=highlighted_attributes,
            filters=filters,
        )
        form = await self._post(f"queries/{board_id}/form", json_body=payload)
        return await self._finalize_board_write(
            action="update",
            confirm=confirm,
            form=form,
            write_path=f"queries/{board_id}",
            write_method="PATCH",
            board_id=board_id,
            project_name=_link_title(current.get("_links", {}).get("project")),
            success_message="Board updated successfully.",
        )

    async def delete_board(
        self,
        *,
        board_id: int,
        confirm: bool = False,
    ) -> BoardWriteResult:
        current = await self._get(f"queries/{board_id}")
        self._ensure_board_payload_allowed(current)
        self._ensure_board_write_payload_allowed(current)
        detail = self.normalize_board_detail(current)
        payload = {"id": detail.id, "name": detail.name}

        if self._preview_mode(confirm, delete=True):
            return BoardWriteResult(
                action="delete",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject found the board. Ask for confirmation, then call again with confirm=true to delete it.",
                board_id=detail.id,
                project=detail.project,
                payload=payload,
                validation_errors={},
                result=detail,
            )

        self._ensure_write_enabled("board")
        await self._delete(f"queries/{board_id}")
        return BoardWriteResult(
            action="delete",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Board deleted successfully.",
            board_id=detail.id,
            project=detail.project,
            payload=payload,
            validation_errors={},
            result=detail,
        )

    async def get_work_package_relations(self, work_package_id: int | str) -> RelationListResult:
        self._ensure_read_enabled("work_package")
        work_package_id = await self._resolve_work_package_id(work_package_id)
        await self.get_work_package(work_package_id)
        # The old work_packages/{id}/relations endpoint is deprecated (308 redirect).
        # Use the canonical relations endpoint with an "involved" filter instead.
        filters = json.dumps([{"involved": {"operator": "=", "values": [str(work_package_id)]}}])
        payload = await self._get("relations", params={"filters": filters})
        results = [self.normalize_relation(item) for item in payload.get("_embedded", {}).get("elements", [])]
        return RelationListResult(count=len(results), results=results)

    async def get_work_package_activities(
        self, work_package_id: int | str, *, limit: int | None = None, text_limit: int | None = None
    ) -> ActivityListResult:
        self._ensure_read_enabled("work_package")
        work_package_id = self._work_package_ref(work_package_id)
        # Existence/access check only — the result is discarded, so cap its text
        # (do NOT forward text_limit here, which could pull a large description).
        await self.get_work_package(work_package_id, text_limit=SUBJECT_LIMIT)
        effective_limit = self._resolve_limit(limit)
        payload = await self._get(f"work_packages/{work_package_id}/activities")
        elements = payload.get("_embedded", {}).get("elements", [])
        # Return most recent first, bounded. Comments come back in full by default
        # (text_limit=None): the activities of a single work package are one item's
        # content, not a multi-row list, so there is no context-flood risk — same
        # rationale as get_work_package. text_limit stays as an opt-in cap.
        elements = elements[-effective_limit:]
        results = [self.normalize_activity(item, text_limit=text_limit) for item in reversed(elements)]
        return ActivityListResult(count=len(results), results=results)

    # --- Emoji reactions (on work-package comment activities) ---

    # Valid reactions per the OpenProject API spec.
    EMOJI_REACTIONS = (
        "thumbs_up",
        "thumbs_down",
        "grinning_face_with_smiling_eyes",
        "confused_face",
        "heart",
        "party_popper",
        "rocket",
        "eyes",
    )

    def normalize_emoji_reaction(self, payload: dict[str, Any]) -> EmojiReactionSummary:
        users = [
            _trim_text(u.get("title"), limit=SUBJECT_LIMIT) or ""
            for u in payload.get("_links", {}).get("reactingUsers", [])
            if isinstance(u, dict)
        ]
        return EmojiReactionSummary(
            reaction=payload.get("reaction", ""),
            emoji=payload.get("emoji"),
            count=int(payload.get("reactionsCount", 0)),
            users=[u for u in users if u],
        )

    def _emoji_reactions_result(self, payload: dict[str, Any]) -> EmojiReactionListResult:
        elements = payload.get("_embedded", {}).get("elements", [])
        results = [self.normalize_emoji_reaction(item) for item in elements if isinstance(item, dict)]
        return EmojiReactionListResult(count=len(results), results=results)

    async def list_work_package_reactions(self, work_package_id: int | str) -> EmojiReactionListResult:
        self._ensure_read_enabled("work_package")
        work_package_id = self._work_package_ref(work_package_id)
        await self.get_work_package(work_package_id)
        payload = await self._get(f"work_packages/{work_package_id}/activities_emoji_reactions")
        return self._emoji_reactions_result(payload)

    async def toggle_activity_emoji_reaction(self, activity_id: int, reaction: str) -> EmojiReactionListResult:
        self._ensure_write_enabled("work_package")
        if reaction not in self.EMOJI_REACTIONS:
            raise InvalidInputError(f"reaction must be one of: {', '.join(self.EMOJI_REACTIONS)}.")
        # Enforce the project write allowlist against the activity's work package.
        # Fail closed: if the activity has no resolvable workPackage link, refuse
        # rather than patch an unchecked target.
        activity = await self._get(f"activities/{activity_id}")
        wp_ref = _id_from_href(activity.get("_links", {}).get("workPackage", {}).get("href"))
        if not wp_ref:
            raise OpenProjectServerError(
                "OpenProject activity is missing a work package link; cannot verify project write access."
            )
        wp_payload = await self._get(f"work_packages/{wp_ref}")
        self._ensure_project_write_link_allowed(wp_payload.get("_links", {}).get("project"))
        # PATCH toggles: adds the reaction if absent, removes it if present, and
        # returns the full reaction collection for the activity afterwards.
        payload = await self._patch(
            f"activities/{activity_id}/emoji_reactions",
            json_body={"reaction": reaction},
        )
        return self._emoji_reactions_result(payload)

    # --- Reminders (personal, on work packages) ---

    def normalize_reminder(self, payload: dict[str, Any]) -> ReminderSummary:
        links = payload.get("_links", {})
        creator = payload.get("_embedded", {}).get("creator", {})
        return self._apply_hidden_fields(
            "reminder",
            ReminderSummary(
                id=int(payload["id"]),
                remind_at=payload.get("remindAt"),
                note=_trim_text(payload.get("note"), limit=SUBJECT_LIMIT),
                work_package_id=_id_from_href(links.get("remindable", {}).get("href")),
                creator=_trim_text(creator.get("name"), limit=SUBJECT_LIMIT) if isinstance(creator, dict) else None,
                url=self._link_to_web_url(links.get("self", {}).get("href")),
            ),
        )

    async def list_reminders(self) -> ReminderListResult:
        self._ensure_read_enabled("work_package")
        payload = await self._get("reminders")
        results = [
            self.normalize_reminder(item)
            for item in payload.get("_embedded", {}).get("elements", [])
            if isinstance(item, dict)
        ]
        return ReminderListResult(count=len(results), results=results)

    async def create_work_package_reminder(
        self,
        *,
        work_package_id: int | str,
        remind_at: str,
        note: str | None = None,
        confirm: bool = False,
    ) -> ReminderWriteResult:
        wp_ref = self._work_package_ref(work_package_id)
        current = await self._get(f"work_packages/{wp_ref}")
        self._ensure_project_write_link_allowed(current.get("_links", {}).get("project"))
        payload: dict[str, Any] = {"remindAt": remind_at}
        if note is not None:
            payload["note"] = note
        if self._preview_mode(confirm):
            return ReminderWriteResult(
                action="create",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject is ready to create this reminder. Ask for confirmation, then call again with confirm=true.",
                reminder_id=None,
                payload=payload,
                validation_errors={},
                result=None,
            )
        self._ensure_write_enabled("work_package")
        # One active reminder per work package/user: a second create returns 409,
        # surfaced as InvalidInputError with the API's "update or delete" message.
        response = await self._post(f"work_packages/{wp_ref}/reminders", json_body=payload)
        result = self.normalize_reminder(response)
        return ReminderWriteResult(
            action="create",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Reminder created successfully.",
            reminder_id=result.id,
            payload=payload,
            validation_errors={},
            result=result,
        )

    async def _ensure_reminder_project_write_allowed(self, reminder_id: int) -> None:
        """Apply the project write allowlist to the reminder's work package."""
        no_read_scope = not self.settings.allowed_projects or _scope_allows_all(self.settings.allowed_projects)
        if no_read_scope and not self.settings.project_write_scope_configured:
            return
        current = await self._get(f"reminders/{reminder_id}")
        remindable = current.get("_links", {}).get("remindable")
        if not isinstance(remindable, dict) or not remindable.get("href"):
            # Fail closed: a configured allowlist must not be bypassed just
            # because the reminder's work-package link is missing/malformed.
            raise PermissionDeniedError(
                "OpenProject writes to this reminder are disabled by OPENPROJECT_ALLOWED_PROJECTS_WRITE."
            )
        work_package = await self._get(self._link_to_api_path(remindable["href"]))
        self._ensure_project_write_link_allowed(work_package.get("_links", {}).get("project"))

    async def update_reminder(
        self,
        *,
        reminder_id: int,
        remind_at: str | None = None,
        note: str | None = None,
        confirm: bool = False,
    ) -> ReminderWriteResult:
        await self._ensure_reminder_project_write_allowed(reminder_id)
        payload: dict[str, Any] = {}
        if remind_at is not None:
            payload["remindAt"] = remind_at
        if note is not None:
            payload["note"] = note
        if not payload:
            raise InvalidInputError("At least one field (remind_at or note) is required.")
        if self._preview_mode(confirm):
            return ReminderWriteResult(
                action="update",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject is ready to update this reminder. Ask for confirmation, then call again with confirm=true.",
                reminder_id=reminder_id,
                payload=payload,
                validation_errors={},
                result=None,
            )
        self._ensure_write_enabled("work_package")
        response = await self._patch(f"reminders/{reminder_id}", json_body=payload)
        result = self.normalize_reminder(response)
        return ReminderWriteResult(
            action="update",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Reminder updated successfully.",
            reminder_id=result.id,
            payload=payload,
            validation_errors={},
            result=result,
        )

    async def delete_reminder(self, *, reminder_id: int, confirm: bool = False) -> ReminderWriteResult:
        await self._ensure_reminder_project_write_allowed(reminder_id)
        if self._preview_mode(confirm, delete=True):
            return ReminderWriteResult(
                action="delete",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject is ready to delete this reminder. Ask for confirmation, then call again with confirm=true.",
                reminder_id=reminder_id,
                payload={},
                validation_errors={},
                result=None,
            )
        self._ensure_write_enabled("work_package")
        await self._delete(f"reminders/{reminder_id}")
        return ReminderWriteResult(
            action="delete",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Reminder deleted successfully.",
            reminder_id=reminder_id,
            payload={},
            validation_errors={},
            result=None,
        )

    # --- Project favorites (via the workspaces endpoint) ---

    async def _run_version_gated(self, coro: Awaitable[Any], *, feature: str, min_version: str) -> Any:
        """Run a call whose endpoint only exists from a newer OpenProject version.

        A NotFoundError from such a call means the endpoint is absent (i.e. the
        instance is too old), not that some resource is missing. Translating it
        into a clear "requires OpenProject X+" message matters for an MCP: the
        calling agent can explain the limitation instead of misreading a raw 404
        as "the project does not exist". Any prerequisite (e.g. the project) has
        already been fetched successfully before this runs, so the 404 is
        unambiguous.
        """
        try:
            return await coro
        except NotFoundError as exc:
            raise NotFoundError(
                f"{feature} requires OpenProject {min_version} or newer; this instance appears to be older."
            ) from exc

    async def _set_project_favorite(self, project: str, *, favorite: bool, confirm: bool) -> FavoriteWriteResult:
        # Use the workspaces endpoint (the project-favorite path is deprecated).
        project_payload = await self._get_project_payload(project, write=True)
        project_id = int(project_payload["id"])
        project_name = _trim_text(project_payload.get("name"), limit=SUBJECT_LIMIT)
        action = "favorite" if favorite else "unfavorite"
        if self._preview_mode(confirm):
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
        self._ensure_write_enabled("project")
        # The workspaces favorite endpoint exists only from 17.0; on older
        # instances a 404 is translated into a clear version hint.
        if favorite:
            # The favorite endpoint returns 204 with no body, so go through
            # _request (not _post, which would try to parse empty JSON).
            await self._run_version_gated(
                self._request("POST", f"workspaces/{project_id}/favorite", json_body={}),
                feature="Project favorites",
                min_version="17.0",
            )
        else:
            await self._run_version_gated(
                self._delete(f"workspaces/{project_id}/favorite"),
                feature="Project favorites",
                min_version="17.0",
            )
        return FavoriteWriteResult(
            action=action,
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message=f"Project {'added to' if favorite else 'removed from'} favorites.",
            project_id=project_id,
            project=project_name,
        )

    async def add_project_favorite(self, *, project: str, confirm: bool = False) -> FavoriteWriteResult:
        return await self._set_project_favorite(project, favorite=True, confirm=confirm)

    async def remove_project_favorite(self, *, project: str, confirm: bool = False) -> FavoriteWriteResult:
        return await self._set_project_favorite(project, favorite=False, confirm=confirm)

    async def get_current_user(self) -> CurrentUser:
        self._ensure_read_enabled("principal")
        payload = await self._get("users/me")
        return self._apply_hidden_fields(
            "current_user",
            CurrentUser(
                id=int(payload["id"]),
                name=payload.get("name"),
                login=payload.get("login"),
                url=self._web_url(f"users/{payload['id']}"),
            ),
        )

    # --- Statuses ---

    async def list_statuses(self) -> StatusListResult:
        self._ensure_read_enabled("work_package")
        payload = await self._get("statuses")
        results = [
            self.normalize_status(item)
            for item in payload.get("_embedded", {}).get("elements", [])
            if isinstance(item, dict)
        ]
        return StatusListResult(count=len(results), results=results)

    async def get_status(self, status_id: int) -> StatusSummary:
        self._ensure_read_enabled("work_package")
        payload = await self._get(f"statuses/{status_id}")
        return self.normalize_status(payload)

    # --- Priorities ---

    async def list_priorities(self) -> PriorityListResult:
        self._ensure_read_enabled("work_package")
        payload = await self._get("priorities")
        results = [
            self.normalize_priority(item)
            for item in payload.get("_embedded", {}).get("elements", [])
            if isinstance(item, dict)
        ]
        return PriorityListResult(count=len(results), results=results)

    async def get_priority(self, priority_id: int) -> PrioritySummary:
        self._ensure_read_enabled("work_package")
        payload = await self._get(f"priorities/{priority_id}")
        return self.normalize_priority(payload)

    # --- Types ---

    async def list_types(self, *, project: str | None = None) -> TypeListResult:
        self._ensure_read_enabled("work_package")
        if project is not None:
            project_id = await self._resolve_project_id(project)
            payload = await self._get(f"projects/{project_id}/types")
        else:
            payload = await self._get("types")
        results = [
            self.normalize_type(item)
            for item in payload.get("_embedded", {}).get("elements", [])
            if isinstance(item, dict)
        ]
        return TypeListResult(count=len(results), results=results)

    async def get_type(self, type_id: int) -> TypeSummary:
        self._ensure_read_enabled("work_package")
        payload = await self._get(f"types/{type_id}")
        return self.normalize_type(payload)

    # --- Work Package Watchers ---

    async def list_work_package_watchers(self, work_package_id: int | str) -> WatcherListResult:
        self._ensure_read_enabled("work_package")
        work_package_id = self._work_package_ref(work_package_id)
        payload = await self._get(f"work_packages/{work_package_id}/watchers")
        results = [
            self.normalize_watcher(item)
            for item in payload.get("_embedded", {}).get("elements", [])
            if isinstance(item, dict)
        ]
        return WatcherListResult(count=len(results), results=results)

    async def add_work_package_watcher(
        self,
        work_package_id: int | str,
        user_id: int,
        *,
        confirm: bool = False,
    ) -> WatcherWriteResult:
        work_package_id = self._work_package_ref(work_package_id)
        wp_payload = await self._get(f"work_packages/{work_package_id}")
        self._ensure_project_write_link_allowed(wp_payload.get("_links", {}).get("project"))
        if self._preview_mode(confirm):
            user_payload = await self._get(f"users/{user_id}")
            watcher = self.normalize_watcher(user_payload)
            return WatcherWriteResult(
                action="add",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject is ready to add the watcher. Ask for confirmation, then call again with confirm=true.",
                work_package_id=work_package_id,
                watcher_user_id=user_id,
                validation_errors={},
                result=watcher,
            )
        self._ensure_write_enabled("work_package")
        response = await self._post(
            f"work_packages/{work_package_id}/watchers",
            json_body={"_links": {"user": {"href": self._api_href(f"users/{user_id}")}}},
        )
        watcher = self.normalize_watcher(response)
        return WatcherWriteResult(
            action="add",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Watcher added successfully.",
            work_package_id=work_package_id,
            watcher_user_id=user_id,
            validation_errors={},
            result=watcher,
        )

    async def remove_work_package_watcher(
        self,
        work_package_id: int | str,
        user_id: int,
        *,
        confirm: bool = False,
    ) -> WatcherWriteResult:
        work_package_id = self._work_package_ref(work_package_id)
        wp_payload = await self._get(f"work_packages/{work_package_id}")
        self._ensure_project_write_link_allowed(wp_payload.get("_links", {}).get("project"))
        if self._preview_mode(confirm, delete=True):
            return WatcherWriteResult(
                action="remove",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject is ready to remove the watcher. Ask for confirmation, then call again with confirm=true.",
                work_package_id=work_package_id,
                watcher_user_id=user_id,
                validation_errors={},
                result=None,
            )
        self._ensure_write_enabled("work_package")
        await self._delete(f"work_packages/{work_package_id}/watchers/{user_id}")
        return WatcherWriteResult(
            action="remove",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Watcher removed successfully.",
            work_package_id=work_package_id,
            watcher_user_id=user_id,
            validation_errors={},
            result=None,
        )

    # --- Notifications ---

    async def list_notifications(
        self,
        *,
        unread_only: bool = False,
        limit: int | None = None,
        offset: int = 1,
    ) -> NotificationListResult:
        self._ensure_read_enabled("work_package")
        effective_limit = self._resolve_limit(limit)
        params: dict[str, str] = {
            "offset": str(offset),
            "pageSize": str(effective_limit),
        }
        if unread_only:
            params["filters"] = _json_param([{"readIAN": {"operator": "=", "values": ["f"]}}])
        payload = await self._get("notifications", params=params)
        results = [
            self.normalize_notification(item)
            for item in payload.get("_embedded", {}).get("elements", [])
            if isinstance(item, dict)
        ]
        total = int(payload.get("total", len(results)))
        return NotificationListResult(count=len(results), total=total, results=results)

    async def mark_notification_read(self, notification_id: int) -> None:
        self._ensure_write_enabled("work_package")
        response = await self._request("POST", f"notifications/{notification_id}/read_ian")
        if response.status_code not in {200, 201, 204}:
            raise OpenProjectServerError(
                f"OpenProject mark notification read failed with status {response.status_code}."
            )

    async def mark_all_notifications_read(self) -> None:
        self._ensure_write_enabled("work_package")
        response = await self._request("POST", "notifications/read_ian")
        if response.status_code not in {200, 201, 204}:
            raise OpenProjectServerError(
                f"OpenProject mark all notifications read failed with status {response.status_code}."
            )

    # --- User CRUD ---

    async def create_user(
        self,
        *,
        login: str,
        email: str,
        firstname: str,
        lastname: str,
        password: str | None = None,
        admin: bool = False,
        status: str = "active",
        language: str | None = None,
        confirm: bool = False,
    ) -> UserWriteResult:
        self._ensure_write_enabled("admin")
        payload: dict[str, Any] = {
            "login": login,
            "email": email,
            "firstName": firstname,
            "lastName": lastname,
            "admin": admin,
            "status": status,
        }
        if password is not None:
            payload["password"] = password
        if language is not None:
            payload["language"] = language
        if self._preview_mode(confirm):
            return UserWriteResult(
                action="create",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject is ready to create the user. Ask for confirmation, then call again with confirm=true.",
                user_id=None,
                payload=payload,
                validation_errors={},
                result=None,
            )
        response = await self._post("users", json_body=payload)
        result = self.normalize_user_detail(response)
        return UserWriteResult(
            action="create",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="User created successfully.",
            user_id=result.id,
            payload=payload,
            validation_errors={},
            result=result,
        )

    async def update_user(
        self,
        user_id: int,
        *,
        login: str | None = None,
        email: str | None = None,
        firstname: str | None = None,
        lastname: str | None = None,
        admin: bool | None = None,
        language: str | None = None,
        confirm: bool = False,
    ) -> UserWriteResult:
        self._ensure_write_enabled("admin")
        payload: dict[str, Any] = {}
        if login is not None:
            payload["login"] = login
        if email is not None:
            payload["email"] = email
        if firstname is not None:
            payload["firstName"] = firstname
        if lastname is not None:
            payload["lastName"] = lastname
        if admin is not None:
            payload["admin"] = admin
        if language is not None:
            payload["language"] = language
        if self._preview_mode(confirm):
            return UserWriteResult(
                action="update",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject is ready to update the user. Ask for confirmation, then call again with confirm=true.",
                user_id=user_id,
                payload=payload,
                validation_errors={},
                result=None,
            )
        response = await self._patch(f"users/{user_id}", json_body=payload)
        result = self.normalize_user_detail(response)
        return UserWriteResult(
            action="update",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="User updated successfully.",
            user_id=result.id,
            payload=payload,
            validation_errors={},
            result=result,
        )

    async def delete_user(
        self,
        user_id: int,
        *,
        confirm: bool = False,
    ) -> UserWriteResult:
        self._ensure_write_enabled("admin")
        payload = {"id": user_id}
        if self._preview_mode(confirm, delete=True):
            return UserWriteResult(
                action="delete",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject is ready to delete the user. Ask for confirmation, then call again with confirm=true.",
                user_id=user_id,
                payload=payload,
                validation_errors={},
                result=None,
            )
        await self._delete(f"users/{user_id}")
        return UserWriteResult(
            action="delete",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="User deleted successfully.",
            user_id=user_id,
            payload=payload,
            validation_errors={},
            result=None,
        )

    async def lock_user(
        self,
        user_id: int,
        *,
        confirm: bool = False,
    ) -> UserWriteResult:
        self._ensure_write_enabled("admin")
        payload = {"id": user_id}
        if self._preview_mode(confirm):
            return UserWriteResult(
                action="lock",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject is ready to lock the user. Ask for confirmation, then call again with confirm=true.",
                user_id=user_id,
                payload=payload,
                validation_errors={},
                result=None,
            )
        response = await self._post(f"users/{user_id}/lock")
        result = self.normalize_user_detail(response)
        return UserWriteResult(
            action="lock",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="User locked successfully.",
            user_id=result.id,
            payload=payload,
            validation_errors={},
            result=result,
        )

    async def unlock_user(
        self,
        user_id: int,
        *,
        confirm: bool = False,
    ) -> UserWriteResult:
        self._ensure_write_enabled("admin")
        payload = {"id": user_id}
        if self._preview_mode(confirm):
            return UserWriteResult(
                action="unlock",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject is ready to unlock the user. Ask for confirmation, then call again with confirm=true.",
                user_id=user_id,
                payload=payload,
                validation_errors={},
                result=None,
            )
        await self._delete(f"users/{user_id}/lock")
        # Re-fetch user to return updated detail
        response = await self._get(f"users/{user_id}")
        result = self.normalize_user_detail(response)
        return UserWriteResult(
            action="unlock",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="User unlocked successfully.",
            user_id=result.id,
            payload=payload,
            validation_errors={},
            result=result,
        )

    # --- Group CRUD ---

    async def create_group(
        self,
        *,
        name: str,
        user_ids: list[int] | None = None,
        confirm: bool = False,
    ) -> GroupWriteResult:
        self._ensure_write_enabled("admin")
        body: dict[str, Any] = {"name": name}
        if user_ids:
            body["_links"] = {"members": [{"href": self._api_href(f"users/{uid}")} for uid in user_ids]}
        payload_preview = {"name": name, "user_ids": user_ids or []}
        if self._preview_mode(confirm):
            return GroupWriteResult(
                action="create",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject is ready to create the group. Ask for confirmation, then call again with confirm=true.",
                group_id=None,
                payload=payload_preview,
                validation_errors={},
                result=None,
            )
        response = await self._post("groups", json_body=body)
        result = self.normalize_group(response)
        return GroupWriteResult(
            action="create",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Group created successfully.",
            group_id=result.id,
            payload=payload_preview,
            validation_errors={},
            result=result,
        )

    async def update_group(
        self,
        group_id: int,
        *,
        name: str | None = None,
        add_user_ids: list[int] | None = None,
        remove_user_ids: list[int] | None = None,
        confirm: bool = False,
    ) -> GroupWriteResult:
        self._ensure_write_enabled("admin")
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        # The groups PATCH endpoint requires a complete members list (full replacement, not delta).
        # Fetch current members and compute the new complete set from add/remove requests.
        if add_user_ids or remove_user_ids:
            current_payload = await self._get(f"groups/{group_id}")
            current_member_links = current_payload.get("_links", {}).get("members", [])
            if not isinstance(current_member_links, list):
                current_member_links = []
            current_ids: set[int] = set()
            for link in current_member_links:
                uid = _id_from_href(link.get("href"))
                if uid is not None:
                    current_ids.add(int(uid))
            new_ids = current_ids.copy()
            if add_user_ids:
                new_ids.update(add_user_ids)
            if remove_user_ids:
                new_ids -= set(remove_user_ids)
            body["_links"] = {"members": [{"href": self._api_href(f"users/{uid}")} for uid in sorted(new_ids)]}
        payload_preview: dict[str, Any] = {}
        if name is not None:
            payload_preview["name"] = name
        if add_user_ids:
            payload_preview["add_user_ids"] = add_user_ids
        if remove_user_ids:
            payload_preview["remove_user_ids"] = remove_user_ids
        if self._preview_mode(confirm):
            return GroupWriteResult(
                action="update",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject is ready to update the group. Ask for confirmation, then call again with confirm=true.",
                group_id=group_id,
                payload=payload_preview,
                validation_errors={},
                result=None,
            )
        response = await self._patch(f"groups/{group_id}", json_body=body)
        result = self.normalize_group(response)
        return GroupWriteResult(
            action="update",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Group updated successfully.",
            group_id=result.id,
            payload=payload_preview,
            validation_errors={},
            result=result,
        )

    async def delete_group(
        self,
        group_id: int,
        *,
        confirm: bool = False,
    ) -> GroupWriteResult:
        self._ensure_write_enabled("admin")
        payload = {"id": group_id}
        if self._preview_mode(confirm, delete=True):
            return GroupWriteResult(
                action="delete",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject is ready to delete the group. Ask for confirmation, then call again with confirm=true.",
                group_id=group_id,
                payload=payload,
                validation_errors={},
                result=None,
            )
        await self._delete(f"groups/{group_id}")
        return GroupWriteResult(
            action="delete",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Group deleted successfully.",
            group_id=group_id,
            payload=payload,
            validation_errors={},
            result=None,
        )

    # --- File Links ---

    async def list_work_package_file_links(self, work_package_id: int | str) -> FileLinkListResult:
        self._ensure_read_enabled("work_package")
        work_package_id = self._work_package_ref(work_package_id)
        payload = await self._get(f"work_packages/{work_package_id}/file_links")
        results = [
            self.normalize_file_link(item)
            for item in payload.get("_embedded", {}).get("elements", [])
            if isinstance(item, dict)
        ]
        return FileLinkListResult(count=len(results), results=results)

    async def delete_file_link(
        self,
        file_link_id: int,
        *,
        confirm: bool = False,
    ) -> FileLinkWriteResult:
        self._ensure_read_enabled("work_package")
        fl_payload = await self._get(f"file_links/{file_link_id}")
        file_link = self.normalize_file_link(fl_payload)
        # Derive work_package_id from the container link
        links = fl_payload.get("_links", {})
        container_href = links.get("container", {}).get("href") if isinstance(links.get("container"), dict) else None
        work_package_id = _id_from_href(container_href) or 0
        # Enforce the project write allowlist against the container work package,
        # not just the global write flag. Fail closed when the container cannot be
        # resolved: _ensure_project_write_link_allowed(None) rejects unless the
        # write scope is unconfigured / "*".
        if work_package_id:
            wp_payload = await self._get(f"work_packages/{work_package_id}")
            self._ensure_project_write_link_allowed(wp_payload.get("_links", {}).get("project"))
        else:
            self._ensure_project_write_link_allowed(None)
        if self._preview_mode(confirm, delete=True):
            return FileLinkWriteResult(
                action="delete",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject found the file link. Ask for confirmation, then call again with confirm=true to delete it.",
                file_link_id=file_link.id,
                work_package_id=work_package_id,
                validation_errors={},
                result=file_link,
            )
        self._ensure_write_enabled("work_package")
        await self._delete(f"file_links/{file_link_id}")
        return FileLinkWriteResult(
            action="delete",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="File link deleted successfully.",
            file_link_id=file_link.id,
            work_package_id=work_package_id,
            validation_errors={},
            result=None,
        )

    # --- Grids ---

    async def list_grids(self, *, scope: str | None = None) -> GridListResult:
        self._ensure_read_enabled("project")
        params: dict[str, str] = {}
        if scope is not None:
            params["filters"] = _json_param([{"scope": {"operator": "=", "values": [scope]}}])
        payload = await self._get("grids", params=params if params else None)
        results = [
            self.normalize_grid(item)
            for item in payload.get("_embedded", {}).get("elements", [])
            if isinstance(item, dict)
        ]
        return GridListResult(count=len(results), results=results)

    async def get_grid(self, grid_id: int) -> GridSummary:
        self._ensure_read_enabled("project")
        payload = await self._get(f"grids/{grid_id}")
        return self.normalize_grid(payload)

    async def create_grid(
        self,
        *,
        name: str,
        scope: str,
        row_count: int | None = None,
        column_count: int | None = None,
        confirm: bool = False,
    ) -> GridWriteResult:
        project_ref = self._project_ref_from_scope_href(scope)
        if project_ref is not None:
            await self._get_project_payload(project_ref, write=True)
        payload: dict[str, Any] = {
            "name": name,
            "_links": {"scope": {"href": scope}},
        }
        if row_count is not None:
            payload["rowCount"] = row_count
        if column_count is not None:
            payload["columnCount"] = column_count
        form = await self._post("grids/form", json_body=payload)
        return await self._finalize_grid_write(
            action="create",
            confirm=confirm,
            form=form,
            write_path="grids",
            preview_message="OpenProject validated the grid. Ask for confirmation, then call again with confirm=true to create it.",
            success_message="Grid created successfully.",
        )

    async def update_grid(
        self,
        *,
        grid_id: int,
        name: str | None = None,
        row_count: int | None = None,
        column_count: int | None = None,
        confirm: bool = False,
    ) -> GridWriteResult:
        current = await self._get(f"grids/{grid_id}")
        project_ref = self._project_ref_from_scope_href(current.get("_links", {}).get("scope", {}).get("href"))
        if project_ref is not None:
            await self._get_project_payload(project_ref, write=True)
        payload: dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if row_count is not None:
            payload["rowCount"] = row_count
        if column_count is not None:
            payload["columnCount"] = column_count
        form = await self._post(f"grids/{grid_id}/form", json_body=payload)
        return await self._finalize_grid_write(
            action="update",
            confirm=confirm,
            form=form,
            write_path=f"grids/{grid_id}",
            write_method="PATCH",
            grid_id=grid_id,
            preview_message="OpenProject validated the grid update. Ask for confirmation, then call again with confirm=true to write it.",
            success_message="Grid updated successfully.",
        )

    async def delete_grid(
        self,
        *,
        grid_id: int,
        confirm: bool = False,
    ) -> GridWriteResult:
        current = await self._get(f"grids/{grid_id}")
        project_ref = self._project_ref_from_scope_href(current.get("_links", {}).get("scope", {}).get("href"))
        if project_ref is not None:
            await self._get_project_payload(project_ref, write=True)
        detail = self.normalize_grid(current)
        scope = current.get("_links", {}).get("scope", {}).get("href")

        if self._preview_mode(confirm, delete=True):
            return GridWriteResult(
                action="delete",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject found the grid. Ask for confirmation, then call again with confirm=true to delete it.",
                grid_id=detail.id,
                scope=scope,
                payload={"id": detail.id},
                validation_errors={},
                result=None,
            )
        self._ensure_write_enabled("project")
        await self._delete(f"grids/{grid_id}")
        return GridWriteResult(
            action="delete",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Grid deleted successfully.",
            grid_id=detail.id,
            scope=scope,
            payload={"id": detail.id},
            validation_errors={},
            result=None,
        )

    # --- User Preferences ---

    async def get_my_preferences(self) -> UserPreferences:
        payload = await self._get("my_preferences")
        return self.normalize_user_preferences(payload)

    async def update_my_preferences(
        self,
        *,
        lang: str | None = None,
        time_zone: str | None = None,
        comment_sort_descending: bool | None = None,
        warn_on_leaving_unsaved: bool | None = None,
        auto_hide_popups: bool | None = None,
        confirm: bool = False,
    ) -> UserPreferencesWriteResult:
        # Self-scoped: only the authenticated token owner's own preferences
        # (language, timezone, popup behaviour). No project/admin scope applies;
        # the confirm/preview flow is the guard here.
        body: dict[str, Any] = {}
        if lang is not None:
            body["lang"] = lang
        if time_zone is not None:
            body["timeZone"] = time_zone
        if comment_sort_descending is not None:
            body["commentSortDescending"] = comment_sort_descending
        if warn_on_leaving_unsaved is not None:
            body["warnOnLeavingUnsaved"] = warn_on_leaving_unsaved
        if auto_hide_popups is not None:
            body["autoHidePopups"] = auto_hide_popups
        if self._preview_mode(confirm):
            return UserPreferencesWriteResult(
                action="update",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message="OpenProject is ready to update your preferences. Call again with confirm=true to write.",
                payload=body,
                result=None,
            )
        response = await self._patch("my_preferences", json_body=body)
        return UserPreferencesWriteResult(
            action="update",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Preferences updated successfully.",
            payload=body,
            result=self.normalize_user_preferences(response),
        )

    # --- Text Rendering ---

    async def render_text(self, *, text: str, format: str = "markdown") -> RenderedText:
        """Render plain or markdown text to HTML via the OpenProject API."""
        self._ensure_read_enabled("work_package")
        endpoint = "render/markdown" if format == "markdown" else "render/plain"
        url = f"{self.settings.base_url}/api/v3/{endpoint}"
        try:
            response = await self._http.post(
                url,
                content=text.encode("utf-8"),
                headers={"Content-Type": "text/plain"},
            )
        except httpx.TimeoutException as exc:
            raise TransportError("OpenProject request timed out.") from exc
        except httpx.HTTPError as exc:
            raise TransportError("Could not reach OpenProject.") from exc
        self._raise_for_status(response)
        data = response.json()
        return RenderedText(
            format=format,
            raw=text,
            html=data.get("html", ""),
        )

    # --- Help Texts ---

    async def list_help_texts(self) -> HelpTextListResult:
        payload = await self._get("help_texts")
        results = [
            self.normalize_help_text(item)
            for item in payload.get("_embedded", {}).get("elements", [])
            if isinstance(item, dict)
        ]
        return HelpTextListResult(count=len(results), results=results)

    async def get_help_text(self, help_text_id: int) -> HelpTextSummary:
        payload = await self._get(f"help_texts/{help_text_id}")
        return self.normalize_help_text(payload)

    # --- Work Schedule / Days ---

    async def list_working_days(self) -> WorkingDayListResult:
        """List the Mon–Sun working-day configuration (7 entries)."""
        payload = await self._get("days/week")
        results = [
            self.normalize_working_day(item)
            for item in payload.get("_embedded", {}).get("elements", [])
            if isinstance(item, dict)
        ]
        return WorkingDayListResult(count=len(results), results=results)

    async def list_non_working_days(self, *, year: int | None = None) -> NonWorkingDayListResult:
        """List non-working days (public holidays / closures) for the given year."""
        params: dict[str, str] = {}
        if year is not None:
            params["filters"] = json.dumps(
                [{"date": {"operator": "<>d", "values": [f"{year}-01-01", f"{year}-12-31"]}}]
            )
        payload = await self._get("days/non_working", params=params or None)
        results = [
            self.normalize_non_working_day(item)
            for item in payload.get("_embedded", {}).get("elements", [])
            if isinstance(item, dict)
        ]
        return NonWorkingDayListResult(count=len(results), results=results)

    # --- Custom Options ---

    async def get_custom_option(self, custom_option_id: int) -> CustomOptionSummary:
        """Fetch a single custom field option value by id."""
        payload = await self._get(f"custom_options/{custom_option_id}")
        return CustomOptionSummary(
            id=int(payload["id"]),
            value=payload.get("value"),
        )

    # --- Relations (update + global list) ---

    async def list_relations(
        self,
        *,
        relation_type: str | None = None,
    ) -> RelationListResult:
        """List all relations, optionally filtered by type.

        Gated by the work_package read scope and filtered by the project read
        allowlist: only relations whose source work package is in an allowed
        project are returned, so this cannot leak work packages from projects the
        caller may not read.
        """
        self._ensure_read_enabled("work_package")
        params: dict[str, str] = {}
        if relation_type is not None:
            params["filters"] = json.dumps([{"type": {"operator": "=", "values": [relation_type]}}])
        payload = await self._get("relations", params=params or None)
        results = []
        allowlisted = self.settings.allowed_projects and not _scope_allows_all(self.settings.allowed_projects)
        results = []
        # Cache project-allow decisions per work package so a batch of relations
        # between the same work packages doesn't refetch (mitigates N+1).
        wp_allowed: dict[str, bool] = {}
        for item in payload.get("_embedded", {}).get("elements", []):
            if not isinstance(item, dict):
                continue
            if allowlisted and not await self._relation_endpoints_allowed(item, wp_allowed):
                continue
            results.append(self.normalize_relation(item))
        return RelationListResult(count=len(results), results=results)

    async def _relation_endpoints_allowed(self, relation: dict[str, Any], cache: dict[str, bool]) -> bool:
        """True only if BOTH linked work packages are in an allowed project.

        Both ``from`` and ``to`` must pass — otherwise a relation to a work
        package in a project the caller may not read would still leak that work
        package's id and subject through ``to_id``/``to_subject``.
        """
        links = relation.get("_links", {})
        for side in ("from", "to"):
            link = links.get(side)
            if not isinstance(link, dict) or not link.get("href"):
                return False
            href = link["href"]
            if href not in cache:
                cache[href] = await self._work_package_project_allowed(href)
            if not cache[href]:
                return False
        return True

    async def _work_package_project_allowed(self, href: str) -> bool:
        try:
            work_package = await self._get(self._link_to_api_path(href))
        except NotFoundError:
            return False
        # Do NOT swallow server/transport errors as "not allowed" — a transient
        # 5xx must not silently drop a relation the caller is entitled to see.
        try:
            self._ensure_project_link_allowed(work_package.get("_links", {}).get("project"))
            return True
        except PermissionDeniedError:
            return False

    async def update_relation(
        self,
        *,
        relation_id: int,
        relation_type: str | None = None,
        description: str | None = None,
        confirm: bool = False,
    ) -> RelationUpdateResult:
        """Update the type or description of an existing relation."""
        current = await self._get(f"relations/{relation_id}")
        source = current.get("_links", {}).get("from")
        if not isinstance(source, dict) or not source.get("href"):
            raise OpenProjectServerError("OpenProject relation is missing its source work package link.")
        work_package = await self._get(self._link_to_api_path(source["href"]))
        self._ensure_project_write_link_allowed(work_package.get("_links", {}).get("project"))
        existing = self.normalize_relation(current)
        body: dict[str, Any] = {}
        if relation_type is not None:
            body["type"] = relation_type
        if description is not None:
            body["description"] = description
        if self._preview_mode(confirm):
            return RelationUpdateResult(
                action="update",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message=f"Ready to update relation {relation_id}. Call again with confirm=true.",
                relation_id=relation_id,
                payload=body,
                result=existing,
            )
        self._ensure_write_enabled("work_package")
        response = await self._patch(f"relations/{relation_id}", json_body=body)
        detail = self.normalize_relation(response)
        return RelationUpdateResult(
            action="update",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="Relation updated successfully.",
            relation_id=relation_id,
            payload=body,
            result=detail,
        )

    async def _get(self, path: str, *, params: dict[str, str] | None = None) -> dict[str, Any]:
        return await self._request_json("GET", path, params=params)

    async def _post(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self._request_json("POST", path, params=params, json_body=json_body)

    async def _patch(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self._request_json("PATCH", path, params=params, json_body=json_body)

    async def _post_multipart(
        self,
        path: str,
        *,
        metadata: dict[str, Any],
        file_name: str,
        file_bytes: bytes,
        content_type: str,
    ) -> dict[str, Any]:
        response = await self._request(
            "POST",
            path,
            files={
                # The metadata part must be a plain form field, NOT a file part: it
                # carries no filename in its Content-Disposition. If a filename is set,
                # Rails' multipart parser treats it as an uploaded file (a Hash with a
                # tempfile) instead of a JSON string, and OpenProject 500s with
                # "no implicit conversion of HashWithIndifferentAccess into String".
                "metadata": (None, json.dumps(metadata), "application/json"),
                "file": (file_name, file_bytes, content_type),
            },
        )
        try:
            return response.json()
        except ValueError as exc:
            raise OpenProjectServerError("OpenProject returned invalid JSON.") from exc

    async def _delete(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
    ) -> None:
        response = await self._request("DELETE", path, params=params)
        if response.status_code not in {200, 202, 204}:
            raise OpenProjectServerError(f"OpenProject delete request failed with status {response.status_code}.")

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = await self._request(method, path, params=params, json_body=json_body)
        try:
            return response.json()
        except ValueError as exc:
            raise OpenProjectServerError("OpenProject returned invalid JSON.") from exc

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        files: dict[str, tuple[str, str | bytes, str]] | None = None,
    ) -> httpx.Response:
        try:
            response = await self._http.request(method, path, params=params, json=json_body, files=files)
        except httpx.TimeoutException as exc:
            raise TransportError("OpenProject request timed out.") from exc
        except httpx.HTTPError as exc:
            raise TransportError("Could not reach OpenProject.") from exc

        self._raise_for_status(response)
        return response

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return

        payload: dict[str, Any] = {}
        try:
            payload = response.json()
        except ValueError:
            payload = {}

        message = str(payload.get("message") or "").strip()
        status_code = response.status_code
        if status_code == 401:
            raise AuthenticationError("OpenProject authentication failed.")
        if status_code == 403:
            lowered = message.lower()
            if "token" in lowered or "authenticate" in lowered:
                raise AuthenticationError("OpenProject authentication failed.")
            raise PermissionDeniedError("OpenProject denied access to this resource.")
        if status_code == 404:
            raise NotFoundError("OpenProject resource not found.")
        if status_code in {400, 409, 422}:
            safe_message = message or "OpenProject rejected the request."
            raise InvalidInputError(safe_message)
        if 500 <= status_code < 600:
            LOGGER.warning("OpenProject server error: status=%s", status_code)
            raise OpenProjectServerError("OpenProject returned a server error.")
        raise OpenProjectServerError(f"OpenProject request failed with status {status_code}.")

    def _preview_mode(self, confirm: bool, *, delete: bool = False) -> bool:
        """Return True if the call should return a preview instead of writing.

        When auto_confirm_write (or auto_confirm_delete for deletes) is enabled
        in settings, the preview step is skipped and the tool writes immediately.
        """
        if delete:
            return not confirm and not self.settings.auto_confirm_delete
        return not confirm and not self.settings.auto_confirm_write

    def _resolve_limit(self, requested_limit: int | None) -> int:
        limit = requested_limit or self.settings.default_page_size
        return min(limit, self.settings.max_page_size, self.settings.max_results)

    def _link_to_api_path(self, href: str) -> str:
        parsed = urlparse(href)
        if not parsed.scheme:
            path = parsed.path or href
        else:
            if _origin_from_url(href) != self._origin:
                raise OpenProjectServerError("OpenProject returned an unexpected link host.")
            path = parsed.path
        if path.startswith(self._api_prefix):
            relative_path = path[len(self._api_prefix) :]
        else:
            relative_path = path.lstrip("/")
        if parsed.query:
            return f"{relative_path}?{parsed.query}"
        return relative_path

    def _web_url(self, relative_path: str) -> str:
        return urljoin(f"{self.settings.base_url.rstrip('/')}/", relative_path.lstrip("/"))

    def normalize_project(self, payload: dict[str, Any]) -> ProjectSummary:
        links = payload.get("_links", {})
        identifier = payload.get("identifier")
        project_path = f"projects/{identifier or payload['id']}"
        return self._apply_hidden_fields(
            "project",
            ProjectSummary(
                id=int(payload["id"]),
                name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or f"Project {payload['id']}",
                identifier=identifier,
                active=payload.get("active"),
                description=self._visible_formattable_text(payload.get("description"), "project", "description"),
                url=self._web_url(project_path),
                public=payload.get("public"),
                status=_link_title(links.get("status")),
                status_explanation=self._visible_formattable_text(
                    payload.get("statusExplanation"), "project", "status_explanation"
                ),
                parent_id=_id_from_href(links.get("parent", {}).get("href")),
                parent_name=_link_title(links.get("parent")),
                created_at=payload.get("createdAt"),
                updated_at=payload.get("updatedAt"),
                can_update="update" in links or "updateImmediately" in links,
                can_delete="delete" in links,
            ),
        )

    def normalize_role(self, payload: dict[str, Any]) -> RoleSummary:
        return self._apply_hidden_fields(
            "role",
            RoleSummary(
                id=int(payload["id"]),
                name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or f"Role {payload['id']}",
                url=self._web_url(f"roles/{payload['id']}"),
            ),
        )

    def normalize_principal(self, payload: dict[str, Any]) -> PrincipalSummary:
        principal_type = _trim_text(payload.get("_type"), limit=SUBJECT_LIMIT)
        principal_id = int(payload["id"])
        path_prefix = "groups" if principal_type == "Group" else "users"
        return self._apply_hidden_fields(
            "principal",
            PrincipalSummary(
                id=principal_id,
                type=principal_type,
                name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or f"Principal {principal_id}",
                login=_trim_text(payload.get("login"), limit=SUBJECT_LIMIT),
                email=_trim_text(payload.get("email"), limit=SUBJECT_LIMIT),
                status=_trim_text(payload.get("status"), limit=SUBJECT_LIMIT),
                url=self._web_url(f"{path_prefix}/{principal_id}"),
            ),
        )

    def normalize_user(self, payload: dict[str, Any]) -> UserSummary:
        links = payload.get("_links", {})
        avatar_link = links.get("avatar")
        return self._apply_hidden_fields(
            "user",
            UserSummary(
                id=int(payload["id"]),
                name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT),
                login=_trim_text(payload.get("login"), limit=SUBJECT_LIMIT),
                email=_trim_text(payload.get("email"), limit=SUBJECT_LIMIT),
                status=_trim_text(payload.get("status"), limit=SUBJECT_LIMIT),
                admin=payload.get("admin"),
                locked=payload.get("locked"),
                avatar_url=self._link_to_web_url(avatar_link.get("href")) if isinstance(avatar_link, dict) else None,
                created_at=payload.get("createdAt"),
                updated_at=payload.get("updatedAt"),
                url=self._web_url(f"users/{payload['id']}"),
            ),
        )

    def normalize_user_detail(self, payload: dict[str, Any]) -> UserDetail:
        summary = self.normalize_user(payload)
        links = payload.get("_links", {})
        groups = [_link_title(item) for item in links.get("groups", []) if isinstance(item, dict) and _link_title(item)]
        auth_source = _link_title(links.get("authSource"))
        identity_url = self._link_to_web_url(links.get("showUser", {}).get("href"))
        return self._apply_hidden_fields(
            "user",
            UserDetail(
                id=summary.id,
                name=summary.name,
                login=summary.login,
                email=summary.email,
                status=summary.status,
                admin=summary.admin,
                locked=summary.locked,
                avatar_url=summary.avatar_url,
                created_at=summary.created_at,
                updated_at=summary.updated_at,
                language=_trim_text(payload.get("language"), limit=SUBJECT_LIMIT),
                identity_url=identity_url,
                auth_source=auth_source,
                groups=groups,
                url=summary.url,
            ),
        )

    def normalize_group(self, payload: dict[str, Any]) -> GroupSummary:
        links = payload.get("_links", {})
        members = payload.get("_embedded", {}).get("members", {})
        member_count = 0
        if isinstance(members, dict):
            member_count = int(members.get("count") or members.get("total") or 0)
        elif isinstance(payload.get("memberships"), list):
            member_count = len(payload.get("memberships", []))
        return self._apply_hidden_fields(
            "group",
            GroupSummary(
                id=int(payload["id"]),
                name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT),
                member_count=member_count,
                created_at=payload.get("createdAt"),
                updated_at=payload.get("updatedAt"),
                can_update=bool(links.get("update") or links.get("updateImmediately")),
                can_delete=bool(links.get("delete")),
                url=self._web_url(f"groups/{payload['id']}"),
            ),
        )

    def normalize_group_detail(self, payload: dict[str, Any]) -> GroupDetail:
        summary = self.normalize_group(payload)
        # OpenProject embeds group members as a flat array (associated_resources
        # :users, as: :members). A collection object with "elements" is not the
        # real shape, but tolerate it defensively rather than crash on .get().
        members = payload.get("_embedded", {}).get("members", [])
        if isinstance(members, dict):
            members = members.get("elements", [])
        member_names = []
        if isinstance(members, list):
            for item in members:
                if isinstance(item, dict):
                    label = _trim_text(item.get("name"), limit=SUBJECT_LIMIT) or _link_title(
                        item.get("_links", {}).get("self")
                    )
                    if label:
                        member_names.append(label)
        memberships_url = self._link_to_web_url(payload.get("_links", {}).get("memberships", {}).get("href"))
        return self._apply_hidden_fields(
            "group",
            GroupDetail(
                id=summary.id,
                name=summary.name,
                member_count=summary.member_count,
                members=member_names,
                memberships_url=memberships_url,
                created_at=summary.created_at,
                updated_at=summary.updated_at,
                can_update=summary.can_update,
                can_delete=summary.can_delete,
                url=summary.url,
            ),
        )

    def normalize_action(self, payload: dict[str, Any]) -> ActionSummary:
        links = payload.get("_links", {})
        modules = [
            _trim_text(item, limit=SUBJECT_LIMIT)
            for item in payload.get("modules", [])
            if _trim_text(item, limit=SUBJECT_LIMIT)
        ]
        href = links.get("self", {}).get("href") if isinstance(links.get("self"), dict) else None
        action_id = _slug_from_href(href) or _trim_text(payload.get("id"), limit=SUBJECT_LIMIT) or ""
        return self._apply_hidden_fields(
            "action",
            ActionSummary(
                id=action_id,
                name=_trim_text(payload.get("name") or links.get("self", {}).get("title"), limit=SUBJECT_LIMIT),
                description=_trim_text(payload.get("description"), limit=FORMATTABLE_LIMIT),
                modules=[item for item in modules if item],
                url=self._link_to_web_url(href),
            ),
        )

    def normalize_capability(self, payload: dict[str, Any]) -> CapabilitySummary:
        links = payload.get("_links", {})
        self_link = links.get("self", {})
        action_link = links.get("action")
        principal_link = links.get("principal")
        context_link = links.get("context")
        href = self_link.get("href") if isinstance(self_link, dict) else None
        capability_id = _slug_from_href(href) or _trim_text(payload.get("id"), limit=SUBJECT_LIMIT) or ""
        return self._apply_hidden_fields(
            "capability",
            CapabilitySummary(
                id=capability_id,
                name=_trim_text(payload.get("name") or self_link.get("title"), limit=SUBJECT_LIMIT),
                action_id=_slug_from_href(action_link.get("href")) if isinstance(action_link, dict) else None,
                action_name=_link_title(action_link),
                principal_id=_id_from_href(principal_link.get("href")) if isinstance(principal_link, dict) else None,
                principal_name=_link_title(principal_link),
                context=_link_title(context_link) if isinstance(context_link, dict) else None,
                url=self._link_to_web_url(href),
            ),
        )

    def normalize_membership(self, payload: dict[str, Any]) -> MembershipSummary:
        links = payload.get("_links", {})
        roles = links.get("roles", [])
        return self._apply_hidden_fields(
            "membership",
            MembershipSummary(
                id=int(payload["id"]),
                principal_id=_id_from_href(links.get("principal", {}).get("href")),
                principal_name=_link_title(links.get("principal")),
                project_id=_id_from_href(links.get("project", {}).get("href")),
                project_name=_link_title(links.get("project")),
                role_ids=[
                    role_id
                    for role in roles
                    if isinstance(role, dict)
                    if (role_id := _id_from_href(role.get("href"))) is not None
                ],
                role_names=[
                    title
                    for role in roles
                    if isinstance(role, dict)
                    if (title := _trim_text(role.get("title"), limit=SUBJECT_LIMIT)) is not None
                ],
                can_update="update" in links,
                can_update_immediately="updateImmediately" in links,
                url=self._web_url(f"memberships/{payload['id']}"),
            ),
        )

    def normalize_work_package_summary(self, payload: dict[str, Any]) -> WorkPackageSummary:
        links = payload.get("_links", {})
        # Summaries stay single-line, capped at settings.text_limit (OPENPROJECT_TEXT_LIMIT,
        # default 500) — a one-paragraph preview for list context. Not SUBJECT_LIMIT, which
        # is the subject field limit, and not the full text, which would flood the context
        # across many rows.
        description, truncated, length = self._visible_formattable_text_with_meta(
            payload.get("description"), "work_package", "description", limit=self.settings.text_limit
        )
        return self._apply_hidden_fields(
            "work_package",
            WorkPackageSummary(
                id=int(payload["id"]),
                display_id=payload.get("displayId"),
                subject=_trim_text(payload.get("subject"), limit=SUBJECT_LIMIT) or f"Work package {payload['id']}",
                type=_link_title(links.get("type")),
                status=_link_title(links.get("status")),
                priority=_link_title(links.get("priority")),
                project_phase=_link_title(links.get("projectPhase")),
                assignee=_link_title(links.get("assignee")),
                responsible=_link_title(links.get("responsible")),
                project=_link_title(links.get("project")),
                version=_link_title(links.get("version")),
                start_date=payload.get("startDate"),
                due_date=payload.get("dueDate"),
                percentage_complete=_percentage_done(payload),
                description=description,
                has_description=description is not None,
                url=self._web_url(f"work_packages/{payload['id']}"),
                description_truncated=truncated,
                description_length=length,
            ),
        )

    def normalize_work_package_detail(
        self, payload: dict[str, Any], *, text_limit: int | None = FORMATTABLE_LIMIT
    ) -> WorkPackageDetail:
        links = payload.get("_links", {})
        # ``text_limit=None`` returns the full description uncapped (single-WP
        # path); the FORMATTABLE_LIMIT default keeps the delete-preview and
        # create/update-response callers capped as before. Newlines preserved so
        # paragraph/list structure survives.
        description, truncated, length = self._visible_formattable_text_with_meta(
            payload.get("description"),
            "work_package",
            "description",
            limit=text_limit,
            preserve_newlines=True,
        )
        return self._apply_hidden_fields(
            "work_package",
            WorkPackageDetail(
                id=int(payload["id"]),
                display_id=payload.get("displayId"),
                subject=_trim_text(payload.get("subject"), limit=SUBJECT_LIMIT) or f"Work package {payload['id']}",
                type=_link_title(links.get("type")),
                status=_link_title(links.get("status")),
                priority=_link_title(links.get("priority")),
                project_phase=_link_title(links.get("projectPhase")),
                assignee=_link_title(links.get("assignee")),
                responsible=_link_title(links.get("responsible")),
                project=_link_title(links.get("project")),
                version=_link_title(links.get("version")),
                parent_id=_id_from_href(links.get("parent", {}).get("href")),
                # Hierarchy links carry displayId from 17.5 (semantic mode); absent on
                # older/classic instances, where this stays None.
                parent_display_id=links.get("parent", {}).get("displayId"),
                start_date=payload.get("startDate"),
                due_date=payload.get("dueDate"),
                percentage_complete=_percentage_done(payload),
                lock_version=payload.get("lockVersion"),
                description=description,
                url=self._web_url(f"work_packages/{payload['id']}"),
                activities_url=self._link_to_web_url(links.get("activities", {}).get("href")),
                relations_url=self._link_to_web_url(links.get("relations", {}).get("href")),
                description_truncated=truncated,
                description_length=length,
            ),
        )

    def normalize_relation(self, payload: dict[str, Any]) -> RelationSummary:
        links = payload.get("_links", {})
        # from_subject/to_subject are the linked work packages' titles, so honor
        # the work_package subject hide list too — not just the relation entity's.
        wp_subject_hidden = self._field_hidden("work_package", "subject")
        from_subject = None if wp_subject_hidden else _link_title(links.get("from"))
        to_subject = None if wp_subject_hidden else _link_title(links.get("to"))
        return self._apply_hidden_fields(
            "relation",
            RelationSummary(
                id=int(payload["id"]),
                type=payload.get("type"),
                description=_trim_text(payload.get("description"), limit=SUBJECT_LIMIT),
                from_id=_id_from_href(links.get("from", {}).get("href")),
                from_subject=from_subject,
                to_id=_id_from_href(links.get("to", {}).get("href")),
                to_subject=to_subject,
            ),
        )

    def normalize_activity(self, payload: dict[str, Any], *, text_limit: int | None = None) -> ActivitySummary:
        links = payload.get("_links", {})
        comment, truncated, length = self._visible_formattable_text_with_meta(
            payload.get("comment"),
            "activity",
            "comment",
            limit=text_limit,
            preserve_newlines=True,
        )
        return self._apply_hidden_fields(
            "activity",
            ActivitySummary(
                id=int(payload["id"]),
                type=payload.get("_type"),
                version=payload.get("version"),
                user=_link_title(links.get("user")),
                comment=comment,
                created_at=payload.get("createdAt"),
                comment_truncated=truncated,
                comment_length=length,
            ),
        )

    def normalize_version(self, payload: dict[str, Any]) -> VersionSummary:
        links = payload.get("_links", {})
        return self._apply_hidden_fields(
            "version",
            VersionSummary(
                id=int(payload["id"]),
                name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or f"Version {payload['id']}",
                status=payload.get("status"),
                sharing=payload.get("sharing"),
                start_date=payload.get("startDate"),
                end_date=payload.get("endDate"),
                defining_project=_link_title(links.get("definingProject")),
                description=_extract_formattable_text(payload.get("description")),
                url=self._web_url(f"versions/{payload['id']}"),
            ),
        )

    def normalize_version_detail(self, payload: dict[str, Any]) -> VersionDetail:
        summary = self.normalize_version(payload)
        return self._apply_hidden_fields(
            "version",
            VersionDetail(
                id=summary.id,
                name=summary.name,
                status=summary.status,
                sharing=summary.sharing,
                start_date=summary.start_date,
                end_date=summary.end_date,
                defining_project=summary.defining_project,
                description=summary.description,
                url=summary.url,
            ),
        )

    def normalize_board(self, payload: dict[str, Any]) -> BoardSummary:
        links = payload.get("_links", {})
        project_link = links.get("project")
        filters = payload.get("filters", [])
        if not isinstance(filters, list):
            filters = []
        return self._apply_hidden_fields(
            "board",
            BoardSummary(
                id=int(payload["id"]),
                name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or f"Board {payload['id']}",
                project_id=_id_from_href(project_link.get("href")) if isinstance(project_link, dict) else None,
                project=_link_title(project_link),
                public=bool(payload.get("public")),
                hidden=bool(payload.get("hidden")),
                starred=bool(payload.get("starred")),
                include_subprojects=bool(payload.get("includeSubprojects")),
                show_hierarchies=bool(payload.get("showHierarchies")),
                timeline_visible=bool(payload.get("timelineVisible")),
                filter_count=len(filters),
                can_update=bool(links.get("update") or links.get("updateImmediately")),
                can_delete=bool(links.get("delete")),
                url=self._board_web_url(payload),
            ),
        )

    def normalize_board_detail(self, payload: dict[str, Any]) -> BoardDetail:
        summary = self.normalize_board(payload)
        links = payload.get("_links", {})
        return self._apply_hidden_fields(
            "board",
            BoardDetail(
                id=summary.id,
                name=summary.name,
                project_id=summary.project_id,
                project=summary.project,
                public=summary.public,
                hidden=summary.hidden,
                starred=summary.starred,
                include_subprojects=summary.include_subprojects,
                show_hierarchies=summary.show_hierarchies,
                timeline_visible=summary.timeline_visible,
                timeline_zoom_level=_trim_text(payload.get("timelineZoomLevel"), limit=SUBJECT_LIMIT),
                highlighting_mode=_trim_text(payload.get("highlightingMode"), limit=SUBJECT_LIMIT),
                group_by=self._normalize_query_link_label(links.get("groupBy")),
                columns=self._normalize_query_link_list(links.get("columns")),
                sort_by=self._normalize_query_link_list(links.get("sortBy")),
                highlighted_attributes=self._normalize_query_link_list(links.get("highlightedAttributes")),
                timestamps=[str(item) for item in payload.get("timestamps", []) if str(item).strip()],
                filters=[
                    self._normalize_board_filter(item) for item in payload.get("filters", []) if isinstance(item, dict)
                ],
                created_at=payload.get("createdAt"),
                updated_at=payload.get("updatedAt"),
                can_update=summary.can_update,
                can_delete=summary.can_delete,
                url=summary.url,
            ),
        )

    def normalize_view(self, payload: dict[str, Any]) -> ViewSummary:
        links = payload.get("_links", {})
        project_link = links.get("project")
        query_link = links.get("query")
        return self._apply_hidden_fields(
            "view",
            ViewSummary(
                id=int(payload["id"]),
                type=_trim_text(payload.get("_type"), limit=SUBJECT_LIMIT),
                name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or f"View {payload['id']}",
                project_id=_id_from_href(project_link.get("href")) if isinstance(project_link, dict) else None,
                project=_link_title(project_link),
                query_id=_id_from_href(query_link.get("href")) if isinstance(query_link, dict) else None,
                query=_link_title(query_link),
                public=bool(payload.get("public")),
                starred=bool(payload.get("starred")),
                created_at=payload.get("createdAt"),
                updated_at=payload.get("updatedAt"),
                url=self._web_url(f"api/v3/views/{payload['id']}"),
            ),
        )

    def normalize_view_detail(self, payload: dict[str, Any]) -> ViewDetail:
        summary = self.normalize_view(payload)
        return self._apply_hidden_fields(
            "view",
            ViewDetail(
                id=summary.id,
                type=summary.type,
                name=summary.name,
                project_id=summary.project_id,
                project=summary.project,
                query_id=summary.query_id,
                query=summary.query,
                public=summary.public,
                starred=summary.starred,
                created_at=summary.created_at,
                updated_at=summary.updated_at,
                links=sorted(payload.get("_links", {}).keys()),
                url=summary.url,
            ),
        )

    def normalize_query_filter(self, payload: dict[str, Any]) -> QueryFilterSummary:
        links = payload.get("_links", {})
        self_link = links.get("self", {})
        href = self_link.get("href") if isinstance(self_link, dict) else None
        filter_id = _slug_from_href(href) or _trim_text(payload.get("id"), limit=SUBJECT_LIMIT) or ""
        return self._apply_hidden_fields(
            "query_filter",
            QueryFilterSummary(
                id=filter_id,
                name=_trim_text(payload.get("name") or self_link.get("title"), limit=SUBJECT_LIMIT),
                url=self._link_to_web_url(href),
            ),
        )

    def normalize_query_column(self, payload: dict[str, Any]) -> QueryColumnSummary:
        links = payload.get("_links", {})
        self_link = links.get("self", {})
        href = self_link.get("href") if isinstance(self_link, dict) else None
        column_id = _slug_from_href(href) or _trim_text(payload.get("id"), limit=SUBJECT_LIMIT) or ""
        return self._apply_hidden_fields(
            "query_column",
            QueryColumnSummary(
                id=column_id,
                name=_trim_text(payload.get("name") or self_link.get("title"), limit=SUBJECT_LIMIT),
                type=_trim_text(payload.get("_type"), limit=SUBJECT_LIMIT),
                relation_type=_trim_text(payload.get("relationType"), limit=SUBJECT_LIMIT),
                url=self._link_to_web_url(href),
            ),
        )

    def normalize_query_operator(self, payload: dict[str, Any]) -> QueryOperatorSummary:
        links = payload.get("_links", {})
        self_link = links.get("self", {})
        href = self_link.get("href") if isinstance(self_link, dict) else None
        operator_id = _slug_from_href(href) or _trim_text(payload.get("id"), limit=SUBJECT_LIMIT) or ""
        return self._apply_hidden_fields(
            "query_operator",
            QueryOperatorSummary(
                id=operator_id,
                name=_trim_text(payload.get("name") or self_link.get("title"), limit=SUBJECT_LIMIT),
                url=self._link_to_web_url(href),
            ),
        )

    def normalize_query_sort_by(self, payload: dict[str, Any]) -> QuerySortBySummary:
        links = payload.get("_links", {})
        self_link = links.get("self", {})
        href = self_link.get("href") if isinstance(self_link, dict) else None
        sort_by_id = _slug_from_href(href) or _trim_text(payload.get("id"), limit=SUBJECT_LIMIT) or ""
        column_link = links.get("column")
        direction_link = links.get("direction")
        direction = _trim_text(payload.get("direction"), limit=SUBJECT_LIMIT)
        if direction is None and isinstance(direction_link, dict):
            direction = _trim_text(direction_link.get("title"), limit=SUBJECT_LIMIT)
        return self._apply_hidden_fields(
            "query_sort_by",
            QuerySortBySummary(
                id=sort_by_id,
                name=_trim_text(payload.get("name") or self_link.get("title"), limit=SUBJECT_LIMIT),
                column=_link_title(column_link) if isinstance(column_link, dict) else None,
                direction=direction,
                url=self._link_to_web_url(href),
            ),
        )

    def normalize_query_filter_instance_schema(self, payload: dict[str, Any]) -> QueryFilterInstanceSchemaSummary:
        links = payload.get("_links", {})
        self_link = links.get("self", {})
        href = self_link.get("href") if isinstance(self_link, dict) else None
        schema_id = _slug_from_href(href) or _trim_text(payload.get("id"), limit=SUBJECT_LIMIT) or ""
        dependencies = payload.get("_dependencies", [])
        operator_count = 0
        if isinstance(dependencies, list):
            for dependency in dependencies:
                if isinstance(dependency, dict):
                    values = dependency.get("dependencies")
                    if isinstance(values, dict):
                        operator_count += len(values)
        return self._apply_hidden_fields(
            "query_filter_instance_schema",
            QueryFilterInstanceSchemaSummary(
                id=schema_id,
                name=_trim_text(
                    payload.get("name", {}).get("name")
                    if isinstance(payload.get("name"), dict)
                    else payload.get("name"),
                    limit=SUBJECT_LIMIT,
                ),
                filter=_link_title(links.get("filter")),
                operator_count=operator_count,
                url=self._link_to_web_url(href),
            ),
        )

    def normalize_document(self, payload: dict[str, Any]) -> DocumentSummary:
        links = payload.get("_links", {})
        attachments = payload.get("_embedded", {}).get("attachments", {})
        attachment_count = 0
        if isinstance(attachments, dict):
            attachment_count = int(attachments.get("count") or attachments.get("total") or 0)
        return self._apply_hidden_fields(
            "document",
            DocumentSummary(
                id=int(payload["id"]),
                title=_trim_text(payload.get("title"), limit=SUBJECT_LIMIT) or f"Document {payload['id']}",
                project_id=_id_from_href(links.get("project", {}).get("href")),
                project=_link_title(links.get("project")),
                description=self._visible_formattable_text(
                    payload.get("description"), "project", "description", limit=SUBJECT_LIMIT
                ),
                created_at=payload.get("createdAt"),
                attachment_count=attachment_count,
                can_update=bool(links.get("update") or links.get("updateImmediately")),
                url=self._web_url(f"documents/{payload['id']}"),
            ),
        )

    def normalize_document_detail(self, payload: dict[str, Any]) -> DocumentDetail:
        summary = self.normalize_document(payload)
        links = payload.get("_links", {})
        return self._apply_hidden_fields(
            "document",
            DocumentDetail(
                id=summary.id,
                title=summary.title,
                project_id=summary.project_id,
                project=summary.project,
                description=self._visible_formattable_text(payload.get("description"), "project", "description"),
                created_at=summary.created_at,
                attachment_count=summary.attachment_count,
                attachments_url=self._link_to_web_url(links.get("attachments", {}).get("href")),
                can_update=summary.can_update,
                url=summary.url,
            ),
        )

    def normalize_news(self, payload: dict[str, Any]) -> NewsSummary:
        links = payload.get("_links", {})
        return self._apply_hidden_fields(
            "news",
            NewsSummary(
                id=int(payload["id"]),
                title=_trim_text(payload.get("title"), limit=SUBJECT_LIMIT) or f"News {payload['id']}",
                summary=_trim_text(payload.get("summary"), limit=SUBJECT_LIMIT),
                description=self._visible_formattable_text(
                    payload.get("description"), "project", "description", limit=SUBJECT_LIMIT
                ),
                project_id=_id_from_href(links.get("project", {}).get("href")),
                project=_link_title(links.get("project")),
                author=_link_title(links.get("author")),
                created_at=payload.get("createdAt"),
                can_update=bool(links.get("update") or links.get("updateImmediately")),
                can_delete=bool(links.get("delete")),
                url=self._web_url(f"news/{payload['id']}"),
            ),
        )

    def normalize_news_detail(self, payload: dict[str, Any]) -> NewsDetail:
        summary = self.normalize_news(payload)
        return self._apply_hidden_fields(
            "news",
            NewsDetail(
                id=summary.id,
                title=summary.title,
                summary=summary.summary,
                description=self._visible_formattable_text(payload.get("description"), "project", "description"),
                project_id=summary.project_id,
                project=summary.project,
                author=summary.author,
                created_at=summary.created_at,
                can_update=summary.can_update,
                can_delete=summary.can_delete,
                url=summary.url,
            ),
        )

    def normalize_wiki_page(self, payload: dict[str, Any]) -> WikiPageDetail:
        links = payload.get("_links", {})
        text_block = payload.get("text") or payload.get("content")
        content: str | None = None
        if isinstance(text_block, dict):
            content = _trim_text(text_block.get("raw"), limit=50_000)
        return self._apply_hidden_fields(
            "wiki_page",
            WikiPageDetail(
                id=int(payload["id"]),
                title=_trim_text(payload.get("title"), limit=SUBJECT_LIMIT) or f"Wiki page {payload['id']}",
                project_id=_id_from_href(links.get("project", {}).get("href")),
                project=_link_title(links.get("project")),
                content=content,
                attachments_url=self._link_to_web_url(links.get("attachments", {}).get("href")),
                url=self._web_url(f"wiki_pages/{payload['id']}"),
            ),
        )

    def normalize_job_status(self, payload: dict[str, Any]) -> JobStatusDetail:
        links = payload.get("_links", {})
        project_link = links.get("project") or links.get("sourceProject")
        resource_link = links.get("createdProject") or links.get("createdResource") or links.get("result")
        return self._apply_hidden_fields(
            "job_status",
            JobStatusDetail(
                id=int(payload["id"])
                if payload.get("id") is not None
                else _id_from_href(links.get("self", {}).get("href")),
                type=_trim_text(payload.get("_type"), limit=SUBJECT_LIMIT),
                status=_trim_text(
                    payload.get("status") or payload.get("jobStatus") or payload.get("state"), limit=SUBJECT_LIMIT
                ),
                message=_trim_text(payload.get("message") or payload.get("error"), limit=FORMATTABLE_LIMIT),
                created_at=payload.get("createdAt"),
                updated_at=payload.get("updatedAt"),
                percentage_complete=payload.get("percentageDone") or payload.get("progress"),
                project_id=_id_from_href(project_link.get("href")) if isinstance(project_link, dict) else None,
                project=_link_title(project_link),
                created_resource_type=_trim_text(resource_link.get("type"), limit=SUBJECT_LIMIT)
                if isinstance(resource_link, dict)
                else None,
                created_resource_id=_id_from_href(resource_link.get("href"))
                if isinstance(resource_link, dict)
                else None,
                created_resource_name=_link_title(resource_link),
                links=sorted(links.keys()),
                url=self._link_to_web_url(links.get("self", {}).get("href")),
            ),
        )

    def normalize_category(
        self,
        payload: dict[str, Any],
        *,
        project_id: int | None,
        project_name: str | None,
    ) -> CategorySummary:
        category_id = int(payload["id"])
        return self._apply_hidden_fields(
            "category",
            CategorySummary(
                id=category_id,
                name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or f"Category {category_id}",
                project_id=project_id,
                project=project_name,
                is_default=bool(payload.get("isDefault")),
                url=self._web_url(f"api/v3/categories/{category_id}"),
            ),
        )

    def normalize_attachment(self, payload: dict[str, Any]) -> AttachmentSummary:
        links = payload.get("_links", {})
        container_link = links.get("container")
        container_href = container_link.get("href") if isinstance(container_link, dict) else None
        container_type = None
        if isinstance(container_href, str):
            if "work_packages/" in container_href:
                container_type = "WorkPackage"
            else:
                container_type = _slug_from_href(container_href)
        download_href = None
        if isinstance(links.get("downloadLocation"), dict):
            download_href = links["downloadLocation"].get("href")
        if not download_href and isinstance(links.get("staticDownloadLocation"), dict):
            download_href = links["staticDownloadLocation"].get("href")
        return self._apply_hidden_fields(
            "attachment",
            AttachmentSummary(
                id=int(payload["id"]),
                title=_trim_text(payload.get("title") or payload.get("fileName"), limit=SUBJECT_LIMIT)
                or f"Attachment {payload['id']}",
                file_name=_trim_text(payload.get("fileName"), limit=SUBJECT_LIMIT),
                file_size=payload.get("fileSize"),
                description=_extract_formattable_text(payload.get("description")),
                content_type=_trim_text(payload.get("contentType"), limit=SUBJECT_LIMIT),
                status=_trim_text(payload.get("status"), limit=SUBJECT_LIMIT),
                author=_link_title(links.get("author")),
                container_type=container_type,
                container_id=_id_from_href(container_href),
                created_at=payload.get("createdAt"),
                download_url=self._link_to_web_url(download_href),
                url=self._web_url(f"api/v3/attachments/{payload['id']}"),
            ),
        )

    def _normalize_board_filter(self, payload: dict[str, Any]) -> BoardFilter:
        links = payload.get("_links", {})
        return BoardFilter(
            key=_slug_from_href(links.get("filter", {}).get("href")),
            name=_link_title(links.get("filter")),
            operator=_link_title(links.get("operator")) or _slug_from_href(links.get("operator", {}).get("href")),
            values=self._normalize_filter_values(links.get("values")),
        )

    def _normalize_filter_values(self, values: Any) -> list[str]:
        if not isinstance(values, list):
            return []
        normalized: list[str] = []
        for item in values:
            if isinstance(item, dict):
                text = (
                    _link_title(item.get("_links", {}).get("self"))
                    or _trim_text(item.get("name"), limit=SUBJECT_LIMIT)
                    or _trim_text(item.get("title"), limit=SUBJECT_LIMIT)
                    or _trim_text(item.get("href"), limit=SUBJECT_LIMIT)
                )
            else:
                text = _trim_text(item, limit=SUBJECT_LIMIT)
            if text:
                normalized.append(text)
        return normalized

    def _normalize_query_link_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        normalized: list[str] = []
        for item in value:
            label = self._normalize_query_link_label(item)
            if label:
                normalized.append(label)
        return normalized

    def _normalize_query_link_label(self, value: Any) -> str | None:
        if isinstance(value, dict):
            return _link_title(value) or _slug_from_href(value.get("href"))
        return _trim_text(value, limit=SUBJECT_LIMIT)

    def _board_web_url(self, payload: dict[str, Any]) -> str:
        board_id = int(payload["id"])
        return urljoin(f"{self.settings.base_url.rstrip('/')}/", f"work_packages?query_id={board_id}")

    def normalize_instance_configuration(self, payload: dict[str, Any]) -> InstanceConfiguration:
        return self._apply_hidden_fields(
            "instance_configuration",
            InstanceConfiguration(
                host_name=_trim_text(payload.get("hostName"), limit=SUBJECT_LIMIT),
                maximum_attachment_file_size=payload.get("maximumAttachmentFileSize"),
                maximum_api_v3_page_size=payload.get("maximumAPIV3PageSize"),
                per_page_options=[int(item) for item in payload.get("perPageOptions", []) if isinstance(item, int)],
                duration_format=_trim_text(payload.get("durationFormat"), limit=SUBJECT_LIMIT),
                hours_per_day=payload.get("hoursPerDay"),
                days_per_month=payload.get("daysPerMonth"),
                active_feature_flags=sorted(
                    str(item) for item in payload.get("activeFeatureFlags", []) if str(item).strip()
                ),
                available_features=sorted(
                    str(item) for item in payload.get("availableFeatures", []) if str(item).strip()
                ),
                trialling_features=sorted(
                    str(item) for item in payload.get("triallingFeatures", []) if str(item).strip()
                ),
            ),
        )

    def normalize_project_configuration(
        self,
        payload: dict[str, Any],
        *,
        project: ProjectSummary,
    ) -> ProjectConfiguration:
        base = self.normalize_instance_configuration(payload)
        return self._apply_hidden_fields(
            "project_configuration",
            ProjectConfiguration(
                project_id=project.id,
                project_name=project.name,
                maximum_attachment_file_size=base.maximum_attachment_file_size,
                maximum_api_v3_page_size=base.maximum_api_v3_page_size,
                per_page_options=base.per_page_options,
                duration_format=base.duration_format,
                hours_per_day=base.hours_per_day,
                days_per_month=base.days_per_month,
                active_feature_flags=base.active_feature_flags,
                available_features=base.available_features,
                trialling_features=base.trialling_features,
                enabled_internal_comments=payload.get("enabledInternalComments"),
                url=self._web_url(f"api/v3/projects/{project.id}/configuration"),
            ),
        )

    def normalize_project_phase_definition(self, payload: dict[str, Any]) -> ProjectPhaseDefinition:
        phase_id = int(payload["id"])
        return self._apply_hidden_fields(
            "project_phase_definition",
            ProjectPhaseDefinition(
                id=phase_id,
                name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or f"Phase {phase_id}",
                start_gate=_trim_text(payload.get("startGateName"), limit=SUBJECT_LIMIT),
                finish_gate=_trim_text(payload.get("finishGateName"), limit=SUBJECT_LIMIT),
                created_at=payload.get("createdAt"),
                updated_at=payload.get("updatedAt"),
                url=self._web_url(f"api/v3/project_phase_definitions/{phase_id}"),
            ),
        )

    def normalize_project_phase(self, payload: dict[str, Any]) -> ProjectPhase:
        phase_id = int(payload["id"])
        links = payload.get("_links", {})
        phase_definition_link = links.get("projectPhaseDefinition")
        return self._apply_hidden_fields(
            "project_phase",
            ProjectPhase(
                id=phase_id,
                name=(
                    _trim_text(payload.get("name"), limit=SUBJECT_LIMIT)
                    or _link_title(phase_definition_link)
                    or f"Project phase {phase_id}"
                ),
                project_id=_id_from_href(links.get("project", {}).get("href")),
                project=_link_title(links.get("project")),
                phase_definition_id=_id_from_href(phase_definition_link.get("href"))
                if isinstance(phase_definition_link, dict)
                else None,
                phase_definition=_link_title(phase_definition_link),
                start_date=payload.get("startDate"),
                finish_date=payload.get("finishDate"),
                created_at=payload.get("createdAt"),
                updated_at=payload.get("updatedAt"),
                url=self._web_url(f"api/v3/project_phases/{phase_id}"),
            ),
        )

    def normalize_time_entry_activity(self, payload: dict[str, Any]) -> TimeEntryActivitySummary:
        activity_id = int(payload["id"])
        projects = [
            _link_title(item) for item in payload.get("_links", {}).get("projects", []) if isinstance(item, dict)
        ]
        return self._apply_hidden_fields(
            "time_entry_activity",
            TimeEntryActivitySummary(
                id=activity_id,
                name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or f"Activity {activity_id}",
                position=payload.get("position"),
                is_default=bool(payload.get("default")),
                projects=[item for item in projects if item],
                url=self._web_url(f"time_entries/activities/{activity_id}"),
            ),
        )

    def normalize_time_entry(self, payload: dict[str, Any]) -> TimeEntrySummary:
        links = payload.get("_links", {})
        project_link = links.get("project")
        entity_link = links.get("entity")
        return self._apply_hidden_fields(
            "time_entry",
            TimeEntrySummary(
                id=int(payload["id"]),
                project=_link_title(project_link),
                entity_type=_trim_text(payload.get("entityType"), limit=SUBJECT_LIMIT),
                entity_id=_id_from_href(entity_link.get("href")) if isinstance(entity_link, dict) else None,
                entity_name=_link_title(entity_link),
                user=_link_title(links.get("user")),
                activity=_link_title(links.get("activity")),
                hours=_trim_text(payload.get("hours"), limit=SUBJECT_LIMIT),
                spent_on=_trim_text(payload.get("spentOn"), limit=SUBJECT_LIMIT),
                # Only present when the admin enabled allow_tracking_start_and_end_times;
                # otherwise absent, so these stay None.
                start_time=_trim_text(payload.get("startTime"), limit=SUBJECT_LIMIT),
                end_time=_trim_text(payload.get("endTime"), limit=SUBJECT_LIMIT),
                ongoing=bool(payload.get("ongoing")),
                comment=self._visible_formattable_text(payload.get("comment"), "activity", "comment"),
                created_at=payload.get("createdAt"),
                updated_at=payload.get("updatedAt"),
                url=self._web_url(f"time_entries/{payload['id']}"),
            ),
        )

    def normalize_status(self, payload: dict[str, Any]) -> StatusSummary:
        status_id = int(payload["id"])
        return StatusSummary(
            id=status_id,
            name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or f"Status {status_id}",
            is_default=bool(payload.get("isDefault")),
            is_closed=bool(payload.get("isClosed")),
            color=_trim_text(payload.get("color"), limit=SUBJECT_LIMIT),
            position=payload.get("position"),
            url=self._api_href(f"statuses/{status_id}"),
        )

    def normalize_priority(self, payload: dict[str, Any]) -> PrioritySummary:
        priority_id = int(payload["id"])
        return PrioritySummary(
            id=priority_id,
            name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or f"Priority {priority_id}",
            is_default=bool(payload.get("isDefault")),
            is_active=bool(payload.get("isActive")),
            color=_trim_text(payload.get("color"), limit=SUBJECT_LIMIT),
            position=payload.get("position"),
        )

    def normalize_type(self, payload: dict[str, Any]) -> TypeSummary:
        type_id = int(payload["id"])
        return TypeSummary(
            id=type_id,
            name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or f"Type {type_id}",
            color=_trim_text(payload.get("color"), limit=SUBJECT_LIMIT),
            position=payload.get("position"),
            is_default=bool(payload.get("isDefault")),
            is_milestone=bool(payload.get("isMilestone")),
            url=self._web_url(f"types/{type_id}"),
        )

    def normalize_watcher(self, payload: dict[str, Any]) -> WatcherSummary:
        watcher_id = int(payload["id"])
        return WatcherSummary(
            id=watcher_id,
            name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or f"User {watcher_id}",
            login=_trim_text(payload.get("login"), limit=SUBJECT_LIMIT),
            url=self._web_url(f"users/{watcher_id}"),
        )

    def normalize_notification(self, payload: dict[str, Any]) -> NotificationSummary:
        notification_id = int(payload["id"])
        links = payload.get("_links", {})
        project_link = links.get("project")
        resource_link = links.get("resource")
        resource_href = resource_link.get("href") if isinstance(resource_link, dict) else None
        work_package_id: int | None = None
        work_package_subject: str | None = None
        if isinstance(resource_href, str) and "work_packages/" in resource_href:
            work_package_id = _id_from_href(resource_href)
            work_package_subject = _link_title(resource_link)
        read_ian = payload.get("readIAN")
        if read_ian is None:
            read_ian = bool(payload.get("read"))
        reason_link = links.get("reason")
        reason = _link_title(reason_link) or _trim_text(payload.get("reason"), limit=SUBJECT_LIMIT)
        return NotificationSummary(
            id=notification_id,
            subject=_trim_text(payload.get("subject"), limit=SUBJECT_LIMIT) or f"Notification {notification_id}",
            reason=reason,
            read=bool(read_ian),
            project_id=_id_from_href(project_link.get("href")) if isinstance(project_link, dict) else None,
            project_name=_link_title(project_link),
            work_package_id=work_package_id,
            work_package_subject=work_package_subject,
            created_at=payload.get("createdAt") or "",
            url=self._api_href(f"notifications/{notification_id}"),
        )

    def normalize_file_link(self, payload: dict[str, Any]) -> FileLinkSummary:
        file_link_id = int(payload["id"])
        links = payload.get("_links", {})
        storage_link = links.get("storage")
        storage_id = _id_from_href(storage_link.get("href")) if isinstance(storage_link, dict) else None
        storage_name = _link_title(storage_link)
        return FileLinkSummary(
            id=file_link_id,
            title=_trim_text(payload.get("title") or payload.get("originData", {}).get("name"), limit=SUBJECT_LIMIT)
            or f"File link {file_link_id}",
            storage_id=storage_id,
            storage_name=storage_name,
            created_at=payload.get("createdAt"),
            updated_at=payload.get("updatedAt"),
            url=self._api_href(f"file_links/{file_link_id}"),
        )

    def normalize_grid(self, payload: dict[str, Any]) -> GridSummary:
        grid_id = int(payload["id"])
        links = payload.get("_links", {})
        scope_href = links.get("scope", {}).get("href") if isinstance(links.get("scope"), dict) else None
        scope = _trim_text(scope_href, limit=SUBJECT_LIMIT)
        return GridSummary(
            id=grid_id,
            row_count=payload.get("rowCount"),
            column_count=payload.get("columnCount"),
            scope=scope,
            created_at=payload.get("createdAt"),
            updated_at=payload.get("updatedAt"),
            url=self._api_href(f"grids/{grid_id}"),
        )

    def normalize_user_preferences(self, payload: dict[str, Any]) -> UserPreferences:
        return UserPreferences(
            id=payload.get("id"),
            lang=payload.get("lang"),
            time_zone=payload.get("timeZone"),
            comment_sort_descending=payload.get("commentSortDescending"),
            warn_on_leaving_unsaved=payload.get("warnOnLeavingUnsaved"),
            auto_hide_popups=payload.get("autoHidePopups"),
            notifications_reminder_time=payload.get("notificationsReminderTime"),
            updated_at=payload.get("updatedAt"),
        )

    def normalize_help_text(self, payload: dict[str, Any]) -> HelpTextSummary:
        return HelpTextSummary(
            id=int(payload["id"]),
            attribute_name=payload.get("attribute") or payload.get("attributeName"),
            attribute_caption=payload.get("attributeCaption"),
            help_text=_trim_text(
                (payload.get("helpText") or {}).get("raw")
                if isinstance(payload.get("helpText"), dict)
                else payload.get("helpText"),
                limit=FORMATTABLE_LIMIT,
            ),
        )

    def normalize_working_day(self, payload: dict[str, Any]) -> WorkingDay:
        return WorkingDay(
            name=payload.get("name", ""),
            day_of_week=int(payload.get("dayOfWeek", 0)),
            working=bool(payload.get("working", True)),
        )

    def normalize_non_working_day(self, payload: dict[str, Any]) -> NonWorkingDay:
        return NonWorkingDay(
            date=payload.get("date", ""),
            name=payload.get("name"),
        )

    def _normalize_option_value(self, payload: dict[str, Any]) -> OptionValue:
        href = payload.get("_links", {}).get("self", {}).get("href")
        title = (
            _trim_text(payload.get("name"), limit=SUBJECT_LIMIT)
            or _trim_text(payload.get("title"), limit=SUBJECT_LIMIT)
            or _trim_text(payload.get("_links", {}).get("self", {}).get("title"), limit=SUBJECT_LIMIT)
            or "Unnamed"
        )
        raw_id = payload.get("id")
        option_id = int(raw_id) if isinstance(raw_id, int | str) and str(raw_id).isdigit() else _id_from_href(href)
        return OptionValue(id=option_id, title=title, href=href)

    def _normalize_field_schema(self, key: str, payload: dict[str, Any]) -> WorkPackageFieldSchema:
        allowed_values = payload.get("_embedded", {}).get("allowedValues", [])
        normalized_allowed_values = [
            self._normalize_option_value(item) for item in allowed_values if isinstance(item, dict)
        ]
        return WorkPackageFieldSchema(
            key=key,
            name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or key,
            type=_trim_text(payload.get("type"), limit=SUBJECT_LIMIT),
            required=bool(payload.get("required")),
            writable=bool(payload.get("writable")),
            has_default=bool(payload.get("hasDefault")),
            # Templated-subject hint (17.3+); present only when a type configures
            # a subject template, otherwise absent.
            placeholder=_trim_text(payload.get("placeholder"), limit=SUBJECT_LIMIT),
            location=_trim_text(payload.get("location"), limit=SUBJECT_LIMIT),
            allowed_values=normalized_allowed_values,
        )

    def _normalize_project_field_schema(self, key: str, payload: dict[str, Any]) -> ProjectFieldSchema:
        normalized_allowed_values: list[OptionValue] = []
        embedded_allowed = payload.get("_embedded", {}).get("allowedValues", [])
        if isinstance(embedded_allowed, list):
            normalized_allowed_values.extend(
                self._normalize_option_value(item) for item in embedded_allowed if isinstance(item, dict)
            )
        link_allowed = payload.get("_links", {}).get("allowedValues", [])
        if isinstance(link_allowed, list):
            normalized_allowed_values.extend(
                OptionValue(
                    id=_id_from_href(item.get("href")),
                    title=_trim_text(item.get("title"), limit=SUBJECT_LIMIT) or "Unnamed",
                    href=item.get("href"),
                )
                for item in link_allowed
                if isinstance(item, dict)
            )
        elif isinstance(embedded_allowed, list) and embedded_allowed and isinstance(embedded_allowed[0], str):
            normalized_allowed_values.extend(
                OptionValue(id=None, title=_trim_text(item, limit=SUBJECT_LIMIT) or "Unnamed", href=None)
                for item in embedded_allowed
                if isinstance(item, str)
            )
        return ProjectFieldSchema(
            key=key,
            name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or key,
            type=_trim_text(payload.get("type"), limit=SUBJECT_LIMIT),
            required=bool(payload.get("required")),
            writable=bool(payload.get("writable")),
            has_default=bool(payload.get("hasDefault")),
            location=_trim_text(payload.get("location"), limit=SUBJECT_LIMIT),
            allowed_values=normalized_allowed_values,
        )

    def _link_to_web_url(self, href: str | None) -> str | None:
        if not href:
            return None
        parsed = urlparse(href)
        if parsed.scheme:
            if _origin_from_url(href) != self._origin:
                return None
            return href
        if href.startswith("/"):
            return urljoin(f"{self._origin.rstrip('/')}/", href.lstrip("/"))
        return urljoin(f"{self.settings.base_url.rstrip('/')}/", href)

    async def _build_write_payload(
        self,
        *,
        project: str,
        type: str | None = None,
        subject: str | None = None,
        description: str | None = None,
        version: str | object | None = None,
        project_phase: str | None = None,
        status: str | None = None,
        assignee: str | None = None,
        responsible: str | None = None,
        priority: str | None = None,
        category: str | None = None,
        custom_fields: dict[str, Any] | None = None,
        parent_work_package_id: int | object | None = None,
        start_date: str | None = None,
        due_date: str | None = None,
        work_package_id: int | None = None,
        lock_version: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        links: dict[str, dict[str, str | None]] = {}

        if custom_fields:
            for raw_key in custom_fields:
                self._ensure_custom_field_input_writable(raw_key)

        if subject is not None:
            self._ensure_field_writable("work_package", "subject")
            payload["subject"] = subject
        if description is not None:
            self._ensure_field_writable("work_package", "description")
            payload["description"] = {"format": "markdown", "raw": description}
        if start_date is not None:
            self._ensure_field_writable("work_package", "start_date")
            payload["startDate"] = start_date
        if due_date is not None:
            self._ensure_field_writable("work_package", "due_date")
            payload["dueDate"] = due_date
        if type is not None:
            self._ensure_field_writable("work_package", "type")
            type_id = await self._resolve_type_id(type, project=project)
            links["type"] = {"href": self._api_href(f"types/{type_id}")}
        if version is CLEAR_VERSION:
            self._ensure_field_writable("work_package", "version")
            links["version"] = {"href": None}
        elif version is not None:
            self._ensure_field_writable("work_package", "version")
            version_id = await self._resolve_version_id(version, project=project)
            links["version"] = {"href": self._api_href(f"versions/{version_id}")}
        if status is not None:
            self._ensure_field_writable("work_package", "status")
            status_id = await self._resolve_status_id(status)
            links["status"] = {"href": self._api_href(f"statuses/{status_id}")}
        if assignee is not None:
            self._ensure_field_writable("work_package", "assignee")
            assignee_id = await self._resolve_assignee_id(assignee)
            links["assignee"] = {"href": self._api_href(f"users/{assignee_id}")}
        if parent_work_package_id is CLEAR_PARENT:
            self._ensure_field_writable("work_package", "parent")
            links["parent"] = {"href": None}
        elif parent_work_package_id is not None:
            self._ensure_field_writable("work_package", "parent")
            links["parent"] = {"href": self._api_href(f"work_packages/{parent_work_package_id}")}

        schema_needs = any(
            value is not None
            for value in (
                responsible,
                priority,
                category,
                project_phase,
                custom_fields,
            )
        )
        if schema_needs:
            if links:
                payload["_links"] = links
            schema = await self._get_write_schema(
                project=project,
                type=type,
                work_package_id=work_package_id,
                draft_payload=payload,
                lock_version=lock_version,
            )
            if responsible is not None:
                self._ensure_field_writable("work_package", "responsible")
                links["responsible"] = {"href": self._resolve_schema_option_href(schema, "responsible", responsible)}
            if priority is not None:
                self._ensure_field_writable("work_package", "priority")
                links["priority"] = {"href": self._resolve_schema_option_href(schema, "priority", priority)}
            if category is not None:
                self._ensure_field_writable("work_package", "category")
                links["category"] = {"href": self._resolve_schema_option_href(schema, "category", category)}
            if project_phase is not None:
                self._ensure_field_writable("work_package", "project_phase")
                links["projectPhase"] = {
                    "href": self._resolve_schema_option_href(schema, "projectPhase", project_phase)
                }
            if custom_fields:
                self._apply_custom_fields(payload, links, schema, custom_fields)
        if links:
            payload["_links"] = links
        return payload

    async def _get_write_schema(
        self,
        *,
        project: str,
        type: str | None,
        work_package_id: int | None,
        draft_payload: dict[str, Any],
        lock_version: int | None = None,
    ) -> dict[str, Any]:
        if work_package_id is not None:
            # OpenProject 17.x rejects the work-package form endpoint with a
            # "could not be updated due to conflicting modifications" (409) error
            # unless the current lockVersion is included, even for a schema-only
            # probe. Inject it so the schema fetch on update succeeds.
            schema_body = dict(draft_payload)
            if lock_version is not None:
                schema_body["lockVersion"] = lock_version
            form = await self._post(f"work_packages/{work_package_id}/form", json_body=schema_body)
            return form.get("_embedded", {}).get("schema", {})

        schema_payload = dict(draft_payload)
        schema_links = dict(schema_payload.get("_links", {}))
        if type is not None and "type" not in schema_links:
            type_id = await self._resolve_type_id(type, project=project)
            schema_links["type"] = {"href": self._api_href(f"types/{type_id}")}
        if schema_links:
            schema_payload["_links"] = schema_links
        form = await self._post(f"projects/{project}/work_packages/form", json_body=schema_payload)
        return form.get("_embedded", {}).get("schema", {})

    def _resolve_schema_option_href(self, schema: dict[str, Any], key: str, raw_value: Any) -> str:
        field = schema.get(key)
        if not isinstance(field, dict):
            raise InvalidInputError(f"OpenProject schema does not expose field '{key}' for this work package.")
        allowed_values = field.get("_embedded", {}).get("allowedValues", [])
        if not isinstance(allowed_values, list):
            raise InvalidInputError(f"OpenProject schema does not expose allowed values for field '{key}'.")

        normalized = str(raw_value).strip()
        if not normalized:
            raise InvalidInputError(f"{key} must not be empty.")

        for item in allowed_values:
            href = item.get("_links", {}).get("self", {}).get("href")
            if not href:
                continue
            item_id = _id_from_href(href)
            title = _trim_text(
                item.get("name") or item.get("_links", {}).get("self", {}).get("title"), limit=SUBJECT_LIMIT
            )
            if normalized.isdigit() and item_id is not None and int(normalized) == item_id:
                return href
            if title and title.casefold() == normalized.casefold():
                return href
        raise InvalidInputError(f"OpenProject value '{raw_value}' is not allowed for field '{key}'.")

    def _apply_custom_fields(
        self,
        payload: dict[str, Any],
        links: dict[str, Any],
        schema: dict[str, Any],
        custom_fields: dict[str, Any],
    ) -> None:
        for raw_key, raw_value in custom_fields.items():
            self._ensure_custom_field_input_writable(raw_key)
            schema_key = self._resolve_custom_field_key(schema, raw_key)
            field = schema[schema_key]
            self._ensure_custom_field_writable(
                _trim_text(field.get("name"), limit=SUBJECT_LIMIT) or schema_key,
                schema_key,
            )
            location = field.get("location")
            if location == "_links":
                hrefs = self._resolve_custom_field_links(field, raw_value, schema_key)
                if len(hrefs) == 1:
                    links[schema_key] = {"href": hrefs[0]}
                else:
                    links[schema_key] = [{"href": href} for href in hrefs]
            else:
                payload[schema_key] = raw_value

    def _resolve_custom_field_key(self, schema: dict[str, Any], raw_key: str) -> str:
        normalized = str(raw_key).strip()
        if not normalized:
            raise InvalidInputError("custom field keys must not be empty.")
        if normalized in schema:
            return normalized
        if normalized.casefold().startswith("customfield") and normalized[11:].isdigit():
            candidate = f"customField{normalized[11:]}"
            if candidate in schema:
                return candidate
        for key, field in schema.items():
            if not key.startswith("customField") or not isinstance(field, dict):
                continue
            name = _trim_text(field.get("name"), limit=SUBJECT_LIMIT)
            if name and name.casefold() == normalized.casefold():
                return key
        raise InvalidInputError(f"OpenProject custom field '{raw_key}' is not available for this work package.")

    def _resolve_custom_field_links(self, field: dict[str, Any], raw_value: Any, key: str) -> list[str]:
        values = raw_value if isinstance(raw_value, list) else [raw_value]
        hrefs = [self._resolve_schema_option_href({key: field}, key, value) for value in values]
        if not hrefs:
            raise InvalidInputError(f"OpenProject custom field '{key}' requires at least one value.")
        return hrefs

    async def _finalize_work_package_write(
        self,
        *,
        action: str,
        confirm: bool,
        form: dict[str, Any],
        write_path: str,
        write_method: str = "POST",
        work_package_id: int | None = None,
        project_name: str | None = None,
        preview_message: str | None = None,
        success_message: str | None = None,
    ) -> WorkPackageWriteResult:
        embedded = form.get("_embedded", {})
        payload = embedded.get("payload", {})
        validation_errors = _normalize_validation_errors(embedded.get("validationErrors"))
        ready = not validation_errors

        if not ready:
            return WorkPackageWriteResult(
                action=action,
                confirmed=False,
                requires_confirmation=not confirm,
                ready=False,
                message="OpenProject rejected the proposed changes. Fix the validation errors before confirming.",
                work_package_id=work_package_id,
                project=project_name,
                payload=payload,
                validation_errors=validation_errors,
                result=None,
            )

        if self._preview_mode(confirm):
            return WorkPackageWriteResult(
                action=action,
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message=preview_message
                or "OpenProject validated the change. Ask for confirmation, then call again with confirm=true to write it.",
                work_package_id=work_package_id,
                project=project_name,
                payload=payload,
                validation_errors={},
                result=None,
            )

        self._ensure_write_enabled("work_package")
        if write_method == "PATCH":
            response = await self._patch(write_path, json_body=payload)
        else:
            response = await self._post(write_path, json_body=payload)
        detail = self.normalize_work_package_detail(response)
        return WorkPackageWriteResult(
            action=action,
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message=success_message or f"Work package {action}d successfully.",
            work_package_id=detail.id,
            project=detail.project,
            payload=payload,
            validation_errors={},
            result=detail,
        )

    def _build_version_write_payload(
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
            self._ensure_field_writable("version", "name")
            payload["name"] = name
        if description is not None:
            self._ensure_field_writable("version", "description")
            payload["description"] = {"format": "plain", "raw": description}
        if start_date is not None:
            self._ensure_field_writable("version", "start_date")
            payload["startDate"] = start_date
        if end_date is not None:
            self._ensure_field_writable("version", "end_date")
            payload["endDate"] = end_date
        if status is not None:
            self._ensure_field_writable("version", "status")
            payload["status"] = status
        if sharing is not None:
            self._ensure_field_writable("version", "sharing")
            payload["sharing"] = sharing
        if project_id is not None:
            self._ensure_field_writable("version", "defining_project")
            links["definingProject"] = {"href": self._api_href(f"projects/{project_id}")}
        if links:
            payload["_links"] = links
        return payload

    async def _build_board_write_payload(
        self,
        *,
        name: str | None,
        project: str | None,
        public: bool | None,
        starred: bool | None,
        hidden: bool | None,
        include_subprojects: bool | None,
        show_hierarchies: bool | None,
        timeline_visible: bool | None,
        group_by: str | None,
        columns: list[str] | None,
        sort_by: list[str] | None,
        highlighted_attributes: list[str] | None,
        filters: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        links: dict[str, Any] = {}

        if name is not None:
            self._ensure_field_writable("board", "name")
            payload["name"] = name
        if public is not None:
            self._ensure_field_writable("board", "public")
            payload["public"] = public
        if starred is not None:
            self._ensure_field_writable("board", "starred")
            payload["starred"] = starred
        if hidden is not None:
            self._ensure_field_writable("board", "hidden")
            payload["hidden"] = hidden
        if include_subprojects is not None:
            self._ensure_field_writable("board", "include_subprojects")
            payload["includeSubprojects"] = include_subprojects
        # group_by and showHierarchies are mutually exclusive in the OpenProject API
        effective_show_hierarchies = show_hierarchies
        if group_by is not None and show_hierarchies is None:
            effective_show_hierarchies = False
        if effective_show_hierarchies is not None:
            self._ensure_field_writable("board", "show_hierarchies")
            payload["showHierarchies"] = effective_show_hierarchies
        if timeline_visible is not None:
            self._ensure_field_writable("board", "timeline_visible")
            payload["timelineVisible"] = timeline_visible
        if filters is not None:
            self._ensure_field_writable("board", "filters")
            payload["filters"] = filters
        if project is not None:
            self._ensure_field_writable("board", "project")
            project_id = await self._resolve_project_id(project)
            links["project"] = {"href": self._api_href(f"projects/{project_id}")}
        if group_by is not None:
            self._ensure_field_writable("board", "group_by")
            links["groupBy"] = {"href": self._resolve_query_reference_href(group_by, kind="group_by")}
        if columns is not None:
            self._ensure_field_writable("board", "columns")
            links["columns"] = [{"href": self._resolve_query_reference_href(item, kind="column")} for item in columns]
        if sort_by is not None:
            self._ensure_field_writable("board", "sort_by")
            links["sortBy"] = [{"href": self._resolve_query_reference_href(item, kind="sort_by")} for item in sort_by]
        if highlighted_attributes is not None:
            self._ensure_field_writable("board", "highlighted_attributes")
            links["highlightedAttributes"] = [
                {"href": self._resolve_query_reference_href(item, kind="column")} for item in highlighted_attributes
            ]
        if links:
            payload["_links"] = links
        return payload

    async def _build_time_entry_write_payload(
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
        activity_project_id: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        links: dict[str, dict[str, str]] = {}

        if hours is not None:
            self._ensure_field_writable("time_entry", "hours")
            payload["hours"] = hours
        if spent_on is not None:
            self._ensure_field_writable("time_entry", "spent_on")
            payload["spentOn"] = spent_on
        # start/end times require the admin setting; OpenProject rejects them when
        # disabled, so we only include them when the caller provides a value.
        if start_time is not None:
            payload["startTime"] = start_time
        if end_time is not None:
            payload["endTime"] = end_time
        if comment is not None:
            self._ensure_field_writable("time_entry", "comment")
            self._ensure_field_writable("activity", "comment")
            payload["comment"] = {"format": "markdown", "raw": comment}
        if ongoing is not None:
            self._ensure_field_writable("time_entry", "ongoing")
            payload["ongoing"] = ongoing
        if work_package_id is not None:
            self._ensure_field_writable("time_entry", "entity")
            links["entity"] = {"href": self._api_href(f"work_packages/{work_package_id}")}
        elif project is not None:
            self._ensure_field_writable("time_entry", "project")
            project_id = await self._resolve_project_id(project)
            links["project"] = {"href": self._api_href(f"projects/{project_id}")}
        if user is not None:
            self._ensure_field_writable("time_entry", "user")
            user_id = await self._resolve_principal_id(user)
            links["user"] = {"href": self._api_href(f"users/{user_id}")}
        if activity is not None:
            self._ensure_field_writable("time_entry", "activity")
            activity_id = await self._resolve_time_entry_activity_id(activity, project_id=activity_project_id)
            links["activity"] = {"href": self._api_href(f"time_entries/activities/{activity_id}")}
        if links:
            payload["_links"] = links
        return payload

    async def _get_project_payload(self, project_ref: str, *, write: bool = False) -> dict[str, Any]:
        payload = await self._get(f"projects/{quote(project_ref, safe='')}")
        if write:
            self._ensure_project_write_allowed(project_ref, payload=payload)
        else:
            self._ensure_project_allowed(project_ref, payload=payload)
        return payload

    async def _time_entry_activities_from_project(self, project_id: int) -> list[TimeEntryActivitySummary]:
        form = await self._post(
            "time_entries/form",
            json_body={"_links": {"project": {"href": self._api_href(f"projects/{project_id}")}}},
        )
        schema = form.get("_embedded", {}).get("schema", {})
        activity_field = schema.get("activity", {})
        allowed = activity_field.get("_embedded", {}).get("allowedValues", [])
        return [self.normalize_time_entry_activity(item) for item in allowed if isinstance(item, dict)]

    async def _finalize_version_write(
        self,
        *,
        action: str,
        confirm: bool,
        form: dict[str, Any],
        write_path: str,
        write_method: str = "POST",
        version_id: int | None = None,
        project_name: str | None = None,
        preview_message: str | None = None,
        success_message: str | None = None,
    ) -> VersionWriteResult:
        embedded = form.get("_embedded", {})
        payload = embedded.get("payload", {})
        validation_errors = _normalize_validation_errors(embedded.get("validationErrors"))
        ready = not validation_errors

        if not ready:
            return VersionWriteResult(
                action=action,
                confirmed=False,
                requires_confirmation=not confirm,
                ready=False,
                message="OpenProject rejected the proposed version changes. Fix the validation errors before confirming.",
                version_id=version_id,
                project=project_name,
                payload=payload,
                validation_errors=validation_errors,
                result=None,
            )

        if self._preview_mode(confirm):
            return VersionWriteResult(
                action=action,
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message=preview_message
                or "OpenProject validated the version change. Ask for confirmation, then call again with confirm=true to write it.",
                version_id=version_id,
                project=project_name,
                payload=payload,
                validation_errors={},
                result=None,
            )

        self._ensure_write_enabled("version")
        if write_method == "PATCH":
            response = await self._patch(write_path, json_body=payload)
        else:
            response = await self._post(write_path, json_body=payload)
        detail = self.normalize_version_detail(response)
        return VersionWriteResult(
            action=action,
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message=success_message or f"Version {action}d successfully.",
            version_id=detail.id,
            project=detail.defining_project,
            payload=payload,
            validation_errors={},
            result=detail,
        )

    async def _finalize_board_write(
        self,
        *,
        action: str,
        confirm: bool,
        form: dict[str, Any],
        write_path: str,
        write_method: str = "POST",
        board_id: int | None = None,
        project_name: str | None = None,
        preview_message: str | None = None,
        success_message: str | None = None,
    ) -> BoardWriteResult:
        embedded = form.get("_embedded", {})
        payload = embedded.get("payload", {})
        validation_errors = _normalize_validation_errors(embedded.get("validationErrors"))
        ready = not validation_errors

        if not ready:
            return BoardWriteResult(
                action=action,
                confirmed=False,
                requires_confirmation=not confirm,
                ready=False,
                message="OpenProject rejected the proposed board changes. Fix the validation errors before confirming.",
                board_id=board_id,
                project=project_name,
                payload=payload,
                validation_errors=validation_errors,
                result=None,
            )

        if self._preview_mode(confirm):
            return BoardWriteResult(
                action=action,
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message=preview_message
                or "OpenProject validated the board change. Ask for confirmation, then call again with confirm=true to write it.",
                board_id=board_id,
                project=project_name,
                payload=payload,
                validation_errors={},
                result=None,
            )

        self._ensure_write_enabled("board")
        if write_method == "PATCH":
            response = await self._patch(write_path, json_body=payload)
        else:
            response = await self._post(write_path, json_body=payload)
        detail = self.normalize_board_detail(response)
        return BoardWriteResult(
            action=action,
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message=success_message or f"Board {action}d successfully.",
            board_id=detail.id,
            project=detail.project,
            payload=payload,
            validation_errors={},
            result=detail,
        )

    async def _finalize_grid_write(
        self,
        *,
        action: str,
        confirm: bool,
        form: dict[str, Any],
        write_path: str,
        write_method: str = "POST",
        grid_id: int | None = None,
        preview_message: str | None = None,
        success_message: str | None = None,
    ) -> GridWriteResult:
        embedded = form.get("_embedded", {})
        payload = embedded.get("payload", {})
        validation_errors = _normalize_validation_errors(embedded.get("validationErrors"))
        ready = not validation_errors
        scope = payload.get("_links", {}).get("scope", {}).get("href")

        if not ready:
            return GridWriteResult(
                action=action,
                confirmed=False,
                requires_confirmation=not confirm,
                ready=False,
                message="OpenProject rejected the proposed grid changes. Fix the validation errors before confirming.",
                grid_id=grid_id,
                scope=scope,
                payload=payload,
                validation_errors=validation_errors,
                result=None,
            )

        if self._preview_mode(confirm):
            return GridWriteResult(
                action=action,
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message=preview_message
                or "OpenProject validated the grid change. Ask for confirmation, then call again with confirm=true to write it.",
                grid_id=grid_id,
                scope=scope,
                payload=payload,
                validation_errors={},
                result=None,
            )

        self._ensure_write_enabled("project")
        if write_method == "PATCH":
            response = await self._patch(write_path, json_body=payload)
        else:
            response = await self._post(write_path, json_body=payload)
        detail = self.normalize_grid(response)
        return GridWriteResult(
            action=action,
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message=success_message or f"Grid {action}d successfully.",
            grid_id=detail.id,
            scope=detail.scope,
            payload=payload,
            validation_errors={},
            result=detail,
        )

    async def _build_project_write_payload(
        self,
        *,
        name: str | None,
        identifier: str | None,
        description: str | None,
        public: bool | None,
        active: bool | None,
        status: str | None,
        status_explanation: str | None,
        parent: str | None,
        project_id: int | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        links: dict[str, dict[str, str | None]] = {}
        schema = await self._get_project_schema(project_id=project_id, draft_payload=payload)

        if name is not None:
            self._ensure_field_writable("project", "name")
            payload["name"] = name
        if identifier is not None:
            self._ensure_field_writable("project", "identifier")
            payload["identifier"] = identifier
        if description is not None:
            self._ensure_field_writable("project", "description")
            payload["description"] = {"format": "markdown", "raw": description}
        if public is not None:
            self._ensure_field_writable("project", "public")
            payload["public"] = public
        if active is not None:
            self._ensure_field_writable("project", "active")
            payload["active"] = active
        if status_explanation is not None:
            self._ensure_field_writable("project", "status_explanation")
            payload["statusExplanation"] = {"format": "markdown", "raw": status_explanation}
        if status is not None:
            self._ensure_field_writable("project", "status")
            links["status"] = {"href": self._resolve_project_status_href(schema, status)}
        if parent is not None:
            self._ensure_field_writable("project", "parent")
            parent_id = await self._resolve_project_id(parent)
            links["parent"] = {"href": self._api_href(f"projects/{parent_id}")}
        if links:
            payload["_links"] = links
        return payload

    async def _get_project_schema(
        self,
        *,
        project_id: int | None,
        draft_payload: dict[str, Any],
    ) -> dict[str, Any]:
        if project_id is None:
            form = await self._post("projects/form", json_body=draft_payload)
        else:
            form = await self._post(f"projects/{project_id}/form", json_body=draft_payload)
        return form.get("_embedded", {}).get("schema", {})

    async def _list_available_parent_projects(
        self,
        project_id: int,
        *,
        schema: dict[str, Any],
    ) -> list[ProjectSummary]:
        parent_field = schema.get("parent")
        if not isinstance(parent_field, dict):
            return []
        href = parent_field.get("_links", {}).get("allowedValues", {}).get("href")
        if not href:
            href = f"/api/v3/projects/available_parent_projects?of={project_id}"
        payload = await self._get(self._link_to_api_path(href))
        return [self.normalize_project(item) for item in payload.get("_embedded", {}).get("elements", [])]

    def _resolve_project_status_href(self, schema: dict[str, Any], raw_value: str) -> str:
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

    async def _finalize_project_write(
        self,
        *,
        action: str,
        confirm: bool,
        form: dict[str, Any],
        write_path: str,
        write_method: str = "POST",
        project_id: int | None = None,
        project_name: str | None = None,
        preview_message: str | None = None,
        success_message: str | None = None,
    ) -> ProjectWriteResult:
        embedded = form.get("_embedded", {})
        payload = embedded.get("payload", {})
        validation_errors = _normalize_validation_errors(embedded.get("validationErrors"))
        ready = not validation_errors
        if not ready:
            return ProjectWriteResult(
                action=action,
                confirmed=False,
                requires_confirmation=not confirm,
                ready=False,
                message="OpenProject rejected the proposed project changes. Fix the validation errors before confirming.",
                project_id=project_id,
                project=project_name,
                payload=payload,
                validation_errors=validation_errors,
                result=None,
            )
        if self._preview_mode(confirm):
            return ProjectWriteResult(
                action=action,
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message=preview_message
                or "OpenProject validated the project change. Ask for confirmation, then call again with confirm=true to write it.",
                project_id=project_id,
                project=project_name,
                payload=payload,
                validation_errors={},
                result=None,
            )
        self._ensure_write_enabled("project")
        if write_method == "PATCH":
            response = await self._patch(write_path, json_body=payload)
        else:
            response = await self._post(write_path, json_body=payload)
        project = self.normalize_project(response)
        return ProjectWriteResult(
            action=action,
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message=success_message or f"Project {action}d successfully.",
            project_id=project.id,
            project=project.name,
            payload=payload,
            validation_errors={},
            result=project,
        )

    async def _finalize_membership_write(
        self,
        *,
        action: str,
        confirm: bool,
        form: dict[str, Any],
        write_path: str,
        write_method: str = "POST",
        membership_id: int | None = None,
        project_name: str | None = None,
        preview_message: str | None = None,
        success_message: str | None = None,
    ) -> MembershipWriteResult:
        embedded = form.get("_embedded", {})
        payload = embedded.get("payload", {})
        validation_errors = _normalize_validation_errors(embedded.get("validationErrors"))
        ready = not validation_errors
        if not ready:
            return MembershipWriteResult(
                action=action,
                confirmed=False,
                requires_confirmation=not confirm,
                ready=False,
                message="OpenProject rejected the proposed membership changes. Fix the validation errors before confirming.",
                membership_id=membership_id,
                project=project_name,
                payload=payload,
                validation_errors=validation_errors,
                result=None,
            )
        if self._preview_mode(confirm):
            return MembershipWriteResult(
                action=action,
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message=preview_message
                or "OpenProject validated the membership change. Ask for confirmation, then call again with confirm=true to write it.",
                membership_id=membership_id,
                project=project_name,
                payload=payload,
                validation_errors={},
                result=None,
            )
        self._ensure_write_enabled("membership")
        if write_method == "PATCH":
            response = await self._patch(write_path, json_body=payload)
        else:
            response = await self._post(write_path, json_body=payload)
        membership = self.normalize_membership(response)
        return MembershipWriteResult(
            action=action,
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message=success_message or f"Membership {action}d successfully.",
            membership_id=membership.id,
            project=membership.project_name,
            payload=payload,
            validation_errors={},
            result=membership,
        )

    def _ensure_write_enabled(self, scope: str) -> None:
        if scope == "admin":
            if not self.settings.enable_admin_write:
                raise PermissionDeniedError(
                    "User/group management is disabled. Set OPENPROJECT_ENABLE_ADMIN_WRITE=true to allow it."
                )
            return
        if self.settings.write_enabled(scope):
            return
        scope_env = {
            "work_package": "OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE",
            "project": "OPENPROJECT_ENABLE_PROJECT_WRITE",
            "membership": "OPENPROJECT_ENABLE_MEMBERSHIP_WRITE",
            "version": "OPENPROJECT_ENABLE_VERSION_WRITE",
            "board": "OPENPROJECT_ENABLE_BOARD_WRITE",
        }.get(scope, "the relevant OPENPROJECT_ENABLE_*_WRITE flag")
        raise PermissionDeniedError(
            f"OpenProject {scope.replace('_', ' ')} write support is disabled. "
            f"Set {scope_env}=true to allow confirmed writes."
        )

    def _ensure_read_enabled(self, scope: str) -> None:
        if self.settings.read_enabled(scope):
            return
        scope_env = {
            "project": "OPENPROJECT_ENABLE_PROJECT_READ",
            "membership": "OPENPROJECT_ENABLE_MEMBERSHIP_READ",
            "role": "OPENPROJECT_ENABLE_MEMBERSHIP_READ",
            "principal": "OPENPROJECT_ENABLE_MEMBERSHIP_READ",
            "work_package": "OPENPROJECT_ENABLE_WORK_PACKAGE_READ",
            "version": "OPENPROJECT_ENABLE_VERSION_READ",
            "board": "OPENPROJECT_ENABLE_BOARD_READ",
        }.get(scope, "the relevant OPENPROJECT_ENABLE_*_READ flag")
        raise PermissionDeniedError(
            f"OpenProject {scope.replace('_', ' ')} read support is disabled. Set {scope_env}=true to allow reads."
        )

    def _ensure_project_allowed(self, project_ref: str, *, payload: dict[str, Any] | None = None) -> None:
        if not self.settings.allowed_projects:
            return
        if _scope_allows_all(self.settings.allowed_projects):
            return
        candidates = self._project_candidates(project_ref=project_ref, payload=payload)
        if not _scope_matches_candidates(self.settings.allowed_projects, candidates):
            raise PermissionDeniedError(
                "OpenProject access to this project is disabled by OPENPROJECT_ALLOWED_PROJECTS_READ."
            )

    def _ensure_project_write_allowed(self, project_ref: str, *, payload: dict[str, Any] | None = None) -> None:
        self._ensure_project_allowed(project_ref, payload=payload)
        if self.settings.project_write_scope_allows_none:
            raise PermissionDeniedError(
                "OpenProject writes to this project are disabled by OPENPROJECT_ALLOWED_PROJECTS_WRITE."
            )
        if not self.settings.project_write_scope_configured:
            return
        if _scope_allows_all(self.settings.allowed_write_projects):
            return
        candidates = self._project_candidates(project_ref=project_ref, payload=payload)
        if not _scope_matches_candidates(self.settings.allowed_write_projects, candidates):
            raise PermissionDeniedError(
                "OpenProject writes to this project are disabled by OPENPROJECT_ALLOWED_PROJECTS_WRITE."
            )

    def _ensure_project_write_candidate_allowed(self, *, identifier: str | None, name: str | None) -> None:
        candidates = self._project_candidates(identifier=identifier, name=name)
        if (
            self.settings.allowed_projects
            and not _scope_allows_all(self.settings.allowed_projects)
            and not _scope_matches_candidates(self.settings.allowed_projects, candidates)
        ):
            raise PermissionDeniedError(
                "OpenProject access to this project is disabled by OPENPROJECT_ALLOWED_PROJECTS_READ."
            )
        if self.settings.project_write_scope_allows_none:
            raise PermissionDeniedError(
                "OpenProject writes to this project are disabled by OPENPROJECT_ALLOWED_PROJECTS_WRITE."
            )
        if not self.settings.project_write_scope_configured:
            return
        if _scope_allows_all(self.settings.allowed_write_projects):
            return
        if not _scope_matches_candidates(self.settings.allowed_write_projects, candidates):
            raise PermissionDeniedError(
                "OpenProject writes to this project are disabled by OPENPROJECT_ALLOWED_PROJECTS_WRITE."
            )

    def _project_payload_allowed(self, payload: dict[str, Any]) -> bool:
        if not self.settings.allowed_projects:
            return True
        try:
            self._ensure_project_allowed(str(payload.get("id", "")), payload=payload)
            return True
        except PermissionDeniedError:
            return False

    def _project_name_allowed(self, project_name: str | None) -> bool:
        if not self.settings.allowed_projects:
            return True
        if _scope_allows_all(self.settings.allowed_projects):
            return True
        if not project_name:
            return False
        return _scope_matches_candidates(self.settings.allowed_projects, {project_name.casefold()})

    def _ensure_project_link_allowed(self, link: Any) -> None:
        if not self.settings.allowed_projects:
            return
        if _scope_allows_all(self.settings.allowed_projects):
            return
        candidates = self._project_candidates(link=link)
        if not _scope_matches_candidates(self.settings.allowed_projects, candidates):
            raise PermissionDeniedError(
                "OpenProject access to this project is disabled by OPENPROJECT_ALLOWED_PROJECTS_READ."
            )

    def _ensure_project_write_link_allowed(self, link: Any) -> None:
        self._ensure_project_link_allowed(link)
        if self.settings.project_write_scope_allows_none:
            raise PermissionDeniedError(
                "OpenProject writes to this project are disabled by OPENPROJECT_ALLOWED_PROJECTS_WRITE."
            )
        if not self.settings.project_write_scope_configured:
            return
        if _scope_allows_all(self.settings.allowed_write_projects):
            return
        candidates = self._project_candidates(link=link)
        if not _scope_matches_candidates(self.settings.allowed_write_projects, candidates):
            raise PermissionDeniedError(
                "OpenProject writes to this project are disabled by OPENPROJECT_ALLOWED_PROJECTS_WRITE."
            )

    def _ensure_board_payload_allowed(self, payload: dict[str, Any]) -> None:
        project_link = payload.get("_links", {}).get("project")
        if not self.settings.allowed_projects:
            return
        if _scope_allows_all(self.settings.allowed_projects):
            return
        if not isinstance(project_link, dict):
            raise PermissionDeniedError(
                "OpenProject access to this board is disabled by OPENPROJECT_ALLOWED_PROJECTS_READ."
            )
        self._ensure_project_link_allowed(project_link)

    def _ensure_board_write_payload_allowed(self, payload: dict[str, Any]) -> None:
        project_link = payload.get("_links", {}).get("project")
        if not self.settings.project_write_scope_configured:
            return
        if _scope_allows_all(self.settings.allowed_write_projects):
            return
        if not isinstance(project_link, dict):
            raise PermissionDeniedError(
                "OpenProject writes to this board are disabled by OPENPROJECT_ALLOWED_PROJECTS_WRITE."
            )
        self._ensure_project_write_link_allowed(project_link)

    def _board_payload_allowed(self, payload: dict[str, Any]) -> bool:
        try:
            self._ensure_board_payload_allowed(payload)
            return True
        except PermissionDeniedError:
            return False

    def _ensure_view_payload_allowed(self, payload: dict[str, Any]) -> None:
        project_link = payload.get("_links", {}).get("project")
        if not self.settings.allowed_projects:
            return
        if _scope_allows_all(self.settings.allowed_projects):
            return
        if not isinstance(project_link, dict):
            raise PermissionDeniedError(
                "OpenProject access to this view is disabled by OPENPROJECT_ALLOWED_PROJECTS_READ."
            )
        self._ensure_project_link_allowed(project_link)

    def _view_payload_allowed(self, payload: dict[str, Any]) -> bool:
        try:
            self._ensure_view_payload_allowed(payload)
            return True
        except PermissionDeniedError:
            return False

    def _ensure_document_payload_allowed(self, payload: dict[str, Any]) -> None:
        self._ensure_project_link_allowed(payload.get("_links", {}).get("project"))

    def _document_payload_allowed(self, payload: dict[str, Any]) -> bool:
        try:
            self._ensure_document_payload_allowed(payload)
            return True
        except PermissionDeniedError:
            return False

    def _ensure_document_write_payload_allowed(self, payload: dict[str, Any]) -> None:
        self._ensure_project_write_link_allowed(payload.get("_links", {}).get("project"))

    def _ensure_news_payload_allowed(self, payload: dict[str, Any]) -> None:
        self._ensure_project_link_allowed(payload.get("_links", {}).get("project"))

    def _news_payload_allowed(self, payload: dict[str, Any]) -> bool:
        try:
            self._ensure_news_payload_allowed(payload)
            return True
        except PermissionDeniedError:
            return False

    def _ensure_news_write_payload_allowed(self, payload: dict[str, Any]) -> None:
        self._ensure_project_write_link_allowed(payload.get("_links", {}).get("project"))

    def _version_payload_allowed(self, payload: dict[str, Any]) -> bool:
        try:
            self._ensure_project_link_allowed(payload.get("_links", {}).get("definingProject"))
            return True
        except PermissionDeniedError:
            return False

    def _project_ref_from_scope_href(self, scope_href: str | None) -> str | None:
        if not scope_href:
            return None
        path = urlparse(scope_href).path
        if not path.startswith("/projects/"):
            return None
        tail = path[len("/projects/") :]
        if not tail:
            return None
        return unquote(tail.split("/", 1)[0])

    def _work_package_payload_allowed(self, payload: dict[str, Any]) -> bool:
        try:
            self._ensure_project_link_allowed(payload.get("_links", {}).get("project"))
            return True
        except PermissionDeniedError:
            return False

    def _time_entry_payload_allowed(self, payload: dict[str, Any]) -> bool:
        try:
            self._ensure_project_link_allowed(payload.get("_links", {}).get("project"))
            return True
        except PermissionDeniedError:
            return False

    def _project_candidates(
        self,
        *,
        project_ref: str | None = None,
        payload: dict[str, Any] | None = None,
        link: Any = None,
        identifier: str | None = None,
        name: str | None = None,
    ) -> set[str]:
        candidates: set[str] = set()
        for value in (project_ref, identifier, name):
            if value:
                candidates.add(str(value).casefold())
        if payload is not None:
            identifier_value = _trim_text(payload.get("identifier"), limit=SUBJECT_LIMIT)
            name_value = _trim_text(payload.get("name"), limit=SUBJECT_LIMIT)
            if identifier_value:
                candidates.add(identifier_value.casefold())
            if name_value:
                candidates.add(name_value.casefold())
            project_id = payload.get("id")
            if project_id is not None:
                candidates.add(str(project_id).casefold())
        if isinstance(link, dict):
            href = link.get("href")
            title = link.get("title")
            if href:
                slug = _slug_from_href(href)
                if slug:
                    candidates.add(slug.casefold())
                project_id = _id_from_href(href)
                if project_id is not None:
                    candidates.add(str(project_id).casefold())
                    known_identifier = self._project_id_to_identifier.get(project_id)
                    if known_identifier:
                        candidates.add(known_identifier.casefold())
            if title:
                title_cf = str(title).casefold()
                candidates.add(title_cf)
                # Also add an identifier-style variant (spaces → hyphens) so that a project
                # named "My Project" matches the pattern "my-project" (its likely identifier).
                candidates.add(title_cf.replace(" ", "-"))
        return {candidate for candidate in candidates if candidate}

    def _link_matches_project_refs(self, link: Any, project_refs: set[str]) -> bool:
        return not self._project_candidates(link=link).isdisjoint(project_refs)

    def _board_matches_project(self, board: BoardSummary, project_refs: set[str]) -> bool:
        return not project_refs.isdisjoint(
            {
                str(board.project_id).casefold() if board.project_id is not None else "",
                (board.project or "").casefold(),
            }
        )

    async def _ensure_attachment_container_allowed(
        self,
        payload: dict[str, Any],
        *,
        write: bool = False,
    ) -> int:
        container_link = payload.get("_links", {}).get("container")
        href = container_link.get("href") if isinstance(container_link, dict) else None
        if not isinstance(href, str) or "work_packages/" not in href:
            raise InvalidInputError("Only work package attachments are supported.")
        work_package_id = _id_from_href(href)
        if work_package_id is None:
            raise OpenProjectServerError("OpenProject returned an attachment without a valid container id.")
        work_package = await self._get(f"work_packages/{work_package_id}")
        if write:
            self._ensure_project_write_link_allowed(work_package.get("_links", {}).get("project"))
        else:
            self._ensure_project_link_allowed(work_package.get("_links", {}).get("project"))
        return work_package_id

    def _attachment_root(self) -> Path:
        """The directory attachment uploads are confined to.

        Defaults to the current working directory (where the client launched the
        server — typically the user's project). OPENPROJECT_ATTACHMENT_ROOT can
        point it elsewhere. This bounds which local files a caller can upload,
        so a malicious/confused agent cannot exfiltrate arbitrary host files
        (e.g. the API token in .mcp.json, SSH keys, /etc/passwd).
        """
        configured = self.settings.attachment_root
        base = Path(configured).expanduser() if configured else Path.cwd()
        return base.resolve()

    # Files that must never be uploaded even from inside the attachment root:
    # the config often lives in the server's working directory, so directory
    # containment alone would still expose the API token and other secrets.
    _ATTACHMENT_DENY_NAMES = frozenset(
        {
            ".mcp.json",
            ".env",
            "credentials",
            "id_rsa",
            "id_ed25519",
        }
    )
    _ATTACHMENT_DENY_SUFFIXES = (".pem", ".key", ".p12", ".pfx")

    def _is_sensitive_attachment(self, path: Path) -> bool:
        name = path.name
        lower = name.lower()
        if lower in self._ATTACHMENT_DENY_NAMES:
            return True
        if lower.startswith(".mcp.json"):  # e.g. .mcp.json.bak.<ts>
            return True
        return any(lower.endswith(suffix) for suffix in self._ATTACHMENT_DENY_SUFFIXES)

    def _prepare_attachment_file(self, file_path: str, *, include_bytes: bool) -> dict[str, Any]:
        root = self._attachment_root()
        # Resolve symlinks and .. so the containment check cannot be defeated.
        path = Path(file_path).expanduser().resolve()
        if root not in path.parents and path != root:
            raise InvalidInputError(
                f"Attachment file '{file_path}' is outside the allowed attachment directory "
                f"({root}). Set OPENPROJECT_ATTACHMENT_ROOT to permit another location."
            )
        if self._is_sensitive_attachment(path):
            raise InvalidInputError(
                f"Attachment file '{file_path}' looks like a credential/config file and cannot be "
                "uploaded. This protects the API token and other local secrets."
            )
        if not path.is_file():
            raise InvalidInputError(f"Attachment file '{file_path}' does not exist or is not a file.")
        file_bytes = path.read_bytes() if include_bytes else None
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return {
            "file_name": path.name,
            "file_size": path.stat().st_size,
            "file_bytes": file_bytes,
            "content_type": content_type,
        }

    async def _validate_attachment_size(self, file_size: int) -> None:
        configuration = await self.get_instance_configuration()
        maximum = configuration.maximum_attachment_file_size
        if maximum is not None and file_size > maximum:
            raise InvalidInputError(
                f"Attachment exceeds the configured OpenProject maximum attachment size of {maximum} bytes."
            )

    def _hidden_patterns(self, entity: str) -> tuple[str, ...]:
        configured = tuple(self.settings.hidden_fields.get(entity, ()))
        legacy = {
            "project": self.settings.hide_project_fields,
            "work_package": self.settings.hide_work_package_fields,
            "activity": self.settings.hide_activity_fields,
        }.get(entity, ())
        if not configured:
            return legacy
        if not legacy:
            return configured
        combined = list(configured)
        for item in legacy:
            if item not in combined:
                combined.append(item)
        return tuple(combined)

    def _normalize_hide_token(self, value: str) -> str:
        return value.casefold().replace("-", "_").replace(" ", "_")

    def _field_hidden(self, entity: str, field_name: str) -> bool:
        patterns = self._hidden_patterns(entity)
        if not patterns:
            return False
        normalized = self._normalize_hide_token(field_name)
        candidates = {normalized, normalized.replace("_", "")}
        return any(
            fnmatchcase(candidate, self._normalize_hide_token(pattern))
            for pattern in patterns
            for candidate in candidates
        )

    def _ensure_field_writable(self, entity: str, field_name: str) -> None:
        if not self._field_hidden(entity, field_name):
            return
        env_name = HIDE_FIELD_ENV_BY_ENTITY.get(entity, "OPENPROJECT_HIDE_FIELDS")
        raise InvalidInputError(f"OpenProject field '{field_name}' is hidden by {env_name} and cannot be written.")

    def _visible_formattable_text(
        self,
        value: Any,
        entity: str,
        field_name: str,
        *,
        limit: int = FORMATTABLE_LIMIT,
    ) -> str | None:
        if self._field_hidden(entity, field_name):
            return None
        return _extract_formattable_text(value, limit=limit)

    def _visible_formattable_text_with_meta(
        self,
        value: Any,
        entity: str,
        field_name: str,
        *,
        limit: int | None = FORMATTABLE_LIMIT,
        preserve_newlines: bool = False,
    ) -> tuple[str | None, bool, int | None]:
        """Hide-aware formattable text plus ``(text, truncated, full_length)``.

        ``limit=None`` returns the full text uncapped. When the field is hidden,
        returns ``(None, False, None)`` — a hidden field is not "truncated", it
        is simply absent.
        """
        if self._field_hidden(entity, field_name):
            return None, False, None
        return _extract_formattable_text_with_meta(value, limit=limit, preserve_newlines=preserve_newlines)

    def _custom_field_hidden(self, field_name: str, key: str) -> bool:
        patterns = tuple(self.settings.hide_custom_fields)
        if not patterns:
            return False
        candidates = {
            self._normalize_hide_token(field_name),
            self._normalize_hide_token(key),
        }
        return any(
            fnmatchcase(candidate, self._normalize_hide_token(pattern))
            for pattern in patterns
            for candidate in candidates
        )

    def _ensure_custom_field_input_writable(self, raw_key: str) -> None:
        normalized = self._normalize_hide_token(str(raw_key).strip())
        if normalized and self._custom_field_hidden(raw_key, raw_key):
            raise InvalidInputError(
                f"OpenProject custom field '{raw_key}' is hidden by OPENPROJECT_HIDE_CUSTOM_FIELDS and cannot be written."
            )

    def _ensure_custom_field_writable(self, field_name: str, key: str) -> None:
        if not self._custom_field_hidden(field_name, key):
            return
        raise InvalidInputError(
            f"OpenProject custom field '{field_name}' is hidden by OPENPROJECT_HIDE_CUSTOM_FIELDS and cannot be written."
        )

    def _apply_hidden_fields(self, entity: str, value: Any) -> Any:
        """Tag a result dataclass with the field names hidden for its entity.

        The names are stamped as a private ``_hidden_keys`` attribute (not a
        dataclass field, so it never appears in the schema/output). The
        serialization seam (tools._to_payload) reads it and drops those keys
        entirely from the response — hidden fields cost neither their key name nor
        a null value (OPM-72). Stamping is possible because the response dataclasses
        are not frozen.
        """
        if not is_dataclass(value):
            return value
        hidden = frozenset(
            field_def.name for field_def in dataclass_fields(value) if self._field_hidden(entity, field_def.name)
        )
        if hidden:
            value._hidden_keys = hidden
        return value

    def _api_href(self, relative_path: str) -> str:
        return f"/{self._api_prefix.lstrip('/')}{relative_path.lstrip('/')}"

    async def _resolve_project_id(self, project_ref: str) -> str:
        if project_ref.isdigit():
            return project_ref
        payload = await self._get(f"projects/{quote(project_ref, safe='')}")
        if payload.get("_type") != "Project":
            raise NotFoundError("OpenProject project not found.")
        return str(payload["id"])

    async def _resolve_principal_id(self, principal_ref: str) -> str:
        if principal_ref.casefold() == "me":
            current_user = await self.get_current_user()
            return str(current_user.id)
        if principal_ref.isdigit():
            return principal_ref
        principals = await self.list_principals(search=principal_ref, offset=1, limit=self.settings.max_results)
        matches = [
            str(item.id) for item in principals.results if (item.name or "").casefold() == principal_ref.casefold()
        ]
        if not matches:
            raise InvalidInputError(f"OpenProject principal '{principal_ref}' was not found.")
        if len(matches) > 1:
            raise InvalidInputError(
                f"OpenProject principal '{principal_ref}' is ambiguous. Pass a numeric user or group id."
            )
        return matches[0]

    async def _resolve_role_hrefs(self, roles: list[str]) -> list[str]:
        available_roles = await self.list_roles()
        hrefs: list[str] = []
        for role_ref in roles:
            normalized = role_ref.strip()
            if not normalized:
                continue
            if normalized.isdigit():
                hrefs.append(self._api_href(f"roles/{normalized}"))
                continue
            matches = [
                role for role in available_roles.results if (role.name or "").casefold() == normalized.casefold()
            ]
            if not matches:
                raise InvalidInputError(f"OpenProject role '{role_ref}' was not found.")
            if len(matches) > 1:
                raise InvalidInputError(f"OpenProject role '{role_ref}' is ambiguous. Pass a numeric role id.")
            hrefs.append(self._api_href(f"roles/{matches[0].id}"))
        if not hrefs:
            raise InvalidInputError("At least one role is required.")
        return hrefs

    async def _resolve_type_id(self, type_ref: str, *, project: str | None) -> str:
        if type_ref.isdigit():
            return type_ref
        if not project:
            raise InvalidInputError("type names require a project filter. Pass a numeric type id or set project.")

        project_id = project
        if not project_id.isdigit():
            project_payload = await self._get(f"projects/{quote(project, safe='')}")
            project_id = str(project_payload["id"])
        payload = await self._get(f"projects/{project_id}/types")
        elements = payload.get("_embedded", {}).get("elements", [])
        matches = [str(item["id"]) for item in elements if str(item.get("name", "")).casefold() == type_ref.casefold()]
        if not matches:
            raise InvalidInputError(f"OpenProject type '{type_ref}' was not found in project '{project}'.")
        return matches[0]

    async def _resolve_version_id(self, version_ref: str, *, project: str | None) -> str:
        if version_ref.isdigit():
            return version_ref

        project_ref = project
        if project_ref is not None and project_ref.isdigit():
            project_payload = await self._get(f"projects/{project_ref}")
            project_ref = project_payload.get("identifier") or project_ref
        versions = await self.list_versions(project=project_ref, offset=1, limit=self.settings.max_results)
        matches = [str(item.id) for item in versions.results if (item.name or "").casefold() == version_ref.casefold()]
        if not matches:
            scope = f" in project '{project}'" if project else ""
            raise InvalidInputError(f"OpenProject version '{version_ref}' was not found{scope}.")
        if len(matches) > 1:
            raise InvalidInputError(
                f"OpenProject version '{version_ref}' is ambiguous without a more specific filter. Pass a numeric version id."
            )
        return matches[0]

    def _work_package_ref(self, ref: int | str) -> str:
        """Return a path-safe work-package reference for a ``work_packages/{id}`` path.

        Both a numeric id and a project-prefixed identifier (e.g. ``PROJ-123``,
        exposed as ``displayId`` in OpenProject 17.5+) are accepted directly by the
        ``GET/PATCH/DELETE /api/v3/work_packages/{id}`` endpoints: in semantic mode
        OpenProject resolves the project-based form on the server. The reference is
        passed through verbatim (URL-encoded) so the behaviour degrades cleanly — on
        instances without semantic identifiers a project-prefixed reference simply
        yields a 404 (mapped to ``NotFoundError``), while numeric ids keep working on
        every supported version.
        """
        return quote(str(ref).strip(), safe="")

    async def _resolve_work_package_id(self, ref: int | str) -> int:
        """Resolve a work-package reference to its canonical numeric id.

        Needed where the numeric id itself is required (e.g. a relation filter or a
        client-side equality check) rather than a request path. A numeric reference
        is returned directly without an API call; a project-prefixed identifier is
        resolved by fetching the work package — the path endpoint accepts the semantic
        form on OpenProject 17.5+ — and reading back its numeric ``id``.
        """
        s = str(ref).strip()
        if s.isdigit():
            return int(s)
        try:
            payload = await self._get(f"work_packages/{quote(s, safe='')}")
        except NotFoundError as exc:
            # A project-prefixed reference only resolves on OpenProject 17.5+ (and
            # requires the exact, case-sensitive project identifier). Give a hint
            # instead of a bare "not found" so a too-old instance or a case/prefix
            # mismatch is distinguishable from a genuinely missing work package.
            raise NotFoundError(
                f"Work package '{s}' was not found. Semantic references like 'PROJ-123' "
                "require OpenProject 17.5+ and the exact project identifier (case-sensitive); "
                "on older instances use the numeric work-package id."
            ) from exc
        return int(payload["id"])

    async def _resolve_status_id(self, status_ref: str) -> str:
        if status_ref.isdigit():
            return status_ref
        payload = await self._get("statuses")
        matches = [
            str(item["id"])
            for item in payload.get("_embedded", {}).get("elements", [])
            if str(item.get("name", "")).casefold() == status_ref.casefold()
        ]
        if not matches:
            raise InvalidInputError(f"OpenProject status '{status_ref}' was not found.")
        return matches[0]

    async def _resolve_assignee_id(self, assignee_ref: str) -> str:
        if assignee_ref.casefold() == "me":
            current_user = await self.get_current_user()
            return str(current_user.id)
        if assignee_ref.isdigit():
            return assignee_ref
        raise InvalidInputError("assignee must be a positive integer user id or 'me'.")

    async def _resolve_time_entry_activity_id(self, activity_ref: str, *, project_id: int | None = None) -> str:
        if activity_ref.isdigit():
            return activity_ref
        if project_id is not None:
            activities = TimeEntryActivityListResult(
                count=0,
                results=await self._time_entry_activities_from_project(project_id),
            )
        else:
            activities = await self.list_time_entry_activities()
        matches = [
            str(item.id) for item in activities.results if (item.name or "").casefold() == activity_ref.casefold()
        ]
        if not matches:
            raise InvalidInputError(f"OpenProject time entry activity '{activity_ref}' was not found.")
        if len(matches) > 1:
            raise InvalidInputError(
                f"OpenProject time entry activity '{activity_ref}' is ambiguous. Pass a numeric activity id."
            )
        return matches[0]

    def _resolve_query_reference_href(self, reference: str, *, kind: str) -> str:
        normalized = str(reference).strip()
        if not normalized:
            raise InvalidInputError(f"{kind.replace('_', ' ')} values must not be empty.")

        if normalized.startswith("http://") or normalized.startswith("https://"):
            parsed = urlparse(normalized)
            if _origin_from_url(normalized) != self._origin:
                raise InvalidInputError(
                    f"OpenProject {kind.replace('_', ' ')} references must stay on the same origin."
                )
            return parsed.path

        if normalized.startswith("/"):
            return normalized

        if kind == "sort_by":
            return self._api_href(f"queries/sort_bys/{normalized}")
        if kind == "group_by":
            return self._api_href(f"queries/group_bys/{normalized}")
        return self._api_href(f"queries/columns/{normalized}")


def _json_param(value: list[dict[str, Any]]) -> str:
    return json.dumps(value, separators=(",", ":"))


def _origin_from_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _normalize_validation_errors(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, str] = {}
    for key, entry in value.items():
        message = _extract_formattable_text(entry, limit=SUBJECT_LIMIT)
        if message is None and isinstance(entry, dict):
            message = _trim_text(entry.get("message"), limit=SUBJECT_LIMIT)
        if message is None:
            message = _trim_text(entry, limit=SUBJECT_LIMIT)
        if message:
            normalized[str(key)] = message
    return normalized


def _trim_text(value: Any, *, limit: int) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _normalize_text(value: Any, *, preserve_newlines: bool) -> str:
    """Normalize whitespace before trimming.

    Default (``preserve_newlines=False``): collapse all whitespace/newlines to
    single spaces — the historic behavior for single-line fields (subjects,
    titles, error messages).

    ``preserve_newlines=True``: keep paragraph/list structure. CRLF→LF, collapse
    inline whitespace per line, strip trailing whitespace per line, strip leading
    and trailing blank lines, and collapse any run of blank lines to a single
    blank line (one visible paragraph break, i.e. ``\\n\\n``).
    """
    if not preserve_newlines:
        return " ".join(str(value).split())
    lines = str(value).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    normalized: list[str] = []
    blank_run = 0
    for line in lines:
        stripped = " ".join(line.split())
        if stripped:
            blank_run = 0
            normalized.append(stripped)
        else:
            blank_run += 1
            if blank_run <= 1:
                normalized.append("")
    # Strip leading/trailing blank lines.
    while normalized and normalized[0] == "":
        normalized.pop(0)
    while normalized and normalized[-1] == "":
        normalized.pop()
    return "\n".join(normalized)


def _trim_text_with_meta(
    value: Any, *, limit: int | None, preserve_newlines: bool = False
) -> tuple[str | None, bool, int | None]:
    """Trim ``value`` to ``limit`` and report truncation metadata.

    ``limit=None`` means *no cap* — return the full text (never truncated). This
    is the single-work-package path, where the caller wants everything.

    Returns ``(text, truncated, full_length)`` where ``full_length`` is the
    character count of the normalized text *before* trimming, so the invariant
    ``truncated == (limit is not None and full_length > limit)`` holds and
    callers can tell how much was cut. ``text``/``full_length`` are ``None`` when
    there is no content.
    """
    if value is None:
        return None, False, None
    text = _normalize_text(value, preserve_newlines=preserve_newlines)
    if not text:
        return None, False, None
    full_length = len(text)
    if limit is None or full_length <= limit:
        return text, False, full_length
    return text[: limit - 1].rstrip() + "…", True, full_length


def _extract_formattable_text(value: Any, *, limit: int = FORMATTABLE_LIMIT) -> str | None:
    if isinstance(value, dict):
        return _trim_text(value.get("raw") or value.get("html"), limit=limit)
    return _trim_text(value, limit=limit)


def _extract_formattable_text_with_meta(
    value: Any, *, limit: int | None = FORMATTABLE_LIMIT, preserve_newlines: bool = False
) -> tuple[str | None, bool, int | None]:
    """Like ``_extract_formattable_text`` but reports truncation metadata.

    ``limit=None`` returns the full text uncapped.
    """
    raw = value.get("raw") or value.get("html") if isinstance(value, dict) else value
    return _trim_text_with_meta(raw, limit=limit, preserve_newlines=preserve_newlines)


def _link_title(link: Any) -> str | None:
    if not isinstance(link, dict):
        return None
    title = link.get("title")
    return _trim_text(title, limit=SUBJECT_LIMIT)


def _next_offset(offset: int, limit: int, total: int) -> int | None:
    if offset * limit >= total:
        return None
    return offset + 1


def _id_from_href(href: str | None) -> int | None:
    if not href:
        return None
    parts = href.rstrip("/").split("/")
    try:
        return int(parts[-1])
    except (ValueError, IndexError):
        return None


def _slug_from_href(href: str | None) -> str | None:
    if not href:
        return None
    parts = href.rstrip("/").split("/")
    try:
        slug = parts[-1]
        return unquote(slug) or None
    except IndexError:
        return None


def _percentage_done(payload: dict[str, Any]) -> int | None:
    if payload.get("percentageDone") is not None:
        return payload.get("percentageDone")
    return payload.get("derivedPercentageDone")


def _scope_allows_all(values: tuple[str, ...]) -> bool:
    return any(item.strip() == "*" for item in values)


def _scope_matches_candidates(scope: tuple[str, ...], candidates: set[str]) -> bool:
    normalized_candidates = {candidate.casefold() for candidate in candidates if candidate}
    if not normalized_candidates:
        return False
    if _scope_allows_all(scope):
        return True
    for raw_pattern in scope:
        pattern = raw_pattern.strip().casefold()
        if not pattern:
            continue
        for candidate in normalized_candidates:
            if fnmatchcase(candidate, pattern):
                return True
    return False
