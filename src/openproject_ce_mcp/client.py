from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
from collections.abc import Awaitable, Callable
from dataclasses import replace
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, TypeVar, cast
from urllib.parse import quote, unquote, urljoin, urlparse

import httpx

from . import __version__
from .app.adapters import httpx_version_api as _httpx_version_api
from .app.adapters.httpx_action_capability_api import HttpxActionCapabilityApi
from .app.adapters.httpx_board_api import HttpxBoardApi
from .app.adapters.httpx_category_api import HttpxCategoryApi
from .app.adapters.httpx_document_api import HttpxDocumentApi
from .app.adapters.httpx_grid_api import HttpxGridApi
from .app.adapters.httpx_membership_api import HttpxMembershipApi
from .app.adapters.httpx_news_api import HttpxNewsApi
from .app.adapters.httpx_project_api import HttpxProjectApi
from .app.adapters.httpx_sprint_api import HttpxSprintApi
from .app.adapters.httpx_version_api import HttpxVersionApi
from .app.adapters.httpx_view_api import HttpxViewApi
from .app.adapters.httpx_wiki_page_api import HttpxWikiPageApi

# AuthenticationError: no longer referenced directly in this module (its only use was
# inside _raise_for_status, now delegated to app.transport.errors.raise_for_status),
# but re-exported deliberately -- existing callers/tests import it from here (e.g.
# `from openproject_ce_mcp.client import AuthenticationError`) and must keep working.
from .app.errors import (
    AuthenticationError,  # noqa: F401
    InvalidInputError,
    NotFoundError,
    OpenProjectError,
    OpenProjectServerError,
    PermissionDeniedError,
    TransportError,
)
from .app.pagination import paginate_client as _paginate_client
from .app.pagination import paginate_server as _paginate_server
from .app.policies import access as _access_policy
from .app.policies import hidden_fields as _hidden_fields_policy
from .app.policies import scope as _scope_policy
from .app.policies import sprint_policy as _sprint_policy
from .app.ports.action_capability_api import ActionCapabilityApi
from .app.ports.board_api import BoardApi
from .app.ports.category_api import CategoryApi
from .app.ports.document_api import DocumentApi
from .app.ports.grid_api import GridApi
from .app.ports.membership_api import MembershipApi
from .app.ports.news_api import NewsApi
from .app.ports.project_api import ProjectApi
from .app.ports.project_resolution import ProjectResolutionContext, WorkPackageResolutionContext
from .app.ports.sprint_api import SprintApi
from .app.ports.version_api import VersionApi
from .app.ports.view_api import ViewApi
from .app.ports.wiki_page_api import WikiPageApi
from .app.resolvers.project_resolver import ProjectResolver
from .app.resolvers.version_resolver import VersionResolver
from .app.services.action_capability_service import ActionCapabilityService
from .app.services.board_service import BoardService
from .app.services.category_service import CategoryService
from .app.services.document_service import DocumentService
from .app.services.grid_service import GridService
from .app.services.membership_service import MembershipService
from .app.services.news_service import NewsService
from .app.services.project_service import CLEAR_PARENT as _PROJECT_CLEAR_PARENT
from .app.services.project_service import ProjectAdminService, ProjectService
from .app.services.sprint_service import SprintService
from .app.services.version_service import VersionService
from .app.services.view_service import ViewService
from .app.services.wiki_page_service import WikiPageService
from .app.transport.errors import raise_for_status as _map_status_to_error
from .app.transport.httpx_transport import HttpxTransport
from .config import Settings
from .hal import normalize_links
from .models import (
    ActionListResult,
    ActivityListResult,
    ActivitySummary,
    ActivityWriteResult,
    AttachmentListResult,
    AttachmentSummary,
    AttachmentWriteResult,
    BatchWorkPackageReadItemResult,
    BatchWorkPackageReadResult,
    BoardDetail,
    BoardListResult,
    BoardSummary,
    BoardWriteResult,
    BulkWorkPackageItemResult,
    BulkWorkPackageWriteResult,
    CapabilityListResult,
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
    EmojiReactionWriteResult,
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
    NotificationMarkResult,
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
    ProjectDetail,
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
    SortCriterion,
    SprintDetail,
    SprintListResult,
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

# Array truncation limits for work package hierarchy and activity details
WORK_PACKAGE_CHILDREN_LIMIT = 50
WORK_PACKAGE_ANCESTORS_LIMIT = 20
PROJECT_ANCESTORS_LIMIT = 20
ACTIVITY_DETAILS_LIMIT = 20
BATCH_READ_MAX_IDS = 100

# Sentinel for update_work_package: distinguishes "clear the parent" (make the work
# package top-level via _links.parent = {"href": null}) from "leave unchanged" (None).
# A dedicated object avoids colliding with numeric ids or the _resolve_work_package_id
# path, and cannot be confused with any valid parent reference.
CLEAR_PARENT = object()

# Sentinel for create/update_work_package: distinguishes "clear the version"
# (unassign via _links.version = {"href": null}) from "leave unchanged" (None). Same
# rationale as CLEAR_PARENT — it must bypass version-name resolution.
CLEAR_VERSION = object()

# Generic "clear this field" sentinel, shared by both nullable HAL-link fields
# (assignee, responsible, category, project_phase on work packages; parent on
# projects — unassigned via _links.<field> = {"href": null}) and plain scalar
# fields (estimated_time, remaining_time, duration — cleared via <field>: null
# directly in the payload). Distinguishes "clear this field" from "leave
# unchanged" (None). parent/version keep their own sentinels above for
# historical reasons; every other clearable field shares this one.
CLEAR = object()

# Type variables for the generic write-finalizer (_finalize_write).
DetailT = TypeVar("DetailT")
ResultT = TypeVar("ResultT")

_NarrowT = TypeVar("_NarrowT")
_FetchT = TypeVar("_FetchT")


def _narrow_cleared(value: _NarrowT | object, *, sentinel: object = None) -> _NarrowT:
    """Narrow a value after the caller has already ruled out None and a clear sentinel.

    mypy cannot narrow a sentinel `object()` instance (CLEAR/CLEAR_VERSION/
    CLEAR_PARENT) out of a wider union via `is not sentinel`/`is not None` checks —
    from its static perspective the value's type is unchanged afterward, forcing a
    bare `cast()` at each call site. This re-asserts the same invariant at the point
    of use instead: a no-op if the caller's guard was correct (the common case), but
    it fails loudly with a clear message if a future refactor ever removes or
    reorders that guard, instead of silently forwarding the sentinel object into a
    resolver several calls downstream, where it would surface as a confusing
    'AttributeError' with no indication of the real cause.
    """
    if value is None or value is sentinel:
        raise AssertionError(f"_narrow_cleared: expected a resolved value, got the clear sentinel or None: {value!r}")
    return cast(_NarrowT, value)


class OpenProjectClient:
    """Small OpenProject API client with optional guarded write support."""

    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings
        self._origin = _origin_from_url(settings.base_url)
        self._api_prefix = urlparse(settings.api_base_url).path.rstrip("/") + "/"
        self._project_id_to_identifier: dict[int, str] = {}

        # Wrap transport with retry logic if max_retries > 0
        if settings.max_retries > 0:
            from .retry_transport import RetryTransport

            # Don't double-wrap if user already provided RetryTransport
            if not isinstance(transport, RetryTransport):
                # If no transport provided, use default httpx transport
                base_transport = transport or httpx.AsyncHTTPTransport()
                transport = RetryTransport(
                    wrapped_transport=base_transport,
                    max_retries=settings.max_retries,
                    base_delay=settings.retry_base_delay,
                    max_delay=settings.retry_max_delay,
                )

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

        # ADR 0001: HttpxTransport wraps the SAME httpx.AsyncClient
        # constructed above (one connection pool, not two).
        self._project_api: ProjectApi = HttpxProjectApi(
            HttpxTransport(self._http), base_url=settings.base_url, api_prefix=self._api_prefix
        )
        self._project_resolver = ProjectResolver(
            api=self._project_api, settings=settings, project_id_to_identifier=self._project_id_to_identifier
        )
        self._project_service = ProjectService(
            api=self._project_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
            resolver=self._project_resolver,
            base_url=settings.base_url,
            api_prefix=self._api_prefix,
        )
        self._project_admin_service = ProjectAdminService(
            api=self._project_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
            resolver=self._project_resolver,
            base_url=settings.base_url,
        )

        self._version_api: VersionApi = HttpxVersionApi(HttpxTransport(self._http), base_url=settings.base_url)
        self._version_service = VersionService(
            api=self._version_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
            resolve_project_ref=self._get_project_payload,
            api_prefix=self._api_prefix,
        )
        # self._project_id_to_identifier is the same live dict object threaded into
        # VersionService/VersionResolver -- initialize() (below) mutates it in place
        # *after* __init__ runs, so both must see the populated cache without being
        # reconstructed. dict(self._project_id_to_identifier) here would silently
        # break allowlist-identifier recovery for Versions.
        self._version_resolver = VersionResolver(
            api=self._version_api,
            resolve_project_ref=self._get_project_payload,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
        )

        self._membership_api: MembershipApi = HttpxMembershipApi(
            HttpxTransport(self._http), base_url=settings.base_url, api_prefix=self._api_prefix
        )
        self._membership_service = MembershipService(
            api=self._membership_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
            resolve_project_ref=self._get_project_payload,
            resolve_principal_ref=self._resolve_principal_id,
            list_roles=self.list_roles,
            api_prefix=self._api_prefix,
        )

        self._news_api: NewsApi = HttpxNewsApi(HttpxTransport(self._http), base_url=settings.base_url)
        self._news_service = NewsService(
            api=self._news_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
            resolve_project_ref=self._get_project_payload,
        )

        self._document_api: DocumentApi = HttpxDocumentApi(HttpxTransport(self._http), base_url=settings.base_url)
        self._document_service = DocumentService(
            api=self._document_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
            resolve_project_ref=self._get_project_payload,
        )

        self._wiki_page_api: WikiPageApi = HttpxWikiPageApi(HttpxTransport(self._http), base_url=settings.base_url)
        self._wiki_page_service = WikiPageService(
            api=self._wiki_page_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
        )

        self._category_api: CategoryApi = HttpxCategoryApi(HttpxTransport(self._http), base_url=settings.base_url)
        self._category_service = CategoryService(
            api=self._category_api,
            settings=settings,
            resolve_project_ref=self._get_project_payload,
        )

        self._view_api: ViewApi = HttpxViewApi(HttpxTransport(self._http), base_url=settings.base_url)
        self._view_service = ViewService(
            api=self._view_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
            resolve_project_ref=self._get_project_payload,
        )

        self._sprint_api: SprintApi = HttpxSprintApi(HttpxTransport(self._http), base_url=settings.base_url)
        self._sprint_service = SprintService(
            api=self._sprint_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
            resolve_project_ref=self._get_project_payload,
        )

        self._grid_api: GridApi = HttpxGridApi(HttpxTransport(self._http), api_prefix=self._api_prefix)
        self._grid_service = GridService(
            api=self._grid_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
        )

        self._board_api: BoardApi = HttpxBoardApi(HttpxTransport(self._http), base_url=settings.base_url)
        self._board_service = BoardService(
            api=self._board_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
            resolve_project_ref=self._get_project_payload,
            api_prefix=self._api_prefix,
            origin=self._origin,
        )

        self._action_capability_api: ActionCapabilityApi = HttpxActionCapabilityApi(
            HttpxTransport(self._http), base_url=settings.base_url
        )
        self._action_capability_service = ActionCapabilityService(
            api=self._action_capability_api,
            settings=settings,
            resolve_project_ref=self._get_project_payload,
        )

    async def initialize(self) -> None:
        # _project_id_to_identifier is consulted for BOTH read and write link-based
        # allowlist matching (see _project_candidates), so population must not skip
        # just because read_projects is wide-open — a wide-open read scope combined
        # with a restricted write_projects (e.g. READ="*", WRITE="OPM") still needs
        # this cache, or write-side identifier matching on an embedded project link
        # silently fails to recognize a valid identifier candidate.
        read_scope = self.settings.read_projects
        write_scope = self.settings.write_projects
        read_needs_lookup = bool(read_scope) and not _scope_allows_all(read_scope)
        write_needs_lookup = bool(write_scope) and not _scope_allows_all(write_scope)
        if not read_needs_lookup and not write_needs_lookup:
            return
        try:
            payload = await self._get("projects", params={"pageSize": "500"})
            for item in payload.get("_embedded", {}).get("elements", []):
                project_id = item.get("id")
                project_identifier = item.get("identifier")
                project_name = item.get("name") or ""
                if not isinstance(project_id, int) or not isinstance(project_identifier, str):
                    continue
                candidates: set[str] = {
                    project_identifier.casefold(),
                    str(project_id),
                    project_name.casefold(),
                    project_name.casefold().replace(" ", "-"),
                }
                if (read_needs_lookup and _scope_matches_candidates(read_scope, candidates)) or (
                    write_needs_lookup and _scope_matches_candidates(write_scope, candidates)
                ):
                    self._project_id_to_identifier[project_id] = project_identifier
        except OpenProjectError as exc:
            LOGGER.warning(
                "initialize: failed to fetch the project list for identifier-cache "
                "population; identifier-based allowlist matching may reject valid "
                "projects until the server is restarted and initialization succeeds: %s",
                exc,
            )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def list_projects(
        self,
        *,
        search: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> ProjectListResult:
        return await self._project_service.list(search=search, offset=offset, limit=limit)

    async def get_project(self, project_ref: str, *, text_limit: int | None = None) -> ProjectDetail:
        return await self._project_service.get(project_ref, text_limit=text_limit)

    async def get_project_admin_context(self, project_ref: str) -> ProjectAdminContext:
        return await self._project_admin_service.get_admin_context(project_ref)

    async def get_project_configuration(self, project_ref: str) -> ProjectConfiguration:
        return await self._project_service.get_configuration(project_ref)

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
        parent: str | object | None = None,
        confirm: bool = False,
    ) -> ProjectWriteResult:
        return await self._project_service.create(
            name=name,
            identifier=identifier,
            description=description,
            public=public,
            active=active,
            status=status,
            status_explanation=status_explanation,
            parent=_PROJECT_CLEAR_PARENT if parent is CLEAR else parent,
            confirm=confirm,
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
        parent: str | object | None = None,
        confirm: bool = False,
    ) -> ProjectWriteResult:
        return await self._project_service.update(
            project_ref=project_ref,
            name=name,
            identifier=identifier,
            description=description,
            public=public,
            active=active,
            status=status,
            status_explanation=status_explanation,
            parent=_PROJECT_CLEAR_PARENT if parent is CLEAR else parent,
            confirm=confirm,
        )

    async def delete_project(
        self,
        *,
        project_ref: str,
        confirm: bool = False,
    ) -> ProjectWriteResult:
        return await self._project_service.delete(project_ref=project_ref, confirm=confirm)

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
        parent: str | object | None = None,
        confirm: bool = False,
    ) -> ProjectCopyResult:
        return await self._project_service.copy(
            source_project=source_project,
            name=name,
            identifier=identifier,
            description=description,
            public=public,
            active=active,
            status=status,
            status_explanation=status_explanation,
            parent=_PROJECT_CLEAR_PARENT if parent is CLEAR else parent,
            confirm=confirm,
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
        self._ensure_read_enabled("admin")
        return await self._list_principals_unchecked(search=search, offset=offset, limit=limit)

    async def _list_principals_unchecked(
        self,
        *,
        search: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> PrincipalListResult:
        # No _ensure_read_enabled("admin") gate here by design: this is also used
        # internally by _resolve_principal_id to turn a name into an id for
        # operations the caller has already been authorized for through that
        # operation's own scope check (e.g. membership/work-package write) — it
        # never returns instance-wide PII to the agent, only a single resolved
        # id. Only the public list_principals tool, which does surface the full
        # PrincipalSummary list (name/login/email/status) to the agent, is
        # gated behind OPENPROJECT_ENABLE_ADMIN_READ.
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
        next_offset, truncated = _paginate_server(offset=offset, limit=effective_limit, total=total)
        return PrincipalListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(results),
            next_offset=next_offset,
            truncated=truncated,
            results=results,
        )

    async def list_users(
        self,
        *,
        search: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> UserListResult:
        self._ensure_read_enabled("admin")
        effective_limit = self._resolve_limit(limit)

        if search is not None:
            # No server-side name/login/email filter exists for /users, so over-fetch
            # up to settings.max_results in one request and paginate the filtered
            # survivors in memory instead of trusting the server's pre-filter total
            # (same pattern as list_versions' project-scoped-with-search branch).
            def post_filter(results: list[UserSummary]) -> list[UserSummary]:
                search_key = search.casefold()
                return [
                    item
                    for item in results
                    if search_key in (item.name or "").casefold()
                    or search_key in (item.login or "").casefold()
                    or search_key in (item.email or "").casefold()
                ]

            page, total, next_offset, truncated = await self._fetch_bounded_and_paginate(
                path="users",
                params_extra=None,
                normalize=self.normalize_user,
                item_allowed=None,
                post_filter=post_filter,
                offset=offset,
                limit=effective_limit,
            )
            return UserListResult(
                offset=offset,
                limit=effective_limit,
                total=total,
                count=len(page),
                next_offset=next_offset,
                truncated=truncated,
                results=page,
            )

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
        total = int(payload.get("total", len(results)))
        next_offset, truncated = _paginate_server(offset=offset, limit=effective_limit, total=total)
        return UserListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(results),
            next_offset=next_offset,
            truncated=truncated,
            results=results,
        )

    async def get_user(self, user_ref: str) -> UserDetail:
        self._ensure_read_enabled("admin")
        payload = await self._get(f"users/{quote(user_ref, safe='')}")
        return self.normalize_user_detail(payload)

    async def list_groups(
        self,
        *,
        search: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> GroupListResult:
        self._ensure_read_enabled("admin")
        effective_limit = self._resolve_limit(limit)

        if search is not None:
            # Same over-fetch-then-filter-then-paginate pattern as list_users above.
            def post_filter(results: list[GroupSummary]) -> list[GroupSummary]:
                search_key = search.casefold()
                return [item for item in results if search_key in (item.name or "").casefold()]

            page, total, next_offset, truncated = await self._fetch_bounded_and_paginate(
                path="groups",
                params_extra=None,
                normalize=self.normalize_group,
                item_allowed=None,
                post_filter=post_filter,
                offset=offset,
                limit=effective_limit,
            )
            return GroupListResult(
                offset=offset,
                limit=effective_limit,
                total=total,
                count=len(page),
                next_offset=next_offset,
                truncated=truncated,
                results=page,
            )

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
        total = int(payload.get("total", len(results)))
        next_offset, truncated = _paginate_server(offset=offset, limit=effective_limit, total=total)
        return GroupListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(results),
            next_offset=next_offset,
            truncated=truncated,
            results=results,
        )

    async def get_group(self, group_id: int) -> GroupDetail:
        self._ensure_read_enabled("admin")
        payload = await self._get(f"groups/{group_id}")
        return self.normalize_group_detail(payload)

    async def list_actions(
        self,
        *,
        offset: int = 1,
        limit: int | None = None,
    ) -> ActionListResult:
        return await self._action_capability_service.list_actions(offset=offset, limit=limit)

    async def list_capabilities(
        self,
        *,
        project: str | None = None,
        capability_id: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> CapabilityListResult:
        return await self._action_capability_service.list_capabilities(
            project=project, capability_id=capability_id, offset=offset, limit=limit
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

    async def list_project_memberships(
        self, project_ref: str, *, offset: int = 1, limit: int | None = None
    ) -> MembershipListResult:
        return await self._membership_service.list_for_project(project_ref, offset=offset, limit=limit)

    async def get_membership(self, membership_id: int) -> MembershipSummary:
        return await self._membership_service.get(membership_id)

    async def create_membership(
        self,
        *,
        project: str,
        principal: str,
        roles: list[str],
        notification_message: str | None = None,
        confirm: bool = False,
    ) -> MembershipWriteResult:
        return await self._membership_service.create(
            project=project,
            principal=principal,
            roles=roles,
            notification_message=notification_message,
            confirm=confirm,
        )

    async def update_membership(
        self,
        *,
        membership_id: int,
        roles: list[str],
        notification_message: str | None = None,
        confirm: bool = False,
    ) -> MembershipWriteResult:
        return await self._membership_service.update(
            membership_id=membership_id, roles=roles, notification_message=notification_message, confirm=confirm
        )

    async def delete_membership(
        self,
        *,
        membership_id: int,
        confirm: bool = False,
    ) -> MembershipWriteResult:
        return await self._membership_service.delete(membership_id=membership_id, confirm=confirm)

    async def get_my_project_access(self, project_ref: str) -> ProjectAccessSummary:
        self._ensure_read_enabled("project")
        self._ensure_read_enabled("membership")
        self._ensure_read_enabled("principal")
        current_user = await self.get_current_user()
        project_payload = await self._resolve_project_ref(project_ref, write=False)
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
        return await self._project_service.list_phase_definitions()

    async def get_project_phase_definition(self, phase_definition_id: int) -> ProjectPhaseDefinition:
        return await self._project_service.get_phase_definition(phase_definition_id)

    async def get_project_phase(self, phase_id: int) -> ProjectPhase:
        return await self._project_service.get_phase(phase_id)

    async def _fetch_bounded_and_paginate(
        self,
        *,
        path: str,
        params_extra: dict[str, str] | None,
        normalize: Callable[[dict[str, Any]], _FetchT],
        item_allowed: Callable[[dict[str, Any]], Awaitable[bool]] | None,
        post_filter: Callable[[list[_FetchT]], list[_FetchT]] | None,
        offset: int,
        limit: int,
    ) -> tuple[list[_FetchT], int, int | None, bool]:
        """Fetch one bounded page (pageSize=settings.max_results), normalize + filter
        the raw elements, apply an optional post-normalize filter (e.g. project/
        search predicates), then paginate the survivors in memory via
        _paginate_client. Shared by every list method that must over-fetch and
        filter client-side (allowlist/search) rather than trust server-side
        paging, so a restrictive filter can't produce a sparse page. Any
        NotFoundError re-wrap (sprints/project_sprints) stays at the call site,
        not here.

        item_allowed is async (rather than plain bool) so ACL checks that need
        their own lookups (e.g. relations checking each linked work package's
        project) can use this helper too -- without it, callers needing an
        async filter had to hand-roll their own fetch+params, which is exactly
        how a prior pageSize-omission bug happened.
        """
        params = {"offset": "1", "pageSize": str(self.settings.max_results)}
        if params_extra:
            params.update(params_extra)
        payload = await self._get(path, params=params)
        results = []
        for item in payload.get("_embedded", {}).get("elements", []):
            if isinstance(item, dict) and (item_allowed is None or await item_allowed(item)):
                results.append(normalize(item))
        if post_filter is not None:
            results = post_filter(results)
        return _paginate_client(offset=offset, limit=limit, results=results)

    async def list_views(
        self,
        *,
        project: str | None = None,
        view_type: str | None = None,
        search: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> ViewListResult:
        return await self._view_service.list(
            project=project, view_type=view_type, search=search, offset=offset, limit=limit
        )

    async def get_view(self, view_id: int) -> ViewDetail:
        return await self._view_service.get(view_id)

    async def list_documents(
        self,
        *,
        project: str | None = None,
        search: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> DocumentListResult:
        return await self._document_service.list(project=project, search=search, offset=offset, limit=limit)

    async def get_document(self, document_id: int) -> DocumentDetail:
        return await self._document_service.get(document_id)

    async def update_document(
        self,
        *,
        document_id: int,
        title: str | None = None,
        description: str | None = None,
        confirm: bool = False,
    ) -> DocumentWriteResult:
        return await self._document_service.update(
            document_id=document_id, title=title, description=description, confirm=confirm
        )

    async def list_news(
        self,
        *,
        project: str | None = None,
        search: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> NewsListResult:
        return await self._news_service.list(project=project, search=search, offset=offset, limit=limit)

    async def get_news(self, news_id: int) -> NewsDetail:
        return await self._news_service.get(news_id)

    async def create_news(
        self,
        *,
        project: str,
        title: str,
        summary: str | None = None,
        description: str | None = None,
        confirm: bool = False,
    ) -> NewsWriteResult:
        return await self._news_service.create(
            project=project, title=title, summary=summary, description=description, confirm=confirm
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
        return await self._news_service.update(
            news_id=news_id, title=title, summary=summary, description=description, confirm=confirm
        )

    async def delete_news(
        self,
        *,
        news_id: int,
        confirm: bool = False,
    ) -> NewsWriteResult:
        return await self._news_service.delete(news_id=news_id, confirm=confirm)

    async def get_wiki_page(self, wiki_page_id: int) -> WikiPageDetail:
        return await self._wiki_page_service.get(wiki_page_id)

    async def list_categories(self, project_ref: str) -> CategoryListResult:
        return await self._category_service.list(project_ref)

    async def get_category(self, *, project_ref: str, category_id: int) -> CategorySummary:
        return await self._category_service.get(project_ref=project_ref, category_id=category_id)

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
        if not confirm:
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
        return await self._finalize_delete(
            result_cls=AttachmentWriteResult,
            confirm=confirm,
            result_kwargs={
                "attachment_id": attachment.id,
                "work_package_id": work_package_id,
                "payload": preview_payload,
            },
            preview_result=attachment,
            commit_result=None,
            write_scope="work_package",
            delete_path=f"attachments/{attachment_id}",
            preview_message="OpenProject found the attachment. Ask for confirmation, then call again with confirm=true to delete it.",
            success_message="Attachment deleted successfully.",
        )

    async def list_time_entry_activities(self) -> TimeEntryActivityListResult:
        self._ensure_read_enabled("work_package")
        fallback_errors = (NotFoundError, PermissionDeniedError, OpenProjectServerError)
        # Try the global endpoint first; fall back to a project-scoped form if it is not available.
        try:
            payload = await self._get("time_entries/activities")
            elements = payload.get("_embedded", {}).get("elements", [])
            results = [self.normalize_time_entry_activity(item) for item in elements if isinstance(item, dict)]
            if results:
                return TimeEntryActivityListResult(count=len(results), results=results)
        except fallback_errors:
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
                    except fallback_errors:
                        continue
                    if results:
                        return TimeEntryActivityListResult(count=len(results), results=results)
                if projects.next_offset is None:
                    break
                offset = projects.next_offset
            return TimeEntryActivityListResult(count=0, results=[])
        except fallback_errors:
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

        async def item_allowed(item: dict[str, Any]) -> bool:
            return self._time_entry_payload_allowed(item) and (
                not project_candidates
                or self._link_matches_project_refs(item.get("_links", {}).get("project"), project_candidates)
            )

        def post_filter(results: list[TimeEntrySummary]) -> list[TimeEntrySummary]:
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
            return results

        page, total, next_offset, truncated = await self._fetch_bounded_and_paginate(
            path="time_entries",
            params_extra=None,
            normalize=lambda item: self.normalize_time_entry(item, text_limit=self.settings.text_limit),
            item_allowed=item_allowed,
            post_filter=post_filter,
            offset=offset,
            limit=effective_limit,
        )
        return TimeEntryListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(page),
            next_offset=next_offset,
            truncated=truncated,
            results=page,
        )

    async def get_time_entry(self, time_entry_id: int, *, text_limit: int | None = None) -> TimeEntrySummary:
        # Default (text_limit=None) returns the full comment uncapped, like
        # get_work_package: opening a single time entry means you want to read it.
        self._ensure_read_enabled("work_package")
        payload = await self._get(f"time_entries/{time_entry_id}")
        project_link = payload.get("_links", {}).get("project")
        self._ensure_project_link_allowed(project_link)
        return self.normalize_time_entry(payload, text_limit=text_limit)

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
        if not confirm:
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
        if not confirm:
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
        return await self._finalize_delete(
            result_cls=TimeEntryWriteResult,
            confirm=confirm,
            result_kwargs={"time_entry_id": detail.id, "project": detail.project, "payload": payload},
            preview_result=detail,
            commit_result=None,
            write_scope="work_package",
            delete_path=f"time_entries/{time_entry_id}",
            preview_message="OpenProject found the time entry. Ask for confirmation, then call again with confirm=true to delete it.",
            success_message="Time entry deleted successfully.",
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
        project_payload = await self._resolve_project_ref(project, write=False)
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
            # These four fields' allowed_values were just hoisted into the
            # available_* lists above — clear them here so the same option
            # enumeration isn't serialized twice in one response.
            hoisted_keys = {"status", "priority", "category", "projectPhase"}
            fields = [
                replace(field, allowed_values=[]) if field.key in hoisted_keys and field.allowed_values else field
                for field in fields
            ]

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
        search: str,
        project: str | None = None,
        status: str | None = None,
        open_only: bool = False,
        assignee_me: bool = False,
        assignee: str | None = None,
        priority: str | None = None,
        created_on: str | None = None,
        created_between: list[str] | None = None,
        updated_on: str | None = None,
        updated_between: list[str] | None = None,
        due_on: str | None = None,
        due_between: list[str] | None = None,
        sort_by: list[SortCriterion] | None = None,
        group_by: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> WorkPackageListResult:
        self._ensure_read_enabled("work_package")
        effective_limit = self._resolve_limit(limit)
        if not self.settings.read_projects:
            return self._empty_work_package_list_result(offset=offset, limit=effective_limit)
        filters: list[dict[str, Any]] = [{"subject_or_id": {"operator": "**", "values": [search]}}]
        project_id: int | None = None
        total_is_scope_safe = _scope_allows_all(self.settings.read_projects)
        if project is not None:
            project_payload = await self._get_project_payload(project)
            project_id = int(project_payload["id"])
            filters.append({"project_id": {"operator": "=", "values": [str(project_id)]}})
            total_is_scope_safe = True
        if status:
            status_id = await self._resolve_status_id(status)
            filters.append({"status_id": {"operator": "=", "values": [status_id]}})
        if open_only:
            filters.append({"status_id": {"operator": "o", "values": []}})
        if assignee_me:
            current_user = await self.get_current_user()
            filters.append({"assigned_to_id": {"operator": "=", "values": [str(current_user.id)]}})

        # Extended filters (same as list_work_packages)
        if assignee and not assignee_me:
            assignee_id = await self._resolve_principal_id(assignee)
            filters.append({"assigned_to_id": {"operator": "=", "values": [assignee_id]}})

        if priority:
            priority_id = await self._resolve_priority_id(priority)
            filters.append({"priority_id": {"operator": "=", "values": [priority_id]}})

        self._apply_work_package_date_filters(
            filters,
            created_on=created_on,
            created_between=created_between,
            updated_on=updated_on,
            updated_between=updated_between,
            due_on=due_on,
            due_between=due_between,
        )

        return await self._list_work_package_collection(
            project_id=project_id,
            filters=filters,
            offset=offset,
            limit=effective_limit,
            sort_by=sort_by,
            group_by=group_by,
            total_is_scope_safe=total_is_scope_safe,
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
        assignee: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        created_on: str | None = None,
        created_between: list[str] | None = None,
        updated_on: str | None = None,
        updated_between: list[str] | None = None,
        due_on: str | None = None,
        due_between: list[str] | None = None,
        sort_by: list[SortCriterion] | None = None,
        group_by: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> WorkPackageListResult:
        self._ensure_read_enabled("work_package")
        effective_limit = self._resolve_limit(limit)
        if not self.settings.read_projects:
            return self._empty_work_package_list_result(offset=offset, limit=effective_limit)
        filters: list[dict[str, Any]] = []
        project_id: int | None = None
        # Bounded to this single call: avoids re-fetching/re-checking the same
        # project when both type and version filters are given alongside project.
        resolution_context = ProjectResolutionContext(self._resolve_project_ref)
        total_is_scope_safe = _scope_allows_all(self.settings.read_projects)
        if project is not None:
            project_payload = await self._get_project_payload(project, context=resolution_context)
            project_id = int(project_payload["id"])
            filters.append({"project_id": {"operator": "=", "values": [str(project_id)]}})
            total_is_scope_safe = True
        elif not total_is_scope_safe:
            # No explicit project given but read scope is restricted — add a server-side
            # project filter so the API only returns WPs from the allowed projects. This
            # cache can still be empty (e.g. every allowed project was created after
            # initialize()'s one-time startup snapshot and no confirmed write has
            # refreshed it since — see ProjectService._remember_identifier). Sending an
            # unfiltered query in that case would silently leak an untrustworthy total
            # instead of failing loudly, so this fails closed with an explicit error
            # instead — consistent with every other project-link-scoped tool
            # (get_work_package/update_work_package/etc. all raise the same error for
            # the identical underlying condition, rather than silently narrowing to
            # nothing).
            allowed_ids = [str(pid) for pid in self._project_id_to_identifier]
            if not allowed_ids:
                raise PermissionDeniedError(
                    "OpenProject access to this project is disabled by OPENPROJECT_READ_PROJECTS."
                )
            filters.append({"project_id": {"operator": "=", "values": allowed_ids}})
            total_is_scope_safe = True
        if open_only:
            filters.append({"status_id": {"operator": "o", "values": []}})
        if assignee_me:
            current_user = await self.get_current_user()
            filters.append({"assigned_to_id": {"operator": "=", "values": [str(current_user.id)]}})
        if type:
            type_id = await self._resolve_type_id(type, project=project, context=resolution_context)
            # Use official filter key per source (type_filter.rb:def self.key → :type_id)
            # PropertyNameConverter tolerates "type" but may break in future versions
            filters.append({"type_id": {"operator": "=", "values": [type_id]}})
        if version:
            version_id = await self._resolve_version_id(version, project=project, context=resolution_context)
            # Use official filter key per source (version_filter.rb:def self.key → :version_id)
            # PropertyNameConverter tolerates "version" but may break in future versions
            filters.append({"version_id": {"operator": "=", "values": [version_id]}})
        if version_status:
            # Filter by the status of a work package's assigned version. The
            # version filter supports operators o/c/l for open/closed/locked
            # (custom operators in VersionFilter beyond base :list_optional strategy).
            status_operator = {"open": "o", "closed": "c", "locked": "l"}[version_status]
            # Use official filter key per source (version_filter.rb:def self.key → :version_id)
            filters.append({"version_id": {"operator": status_operator, "values": []}})

        # Extended filters
        # assignee_me takes precedence for backward compatibility
        if assignee and not assignee_me:
            assignee_id = await self._resolve_principal_id(assignee)
            filters.append({"assigned_to_id": {"operator": "=", "values": [assignee_id]}})

        if status:
            status_id = await self._resolve_status_id(status)
            filters.append({"status_id": {"operator": "=", "values": [status_id]}})

        if priority:
            priority_id = await self._resolve_priority_id(priority)
            filters.append({"priority_id": {"operator": "=", "values": [priority_id]}})

        self._apply_work_package_date_filters(
            filters,
            created_on=created_on,
            created_between=created_between,
            updated_on=updated_on,
            updated_between=updated_between,
            due_on=due_on,
            due_between=due_between,
        )

        return await self._list_work_package_collection(
            project_id=project_id,
            filters=filters,
            offset=offset,
            limit=effective_limit,
            sort_by=sort_by,
            group_by=group_by,
            total_is_scope_safe=total_is_scope_safe,
        )

    def _empty_work_package_list_result(self, *, offset: int, limit: int) -> WorkPackageListResult:
        return WorkPackageListResult(
            offset=offset,
            limit=limit,
            total=0,
            count=0,
            next_offset=None,
            truncated=False,
            results=[],
        )

    def _work_package_collection_page(
        self,
        *,
        offset: int,
        limit: int,
        total_is_scope_safe: bool,
        server_total: int,
        raw_elements: list[dict[str, Any]],
        raw_items: list[dict[str, Any]],
        results: list[WorkPackageSummary],
    ) -> tuple[int, int | None, bool]:
        """Shared total/next_offset/truncated derivation for the two work-package
        collection endpoints (_list_work_package_collection,
        list_my_open_work_packages). The server total is only safe to expose
        when the query itself was provably restricted to the allowed scope
        server-side (total_is_scope_safe) -- a clean current page is NOT
        sufficient on its own, since a later page could still contain
        disallowed-project matches that the total would otherwise leak the
        existence of. The per-page equality check stays as defense in depth
        against a scoped query somehow still returning a disallowed item.
        """
        total_trustworthy = total_is_scope_safe and len(raw_items) == len(raw_elements)
        if total_trustworthy:
            next_offset, truncated = _paginate_server(offset=offset, limit=limit, total=server_total)
            return server_total, next_offset, truncated
        # Pagination hints must not be derived from the untrustworthy server
        # total either -- that would leak the existence of disallowed-project
        # matches just as much as exposing the total itself. "Is there more to
        # page through" is instead based purely on whether this raw server
        # page came back full, which reveals nothing beyond what any paginated
        # API already implies.
        total = len(results)
        next_offset = (offset + 1) if len(raw_elements) == limit else None
        truncated = len(raw_elements) == limit
        return total, next_offset, truncated

    def _build_work_package_list_result(
        self,
        *,
        payload: dict[str, Any],
        offset: int,
        limit: int,
        total_is_scope_safe: bool,
    ) -> WorkPackageListResult:
        raw_elements = [item for item in payload.get("_embedded", {}).get("elements", []) if isinstance(item, dict)]
        raw_items = [item for item in raw_elements if self._work_package_payload_allowed(item)]
        results = [self.normalize_work_package_summary(item) for item in raw_items]
        server_total = int(payload.get("total", len(results)))
        total, next_offset, truncated = self._work_package_collection_page(
            offset=offset,
            limit=limit,
            total_is_scope_safe=total_is_scope_safe,
            server_total=server_total,
            raw_elements=raw_elements,
            raw_items=raw_items,
            results=results,
        )
        return WorkPackageListResult(
            offset=offset,
            limit=limit,
            total=total,
            count=len(results),
            next_offset=next_offset,
            truncated=truncated,
            results=results,
        )

    def _apply_work_package_date_filters(
        self,
        filters: list[dict[str, Any]],
        *,
        created_on: str | None,
        created_between: list[str] | None,
        updated_on: str | None,
        updated_between: list[str] | None,
        due_on: str | None,
        due_between: list[str] | None,
    ) -> None:
        # Mutual exclusivity: can't use both _on and _between for same field
        if created_on and created_between:
            raise InvalidInputError("Cannot specify both created_on and created_between")
        if updated_on and updated_between:
            raise InvalidInputError("Cannot specify both updated_on and updated_between")
        if due_on and due_between:
            raise InvalidInputError("Cannot specify both due_on and due_between")

        if created_on:
            validated_date = self._validate_date_format(created_on, "created_on")
            filters.append({"created_at": {"operator": "=d", "values": [validated_date]}})

        if created_between:
            validated_range = self._validate_date_range(created_between, "created_between")
            filters.append({"created_at": {"operator": "<>d", "values": validated_range}})

        if updated_on:
            validated_date = self._validate_date_format(updated_on, "updated_on")
            filters.append({"updated_at": {"operator": "=d", "values": [validated_date]}})

        if updated_between:
            validated_range = self._validate_date_range(updated_between, "updated_between")
            filters.append({"updated_at": {"operator": "<>d", "values": validated_range}})

        if due_on:
            validated_date = self._validate_date_format(due_on, "due_on")
            filters.append({"due_date": {"operator": "=d", "values": [validated_date]}})

        if due_between:
            validated_range = self._validate_date_range(due_between, "due_between")
            filters.append({"due_date": {"operator": "<>d", "values": validated_range}})

    async def _list_work_package_collection(
        self,
        *,
        project_id: int | None,
        filters: list[dict[str, Any]],
        offset: int,
        limit: int,
        sort_by: list[SortCriterion] | None = None,
        group_by: str | None = None,
        total_is_scope_safe: bool,
    ) -> WorkPackageListResult:
        if not self.settings.read_projects:
            # Defense-in-depth: both public callers already guard on this before
            # reaching here, but this must stay correct on its own for any future caller.
            return self._empty_work_package_list_result(offset=offset, limit=limit)
        params = {
            "offset": str(offset),
            "pageSize": str(limit),
            "filters": _json_param(filters),
        }

        # Add sortBy as JSON array if provided
        # Format: [["field", "direction"], ...] e.g. [["status", "desc"], ["priority", "asc"]]
        # sort_by is already validated and parsed to SortCriterion by tool layer
        if sort_by:
            sort_criteria = [[criterion.field, criterion.direction] for criterion in sort_by]
            params["sortBy"] = json.dumps(sort_criteria, separators=(",", ":"))

        # Add groupBy as simple field name string if provided
        # group_by is already validated and normalized by tool layer
        if group_by:
            params["groupBy"] = group_by

        payload = await self._get("work_packages", params=params)
        return self._build_work_package_list_result(
            payload=payload, offset=offset, limit=limit, total_is_scope_safe=total_is_scope_safe
        )

    async def get_work_package(self, work_package_id: int | str, *, text_limit: int | None = None) -> WorkPackageDetail:
        self._ensure_read_enabled("work_package")
        work_package_id = self._work_package_ref(work_package_id)
        payload = await self._get(f"work_packages/{work_package_id}")
        self._ensure_project_link_allowed(payload.get("_links", {}).get("project"))
        # Default (text_limit=None) returns the full description uncapped: opening
        # a single work package means you want to read/edit it, so nothing is cut.
        return self.normalize_work_package_detail(payload, text_limit=text_limit)

    async def get_work_packages(
        self,
        *,
        ids: list[int | str],
        text_limit: int | None = None,
    ) -> BatchWorkPackageReadResult:
        """Fetch multiple work packages in parallel.

        Args:
            ids: List of work package IDs (numeric or PROJ-123 format)
            text_limit: Optional description truncation limit

        Returns:
            BatchWorkPackageReadResult with per-item success/failure tracking

        Raises:
            ValueError: If ids list is empty or exceeds 100 items
        """
        # Validation and deduplication is done by tool layer
        if not ids:
            raise ValueError("ids list cannot be empty")
        if len(ids) > BATCH_READ_MAX_IDS:
            raise ValueError(
                f"Maximum {BATCH_READ_MAX_IDS} work packages per batch (got {len(ids)}). Split into multiple calls."
            )

        # Create parallel fetch tasks
        async def fetch_one(work_package_ref: int | str) -> tuple[int | str, WorkPackageDetail | None, str | None]:
            try:
                work_package = await self.get_work_package(work_package_ref, text_limit=text_limit)
                return (work_package_ref, work_package, None)
            except (OpenProjectError, InvalidInputError, httpx.HTTPError) as e:
                # Catch expected API errors, not system exceptions like CancelledError
                return (work_package_ref, None, str(e))

        # Execute in parallel
        results = await asyncio.gather(*[fetch_one(work_package_ref) for work_package_ref in ids])

        # Build result items
        items = []
        succeeded = 0
        failed = 0
        for input_id, work_package, error in results:
            if work_package is not None:
                succeeded += 1
                items.append(
                    BatchWorkPackageReadItemResult(
                        id=input_id,
                        success=True,
                        work_package=work_package,
                        error=None,
                    )
                )
            else:
                failed += 1
                items.append(
                    BatchWorkPackageReadItemResult(
                        id=input_id,
                        success=False,
                        work_package=None,
                        error=error,
                    )
                )

        # Build user-facing summary message
        if failed == 0:
            message = f"Successfully fetched all {succeeded} work packages."
        elif succeeded == 0:
            message = f"Failed to fetch all {failed} work packages."
        else:
            message = f"Fetched {succeeded} work packages successfully, {failed} failed."

        return BatchWorkPackageReadResult(
            action="batch_read",
            total=len(ids),
            succeeded=succeeded,
            failed=failed,
            message=message,
            results=items,
        )

    def _new_wp_context(self) -> WorkPackageResolutionContext:
        """Construct a fresh, per-call WorkPackageResolutionContext (never reused across calls; see ProjectResolutionContext's lifetime rule)."""
        return WorkPackageResolutionContext(ProjectResolutionContext(self._resolve_project_ref))

    async def create_work_package(
        self,
        *,
        project: str,
        type: str,
        subject: str,
        description: str | None = None,
        version: str | object | None = None,
        project_phase: str | object | None = None,
        assignee: str | object | None = None,
        responsible: str | object | None = None,
        priority: str | None = None,
        category: str | object | None = None,
        custom_fields: dict[str, Any] | None = None,
        parent_work_package_id: int | str | None = None,
        start_date: str | None = None,
        due_date: str | None = None,
        estimated_time: str | None = None,
        remaining_time: str | None = None,
        duration: str | None = None,
        confirm: bool = False,
        wp_context: WorkPackageResolutionContext | None = None,
    ) -> WorkPackageWriteResult:
        # When a caller shares a wp_context across a bulk batch, route this resolve
        # through its cache too -- items sharing the same project then only trigger
        # one real project fetch for the whole batch, not one per item. With no
        # wp_context (the default, single-call case) this is exactly the raw
        # self._resolve_project_ref(project, write=True) call, uncached.
        project_payload = await self._get_project_payload(
            project, write=True, context=wp_context.project_context if wp_context is not None else None
        )
        project_id = str(project_payload["id"])
        # Default: a fresh context per call. A bulk caller (bulk_create_work_packages)
        # passes one shared across all its items instead.
        if wp_context is None:
            wp_context = self._new_wp_context()
        # write=True already implies read=True passed (write checks read first),
        # so both keys are safe to seed from the same payload -- this is what lets
        # the type/version resolvers below reuse it instead of re-fetching.
        wp_context.project_context.seed(project_id, project_payload, write=True)
        wp_context.project_context.seed(project_id, project_payload, write=False)
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
            estimated_time=estimated_time,
            remaining_time=remaining_time,
            duration=duration,
            resolution_context=wp_context,
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
        project_phase: str | object | None = None,
        assignee: str | object | None = None,
        responsible: str | object | None = None,
        priority: str | None = None,
        category: str | object | None = None,
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

        wp_context = self._new_wp_context()
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
            resolution_context=wp_context,
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
        sprint: str | object | None = None,
        project_phase: str | object | None = None,
        status: str | None = None,
        assignee: str | object | None = None,
        responsible: str | object | None = None,
        priority: str | None = None,
        category: str | object | None = None,
        custom_fields: dict[str, Any] | None = None,
        parent_work_package_id: int | str | object | None = None,
        start_date: str | None = None,
        due_date: str | None = None,
        estimated_time: str | object | None = None,
        remaining_time: str | object | None = None,
        duration: str | object | None = None,
        percentage_done: int | None = None,
        confirm: bool = False,
        wp_context: WorkPackageResolutionContext | None = None,
    ) -> WorkPackageWriteResult:
        work_package_id = self._work_package_ref(work_package_id)
        if parent_work_package_id is not None and parent_work_package_id is not CLEAR_PARENT:
            # parent goes into a HAL link href, which resolves only by numeric id.
            # CLEAR_PARENT is a sentinel (un-parent) and must pass through unresolved.
            parent_work_package_id = await self._resolve_work_package_id(
                _narrow_cleared(parent_work_package_id, sentinel=CLEAR_PARENT)
            )
        current = await self._get(f"work_packages/{work_package_id}")
        project_id = _id_from_href(current.get("_links", {}).get("project", {}).get("href"))
        if project_id is None:
            raise OpenProjectServerError("OpenProject work package is missing a project link.")
        self._ensure_project_write_link_allowed(current.get("_links", {}).get("project"))

        # Default: a fresh context per call. A bulk caller (bulk_update_work_packages)
        # passes one shared across all its items instead.
        if wp_context is None:
            wp_context = self._new_wp_context()
        lock_version = current.get("lockVersion")
        payload = await self._build_write_payload(
            project=str(project_id),
            type=type,
            subject=subject,
            description=description,
            version=version,
            sprint=sprint,
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
            estimated_time=estimated_time,
            remaining_time=remaining_time,
            duration=duration,
            percentage_done=percentage_done,
            work_package_id=work_package_id,
            lock_version=lock_version,
            resolution_context=wp_context,
        )

        # Auto-derive percentageDone/remainingTime when the status is transitioning to a closed
        # status and the caller didn't already supply them explicitly. Only attempted when status
        # is actually changing, to avoid an extra lookup on every plain field update.
        want_auto_percentage = percentage_done is None
        want_auto_remaining = remaining_time is None
        auto_percentage: int | None = None
        auto_remaining: str | object | None = None
        if status is not None and (want_auto_percentage or want_auto_remaining):
            # Reuse the status id _build_write_payload already resolved for the status
            # link (avoids a redundant name->id lookup when status is given by name).
            status_id = _id_from_href(payload.get("_links", {}).get("status", {}).get("href"))
            # Deliberately not using get_status() here: it calls
            # _ensure_read_enabled("work_package"), which would incorrectly block this
            # purely internal lookup (and thus the whole status-changing write) on
            # instances that have work-package writes enabled but reads disabled.
            status_payload = await self._get(f"statuses/{status_id}")
            target_status = self.normalize_status(status_payload)
            if target_status.is_closed:
                auto_percentage = 100 if want_auto_percentage else None
                if want_auto_remaining:
                    # OpenProject's own validation requires the OPPOSITE target
                    # depending on whether an estimate exists: remainingTime must be
                    # exactly "PT0H" when estimatedTime is set, but must be null/absent
                    # when it isn't -- live-verified against real OpenProject (a bare
                    # "PT0H" gets rejected with "must stay empty" on an estimate-less
                    # work package). "Effective" estimate: this same call's own
                    # estimated_time if it set one, else the work package's existing
                    # value from the pre-write GET.
                    effective_estimated_time = (
                        payload.get("estimatedTime") if "estimatedTime" in payload else current.get("estimatedTime")
                    )
                    auto_remaining = "PT0H" if effective_estimated_time else CLEAR

        payload["lockVersion"] = lock_version
        form = await self._post(f"work_packages/{work_package_id}/form", json_body=payload)

        if auto_percentage is not None or auto_remaining is not None:
            schema = form.get("_embedded", {}).get("schema", {})
            changed = False
            if (
                auto_percentage is not None
                and schema.get("percentageDone", {}).get("writable") is True
                and not self._field_hidden("work_package", "percentage_done")
            ):
                payload["percentageDone"] = auto_percentage
                changed = True
            if (
                auto_remaining is not None
                and schema.get("remainingTime", {}).get("writable") is True
                and not self._field_hidden("work_package", "remaining_time")
            ):
                payload["remainingTime"] = None if auto_remaining is CLEAR else auto_remaining
                changed = True
            if changed:
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
        # Shared across every item in this bulk call (see WorkPackageResolutionContext):
        # items in the same project skip repeating the same project fetch and
        # type/version name->id lookups. Discarded once this call returns -- never
        # reused across separate bulk_create_work_packages calls.
        wp_context = self._new_wp_context()
        try:
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
                        estimated_time=item.get("estimated_time"),
                        remaining_time=item.get("remaining_time"),
                        duration=item.get("duration"),
                        confirm=confirm,
                        wp_context=wp_context,
                    )
                    item_results.append(_bulk_item_result(index=i, result=result))
                except Exception as exc:
                    item_results.append(BulkWorkPackageItemResult(index=i, success=False, error=str(exc), result=None))
        except asyncio.CancelledError:
            _log_bulk_cancellation(
                "bulk_create_work_packages", confirm=confirm, total=len(items), item_results=item_results
            )
            raise

        succeeded = sum(1 for r in item_results if r.success)
        failed = len(item_results) - succeeded
        requires_confirmation = not confirm and failed == 0
        message = _bulk_summary_message(
            confirm=confirm, succeeded=succeeded, failed=failed, total=len(items), verb="create", past_tense="created"
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
        # Shared across every item in this bulk call (see WorkPackageResolutionContext):
        # items in the same project skip repeating the same project fetch and
        # type/version name->id lookups. Discarded once this call returns -- never
        # reused across separate bulk_update_work_packages calls.
        wp_context = self._new_wp_context()
        try:
            for i, item in enumerate(items):
                try:
                    result = await self.update_work_package(
                        work_package_id=item["work_package_id"],
                        subject=item.get("subject"),
                        description=item.get("description"),
                        type=item.get("type"),
                        version=item.get("version"),
                        sprint=item.get("sprint"),
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
                        estimated_time=item.get("estimated_time"),
                        remaining_time=item.get("remaining_time"),
                        duration=item.get("duration"),
                        percentage_done=item.get("percentage_done"),
                        confirm=confirm,
                        wp_context=wp_context,
                    )
                    item_results.append(_bulk_item_result(index=i, result=result))
                except Exception as exc:
                    item_results.append(BulkWorkPackageItemResult(index=i, success=False, error=str(exc), result=None))
        except asyncio.CancelledError:
            _log_bulk_cancellation(
                "bulk_update_work_packages", confirm=confirm, total=len(items), item_results=item_results
            )
            raise

        succeeded = sum(1 for r in item_results if r.success)
        failed = len(item_results) - succeeded
        requires_confirmation = not confirm and failed == 0
        message = _bulk_summary_message(
            confirm=confirm, succeeded=succeeded, failed=failed, total=len(items), verb="update", past_tense="updated"
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

        if not confirm:
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
        activity = await self._fill_missing_activity_user(activity)
        # OpenProject can aggregate a new note into an existing, more recent
        # journal entry (e.g. a prior status change) instead of always creating
        # a fresh one. When that happens, this endpoint's response carries that
        # other journal entry's field-change `details` and `createdAt` alongside
        # the comment. There is no reliable signal to tell an aggregated
        # response from a fresh one, so both are suppressed unconditionally -
        # including for an ordinary, non-aggregated comment, which sacrifices
        # its own correct timestamp too. `comment`/`id` are unaffected by this
        # and still reflect the activities POST response.
        normalized_activity = self._replace_and_restamp(
            "activity",
            # Capped like every other write-echo (create/update_work_package's
            # description, etc.) -- the caller already has the comment it just
            # sent, so echoing it back uncapped costs tokens for no benefit.
            self.normalize_activity(activity, text_limit=FORMATTABLE_LIMIT),
            details=None,
            details_truncated=False,
            created_at=None,
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
            result=normalized_activity,
        )

    async def _fill_missing_activity_user(self, activity: dict[str, Any]) -> dict[str, Any]:
        """Best-effort: fill in a missing `_links.user` on a freshly-posted activity.

        The activities POST response can be leaner than a subsequent GET and
        omit `_links.user` entirely, even though the activity was persisted
        correctly. Re-fetches the canonical activity by id and merges in its
        `_links.user`. A failure here (404, permission, timeout, ...) must
        never turn an already-successful write into a reported error, so it
        is swallowed and just logged - the caller then simply keeps user
        unset. Only attempted when the response carries a usable id (a
        missing/unusable id is left to normalize_activity()'s existing
        requirement for one) and when `user` isn't configured hidden for
        activities anyway, since fetching it would just be discarded.
        """
        if self._field_hidden("activity", "user"):
            return activity
        activity_links = activity.get("_links", {})
        activity_id = activity.get("id")
        if _link_title(activity_links.get("user")) or not _is_usable_positive_id(activity_id):
            return activity
        try:
            fetched_activity = await self._get(f"activities/{activity_id}")
        except OpenProjectError:
            LOGGER.warning(
                "add_work_package_comment: fallback fetch of activity %s for a missing "
                "user link failed; the comment was still saved, user stays unset.",
                activity_id,
            )
            return activity
        fetched_user_link = fetched_activity.get("_links", {}).get("user")
        if not fetched_user_link:
            return activity
        return {**activity, "_links": {**activity_links, "user": fetched_user_link}}

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
        if not confirm:
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
        payload = {"id": detail.id, "subject": detail.subject, "lockVersion": detail.lock_version}
        return await self._finalize_delete(
            result_cls=WorkPackageWriteResult,
            confirm=confirm,
            result_kwargs={"work_package_id": detail.id, "project": detail.project, "payload": payload},
            preview_result=detail,
            commit_result=None,
            write_scope="work_package",
            delete_path=f"work_packages/{work_package_id}",
            preview_message="OpenProject is ready to delete this work package. Ask for confirmation, then call again with confirm=true.",
            success_message="Work package deleted successfully.",
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
        return await self._finalize_delete(
            result_cls=RelationWriteResult,
            confirm=confirm,
            result_kwargs={"relation_id": normalized.id, "work_package_id": normalized.from_id, "payload": payload},
            preview_result=normalized,
            commit_result=None,
            write_scope="work_package",
            delete_path=f"relations/{relation_id}",
            preview_message="OpenProject is ready to delete this relation. Ask for confirmation, then call again with confirm=true.",
            success_message="Relation deleted successfully.",
        )

    async def list_my_open_work_packages(
        self,
        *,
        offset: int = 1,
        limit: int | None = None,
    ) -> WorkPackageListResult:
        self._ensure_read_enabled("work_package")
        effective_limit = self._resolve_limit(limit)
        if not self.settings.read_projects:
            return self._empty_work_package_list_result(offset=offset, limit=effective_limit)
        current_user = await self.get_current_user()
        payload = await self._get(
            "work_packages",
            params={
                "offset": str(offset),
                "pageSize": str(effective_limit),
                "filters": _json_param(
                    [
                        {"assigned_to_id": {"operator": "=", "values": [str(current_user.id)]}},
                        {"status_id": {"operator": "o", "values": []}},
                    ]
                ),
            },
        )
        # This query has no server-side project filter at all, so the server total
        # counts matches across every project regardless of the allowlist — only
        # trust it when the scope is unrestricted (see _work_package_collection_page
        # for why a clean current page alone isn't sufficient either).
        total_is_scope_safe = _scope_allows_all(self.settings.read_projects)
        return self._build_work_package_list_result(
            payload=payload, offset=offset, limit=effective_limit, total_is_scope_safe=total_is_scope_safe
        )

    async def list_versions(
        self,
        *,
        project: str | None = None,
        search: str | None = None,
        offset: int = 1,
        limit: int | None = None,
        context: ProjectResolutionContext | None = None,
    ) -> VersionListResult:
        return await self._version_service.list(
            project=project, search=search, offset=offset, limit=limit, context=context
        )

    async def get_version(self, version_id: int, *, text_limit: int | None = None) -> VersionDetail:
        return await self._version_service.get(version_id, text_limit=text_limit)

    async def list_sprints(
        self,
        *,
        search: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> SprintListResult:
        return await self._sprint_service.list(search=search, offset=offset, limit=limit)

    async def list_project_sprints(
        self,
        project: str,
        *,
        search: str | None = None,
        offset: int = 1,
        limit: int | None = None,
        context: ProjectResolutionContext | None = None,
    ) -> SprintListResult:
        return await self._sprint_service.list_for_project(
            project, search=search, offset=offset, limit=limit, context=context
        )

    async def get_sprint(self, sprint_id: int) -> SprintDetail:
        return await self._sprint_service.get(sprint_id)

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
        return await self._version_service.create(
            project=project,
            name=name,
            description=description,
            start_date=start_date,
            end_date=end_date,
            status=status,
            sharing=sharing,
            confirm=confirm,
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
        return await self._version_service.update(
            version_id=version_id,
            name=name,
            description=description,
            start_date=start_date,
            end_date=end_date,
            status=status,
            sharing=sharing,
            confirm=confirm,
        )

    async def delete_version(
        self,
        *,
        version_id: int,
        confirm: bool = False,
    ) -> VersionWriteResult:
        return await self._version_service.delete(version_id=version_id, confirm=confirm)

    async def list_boards(
        self,
        *,
        project: str | None = None,
        search: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> BoardListResult:
        return await self._board_service.list(project=project, search=search, offset=offset, limit=limit)

    async def get_board(self, board_id: int) -> BoardDetail:
        return await self._board_service.get(board_id)

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
        return await self._board_service.create(
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
            confirm=confirm,
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
        return await self._board_service.update(
            board_id=board_id,
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
            confirm=confirm,
        )

    async def delete_board(
        self,
        *,
        board_id: int,
        confirm: bool = False,
    ) -> BoardWriteResult:
        return await self._board_service.delete(board_id=board_id, confirm=confirm)

    async def get_work_package_relations(
        self, work_package_id: int | str, *, offset: int = 1, limit: int | None = None
    ) -> RelationListResult:
        self._ensure_read_enabled("work_package")
        # Resolving the id already confirms the anchor work package itself is
        # allowed; a second self.get_work_package() fetch here would be redundant.
        work_package_id = await self._resolve_work_package_id(work_package_id)
        effective_limit = self._resolve_limit(limit)
        # The old work_packages/{id}/relations endpoint is deprecated (308 redirect).
        # Use the canonical relations endpoint with an "involved" filter instead.
        filters = json.dumps([{"involved": {"operator": "=", "values": [str(work_package_id)]}}])
        # Filter out relations whose OTHER side sits in a project outside the
        # READ_PROJECTS allowlist — otherwise that work package's id/subject
        # would leak through to_id/to_subject even though it isn't readable
        # on its own. Same helper/caching as list_relations.
        allowlisted = not _scope_allows_all(self.settings.read_projects)
        wp_allowed: dict[str, bool] = {}

        async def item_allowed(item: dict[str, Any]) -> bool:
            return not allowlisted or await self._relation_endpoints_allowed(item, wp_allowed)

        page, total, next_offset, truncated = await self._fetch_bounded_and_paginate(
            path="relations",
            params_extra={"filters": filters},
            normalize=self.normalize_relation,
            item_allowed=item_allowed,
            post_filter=None,
            offset=offset,
            limit=effective_limit,
        )
        return RelationListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(page),
            next_offset=next_offset,
            truncated=truncated,
            results=page,
        )

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

    async def toggle_activity_emoji_reaction(
        self, activity_id: int, reaction: str, *, confirm: bool = False
    ) -> EmojiReactionWriteResult:
        if reaction not in self.EMOJI_REACTIONS:
            raise InvalidInputError(f"reaction must be one of: {', '.join(self.EMOJI_REACTIONS)}.")
        # Enforce the project write allowlist against the activity's work package.
        # Fail closed: if the activity has no resolvable workPackage link, refuse
        # rather than patch an unchecked target. This check always runs, even in
        # preview mode — it is an authorization gate, not the mutation itself.
        activity = await self._get(f"activities/{activity_id}")
        work_package_ref = _id_from_href(activity.get("_links", {}).get("workPackage", {}).get("href"))
        if not work_package_ref:
            raise OpenProjectServerError(
                "OpenProject activity is missing a work package link; cannot verify project write access."
            )
        work_package_payload = await self._get(f"work_packages/{work_package_ref}")
        self._ensure_project_write_link_allowed(work_package_payload.get("_links", {}).get("project"))
        if not confirm:
            # The resulting add/remove state is not predicted here — OpenProject
            # decides that server-side and doing so ourselves would need an extra
            # lookup. The preview names the toggle's nature instead.
            return EmojiReactionWriteResult(
                action="toggle_reaction",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message=(
                    f"Toggles the '{reaction}' reaction on activity {activity_id} — adds it if not "
                    "already present, removes it if present. Ask for confirmation, then call again "
                    "with confirm=true to apply it."
                ),
                activity_id=activity_id,
                reaction=reaction,
                result=None,
            )
        self._ensure_write_enabled("work_package")
        # PATCH toggles: adds the reaction if absent, removes it if present, and
        # returns the full reaction collection for the activity afterwards.
        payload = await self._patch(
            f"activities/{activity_id}/emoji_reactions",
            json_body={"reaction": reaction},
        )
        return EmojiReactionWriteResult(
            action="toggle_reaction",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message=f"Toggled '{reaction}' reaction on activity {activity_id}.",
            activity_id=activity_id,
            reaction=reaction,
            result=self._emoji_reactions_result(payload),
        )

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
        if not self.settings.read_projects:
            return ReminderListResult(count=0, results=[])  # deny-all: skip the network call entirely
        payload = await self._get("reminders")
        elements = [item for item in payload.get("_embedded", {}).get("elements", []) if isinstance(item, dict)]
        if not _scope_allows_all(self.settings.read_projects):
            cache: dict[str, bool] = {}
            filtered = []
            for item in elements:
                href = item.get("_links", {}).get("remindable", {}).get("href")
                if not href:
                    continue  # can't verify -> fail closed
                if href not in cache:
                    cache[href] = await self._work_package_project_allowed(href)
                if cache[href]:
                    filtered.append(item)
            elements = filtered
        results = [self.normalize_reminder(item) for item in elements]
        return ReminderListResult(count=len(results), results=results)

    async def create_work_package_reminder(
        self,
        *,
        work_package_id: int | str,
        remind_at: str,
        note: str | None = None,
        confirm: bool = False,
    ) -> ReminderWriteResult:
        work_package_ref = self._work_package_ref(work_package_id)
        current = await self._get(f"work_packages/{work_package_ref}")
        self._ensure_project_write_link_allowed(current.get("_links", {}).get("project"))
        payload: dict[str, Any] = {"remindAt": remind_at}
        if note is not None:
            payload["note"] = note
        if not confirm:
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
        response = await self._post(f"work_packages/{work_package_ref}/reminders", json_body=payload)
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
        current = await self._get(f"reminders/{reminder_id}")
        remindable = current.get("_links", {}).get("remindable")
        if not isinstance(remindable, dict) or not remindable.get("href"):
            # Fail closed: an unresolvable work-package link must not be bypassed,
            # even under a fully open READ_PROJECTS=*/WRITE_PROJECTS=* scope.
            raise PermissionDeniedError(
                "OpenProject writes to this reminder are disabled by OPENPROJECT_WRITE_PROJECTS."
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
        if not confirm:
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
        return await self._finalize_delete(
            result_cls=ReminderWriteResult,
            confirm=confirm,
            result_kwargs={"reminder_id": reminder_id, "payload": {}},
            preview_result=None,
            commit_result=None,
            write_scope="work_package",
            delete_path=f"reminders/{reminder_id}",
            preview_message="OpenProject is ready to delete this reminder. Ask for confirmation, then call again with confirm=true.",
            success_message="Reminder deleted successfully.",
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
        return await self._project_service.set_favorite(project, favorite=favorite, confirm=confirm)

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
        work_package_payload = await self._get(f"work_packages/{work_package_id}")
        self._ensure_project_write_link_allowed(work_package_payload.get("_links", {}).get("project"))
        if not confirm:
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
        work_package_payload = await self._get(f"work_packages/{work_package_id}")
        self._ensure_project_write_link_allowed(work_package_payload.get("_links", {}).get("project"))
        if not confirm:
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
        self._ensure_read_enabled("personal")
        effective_limit = self._resolve_limit(limit)
        params: dict[str, str] = {
            "offset": str(offset),
            "pageSize": str(effective_limit),
        }
        if unread_only:
            params["filters"] = _json_param([{"readIAN": {"operator": "=", "values": ["f"]}}])
        payload = await self._get("notifications", params=params)
        elements = [item for item in payload.get("_embedded", {}).get("elements", []) if isinstance(item, dict)]
        if _scope_allows_all(self.settings.read_projects):
            filtered = elements
            total = int(payload.get("total", len(elements)))
        else:
            # Server-side pagination has no project filter, so this only scopes the
            # current page — a filtered-empty page does not prove no further allowed
            # notifications exist on later pages (see docs/architecture.md).
            wp_cache: dict[str, bool] = {}
            filtered = []
            for item in elements:
                if await self._notification_payload_allowed(item, wp_cache):
                    filtered.append(item)
            total = len(filtered)
        results = [self.normalize_notification(item) for item in filtered]
        return NotificationListResult(count=len(results), total=total, results=results)

    async def _notification_payload_allowed(self, payload: dict[str, Any], wp_cache: dict[str, bool]) -> bool:
        links = payload.get("_links", {})
        project_link = links.get("project")
        if isinstance(project_link, dict):
            return self._payload_allowed(lambda: self._ensure_project_link_allowed(project_link))
        resource_link = links.get("resource")
        resource_href = resource_link.get("href") if isinstance(resource_link, dict) else None
        if isinstance(resource_href, str) and "work_packages/" in resource_href:
            # Work-package-linked notification without its own resolvable project
            # link — resolve via the work package itself instead of trusting the
            # absent link (same helper/cache pattern as list_relations/list_reminders).
            if resource_href not in wp_cache:
                wp_cache[resource_href] = await self._work_package_project_allowed(resource_href)
            return wp_cache[resource_href]
        return True  # no project link and no work-package resource link: genuinely personal/global

    async def mark_notification_read(self, notification_id: int, *, confirm: bool = False) -> NotificationMarkResult:
        self._ensure_write_enabled("personal")
        if not confirm:
            # No OpenProject dry-run endpoint exists for this action — this is a
            # client-side preview only: ready=True means the request is
            # valid and will be sent once confirmed, not that OpenProject has
            # already validated it.
            return NotificationMarkResult(
                action="mark_read",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message=(
                    f"Ask for confirmation, then call again with confirm=true to mark "
                    f"notification {notification_id} read."
                ),
                notification_id=notification_id,
            )
        response = await self._request("POST", f"notifications/{notification_id}/read_ian")
        if response.status_code not in {200, 201, 204}:
            raise OpenProjectServerError(
                f"OpenProject mark notification read failed with status {response.status_code}."
            )
        return NotificationMarkResult(
            action="mark_read",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message=f"Notification {notification_id} marked read.",
            notification_id=notification_id,
        )

    async def mark_all_notifications_read(self, *, confirm: bool = False) -> NotificationMarkResult:
        self._ensure_write_enabled("personal")
        if not confirm:
            return NotificationMarkResult(
                action="mark_all_read",
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message=(
                    "Marks all currently unread notifications read. Ask for confirmation, "
                    "then call again with confirm=true to apply it."
                ),
                notification_id=None,
            )
        response = await self._request("POST", "notifications/read_ian")
        if response.status_code not in {200, 201, 204}:
            raise OpenProjectServerError(
                f"OpenProject mark all notifications read failed with status {response.status_code}."
            )
        return NotificationMarkResult(
            action="mark_all_read",
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message="All unread notifications marked read.",
            notification_id=None,
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
        form = await self._post("users/form", json_body=payload)
        return await self._finalize_user_write(
            action="create",
            confirm=confirm,
            form=form,
            write_path="users",
            preview_message="OpenProject validated the user. Ask for confirmation, then call again with confirm=true to create it.",
            success_message="User created successfully.",
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
        form = await self._post(f"users/{user_id}/form", json_body=payload)
        return await self._finalize_user_write(
            action="update",
            confirm=confirm,
            form=form,
            write_path=f"users/{user_id}",
            write_method="PATCH",
            user_id=user_id,
            success_message="User updated successfully.",
        )

    async def delete_user(
        self,
        user_id: int,
        *,
        confirm: bool = False,
    ) -> UserWriteResult:
        # Checked unconditionally (not just on confirm) since there's no prior GET
        # to gate an unauthorized preview request on -- preserved as-is below,
        # write_scope on the helper call is a harmless redundant re-check.
        self._ensure_write_enabled("admin")
        payload = {"id": user_id}
        return await self._finalize_delete(
            result_cls=UserWriteResult,
            confirm=confirm,
            result_kwargs={"user_id": user_id, "payload": payload},
            preview_result=None,
            commit_result=None,
            write_scope="admin",
            delete_path=f"users/{user_id}",
            preview_message="OpenProject is ready to delete the user. Ask for confirmation, then call again with confirm=true.",
            success_message="User deleted successfully.",
        )

    async def lock_user(
        self,
        user_id: int,
        *,
        confirm: bool = False,
    ) -> UserWriteResult:
        self._ensure_write_enabled("admin")
        payload = {"id": user_id}
        if not confirm:
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
        if not confirm:
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
        # DELETE .../lock already returns the full updated user representation
        # (OpenProject's user_transition helper responds with UserRepresenter
        # for both the POST and DELETE lock transitions, verified against
        # .op-sources) -- no need for a follow-up GET, mirroring lock_user.
        response = await self._request_json("DELETE", f"users/{user_id}/lock")
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
        if not confirm:
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
        if not confirm:
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
        # Checked unconditionally, same reasoning as delete_user above.
        self._ensure_write_enabled("admin")
        payload = {"id": group_id}
        return await self._finalize_delete(
            result_cls=GroupWriteResult,
            confirm=confirm,
            result_kwargs={"group_id": group_id, "payload": payload},
            preview_result=None,
            commit_result=None,
            write_scope="admin",
            delete_path=f"groups/{group_id}",
            preview_message="OpenProject is ready to delete the group. Ask for confirmation, then call again with confirm=true.",
            success_message="Group deleted successfully.",
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
        work_package_id = _id_from_href(container_href)
        # Enforce the project write allowlist against the container work package,
        # not just the global write flag. Fail closed when the container cannot be
        # resolved: _ensure_project_write_link_allowed(None) rejects unless the
        # write scope is unconfigured / "*".
        if work_package_id:
            work_package_payload = await self._get(f"work_packages/{work_package_id}")
            self._ensure_project_write_link_allowed(work_package_payload.get("_links", {}).get("project"))
        else:
            self._ensure_project_write_link_allowed(None)
        return await self._finalize_delete(
            result_cls=FileLinkWriteResult,
            confirm=confirm,
            result_kwargs={"file_link_id": file_link.id, "work_package_id": work_package_id},
            preview_result=file_link,
            commit_result=None,
            write_scope="work_package",
            delete_path=f"file_links/{file_link_id}",
            preview_message="OpenProject found the file link. Ask for confirmation, then call again with confirm=true to delete it.",
            success_message="File link deleted successfully.",
        )

    # --- Grids ---

    async def list_grids(self, *, scope: str | None = None) -> GridListResult:
        return await self._grid_service.list(scope=scope)

    async def get_grid(self, grid_id: int) -> GridSummary:
        return await self._grid_service.get(grid_id)

    async def create_grid(
        self,
        *,
        name: str,
        scope: str,
        row_count: int | None = None,
        column_count: int | None = None,
        confirm: bool = False,
    ) -> GridWriteResult:
        return await self._grid_service.create(
            name=name, scope=scope, row_count=row_count, column_count=column_count, confirm=confirm
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
        return await self._grid_service.update(
            grid_id=grid_id, name=name, row_count=row_count, column_count=column_count, confirm=confirm
        )

    async def delete_grid(
        self,
        *,
        grid_id: int,
        confirm: bool = False,
    ) -> GridWriteResult:
        return await self._grid_service.delete(grid_id=grid_id, confirm=confirm)

    # --- User Preferences ---

    async def get_my_preferences(self) -> UserPreferences:
        self._ensure_read_enabled("personal")
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
        # (language, timezone, popup behaviour). Gated by "personal" write
        # (OPENPROJECT_ENABLE_PERSONAL_WRITE); the confirm/preview flow is a
        # separate, additional guard on top, not a substitute for it.
        self._ensure_write_enabled("personal")
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
        if not confirm:
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
        data = await self._request_json(
            "POST",
            endpoint,
            content=text.encode("utf-8"),
            headers={"Content-Type": "text/plain"},
        )
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
        offset: int = 1,
        limit: int | None = None,
    ) -> RelationListResult:
        """List all relations, optionally filtered by type.

        Gated by the work_package read scope and filtered by the project read
        allowlist: only relations whose source work package is in an allowed
        project are returned, so this cannot leak work packages from projects the
        caller may not read.
        """
        self._ensure_read_enabled("work_package")
        effective_limit = self._resolve_limit(limit)
        params_extra: dict[str, str] | None = None
        if relation_type is not None:
            params_extra = {"filters": json.dumps([{"type": {"operator": "=", "values": [relation_type]}}])}
        allowlisted = not _scope_allows_all(self.settings.read_projects)
        # Cache project-allow decisions per work package so a batch of relations
        # between the same work packages doesn't refetch (mitigates N+1).
        wp_allowed: dict[str, bool] = {}

        async def item_allowed(item: dict[str, Any]) -> bool:
            return not allowlisted or await self._relation_endpoints_allowed(item, wp_allowed)

        page, total, next_offset, truncated = await self._fetch_bounded_and_paginate(
            path="relations",
            params_extra=params_extra,
            normalize=self.normalize_relation,
            item_allowed=item_allowed,
            post_filter=None,
            offset=offset,
            limit=effective_limit,
        )
        return RelationListResult(
            offset=offset,
            limit=effective_limit,
            total=total,
            count=len(page),
            next_offset=next_offset,
            truncated=truncated,
            results=page,
        )

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
        return self._payload_allowed(
            lambda: self._ensure_project_link_allowed(work_package.get("_links", {}).get("project"))
        )

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
        if not confirm:
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

    async def _fetch_and_normalize_detail(
        self,
        *,
        scope: str,
        path: str,
        ensure_fn: Callable[[dict[str, Any]], None],
        normalize_fn: Callable[[dict[str, Any]], DetailT],
        not_found_message: str | None = None,
    ) -> DetailT:
        """Shared shape behind the simple `get_X_detail` methods: check read access,
        fetch the payload, enforce the entity's allow-check, then normalize it.
        """
        self._ensure_read_enabled(scope)
        if not_found_message is not None:
            try:
                payload = await self._get(path)
            except NotFoundError as exc:
                raise NotFoundError(not_found_message) from exc
        else:
            payload = await self._get(path)
        ensure_fn(payload)
        return normalize_fn(payload)

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
        return _parse_response_json(response)

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
        content: bytes | str | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        response = await self._request(
            method, path, params=params, json_body=json_body, content=content, headers=headers
        )
        return _parse_response_json(response)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        files: dict[str, tuple[str | None, str | bytes, str]] | None = None,
        content: bytes | str | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        try:
            response = await self._http.request(
                method, path, params=params, json=json_body, files=files, content=content, headers=headers
            )
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
        _map_status_to_error(response.status_code, payload)

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
        # List-row context: capped at settings.text_limit (default 500), same
        # convention as WorkPackageSummary.description. Single-item
        # reads go through normalize_project_detail, which uses a larger/opt-in cap.
        description, description_truncated, description_length = self._visible_formattable_text_with_meta(
            payload.get("description"), "project", "description", limit=self.settings.text_limit
        )
        status_explanation, status_explanation_truncated, status_explanation_length = (
            self._visible_formattable_text_with_meta(
                payload.get("statusExplanation"), "project", "status_explanation", limit=self.settings.text_limit
            )
        )
        return self._apply_hidden_fields(
            "project",
            ProjectSummary(
                id=int(payload["id"]),
                name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or f"Project {payload['id']}",
                identifier=identifier,
                active=payload.get("active"),
                description=description,
                description_truncated=description_truncated,
                description_length=description_length,
                url=self._web_url(project_path),
                public=payload.get("public"),
                status=_link_title(links.get("status")),
                status_explanation=status_explanation,
                status_explanation_truncated=status_explanation_truncated,
                status_explanation_length=status_explanation_length,
                parent_id=_id_from_href(links.get("parent", {}).get("href")),
                parent_name=_link_title(links.get("parent")),
                created_at=payload.get("createdAt"),
                updated_at=payload.get("updatedAt"),
                can_update="update" in links or "updateImmediately" in links,
                can_delete="delete" in links,
                favorited=payload.get("favorited"),
            ),
        )

    def normalize_project_detail(
        self, payload: dict[str, Any], *, text_limit: int | None = FORMATTABLE_LIMIT
    ) -> ProjectDetail:
        """Single-project read. ``text_limit=None`` (used by get_project) returns
        the full description/status_explanation uncapped, like get_work_package;
        the FORMATTABLE_LIMIT default keeps write-preview callers capped."""
        summary = self.normalize_project(payload)
        links = payload.get("_links", {})
        description, description_truncated, description_length = self._visible_formattable_text_with_meta(
            payload.get("description"), "project", "description", limit=text_limit, preserve_newlines=True
        )
        status_explanation, status_explanation_truncated, status_explanation_length = (
            self._visible_formattable_text_with_meta(
                payload.get("statusExplanation"),
                "project",
                "status_explanation",
                limit=text_limit,
                preserve_newlines=True,
            )
        )
        ancestors_raw = links.get("ancestors", [])
        ancestors = None
        ancestors_truncated = False
        if ancestors_raw:
            ancestors = [
                {"href": a.get("href"), "title": a.get("title"), "display_id": a.get("displayId")}
                for a in ancestors_raw[:PROJECT_ANCESTORS_LIMIT]
            ]
            ancestors_truncated = len(ancestors_raw) > PROJECT_ANCESTORS_LIMIT
        return self._apply_hidden_fields(
            "project",
            ProjectDetail(
                id=summary.id,
                name=summary.name,
                identifier=summary.identifier,
                active=summary.active,
                description=description,
                description_truncated=description_truncated,
                description_length=description_length,
                url=summary.url,
                public=summary.public,
                status=summary.status,
                status_explanation=status_explanation,
                status_explanation_truncated=status_explanation_truncated,
                status_explanation_length=status_explanation_length,
                parent_id=summary.parent_id,
                parent_name=summary.parent_name,
                created_at=summary.created_at,
                updated_at=summary.updated_at,
                can_update=summary.can_update,
                can_delete=summary.can_delete,
                favorited=summary.favorited,
                ancestors=ancestors,
                ancestors_truncated=ancestors_truncated,
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
                firstname=_trim_text(payload.get("firstName"), limit=SUBJECT_LIMIT),
                lastname=_trim_text(payload.get("lastName"), limit=SUBJECT_LIMIT),
            ),
        )

    def normalize_user_detail(self, payload: dict[str, Any]) -> UserDetail:
        summary = self.normalize_user(payload)
        links = payload.get("_links", {})
        groups = [title for item in links.get("groups", []) if isinstance(item, dict) and (title := _link_title(item))]
        auth_source = _link_title(links.get("authSource"))
        # The real `identityUrl` API property (OmniAuth/SSO subject),
        # a top-level property -- not the `showUser` HAL link, which just
        # duplicates the already-modeled `url` field (both resolve to the same
        # /users/{id} web path).
        identity_url = payload.get("identityUrl")
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
                firstname=summary.firstname,
                lastname=summary.lastname,
            ),
        )

    def normalize_group(self, payload: dict[str, Any]) -> GroupSummary:
        links = payload.get("_links", {})
        # The real API embeds group members as a flat array, not a
        # {count, elements} collection object — same shape normalize_group_detail
        # already tolerates below. A {count, ...} dict is tolerated too in case a
        # future/older API version does emit that shape.
        members = payload.get("_embedded", {}).get("members", [])
        if isinstance(members, dict):
            member_count = int(members.get("count") or members.get("total") or 0)
        elif isinstance(members, list):
            member_count = len(members)
        else:
            member_count = 0
        return self._apply_hidden_fields(
            "group",
            GroupSummary(
                id=int(payload["id"]),
                name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT),
                member_count=member_count,
                created_at=payload.get("createdAt"),
                updated_at=payload.get("updatedAt"),
                can_update=_can_update_from_links(links),
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

    def _work_package_dates(self, payload: dict[str, Any]) -> tuple[str | None, str | None]:
        """(start_date, due_date) for a work package, accounting for milestones.

        OpenProject's work_package_representer.rb omits `startDate`/`dueDate`
        entirely for milestone-type work packages (`skip_render` when
        `represented.milestone?`) and instead reports the single day under a
        separate `date` key, whose own getter reads the underlying `due_date`
        value. Without this, every milestone work package normalizes to
        start_date=None, due_date=None even when it has a real date set --
        confirmed live against a milestone created via this client itself.
        """
        start_date = payload.get("startDate")
        due_date = payload.get("dueDate")
        if start_date is None and due_date is None and payload.get("date") is not None:
            milestone_date = payload["date"]
            return milestone_date, milestone_date
        return start_date, due_date

    def normalize_work_package_summary(self, payload: dict[str, Any]) -> WorkPackageSummary:
        links = payload.get("_links", {})
        # Summaries stay single-line, capped at settings.text_limit (OPENPROJECT_TEXT_LIMIT,
        # default 500) — a one-paragraph preview for list context. Not SUBJECT_LIMIT, which
        # is the subject field limit, and not the full text, which would flood the context
        # across many rows.
        description, truncated, length = self._visible_formattable_text_with_meta(
            payload.get("description"), "work_package", "description", limit=self.settings.text_limit
        )
        start_date, due_date = self._work_package_dates(payload)
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
                sprint=_link_title(links.get("sprint")),
                start_date=start_date,
                due_date=due_date,
                description=description,
                has_description=description is not None,
                url=self._web_url(f"work_packages/{payload['id']}"),
                description_truncated=truncated,
                description_length=length,
                estimated_time=payload.get("estimatedTime"),
                derived_estimated_time=payload.get("derivedEstimatedTime"),
                spent_time=payload.get("spentTime"),
                remaining_time=payload.get("remainingTime"),
                derived_remaining_time=payload.get("derivedRemainingTime"),
                duration=payload.get("duration"),
                parent_id=_id_from_href(links.get("parent", {}).get("href")),
                # Hierarchy links carry displayId from 17.5 (semantic mode); absent on
                # older/classic instances, where this stays None.
                parent_display_id=links.get("parent", {}).get("displayId"),
                created_at=payload.get("createdAt"),
                updated_at=payload.get("updatedAt"),
                author=_link_title(links.get("author")),
                category=_link_title(links.get("category")),
                schedule_manually=payload.get("scheduleManually"),
                ignore_non_working_days=payload.get("ignoreNonWorkingDays"),
                derived_start_date=payload.get("derivedStartDate"),
                derived_due_date=payload.get("derivedDueDate"),
                percentage_done=payload.get("percentageDone"),
                derived_percentage_done=payload.get("derivedPercentageDone"),
                readonly=payload.get("readonly"),
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

        # Hierarchy arrays with limits
        children_raw = links.get("children", [])
        children = None
        children_truncated = False
        if children_raw:
            children = [
                {"href": c.get("href"), "title": c.get("title"), "display_id": c.get("displayId")}
                for c in children_raw[:WORK_PACKAGE_CHILDREN_LIMIT]
            ]
            children_truncated = len(children_raw) > WORK_PACKAGE_CHILDREN_LIMIT

        ancestors_raw = links.get("ancestors", [])
        ancestors = None
        ancestors_truncated = False
        if ancestors_raw:
            ancestors = [
                {"href": a.get("href"), "title": a.get("title"), "display_id": a.get("displayId")}
                for a in ancestors_raw[:WORK_PACKAGE_ANCESTORS_LIMIT]
            ]
            ancestors_truncated = len(ancestors_raw) > WORK_PACKAGE_ANCESTORS_LIMIT

        start_date, due_date = self._work_package_dates(payload)
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
                sprint=_link_title(links.get("sprint")),
                parent_id=_id_from_href(links.get("parent", {}).get("href")),
                # Hierarchy links carry displayId from 17.5 (semantic mode); absent on
                # older/classic instances, where this stays None.
                parent_display_id=links.get("parent", {}).get("displayId"),
                start_date=start_date,
                due_date=due_date,
                lock_version=payload.get("lockVersion"),
                description=description,
                url=self._web_url(f"work_packages/{payload['id']}"),
                activities_url=self._link_to_web_url(links.get("activities", {}).get("href")),
                relations_url=self._link_to_web_url(links.get("relations", {}).get("href")),
                description_truncated=truncated,
                description_length=length,
                estimated_time=payload.get("estimatedTime"),
                derived_estimated_time=payload.get("derivedEstimatedTime"),
                spent_time=payload.get("spentTime"),
                remaining_time=payload.get("remainingTime"),
                derived_remaining_time=payload.get("derivedRemainingTime"),
                duration=payload.get("duration"),
                created_at=payload.get("createdAt"),
                updated_at=payload.get("updatedAt"),
                author=_link_title(links.get("author")),
                category=_link_title(links.get("category")),
                children=children,
                children_truncated=children_truncated,
                ancestors=ancestors,
                ancestors_truncated=ancestors_truncated,
                schedule_manually=payload.get("scheduleManually"),
                ignore_non_working_days=payload.get("ignoreNonWorkingDays"),
                derived_start_date=payload.get("derivedStartDate"),
                derived_due_date=payload.get("derivedDueDate"),
                percentage_done=payload.get("percentageDone"),
                derived_percentage_done=payload.get("derivedPercentageDone"),
                readonly=payload.get("readonly"),
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

        # Details array with limit. OpenProject sends each entry as both a
        # plain-text "raw" and a markup "html" rendering of the SAME change
        # description — keep only "raw" (dropping the duplicate "html"/"format"
        # keys) and delimit it like every other free-text field here, since
        # it is equally untrusted user-authored content.
        details_raw = payload.get("details", [])
        details = None
        details_truncated = False
        if details_raw:
            details = [
                {"raw": _delimit_user_content(item.get("raw"))}
                for item in details_raw[:ACTIVITY_DETAILS_LIMIT]
                if isinstance(item, dict)
            ]
            details_truncated = len(details_raw) > ACTIVITY_DETAILS_LIMIT

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
                details=details,
                details_truncated=details_truncated,
            ),
        )

    def normalize_version(
        self, payload: dict[str, Any], *, text_limit: int | None = FORMATTABLE_LIMIT
    ) -> VersionSummary:
        summary = _httpx_version_api.normalize_version(payload, base_url=self.settings.base_url, text_limit=text_limit)
        return self._apply_hidden_fields("version", summary)

    def normalize_version_detail(
        self, payload: dict[str, Any], *, text_limit: int | None = FORMATTABLE_LIMIT
    ) -> VersionDetail:
        detail = _httpx_version_api.normalize_version_detail(
            payload, base_url=self.settings.base_url, text_limit=text_limit
        )
        return self._apply_hidden_fields("version", detail)

    def normalize_query_filter(self, payload: dict[str, Any]) -> QueryFilterSummary:
        links = payload.get("_links", {})
        self_link, href, filter_id = _query_ref_identity(links, payload)
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
        self_link, href, column_id = _query_ref_identity(links, payload)
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
        self_link, href, operator_id = _query_ref_identity(links, payload)
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
        self_link, href, sort_by_id = _query_ref_identity(links, payload)
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
        self_link, href, schema_id = _query_ref_identity(links, payload)
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

    def normalize_time_entry(
        self, payload: dict[str, Any], *, text_limit: int | None = FORMATTABLE_LIMIT
    ) -> TimeEntrySummary:
        """``text_limit=None`` returns the full comment uncapped (get_time_entry);
        the FORMATTABLE_LIMIT default keeps write-preview callers capped. List rows
        (list_time_entries) explicitly pass settings.text_limit."""
        links = payload.get("_links", {})
        project_link = links.get("project")
        entity_link = links.get("entity")
        comment, comment_truncated, comment_length = self._visible_formattable_text_with_meta(
            payload.get("comment"), "time_entry", "comment", limit=text_limit
        )
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
                comment=comment,
                comment_truncated=comment_truncated,
                comment_length=comment_length,
                created_at=payload.get("createdAt"),
                updated_at=payload.get("updatedAt"),
                url=self._web_url(f"time_entries/{payload['id']}"),
            ),
        )

    def normalize_status(self, payload: dict[str, Any]) -> StatusSummary:
        status_id = int(payload["id"])
        return self._apply_hidden_fields(
            "status",
            StatusSummary(
                id=status_id,
                name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or f"Status {status_id}",
                is_default=bool(payload.get("isDefault")),
                is_closed=bool(payload.get("isClosed")),
                color=_trim_text(payload.get("color"), limit=SUBJECT_LIMIT),
                position=payload.get("position"),
                url=self._api_href(f"statuses/{status_id}"),
                is_readonly=payload.get("isReadonly"),
                default_done_ratio=payload.get("defaultDoneRatio"),
                excluded_from_totals=payload.get("excludedFromTotals"),
            ),
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
        return self._apply_hidden_fields(
            "type",
            TypeSummary(
                id=type_id,
                name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or f"Type {type_id}",
                color=_trim_text(payload.get("color"), limit=SUBJECT_LIMIT),
                position=payload.get("position"),
                is_default=bool(payload.get("isDefault")),
                is_milestone=bool(payload.get("isMilestone")),
                url=self._web_url(f"types/{type_id}"),
                created_at=payload.get("createdAt"),
                updated_at=payload.get("updatedAt"),
            ),
        )

    def normalize_watcher(self, payload: dict[str, Any]) -> WatcherSummary:
        watcher_id = int(payload["id"])
        return self._apply_hidden_fields(
            "watcher",
            WatcherSummary(
                id=watcher_id,
                name=_trim_text(payload.get("name"), limit=SUBJECT_LIMIT) or f"User {watcher_id}",
                login=_trim_text(payload.get("login"), limit=SUBJECT_LIMIT),
                url=self._web_url(f"users/{watcher_id}"),
            ),
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
        return self._apply_hidden_fields(
            "file_link",
            FileLinkSummary(
                id=file_link_id,
                title=_trim_text(payload.get("title") or payload.get("originData", {}).get("name"), limit=SUBJECT_LIMIT)
                or f"File link {file_link_id}",
                storage_id=storage_id,
                storage_name=storage_name,
                created_at=payload.get("createdAt"),
                updated_at=payload.get("updatedAt"),
                url=self._api_href(f"file_links/{file_link_id}"),
            ),
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
        sprint: str | object | None = None,
        project_phase: str | object | None = None,
        status: str | None = None,
        assignee: str | object | None = None,
        responsible: str | object | None = None,
        priority: str | None = None,
        category: str | object | None = None,
        custom_fields: dict[str, Any] | None = None,
        parent_work_package_id: int | object | None = None,
        start_date: str | None = None,
        due_date: str | None = None,
        estimated_time: str | object | None = None,
        remaining_time: str | object | None = None,
        duration: str | object | None = None,
        percentage_done: int | None = None,
        work_package_id: int | str | None = None,
        lock_version: int | None = None,
        resolution_context: WorkPackageResolutionContext | None = None,
    ) -> dict[str, Any]:
        project_context = resolution_context.project_context if resolution_context is not None else None
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
        if estimated_time is CLEAR:
            self._ensure_field_writable("work_package", "estimated_time")
            payload["estimatedTime"] = None
        elif estimated_time is not None:
            self._ensure_field_writable("work_package", "estimated_time")
            payload["estimatedTime"] = estimated_time
        if remaining_time is CLEAR:
            self._ensure_field_writable("work_package", "remaining_time")
            payload["remainingTime"] = None
        elif remaining_time is not None:
            self._ensure_field_writable("work_package", "remaining_time")
            payload["remainingTime"] = remaining_time
        if percentage_done is not None:
            self._ensure_field_writable("work_package", "percentage_done")
            payload["percentageDone"] = percentage_done
        if duration is CLEAR:
            self._ensure_field_writable("work_package", "duration")
            payload["duration"] = None
        elif duration is not None:
            self._ensure_field_writable("work_package", "duration")
            payload["duration"] = duration
        if type is not None:
            self._ensure_field_writable("work_package", "type")
            type_id = await self._resolve_wp_ref_id(
                "type",
                type,
                project=project,
                cache=resolution_context,
                resolve=lambda: self._resolve_type_id(type, project=project, context=project_context),
            )
            links["type"] = {"href": self._api_href(f"types/{type_id}")}
        if version is CLEAR_VERSION:
            self._ensure_field_writable("work_package", "version")
            links["version"] = {"href": None}
        elif version is not None:
            self._ensure_field_writable("work_package", "version")
            version_ref: str = _narrow_cleared(version, sentinel=CLEAR_VERSION)
            version_id = await self._resolve_wp_ref_id(
                "version",
                version_ref,
                project=project,
                cache=resolution_context,
                resolve=lambda: self._resolve_version_id(version_ref, project=project, context=project_context),
            )
            links["version"] = {"href": self._api_href(f"versions/{version_id}")}
        if sprint is CLEAR:
            self._ensure_field_writable("work_package", "sprint")
            links["sprint"] = {"href": None}
        elif sprint is not None:
            self._ensure_field_writable("work_package", "sprint")
            sprint_ref: str = _narrow_cleared(sprint, sentinel=CLEAR)
            sprint_id = await self._resolve_wp_ref_id(
                "sprint",
                sprint_ref,
                project=project,
                cache=resolution_context,
                resolve=lambda: self._resolve_sprint_id(sprint_ref, project=project, context=project_context),
            )
            links["sprint"] = {"href": self._api_href(f"sprints/{sprint_id}")}
        if status is not None:
            self._ensure_field_writable("work_package", "status")
            status_id = await self._resolve_status_id(status)
            links["status"] = {"href": self._api_href(f"statuses/{status_id}")}
        if assignee is CLEAR:
            self._ensure_field_writable("work_package", "assignee")
            links["assignee"] = {"href": None}
        elif assignee is not None:
            self._ensure_field_writable("work_package", "assignee")
            assignee_id = await self._resolve_assignee_id(_narrow_cleared(assignee, sentinel=CLEAR))
            links["assignee"] = {"href": self._api_href(f"users/{assignee_id}")}
        if parent_work_package_id is CLEAR_PARENT:
            self._ensure_field_writable("work_package", "parent")
            links["parent"] = {"href": None}
        elif parent_work_package_id is not None:
            self._ensure_field_writable("work_package", "parent")
            links["parent"] = {"href": self._api_href(f"work_packages/{parent_work_package_id}")}

        # Clear (CLEAR sentinel) the schema-backed fields directly — a null href needs
        # no schema-option resolution, and must not trigger the schema probe below.
        if responsible is CLEAR:
            self._ensure_field_writable("work_package", "responsible")
            links["responsible"] = {"href": None}
        if category is CLEAR:
            self._ensure_field_writable("work_package", "category")
            links["category"] = {"href": None}
        if project_phase is CLEAR:
            self._ensure_field_writable("work_package", "project_phase")
            links["projectPhase"] = {"href": None}

        schema_needs = any(
            value is not None and value is not CLEAR
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
                project_context=project_context,
            )
            if responsible is not None and responsible is not CLEAR:
                self._ensure_field_writable("work_package", "responsible")
                links["responsible"] = {"href": self._resolve_schema_option_href(schema, "responsible", responsible)}
            if priority is not None:
                self._ensure_field_writable("work_package", "priority")
                links["priority"] = {"href": self._resolve_schema_option_href(schema, "priority", priority)}
            if category is not None and category is not CLEAR:
                self._ensure_field_writable("work_package", "category")
                links["category"] = {"href": self._resolve_schema_option_href(schema, "category", category)}
            if project_phase is not None and project_phase is not CLEAR:
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
        work_package_id: int | str | None,
        draft_payload: dict[str, Any],
        lock_version: int | None = None,
        project_context: ProjectResolutionContext | None = None,
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
            # Latent/unreachable in current call patterns: _build_write_payload
            # already puts "type" in schema_links whenever `type` is given, so this
            # branch only fires for a hypothetical future caller that doesn't. Still
            # threaded through for consistency with every other resolver call in
            # this flow.
            type_id = await self._resolve_type_id(type, project=project, context=project_context)
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

    async def _finalize_write(
        self,
        *,
        result_cls: type[ResultT],
        action: str,
        confirm: bool,
        form: dict[str, Any],
        write_path: str,
        write_method: str = "POST",
        write_scope: str,
        identity_kwargs: Callable[[dict[str, Any]], dict[str, Any]],
        normalize: Callable[[dict[str, Any]], DetailT],
        committed_kwargs: Callable[[DetailT], dict[str, Any]],
        rejected_message: str,
        preview_message: str,
        success_message: str,
    ) -> ResultT:
        """Shared rejected/preview/committed state machine for the 7 form-based
        write finalizers. Each entity differs in its identity
        field(s), write scope, and normalizer — those are parameterized here,
        not the messages, which callers supply verbatim so no wording changes.

        identity_kwargs receives the extracted payload (not just static caller
        args) because at least one entity (grid) derives part of its identity
        (`scope`) from the payload itself, not from a value the caller passed in.
        """
        embedded = form.get("_embedded", {})
        payload = embedded.get("payload", {})
        validation_errors = _normalize_validation_errors(embedded.get("validationErrors"))
        ready = not validation_errors
        identity = identity_kwargs(payload)

        if not ready:
            # ResultT is an unbound TypeVar (each of the 7 write finalizers binds it to
            # a different dataclass with different fields), so mypy can't verify these
            # kwargs against result_cls's actual __init__ — identity_kwargs/
            # committed_kwargs are written per call site to match result_cls exactly.
            return result_cls(  # type: ignore[call-arg]
                action=action,
                confirmed=False,
                requires_confirmation=not confirm,
                ready=False,
                message=rejected_message,
                payload=payload,
                validation_errors=validation_errors,
                result=None,
                **identity,
            )

        if not confirm:
            return result_cls(  # type: ignore[call-arg]
                action=action,
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message=preview_message,
                payload=payload,
                validation_errors={},
                result=None,
                **identity,
            )

        self._ensure_write_enabled(write_scope)
        if write_method == "PATCH":
            response = await self._patch(write_path, json_body=payload)
        else:
            response = await self._post(write_path, json_body=payload)
        detail = normalize(response)
        return result_cls(  # type: ignore[call-arg]
            action=action,
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message=success_message,
            payload=payload,
            validation_errors={},
            result=detail,
            **committed_kwargs(detail),
        )

    async def _finalize_delete(
        self,
        *,
        result_cls: type[ResultT],
        action: str = "delete",
        confirm: bool,
        result_kwargs: dict[str, Any],
        preview_result: Any,
        commit_result: Any,
        write_scope: str,
        delete_path: str,
        preview_message: str,
        success_message: str,
    ) -> ResultT:
        """Shared preview/committed state machine for the 13 GET-then-delete
        finalizers. Each entity's pre-delete setup (GET, allowlist check,
        normalization) is genuinely heterogeneous -- e.g. delete_attachment
        needs the return value of its allow-check for the result identity,
        delete_user/delete_group do no GET at all -- so that setup stays at
        each call site unchanged. Only the identical "preview or commit"
        branching is shared here. result_kwargs carries whatever extra fields
        that entity's Result dataclass actually declares (identity fields,
        and payload where the class has one -- not every Result class has a
        payload field, e.g. FileLinkWriteResult does not).
        """
        if not confirm:
            # ResultT is an unbound TypeVar (each of the 13 delete methods binds it to
            # a different dataclass with different fields, assembled per call site in
            # result_kwargs) -- mypy can't verify this statically, same as _finalize_write.
            return result_cls(  # type: ignore[call-arg]
                action=action,
                confirmed=False,
                requires_confirmation=True,
                ready=True,
                message=preview_message,
                validation_errors={},
                result=preview_result,
                **result_kwargs,
            )
        self._ensure_write_enabled(write_scope)
        await self._delete(delete_path)
        return result_cls(  # type: ignore[call-arg]
            action=action,
            confirmed=True,
            requires_confirmation=False,
            ready=True,
            message=success_message,
            validation_errors={},
            result=commit_result,
            **result_kwargs,
        )

    async def _finalize_work_package_write(
        self,
        *,
        action: str,
        confirm: bool,
        form: dict[str, Any],
        write_path: str,
        write_method: str = "POST",
        work_package_id: int | str | None = None,
        project_name: str | None = None,
        preview_message: str | None = None,
        success_message: str | None = None,
    ) -> WorkPackageWriteResult:
        return await self._finalize_write(
            result_cls=WorkPackageWriteResult,
            action=action,
            confirm=confirm,
            form=form,
            write_path=write_path,
            write_method=write_method,
            write_scope="work_package",
            identity_kwargs=lambda _payload: {"work_package_id": work_package_id, "project": project_name},
            normalize=self.normalize_work_package_detail,
            committed_kwargs=lambda d: {"work_package_id": d.id, "project": d.project},
            rejected_message="OpenProject rejected the proposed changes. Fix the validation errors before confirming.",
            preview_message=preview_message
            or "OpenProject validated the change. Ask for confirmation, then call again with confirm=true to write it.",
            success_message=success_message or f"Work package {action}d successfully.",
        )

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

    async def _get_project_payload(
        self,
        project_ref: str,
        *,
        write: bool = False,
        context: ProjectResolutionContext | None = None,
    ) -> dict[str, Any]:
        if context is not None:
            return await context.resolve(project_ref, write=write)
        return await self._resolve_project_ref(project_ref, write=write)

    async def _resolve_project_ref(self, project_ref: str, *, write: bool = False) -> dict[str, Any]:
        """Resolve a project by numeric id, exact identifier, or (as a fallback) display name.

        Delegates to the layered ProjectResolver (app/resolvers/project_resolver.py),
        which is a verbatim behavioral port of this method's former inline
        implementation. Kept as a stable internal facade -- every other domain's
        client.py code (list_project_memberships, get_my_project_access, ...) still
        calls this method (or _get_project_payload, which calls it) directly and
        expects the identical raw-payload contract; only the body changed.
        """
        return await self._project_resolver.resolve(project_ref, write=write)

    async def _resolve_project_filter_candidates(self, project: str | None) -> set[str] | None:
        if project is None:
            return None
        project_payload = await self._resolve_project_ref(project, write=False)
        return {
            str(project_payload["id"]).casefold(),
            (_trim_text(project_payload.get("identifier"), limit=SUBJECT_LIMIT) or "").casefold(),
            (_trim_text(project_payload.get("name"), limit=SUBJECT_LIMIT) or "").casefold(),
        }

    async def _time_entry_activities_from_project(self, project_id: int) -> list[TimeEntryActivitySummary]:
        form = await self._post(
            "time_entries/form",
            json_body={"_links": {"project": {"href": self._api_href(f"projects/{project_id}")}}},
        )
        schema = form.get("_embedded", {}).get("schema", {})
        activity_field = schema.get("activity", {})
        allowed = activity_field.get("_embedded", {}).get("allowedValues", [])
        return [self.normalize_time_entry_activity(item) for item in allowed if isinstance(item, dict)]

    async def _finalize_user_write(
        self,
        *,
        action: str,
        confirm: bool,
        form: dict[str, Any],
        write_path: str,
        write_method: str = "POST",
        user_id: int | None = None,
        preview_message: str | None = None,
        success_message: str | None = None,
    ) -> UserWriteResult:
        return await self._finalize_write(
            result_cls=UserWriteResult,
            action=action,
            confirm=confirm,
            form=form,
            write_path=write_path,
            write_method=write_method,
            write_scope="admin",
            identity_kwargs=lambda _payload: {"user_id": user_id},
            normalize=self.normalize_user_detail,
            committed_kwargs=lambda u: {"user_id": u.id},
            rejected_message="OpenProject rejected the proposed user changes. Fix the validation errors before confirming.",
            preview_message=preview_message
            or "OpenProject validated the user change. Ask for confirmation, then call again with confirm=true to write it.",
            success_message=success_message or f"User {action}d successfully.",
        )

    def _ensure_write_enabled(self, scope: str) -> None:
        _access_policy.ensure_write_enabled(scope, settings=self.settings)

    def _ensure_read_enabled(self, scope: str) -> None:
        _access_policy.ensure_read_enabled(scope, settings=self.settings)

    def _payload_allowed(self, ensure: Callable[[], None]) -> bool:
        """Run an `_ensure_*_allowed` check, turning PermissionDeniedError into False.

        Shared by every bool-returning `_X_payload_allowed` wrapper in this class.
        """
        return _scope_policy.payload_allowed(ensure)

    def _ensure_project_link_allowed(self, link: Any) -> None:
        _scope_policy.ensure_project_link_allowed(
            link, settings=self.settings, project_id_to_identifier=self._project_id_to_identifier
        )

    def _ensure_project_write_link_allowed(self, link: Any) -> None:
        _scope_policy.ensure_project_write_link_allowed(
            link, settings=self.settings, project_id_to_identifier=self._project_id_to_identifier
        )

    def _work_package_payload_allowed(self, payload: dict[str, Any]) -> bool:
        return self._payload_allowed(
            lambda: self._ensure_project_link_allowed(payload.get("_links", {}).get("project"))
        )

    def _time_entry_payload_allowed(self, payload: dict[str, Any]) -> bool:
        return self._payload_allowed(
            lambda: self._ensure_project_link_allowed(payload.get("_links", {}).get("project"))
        )

    def _project_candidates(
        self,
        *,
        project_ref: str | None = None,
        payload: dict[str, Any] | None = None,
        link: Any = None,
        identifier: str | None = None,
        name: str | None = None,
    ) -> set[str]:
        return _scope_policy.project_candidates(
            project_id_to_identifier=self._project_id_to_identifier,
            project_ref=project_ref,
            payload=payload,
            link=link,
            identifier=identifier,
            name=name,
        )

    def _link_matches_project_refs(self, link: Any, project_refs: set[str]) -> bool:
        return not self._project_candidates(link=link).isdisjoint(project_refs)

    def _summary_matches_project_candidates(
        self,
        item: BoardSummary | ViewSummary | DocumentSummary | NewsSummary,
        project_candidates: set[str],
    ) -> bool:
        return not project_candidates.isdisjoint(
            {
                str(item.project_id).casefold() if item.project_id is not None else "",
                (item.project or "").casefold(),
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

        OPENPROJECT_ATTACHMENT_ROOT must be set to an absolute directory; there
        is no current-working-directory fallback (a globally installed MCP
        server's cwd is unpredictable, so silently falling back to it would let
        an upload land in, or escape from, whatever directory happened to
        launch the server). This bounds which local files a caller can upload,
        so a malicious/confused agent cannot exfiltrate arbitrary host files
        (e.g. the API token in .mcp.json, SSH keys, /etc/passwd). tools.py also
        only registers create_work_package_attachment when this is set;
        this check is defense-in-depth for a caller that constructs
        OpenProjectClient directly, bypassing that registration gate (as
        several tests in tests/unit/ already do).
        """
        configured = self.settings.attachment_root
        if not configured:
            raise PermissionDeniedError(
                "Attachment uploads are disabled: OPENPROJECT_ATTACHMENT_ROOT is not set. "
                "There is no current-working-directory fallback — set it to an absolute, "
                "existing directory to allow local file uploads."
            )
        return Path(configured).expanduser().resolve()

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
        return _hidden_fields_policy.hidden_patterns(entity, settings=self.settings)

    def _normalize_hide_token(self, value: str) -> str:
        return _hidden_fields_policy.normalize_hide_token(value)

    def _field_hidden(self, entity: str, field_name: str) -> bool:
        return _hidden_fields_policy.field_hidden(entity, field_name, settings=self.settings)

    def _ensure_field_writable(self, entity: str, field_name: str) -> None:
        _hidden_fields_policy.ensure_field_writable(entity, field_name, settings=self.settings)

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
        """Hide-aware, delimited formattable text plus ``(text, truncated, full_length)``.

        ``limit=None`` returns the full text uncapped. When the field is hidden,
        returns ``(None, False, None)`` — a hidden field is not "truncated", it
        is simply absent. The returned text is always wrapped by
        ``_delimit_user_content`` — every caller did this immediately after
        calling this method, so it is folded in here instead of repeated at
        each of the 3 call sites.
        """
        if self._field_hidden(entity, field_name):
            return None, False, None
        text, truncated, length = _extract_formattable_text_with_meta(
            value, limit=limit, preserve_newlines=preserve_newlines
        )
        return _delimit_user_content(text), truncated, length

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
        a null value. Stamping is possible because the response dataclasses
        are not frozen.
        """
        return _hidden_fields_policy.apply_hidden_fields(entity, value, settings=self.settings)

    def _replace_and_restamp(self, entity: str, value: Any, **changes: Any) -> Any:
        """Like ``dataclasses.replace()``, but preserves the ``_hidden_keys`` stamp.

        ``dataclasses.replace()`` rebuilds the instance via the constructor,
        which drops any ``_hidden_keys`` attribute ``_apply_hidden_fields``
        previously stamped onto it - re-stamp so a configured hide-fields
        entry still takes effect on the replaced instance.
        """
        return self._apply_hidden_fields(entity, replace(value, **changes))

    def _api_href(self, relative_path: str) -> str:
        return f"/{self._api_prefix.lstrip('/')}{relative_path.lstrip('/')}"

    async def _resolve_project_id(self, project_ref: str) -> str:
        return await self._project_resolver.resolve_id(project_ref, write=False)

    async def _resolve_principal_id(self, principal_ref: str) -> str:
        if principal_ref.casefold() == "me":
            current_user = await self.get_current_user()
            return str(current_user.id)
        if principal_ref.isdigit():
            return principal_ref
        principals = await self._list_principals_unchecked(
            search=principal_ref, offset=1, limit=self.settings.max_results
        )
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

    async def _resolve_wp_ref_id(
        self,
        kind: str,
        ref: str,
        *,
        project: str,
        cache: WorkPackageResolutionContext | None,
        resolve: Callable[[], Awaitable[str]],
    ) -> str:
        """Cache-then-resolve wrapper around _resolve_type_id/_resolve_version_id/
        _resolve_sprint_id. When `cache` is shared across a bulk call's items (see
        WorkPackageResolutionContext), a repeated name->id lookup for the same
        (project, kind, ref) is skipped instead of re-querying OpenProject once per
        item. The resolvers themselves are unchanged -- this is purely a wrapping
        layer around them.
        """
        if cache is not None:
            cached = cache.get_id(kind, project, ref)
            if cached is not None:
                return cached
        resolved = await resolve()
        if cache is not None:
            cache.store_id(kind, project, ref, resolved)
        return resolved

    async def _resolve_type_id(
        self, type_ref: str, *, project: str | None, context: ProjectResolutionContext | None = None
    ) -> str:
        if type_ref.isdigit():
            return type_ref
        if not project:
            raise InvalidInputError("type names require a project filter. Pass a numeric type id or set project.")

        project_payload = await self._get_project_payload(project, context=context)
        project_id = str(project_payload["id"])
        payload = await self._get(f"projects/{project_id}/types")
        elements = payload.get("_embedded", {}).get("elements", [])
        matches = [str(item["id"]) for item in elements if str(item.get("name", "")).casefold() == type_ref.casefold()]
        if not matches:
            raise InvalidInputError(f"OpenProject type '{type_ref}' was not found in project '{project}'.")
        if len(matches) > 1:
            raise InvalidInputError(f"OpenProject type '{type_ref}' is ambiguous. Pass a numeric type id.")
        return matches[0]

    async def _resolve_version_id(
        self, version_ref: str, *, project: str | None = None, context: ProjectResolutionContext | None = None
    ) -> str:
        return await self._version_resolver.resolve_id(version_ref, project=project, context=context)

    async def _resolve_sprint_id(
        self, sprint_ref: str, *, project: str, context: ProjectResolutionContext | None = None
    ) -> str:
        if sprint_ref.isdigit():
            try:
                record = await self._sprint_api.get(int(sprint_ref))
            except NotFoundError as exc:
                raise NotFoundError(
                    "OpenProject sprint not found, or the Backlogs module / sprint API is unavailable."
                ) from exc
            _sprint_policy.ensure_sprint_workspace_allowed(
                defining_workspace_payload=record.defining_workspace_payload,
                defining_workspace_link=record.defining_workspace_link,
                settings=self.settings,
                project_id_to_identifier=self._project_id_to_identifier,
            )
            return sprint_ref

        # Page-walk real server pages directly (NOT via list_project_sprints):
        # that method's over-fetch-then-paginate-in-memory shape always requests
        # offset=1/pageSize=max_results and paginates the same bounded result
        # in memory, so calling it again with a different offset just re-fetches
        # the identical first server page — a project with more sprints than
        # max_results would never be fully searched no matter how many
        # "pages" were walked. This resolver instead pages the server itself,
        # trusting its reported `total` (mirrors VersionResolver.resolve_id's
        # genuine server-paginated project path).
        self._ensure_read_enabled("project")
        project_payload = await self._get_project_payload(project, context=context)
        project_id = int(project_payload["id"])
        page_size = self.settings.max_page_size
        matches: list[str] = []
        offset = 1
        while True:
            try:
                records, total = await self._sprint_api.list_for_project_page(
                    project_id, offset=offset, page_size=page_size
                )
            except NotFoundError as exc:
                raise NotFoundError(
                    "OpenProject project sprints require the Backlogs module and OpenProject 17.3 or newer."
                ) from exc
            for record in records:
                if not _sprint_policy.sprint_payload_allowed(
                    defining_workspace_payload=record.defining_workspace_payload,
                    defining_workspace_link=record.defining_workspace_link,
                    settings=self.settings,
                    project_id_to_identifier=self._project_id_to_identifier,
                ):
                    continue
                if (record.summary.name or "").casefold() == sprint_ref.casefold():
                    matches.append(str(record.summary.id))
            next_offset, _truncated = _paginate_server(offset=offset, limit=page_size, total=total)
            if next_offset is None:
                break
            offset = next_offset
        if not matches:
            raise InvalidInputError(f"OpenProject sprint '{sprint_ref}' was not found in project '{project}'.")
        if len(matches) > 1:
            raise InvalidInputError(
                f"OpenProject sprint '{sprint_ref}' is ambiguous without a more specific filter. Pass a numeric sprint id."
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
        does not short-circuit: it always triggers a fetch of the work
        package too, so its project can be validated against the allowlist before
        its ``id`` is read back. A project-prefixed identifier is resolved the same
        way, but additionally only works on OpenProject 17.5+ (and requires the
        exact, case-sensitive project identifier).
        """
        reference = str(ref).strip()
        try:
            payload = await self._get(f"work_packages/{quote(reference, safe='')}")
        except NotFoundError as exc:
            if reference.isdigit():
                raise
            # A project-prefixed reference only resolves on OpenProject 17.5+ (and
            # requires the exact, case-sensitive project identifier). Give a hint
            # instead of a bare "not found" so a too-old instance or a case/prefix
            # mismatch is distinguishable from a genuinely missing work package.
            raise NotFoundError(
                f"Work package '{reference}' was not found. Semantic references like 'PROJ-123' "
                "require OpenProject 17.5+ and the exact project identifier (case-sensitive); "
                "on older instances use the numeric work-package id."
            ) from exc
        self._ensure_project_link_allowed(payload.get("_links", {}).get("project"))
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

    async def _resolve_priority_id(self, priority_ref: str) -> str:
        if priority_ref.isdigit():
            return priority_ref
        payload = await self._get("priorities")
        matches = [
            str(item["id"])
            for item in payload.get("_embedded", {}).get("elements", [])
            if str(item.get("name", "")).casefold() == priority_ref.casefold()
        ]
        if not matches:
            raise InvalidInputError(f"OpenProject priority '{priority_ref}' was not found.")
        return matches[0]

    def _validate_date_format(self, date_str: str, field_name: str) -> str:
        """Validate ISO 8601 date format (YYYY-MM-DD)."""
        import datetime

        normalized = date_str.strip()
        try:
            datetime.date.fromisoformat(normalized)
            return normalized
        except ValueError as exc:
            raise InvalidInputError(f"{field_name} must be in YYYY-MM-DD format: {exc}") from exc

    def _validate_date_range(self, dates: list[str], field_name: str) -> list[str]:
        """Validate date range has exactly 2 dates with start <= end."""
        if len(dates) != 2:
            raise InvalidInputError(f"{field_name} must contain exactly 2 dates [start, end], got {len(dates)}")
        start = self._validate_date_format(dates[0], f"{field_name}[0]")
        end = self._validate_date_format(dates[1], f"{field_name}[1]")
        if start > end:
            raise InvalidInputError(f"{field_name}: start date must be <= end date ({start} > {end})")
        return [start, end]

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


def _json_param(value: list[dict[str, Any]]) -> str:
    return json.dumps(value, separators=(",", ":"))


def _delimit_user_content(text: str | None) -> str | None:
    """Wrap user-provided text in boundary markers for prompt injection safety."""
    if text is None or not text.strip():
        return text
    return f"<user-content>{text}</user-content>"


def _origin_from_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _bulk_item_result(*, index: int, result: WorkPackageWriteResult) -> BulkWorkPackageItemResult:
    if not result.ready:
        return BulkWorkPackageItemResult(index=index, success=False, error=result.message, result=result)
    return BulkWorkPackageItemResult(index=index, success=True, error=None, result=result)


def _bulk_summary_message(*, confirm: bool, succeeded: int, failed: int, total: int, verb: str, past_tense: str) -> str:
    if confirm:
        return (
            f"{succeeded} of {total} work packages {past_tense} successfully."
            if failed == 0
            else f"{succeeded} {past_tense}, {failed} failed."
        )
    return (
        f"Validated {succeeded} of {total} work packages. Call again with confirm=true to {verb} them."
        if failed == 0
        else f"{succeeded} validated, {failed} failed validation."
    )


def _log_bulk_cancellation(
    operation: str,
    *,
    confirm: bool,
    total: int,
    item_results: list[BulkWorkPackageItemResult],
) -> None:
    """Log what is actually known about a bulk create/update call cancelled mid-loop.

    This is diagnostic logging only, for operators/support - it does not close
    the gap that the MCP caller receives no result on cancellation (a raised
    CancelledError and a normal return value are mutually exclusive). It must
    not overclaim: whether the in-flight request at the time of cancellation
    reached OpenProject is unknown, so that item is reported as "unknown
    outcome", never as succeeded/written.
    """
    completed = len(item_results)
    completed_range = f"0-{completed - 1}" if completed else "none"
    if completed < total:
        if confirm:
            in_flight_desc = (
                f"item at index {completed} has an unknown outcome (may have been in flight when "
                "cancelled; not necessarily written to OpenProject)"
            )
        else:
            in_flight_desc = (
                f"item at index {completed} has an unknown validation outcome (was in flight when "
                "cancelled); confirm=false means no item in this call could have been written to "
                "OpenProject regardless"
            )
        not_started = max(0, total - completed - 1)
    else:
        in_flight_desc = "no item was in flight (all items already had a known outcome)"
        not_started = 0
    LOGGER.warning(
        "%s cancelled (confirm=%s): %d/%d item(s) completed before cancellation (indices %s); "
        "%s; %d item(s) were not yet attempted.",
        operation,
        confirm,
        completed,
        total,
        completed_range,
        in_flight_desc,
        not_started,
    )


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


def _parse_response_json(response: httpx.Response) -> dict[str, Any]:
    try:
        return normalize_links(response.json())
    except ValueError as exc:
        raise OpenProjectServerError("OpenProject returned invalid JSON.") from exc


def _link_title(link: Any) -> str | None:
    if not isinstance(link, dict):
        return None
    title = link.get("title")
    return _trim_text(title, limit=SUBJECT_LIMIT)


def _can_update_from_links(links: dict[str, Any]) -> bool:
    """Shared `update`-or-`updateImmediately` link check repeated across several normalizers."""
    return bool(links.get("update") or links.get("updateImmediately"))


def _is_usable_positive_id(value: Any) -> bool:
    """True for a positive int; bool is excluded even though it is technically
    an int subclass. OpenProject's JSON API always emits ids as plain
    integers, matching how every other id field in this file is handled
    (e.g. ``int(payload["id"])``), so no string/numeric-string form is
    accepted here."""
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


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


def _query_ref_identity(links: dict[str, Any], payload: dict[str, Any]) -> tuple[Any, str | None, str]:
    """Shared self-link/href/id triple repeated across the 5 normalize_query_* methods."""
    self_link = links.get("self", {})
    href = self_link.get("href") if isinstance(self_link, dict) else None
    ref_id = _slug_from_href(href) or _trim_text(payload.get("id"), limit=SUBJECT_LIMIT) or ""
    return self_link, href, ref_id


# _scope_allows_all/_scope_matches_candidates: relocated to app/policies/scope.py
# (ADR 0001). Rebound here rather than rewritten as wrapper
# functions since both are pure module-level functions with no `self` — a direct
# name rebind is behaviorally identical and requires zero changes at any of the
# ~30 existing call sites across every domain.
_scope_allows_all = _scope_policy.scope_allows_all
_scope_matches_candidates = _scope_policy.scope_matches_candidates
