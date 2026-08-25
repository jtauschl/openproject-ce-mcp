from __future__ import annotations

import logging
from dataclasses import replace
from fnmatch import fnmatchcase
from typing import Any
from urllib.parse import urlparse

import httpx

from . import __version__
from .app.adapters.httpx_action_capability_api import HttpxActionCapabilityApi
from .app.adapters.httpx_activity_api import HttpxActivityApi
from .app.adapters.httpx_attachment_api import HttpxAttachmentApi
from .app.adapters.httpx_backlog_bucket_api import HttpxBacklogBucketApi
from .app.adapters.httpx_board_api import HttpxBoardApi
from .app.adapters.httpx_category_api import HttpxCategoryApi
from .app.adapters.httpx_cost_api import HttpxCostApi
from .app.adapters.httpx_current_user_api import HttpxCurrentUserApi
from .app.adapters.httpx_document_api import HttpxDocumentApi
from .app.adapters.httpx_emoji_reaction_api import HttpxEmojiReactionApi
from .app.adapters.httpx_extended_metadata_api import HttpxExtendedMetadataApi
from .app.adapters.httpx_file_link_api import HttpxFileLinkApi
from .app.adapters.httpx_github_gitlab_link_api import HttpxGithubGitlabLinkApi
from .app.adapters.httpx_grid_api import HttpxGridApi
from .app.adapters.httpx_group_api import HttpxGroupApi
from .app.adapters.httpx_instance_configuration_api import HttpxInstanceConfigurationApi
from .app.adapters.httpx_job_status_api import HttpxJobStatusApi
from .app.adapters.httpx_meeting_agenda_item_api import HttpxMeetingAgendaItemApi
from .app.adapters.httpx_meeting_api import HttpxMeetingApi
from .app.adapters.httpx_meeting_outcome_api import HttpxMeetingOutcomeApi
from .app.adapters.httpx_meeting_section_api import HttpxMeetingSectionApi
from .app.adapters.httpx_membership_api import HttpxMembershipApi
from .app.adapters.httpx_news_api import HttpxNewsApi
from .app.adapters.httpx_notification_api import HttpxNotificationApi
from .app.adapters.httpx_post_api import HttpxPostApi
from .app.adapters.httpx_principal_api import HttpxPrincipalApi
from .app.adapters.httpx_project_api import HttpxProjectApi
from .app.adapters.httpx_project_api import normalize_option_value as _normalize_option_value
from .app.adapters.httpx_project_api import normalize_project as _normalize_project
from .app.adapters.httpx_project_storage_api import HttpxProjectStorageApi
from .app.adapters.httpx_query_execution_api import HttpxQueryExecutionApi
from .app.adapters.httpx_query_metadata_api import HttpxQueryMetadataApi
from .app.adapters.httpx_recurring_meeting_api import HttpxRecurringMeetingApi
from .app.adapters.httpx_relation_api import HttpxRelationApi
from .app.adapters.httpx_reminder_api import HttpxReminderApi
from .app.adapters.httpx_role_api import HttpxRoleApi
from .app.adapters.httpx_sprint_api import HttpxSprintApi
from .app.adapters.httpx_status_priority_type_api import HttpxStatusPriorityTypeApi
from .app.adapters.httpx_storage_api import HttpxStorageApi
from .app.adapters.httpx_time_entry_api import HttpxTimeEntryApi
from .app.adapters.httpx_user_api import HttpxUserApi
from .app.adapters.httpx_user_non_working_time_api import HttpxUserNonWorkingTimeApi
from .app.adapters.httpx_user_preferences_api import HttpxUserPreferencesApi
from .app.adapters.httpx_user_working_hours_api import HttpxUserWorkingHoursApi
from .app.adapters.httpx_version_api import HttpxVersionApi
from .app.adapters.httpx_view_api import HttpxViewApi
from .app.adapters.httpx_watcher_api import HttpxWatcherApi
from .app.adapters.httpx_wiki_page_api import HttpxWikiPageApi
from .app.adapters.httpx_wiki_page_link_api import HttpxWikiPageLinkApi
from .app.adapters.httpx_work_package_api import HttpxWorkPackageApi
from .app.adapters.httpx_work_package_lookup_api import HttpxWorkPackageLookupApi
from .app.caches import SingletonCache

# AuthenticationError/PermissionDeniedError: not referenced directly in this
# module, but re-exported deliberately -- existing callers/tests import them
# from here (e.g. `from openproject_ce_mcp.client import
# PermissionDeniedError`, used by tests/integration/test_work_packages.py among
# others) and must keep working.
from .app.errors import (
    AuthenticationError,  # noqa: F401
    InvalidInputError,  # noqa: F401
    NotFoundError,  # noqa: F401
    OpenProjectError,
    OpenProjectServerError,
    PermissionDeniedError,  # noqa: F401
    TransportError,
)
from .app.pagination import (
    paginate_client as _paginate_client,  # noqa: F401 -- re-exported, test_versions_and_sprints.py imports it directly
)
from .app.pagination import (
    paginate_server as _paginate_server,  # noqa: F401 -- re-exported, test_versions_and_sprints.py imports it directly
)
from .app.policies import access as _access_policy
from .app.policies import hidden_fields as _hidden_fields_policy
from .app.policies import scope as _scope_policy
from .app.ports.action_capability_api import ActionCapabilityApi
from .app.ports.activity_api import ActivityApi
from .app.ports.attachment_api import AttachmentApi
from .app.ports.backlog_bucket_api import BacklogBucketApi
from .app.ports.board_api import BoardApi
from .app.ports.category_api import CategoryApi
from .app.ports.cost_api import CostApi
from .app.ports.current_user_api import CurrentUserApi, CurrentUserRecord
from .app.ports.document_api import DocumentApi
from .app.ports.emoji_reaction_api import EmojiReactionApi
from .app.ports.extended_metadata_api import ExtendedMetadataApi
from .app.ports.file_link_api import FileLinkApi
from .app.ports.github_gitlab_link_api import GithubGitlabLinkApi
from .app.ports.grid_api import GridApi
from .app.ports.group_api import GroupApi
from .app.ports.instance_configuration_api import InstanceConfigurationApi, InstanceConfigurationRecord
from .app.ports.job_status_api import JobStatusApi
from .app.ports.meeting_agenda_item_api import MeetingAgendaItemApi
from .app.ports.meeting_api import MeetingApi
from .app.ports.meeting_outcome_api import MeetingOutcomeApi
from .app.ports.meeting_section_api import MeetingSectionApi
from .app.ports.membership_api import MembershipApi
from .app.ports.news_api import NewsApi
from .app.ports.notification_api import NotificationApi
from .app.ports.post_api import PostApi
from .app.ports.principal_api import PrincipalApi
from .app.ports.project_api import ProjectApi
from .app.ports.project_resolution import ProjectResolutionContext
from .app.ports.project_storage_api import ProjectStorageApi
from .app.ports.query_execution_api import QueryExecutionApi
from .app.ports.query_metadata_api import QueryMetadataApi
from .app.ports.recurring_meeting_api import RecurringMeetingApi
from .app.ports.relation_api import RelationApi
from .app.ports.reminder_api import ReminderApi
from .app.ports.role_api import RoleApi
from .app.ports.sprint_api import SprintApi
from .app.ports.status_priority_type_api import PriorityRecord, StatusPriorityTypeApi, StatusRecord
from .app.ports.storage_api import StorageApi
from .app.ports.time_entry_api import TimeEntryApi
from .app.ports.user_api import UserApi
from .app.ports.user_non_working_time_api import UserNonWorkingTimeApi
from .app.ports.user_preferences_api import UserPreferencesApi
from .app.ports.user_working_hours_api import UserWorkingHoursApi
from .app.ports.version_api import VersionApi
from .app.ports.view_api import ViewApi
from .app.ports.watcher_api import WatcherApi
from .app.ports.wiki_page_api import WikiPageApi
from .app.ports.wiki_page_link_api import WikiPageLinkApi
from .app.ports.work_package_api import WorkPackageApi
from .app.ports.work_package_lookup_api import WorkPackageLookupApi
from .app.resolvers.assignee_resolver import AssigneeResolver
from .app.resolvers.current_user_resolver import CurrentUserResolver
from .app.resolvers.principal_resolver import PrincipalResolver
from .app.resolvers.project_resolver import ProjectResolver
from .app.resolvers.sprint_resolver import SprintResolver
from .app.resolvers.status_priority_type_resolver import StatusPriorityTypeResolver
from .app.resolvers.type_resolver import TypeResolver
from .app.resolvers.version_resolver import VersionResolver
from .app.resolvers.work_package_resolver import WorkPackageResolver
from .app.services.action_capability_service import ActionCapabilityService
from .app.services.activity_service import ActivityService
from .app.services.attachment_service import AttachmentService
from .app.services.backlog_bucket_service import BacklogBucketService
from .app.services.board_service import BoardService
from .app.services.category_service import CategoryService
from .app.services.cost_service import CostService
from .app.services.current_user_service import CurrentUserService
from .app.services.document_service import DocumentService
from .app.services.emoji_reaction_service import EmojiReactionService
from .app.services.extended_metadata_service import ExtendedMetadataService
from .app.services.file_link_service import FileLinkService
from .app.services.github_gitlab_link_service import GithubGitlabLinkService
from .app.services.grid_service import GridService
from .app.services.group_service import GroupService
from .app.services.instance_configuration_service import InstanceConfigurationService
from .app.services.job_status_service import JobStatusService
from .app.services.meeting_agenda_item_service import MeetingAgendaItemService
from .app.services.meeting_outcome_service import MeetingOutcomeService
from .app.services.meeting_section_service import MeetingSectionService
from .app.services.meeting_service import MeetingService
from .app.services.membership_service import MembershipService
from .app.services.news_service import NewsService
from .app.services.notification_service import NotificationService
from .app.services.post_service import PostService
from .app.services.principal_service import PrincipalService
from .app.services.project_service import CLEAR_PARENT as _PROJECT_CLEAR_PARENT
from .app.services.project_service import ProjectAdminService, ProjectService
from .app.services.project_storage_service import ProjectStorageService
from .app.services.query_execution_service import QueryExecutionService
from .app.services.query_metadata_service import QueryMetadataService
from .app.services.recurring_meeting_service import RecurringMeetingService
from .app.services.relation_service import RelationService
from .app.services.reminder_service import ReminderService
from .app.services.role_service import RoleService
from .app.services.sprint_service import SprintService
from .app.services.status_priority_type_service import StatusPriorityTypeService
from .app.services.storage_service import StorageService
from .app.services.time_entry_service import TimeEntryService
from .app.services.user_non_working_time_service import UserNonWorkingTimeService
from .app.services.user_preferences_service import UserPreferencesService
from .app.services.user_service import UserService
from .app.services.user_working_hours_service import UserWorkingHoursService
from .app.services.version_service import VersionService
from .app.services.view_service import ViewService
from .app.services.watcher_service import WatcherService
from .app.services.wiki_page_link_service import WikiPageLinkService
from .app.services.wiki_page_service import WikiPageService

# CLEAR/CLEAR_VERSION/CLEAR_PARENT are canonically defined in
# app/services/work_package_service.py (this domain's write-path migration
# moved them there) and re-exported here unchanged -- object identity is
# preserved by Python's normal import semantics, so tools_work_packages.py's
# existing `from .client import CLEAR, CLEAR_PARENT, CLEAR_VERSION` keeps
# working without any change. `CLEAR` is also still used internally below
# (Projects' write path, a DIFFERENT, unrelated sentinel from the same-named
# CLEAR_PARENT here -- Projects' own is aliased to _PROJECT_CLEAR_PARENT
# above, never conflated with this one). `_narrow_cleared` is NOT re-exported
# -- it was client.py-internal only, never imported by the tool layer, and
# the Service now has its own copy.
from .app.services.work_package_service import CLEAR, CLEAR_PARENT, CLEAR_VERSION, WorkPackageService  # noqa: F401
from .app.transport.errors import raise_for_status as _map_status_to_error
from .app.transport.httpx_transport import HttpxTransport
from .config import Settings
from .hal import normalize_links
from .models import (
    BatchWorkPackageReadResult,
    CustomOptionSummary,
    FavoriteWriteResult,
    NonWorkingDayListResult,
    OptionValue,
    ProjectAccessSummary,
    ProjectWorkPackageContext,
    ProjectWriteResult,
    RenderedText,
    WorkingDayListResult,
    WorkPackageFieldSchema,
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
ACTIVITY_DETAILS_LIMIT = 20
BATCH_READ_MAX_IDS = 100


class OpenProjectClient:
    """Small OpenProject API client with optional guarded write support."""

    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings
        self._origin = _origin_from_url(settings.base_url)
        self._api_prefix = urlparse(settings.api_base_url).path.rstrip("/") + "/"
        self._project_id_to_identifier: dict[int, str] = {}
        # Process-lifetime caches for read-only, process-global API responses
        # (see app/caches.py) -- each is shared by every real consumer of
        # that value (Service and, where one exists, Resolver alike).
        self._current_user_cache: SingletonCache[CurrentUserRecord] = SingletonCache()
        self._statuses_cache: SingletonCache[list[StatusRecord]] = SingletonCache()
        self._priorities_cache: SingletonCache[list[PriorityRecord]] = SingletonCache()
        self._instance_configuration_cache: SingletonCache[InstanceConfigurationRecord] = SingletonCache()

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

        # HttpxTransport wraps the SAME httpx.AsyncClient
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

        self._version_api: VersionApi = HttpxVersionApi(HttpxTransport(self._http))
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

        self._role_api: RoleApi = HttpxRoleApi(HttpxTransport(self._http))
        self._role_service = RoleService(api=self._role_api, settings=settings)

        self._instance_configuration_api: InstanceConfigurationApi = HttpxInstanceConfigurationApi(
            HttpxTransport(self._http)
        )
        self._instance_configuration_service = InstanceConfigurationService(
            api=self._instance_configuration_api, settings=settings, cache=self._instance_configuration_cache
        )

        self._current_user_api: CurrentUserApi = HttpxCurrentUserApi(HttpxTransport(self._http))
        self._current_user_service = CurrentUserService(
            api=self._current_user_api, settings=settings, cache=self._current_user_cache
        )
        self._current_user_resolver = CurrentUserResolver(
            api=self._current_user_api, settings=settings, cache=self._current_user_cache
        )

        self._principal_api: PrincipalApi = HttpxPrincipalApi(HttpxTransport(self._http))
        self._principal_service = PrincipalService(api=self._principal_api, settings=settings)
        self._principal_resolver = PrincipalResolver(
            api=self._principal_api, current_user=self._current_user_resolver, settings=settings
        )
        self._assignee_resolver = AssigneeResolver(current_user=self._current_user_resolver)

        self._user_api: UserApi = HttpxUserApi(HttpxTransport(self._http), base_url=settings.base_url)
        self._user_service = UserService(api=self._user_api, settings=settings)

        self._user_preferences_api: UserPreferencesApi = HttpxUserPreferencesApi(HttpxTransport(self._http))
        self._user_preferences_service = UserPreferencesService(api=self._user_preferences_api, settings=settings)

        self._group_api: GroupApi = HttpxGroupApi(HttpxTransport(self._http))
        self._group_service = GroupService(api=self._group_api, settings=settings, api_prefix=self._api_prefix)

        self._storage_api: StorageApi = HttpxStorageApi(HttpxTransport(self._http))
        self._storage_service = StorageService(api=self._storage_api, settings=settings)

        self._project_storage_api: ProjectStorageApi = HttpxProjectStorageApi(HttpxTransport(self._http))
        self._project_storage_service = ProjectStorageService(
            api=self._project_storage_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
            resolve_project_ref=self._get_project_payload,
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
            role_api=self._role_api,
            api_prefix=self._api_prefix,
        )

        self._news_api: NewsApi = HttpxNewsApi(HttpxTransport(self._http))
        self._news_service = NewsService(
            api=self._news_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
            resolve_project_ref=self._get_project_payload,
        )

        self._document_api: DocumentApi = HttpxDocumentApi(HttpxTransport(self._http))
        self._document_service = DocumentService(
            api=self._document_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
            resolve_project_ref=self._get_project_payload,
        )

        self._wiki_page_api: WikiPageApi = HttpxWikiPageApi(HttpxTransport(self._http))
        self._wiki_page_service = WikiPageService(
            api=self._wiki_page_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
        )

        self._post_api: PostApi = HttpxPostApi(HttpxTransport(self._http))
        self._post_service = PostService(
            api=self._post_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
        )

        self._category_api: CategoryApi = HttpxCategoryApi(HttpxTransport(self._http))
        self._category_service = CategoryService(
            api=self._category_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
            resolve_project_ref=self._get_project_payload,
        )

        self._view_api: ViewApi = HttpxViewApi(HttpxTransport(self._http))
        self._view_service = ViewService(
            api=self._view_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
            resolve_project_ref=self._get_project_payload,
        )

        self._sprint_api: SprintApi = HttpxSprintApi(HttpxTransport(self._http))
        self._sprint_service = SprintService(
            api=self._sprint_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
            resolve_project_ref=self._get_project_payload,
        )
        self._sprint_resolver = SprintResolver(
            api=self._sprint_api,
            resolve_project_ref=self._get_project_payload,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
        )

        self._backlog_bucket_api: BacklogBucketApi = HttpxBacklogBucketApi(HttpxTransport(self._http))
        self._backlog_bucket_service = BacklogBucketService(
            api=self._backlog_bucket_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
            resolve_project_ref=self._get_project_payload,
        )

        self._grid_api: GridApi = HttpxGridApi(HttpxTransport(self._http))
        self._grid_service = GridService(
            api=self._grid_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
        )

        self._board_api: BoardApi = HttpxBoardApi(HttpxTransport(self._http))
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
            project_id_to_identifier=self._project_id_to_identifier,
            resolve_project_ref=self._get_project_payload,
        )

        self._status_priority_type_api: StatusPriorityTypeApi = HttpxStatusPriorityTypeApi(HttpxTransport(self._http))
        self._status_priority_type_service = StatusPriorityTypeService(
            api=self._status_priority_type_api,
            settings=settings,
            resolve_project_ref=self._get_project_payload,
            statuses_cache=self._statuses_cache,
            priorities_cache=self._priorities_cache,
        )
        self._status_priority_type_resolver = StatusPriorityTypeResolver(
            api=self._status_priority_type_api,
            statuses_cache=self._statuses_cache,
            priorities_cache=self._priorities_cache,
        )
        self._type_resolver = TypeResolver(
            api=self._status_priority_type_api, resolve_project_ref=self._get_project_payload
        )

        self._query_metadata_api: QueryMetadataApi = HttpxQueryMetadataApi(
            HttpxTransport(self._http), base_url=settings.base_url, origin=self._origin
        )
        self._query_metadata_service = QueryMetadataService(
            api=self._query_metadata_api,
            settings=settings,
            resolve_project_ref=self._get_project_payload,
        )

        self._job_status_api: JobStatusApi = HttpxJobStatusApi(HttpxTransport(self._http))
        self._job_status_service = JobStatusService(
            api=self._job_status_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
            project_api=self._project_api,
        )

        self._extended_metadata_api: ExtendedMetadataApi = HttpxExtendedMetadataApi(HttpxTransport(self._http))
        self._extended_metadata_service = ExtendedMetadataService(api=self._extended_metadata_api, settings=settings)

        # Narrow reference-resolution seam (WorkPackageIdResolver/
        # WorkPackageProjectAllowedCheck) that several other app/ domains
        # depend on. Kept exactly as-is below -- see that block's own
        # comment for why.
        self._work_package_lookup_api: WorkPackageLookupApi = HttpxWorkPackageLookupApi(
            HttpxTransport(self._http), base_url=settings.base_url, api_prefix=self._api_prefix
        )
        self._work_package_resolver = WorkPackageResolver(
            api=self._work_package_lookup_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
        )

        # Domain API port/adapter for Work Packages -- covers both the READ
        # slice (list/search/get/batch/list_my_open) and the write slice
        # (create/update/delete/bulk_*/add_comment/create_subtask). A
        # separate, parallel port/adapter from work_package_lookup_api above
        # -- see app/ports/work_package_api.py's module docstring for why
        # this does NOT wrap/replace WorkPackageLookupApi, and why
        # WorkPackageResolver above stays bound to work_package_lookup_api,
        # the seam every work-package-reference-dependent domain uses.
        self._work_package_api: WorkPackageApi = HttpxWorkPackageApi(
            HttpxTransport(self._http), base_url=settings.base_url, api_prefix=self._api_prefix
        )
        # Constructed here so WorkPackageService can depend on it directly
        # for add_comment()'s reuse of the Activities normalizer, instead of
        # duplicating that logic onto WorkPackageApi.
        self._activity_api: ActivityApi = HttpxActivityApi(HttpxTransport(self._http))
        self._work_package_service = WorkPackageService(
            api=self._work_package_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
            resolve_project_ref=self._get_project_payload,
            resolve_type_id=self._type_resolver.resolve_id,
            resolve_version_id=self._resolve_version_id,
            resolve_status_id=self._status_priority_type_resolver.resolve_status_id,
            resolve_priority_id=self._status_priority_type_resolver.resolve_priority_id,
            resolve_principal_id=self._resolve_principal_id,
            resolve_assignee_id=self._assignee_resolver.resolve_id,
            resolve_sprint_id=self._sprint_resolver.resolve_id,
            resolve_work_package_id=self._work_package_resolver.resolve_id,
            status_api=self._status_priority_type_api,
            activity_api=self._activity_api,
            current_user=self._current_user_resolver,
            work_package_project_allowed=self._work_package_resolver.project_link_allowed,
            work_package_project_allowed_bulk=self._work_package_resolver.project_links_allowed,
            api_prefix=self._api_prefix,
        )

        self._file_link_api: FileLinkApi = HttpxFileLinkApi(HttpxTransport(self._http))
        self._file_link_service = FileLinkService(
            api=self._file_link_api,
            work_package_lookup_api=self._work_package_lookup_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
            resolve_work_package_id=self._work_package_resolver.resolve_id,
        )

        self._watcher_api: WatcherApi = HttpxWatcherApi(HttpxTransport(self._http), api_prefix=self._api_prefix)
        self._watcher_service = WatcherService(
            api=self._watcher_api,
            settings=settings,
            resolve_work_package_id=self._work_package_resolver.resolve_id,
        )

        self._emoji_reaction_api: EmojiReactionApi = HttpxEmojiReactionApi(HttpxTransport(self._http))
        self._emoji_reaction_service = EmojiReactionService(
            api=self._emoji_reaction_api,
            work_package_lookup_api=self._work_package_lookup_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
            resolve_work_package_id=self._work_package_resolver.resolve_id,
        )

        self._wiki_page_link_api: WikiPageLinkApi = HttpxWikiPageLinkApi(HttpxTransport(self._http))
        self._wiki_page_link_service = WikiPageLinkService(
            api=self._wiki_page_link_api,
            settings=settings,
            resolve_work_package_id=self._work_package_resolver.resolve_id,
            current_user=self._current_user_resolver,
        )

        self._user_non_working_time_api: UserNonWorkingTimeApi = HttpxUserNonWorkingTimeApi(HttpxTransport(self._http))
        self._user_non_working_time_service = UserNonWorkingTimeService(
            api=self._user_non_working_time_api, settings=settings
        )

        self._user_working_hours_api: UserWorkingHoursApi = HttpxUserWorkingHoursApi(HttpxTransport(self._http))
        self._user_working_hours_service = UserWorkingHoursService(api=self._user_working_hours_api, settings=settings)

        # Depends on self._work_package_api (constructed above) directly, to
        # normalize each raw embedded query result via its to_record() --
        # matching WorkPackageService's own precedent of depending on
        # self._activity_api directly rather than duplicating that domain's
        # normalization logic.
        self._query_execution_api: QueryExecutionApi = HttpxQueryExecutionApi(HttpxTransport(self._http))
        self._query_execution_service = QueryExecutionService(
            api=self._query_execution_api,
            work_package_api=self._work_package_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
        )

        self._reminder_api: ReminderApi = HttpxReminderApi(HttpxTransport(self._http))
        self._reminder_service = ReminderService(
            api=self._reminder_api,
            work_package_lookup_api=self._work_package_lookup_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
            resolve_work_package_id=self._work_package_resolver.resolve_id,
            work_package_project_allowed=self._work_package_resolver.project_link_allowed,
            work_package_project_allowed_bulk=self._work_package_resolver.project_links_allowed,
        )

        self._notification_api: NotificationApi = HttpxNotificationApi(HttpxTransport(self._http))
        self._notification_service = NotificationService(
            api=self._notification_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
            work_package_project_allowed=self._work_package_resolver.project_link_allowed,
            work_package_project_allowed_bulk=self._work_package_resolver.project_links_allowed,
        )

        self._relation_api: RelationApi = HttpxRelationApi(HttpxTransport(self._http))
        self._relation_service = RelationService(
            api=self._relation_api,
            work_package_lookup_api=self._work_package_lookup_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
            resolve_work_package_id=self._work_package_resolver.resolve_id,
            work_package_project_allowed=self._work_package_resolver.project_link_allowed,
            work_package_project_allowed_bulk=self._work_package_resolver.project_links_allowed,
            api_prefix=self._api_prefix,
        )

        self._time_entry_api: TimeEntryApi = HttpxTimeEntryApi(
            HttpxTransport(self._http), base_url=settings.base_url, api_prefix=self._api_prefix
        )
        self._time_entry_service = TimeEntryService(
            api=self._time_entry_api,
            project_api=self._project_api,
            user_api=self._user_api,
            work_package_lookup_api=self._work_package_lookup_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
            resolve_work_package_id=self._work_package_resolver.resolve_id,
            resolve_project_ref=self._get_project_payload,
            resolve_project_id=self._resolve_project_id,
            resolve_principal_id=self._resolve_principal_id,
            get_current_user=self._current_user_resolver,
            api_prefix=self._api_prefix,
        )

        self._cost_api: CostApi = HttpxCostApi(HttpxTransport(self._http))
        self._cost_service = CostService(
            api=self._cost_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
            resolve_work_package_id=self._work_package_resolver.resolve_id,
        )

        self._github_gitlab_link_api: GithubGitlabLinkApi = HttpxGithubGitlabLinkApi(
            HttpxTransport(self._http), text_limit=settings.text_limit
        )
        self._github_gitlab_link_service = GithubGitlabLinkService(
            api=self._github_gitlab_link_api,
            settings=settings,
            resolve_work_package_id=self._work_package_resolver.resolve_id,
        )

        self._activity_service = ActivityService(
            api=self._activity_api,
            settings=settings,
            resolve_work_package_id=self._work_package_resolver.resolve_id,
        )

        self._attachment_api: AttachmentApi = HttpxAttachmentApi(
            HttpxTransport(self._http), base_url=settings.base_url, origin=self._origin
        )
        self._attachment_service = AttachmentService(
            api=self._attachment_api,
            work_package_lookup_api=self._work_package_lookup_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
            resolve_work_package_id=self._work_package_resolver.resolve_id,
        )

        # Meetings (5 sub-resources). Meeting is constructed first --
        # the other four sub-resources have no project of their own and
        # depend on MeetingApi as a cross-domain Port to resolve their
        # allowlist check through a parent Meeting (the precedent already
        # established by WorkPackageService->ActivityApi/
        # FileLinkService->WorkPackageLookupApi).
        self._meeting_api: MeetingApi = HttpxMeetingApi(HttpxTransport(self._http))
        self._meeting_service = MeetingService(
            api=self._meeting_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
            resolve_project_ref=self._get_project_payload,
            resolve_project_id=self._resolve_project_id,
            resolve_principal_id=self._resolve_principal_id,
            api_prefix=self._api_prefix,
        )

        self._meeting_agenda_item_api: MeetingAgendaItemApi = HttpxMeetingAgendaItemApi(
            HttpxTransport(self._http), text_limit=settings.text_limit
        )
        self._meeting_agenda_item_service = MeetingAgendaItemService(
            api=self._meeting_agenda_item_api,
            meeting_api=self._meeting_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
            resolve_work_package_id=self._work_package_resolver.resolve_id,
            api_prefix=self._api_prefix,
        )

        self._meeting_section_api: MeetingSectionApi = HttpxMeetingSectionApi(HttpxTransport(self._http))
        self._meeting_section_service = MeetingSectionService(
            api=self._meeting_section_api,
            meeting_api=self._meeting_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
            api_prefix=self._api_prefix,
        )

        self._meeting_outcome_api: MeetingOutcomeApi = HttpxMeetingOutcomeApi(
            HttpxTransport(self._http), text_limit=settings.text_limit
        )
        self._meeting_outcome_service = MeetingOutcomeService(
            api=self._meeting_outcome_api,
            meeting_agenda_item_api=self._meeting_agenda_item_api,
            meeting_api=self._meeting_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
            api_prefix=self._api_prefix,
        )

        self._recurring_meeting_api: RecurringMeetingApi = HttpxRecurringMeetingApi(HttpxTransport(self._http))
        self._recurring_meeting_service = RecurringMeetingService(
            api=self._recurring_meeting_api,
            settings=settings,
            project_id_to_identifier=self._project_id_to_identifier,
            resolve_project_ref=self._get_project_payload,
            api_prefix=self._api_prefix,
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
            # Projects is genuinely OffsetPaginatedCollection server-side (verified
            # against OpenProject's own API implementation). A single bounded fetch
            # would silently skip caching the identifier of any project beyond
            # that cap, which would then fail link-based allowlist matching for
            # that project. Walk every server page instead, terminating on a
            # short page (fewer records than requested page size) rather than
            # trusting a possibly-absent/inconsistent `total` field.
            server_page_size = self.settings.max_page_size
            server_offset = 1
            seen_ids: set[int] = set()
            is_first_page = True
            while True:
                payload = await self._get(
                    "projects", params={"offset": str(server_offset), "pageSize": str(server_page_size)}
                )
                elements = payload.get("_embedded", {}).get("elements", [])
                raw_ids = (item.get("id") for item in elements if isinstance(item, dict))
                page_ids = {raw_id for raw_id in raw_ids if isinstance(raw_id, int)}
                if not is_first_page and page_ids and page_ids <= seen_ids:
                    break
                is_first_page = False
                seen_ids.update(page_ids)
                for item in elements:
                    if not isinstance(item, dict):
                        continue
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
                if len(elements) < server_page_size:
                    break
                server_offset += 1
        except OpenProjectError as exc:
            LOGGER.warning(
                "initialize: failed to fetch the project list for identifier-cache "
                "population; identifier-based allowlist matching may reject valid "
                "projects until the server is restarted and initialization succeeds: %s",
                exc,
            )

    def _remember_project_identifier(self, result: ProjectWriteResult) -> None:
        """Keep _project_id_to_identifier in sync with a just-committed create/update.

        This dict is otherwise populated exactly once, by initialize() at
        server startup -- a project created or renamed through this same
        server afterward was invisible to every link-shaped allowlist check
        (_ensure_project_link_allowed, used by every work-package/membership/
        version/etc. write and read that scopes by an embedded project link,
        which carries no identifier field) until the process restarted.
        """
        if result.state != "confirmed" or result.result is None:
            return
        identifier = result.result.identifier
        if identifier:
            self._project_id_to_identifier[result.result.id] = identifier

    async def aclose(self) -> None:
        await self._http.aclose()

    # ── Service namespace properties (OPM-394) ─────────────────────────────────
    #
    # Read-only views onto the same Service instances constructed in __init__ --
    # a named alias, not a second implementation. All call sites have migrated
    # to the namespaced form (e.g. `client.project.list(...)`); the flat
    # delegation methods this comment used to describe (e.g. a former
    # `client.list_projects(...)`) have been deleted (OPM-394) except for a
    # small number of remaining flat methods still called directly (see their
    # own docstrings/callers) or composed into a handful of multi-Service
    # convenience methods below (e.g. `get_my_project_access`,
    # `get_project_work_package_context`). Object identity with the private
    # `self._<domain>_service` attribute is enforced by
    # `test_client_service_namespaces_are_complete_and_identity_preserving` in
    # tests/test_architecture_boundaries.py, which also fails if a future Service
    # is added without a matching property here.

    @property
    def action_capability(self) -> ActionCapabilityService:
        """Same object as `self._action_capability_service` -- a named view, not a second implementation."""
        return self._action_capability_service

    @property
    def activity(self) -> ActivityService:
        """Same object as `self._activity_service` -- a named view, not a second implementation."""
        return self._activity_service

    @property
    def attachment(self) -> AttachmentService:
        """Same object as `self._attachment_service` -- a named view, not a second implementation."""
        return self._attachment_service

    @property
    def backlog_bucket(self) -> BacklogBucketService:
        """Same object as `self._backlog_bucket_service` -- a named view, not a second implementation."""
        return self._backlog_bucket_service

    @property
    def board(self) -> BoardService:
        """Same object as `self._board_service` -- a named view, not a second implementation."""
        return self._board_service

    @property
    def category(self) -> CategoryService:
        """Same object as `self._category_service` -- a named view, not a second implementation."""
        return self._category_service

    @property
    def cost(self) -> CostService:
        """Same object as `self._cost_service` -- a named view, not a second implementation."""
        return self._cost_service

    @property
    def current_user(self) -> CurrentUserService:
        """Same object as `self._current_user_service` -- a named view, not a second implementation."""
        return self._current_user_service

    @property
    def document(self) -> DocumentService:
        """Same object as `self._document_service` -- a named view, not a second implementation."""
        return self._document_service

    @property
    def emoji_reaction(self) -> EmojiReactionService:
        """Same object as `self._emoji_reaction_service` -- a named view, not a second implementation."""
        return self._emoji_reaction_service

    @property
    def extended_metadata(self) -> ExtendedMetadataService:
        """Same object as `self._extended_metadata_service` -- a named view, not a second implementation."""
        return self._extended_metadata_service

    @property
    def file_link(self) -> FileLinkService:
        """Same object as `self._file_link_service` -- a named view, not a second implementation."""
        return self._file_link_service

    @property
    def github_gitlab_link(self) -> GithubGitlabLinkService:
        """Same object as `self._github_gitlab_link_service` -- a named view, not a second implementation."""
        return self._github_gitlab_link_service

    @property
    def grid(self) -> GridService:
        """Same object as `self._grid_service` -- a named view, not a second implementation."""
        return self._grid_service

    @property
    def group(self) -> GroupService:
        """Same object as `self._group_service` -- a named view, not a second implementation."""
        return self._group_service

    @property
    def instance_configuration(self) -> InstanceConfigurationService:
        """Same object as `self._instance_configuration_service` -- a named view, not a second implementation."""
        return self._instance_configuration_service

    @property
    def job_status(self) -> JobStatusService:
        """Same object as `self._job_status_service` -- a named view, not a second implementation."""
        return self._job_status_service

    @property
    def meeting(self) -> MeetingService:
        """Same object as `self._meeting_service` -- a named view, not a second implementation."""
        return self._meeting_service

    @property
    def meeting_agenda_item(self) -> MeetingAgendaItemService:
        """Same object as `self._meeting_agenda_item_service` -- a named view, not a second implementation."""
        return self._meeting_agenda_item_service

    @property
    def meeting_outcome(self) -> MeetingOutcomeService:
        """Same object as `self._meeting_outcome_service` -- a named view, not a second implementation."""
        return self._meeting_outcome_service

    @property
    def meeting_section(self) -> MeetingSectionService:
        """Same object as `self._meeting_section_service` -- a named view, not a second implementation."""
        return self._meeting_section_service

    @property
    def membership(self) -> MembershipService:
        """Same object as `self._membership_service` -- a named view, not a second implementation."""
        return self._membership_service

    @property
    def news(self) -> NewsService:
        """Same object as `self._news_service` -- a named view, not a second implementation."""
        return self._news_service

    @property
    def notification(self) -> NotificationService:
        """Same object as `self._notification_service` -- a named view, not a second implementation."""
        return self._notification_service

    @property
    def post(self) -> PostService:
        """Same object as `self._post_service` -- a named view, not a second
        implementation. Named after OpenProject's "Post" (forum message) domain,
        not the HTTP POST method -- see PostService for its actual operations.
        """
        return self._post_service

    @property
    def principal(self) -> PrincipalService:
        """Same object as `self._principal_service` -- a named view, not a second implementation."""
        return self._principal_service

    @property
    def project(self) -> ProjectService:
        """Same object as `self._project_service` -- a named view, not a second implementation."""
        return self._project_service

    @property
    def project_admin(self) -> ProjectAdminService:
        """Same object as `self._project_admin_service` -- a named view, not a second implementation."""
        return self._project_admin_service

    @property
    def project_storage(self) -> ProjectStorageService:
        """Same object as `self._project_storage_service` -- a named view, not a second implementation."""
        return self._project_storage_service

    @property
    def query_execution(self) -> QueryExecutionService:
        """Same object as `self._query_execution_service` -- a named view, not a second implementation."""
        return self._query_execution_service

    @property
    def query_metadata(self) -> QueryMetadataService:
        """Same object as `self._query_metadata_service` -- a named view, not a second implementation."""
        return self._query_metadata_service

    @property
    def recurring_meeting(self) -> RecurringMeetingService:
        """Same object as `self._recurring_meeting_service` -- a named view, not a second implementation."""
        return self._recurring_meeting_service

    @property
    def relation(self) -> RelationService:
        """Same object as `self._relation_service` -- a named view, not a second implementation."""
        return self._relation_service

    @property
    def reminder(self) -> ReminderService:
        """Same object as `self._reminder_service` -- a named view, not a second implementation."""
        return self._reminder_service

    @property
    def role(self) -> RoleService:
        """Same object as `self._role_service` -- a named view, not a second implementation."""
        return self._role_service

    @property
    def sprint(self) -> SprintService:
        """Same object as `self._sprint_service` -- a named view, not a second implementation."""
        return self._sprint_service

    @property
    def status_priority_type(self) -> StatusPriorityTypeService:
        """Same object as `self._status_priority_type_service` -- a named view, not a second implementation."""
        return self._status_priority_type_service

    @property
    def storage(self) -> StorageService:
        """Same object as `self._storage_service` -- a named view, not a second implementation."""
        return self._storage_service

    @property
    def time_entry(self) -> TimeEntryService:
        """Same object as `self._time_entry_service` -- a named view, not a second implementation."""
        return self._time_entry_service

    @property
    def user(self) -> UserService:
        """Same object as `self._user_service` -- a named view, not a second implementation."""
        return self._user_service

    @property
    def user_non_working_time(self) -> UserNonWorkingTimeService:
        """Same object as `self._user_non_working_time_service` -- a named view, not a second implementation."""
        return self._user_non_working_time_service

    @property
    def user_preferences(self) -> UserPreferencesService:
        """Same object as `self._user_preferences_service` -- a named view, not a second implementation."""
        return self._user_preferences_service

    @property
    def user_working_hours(self) -> UserWorkingHoursService:
        """Same object as `self._user_working_hours_service` -- a named view, not a second implementation."""
        return self._user_working_hours_service

    @property
    def version(self) -> VersionService:
        """Same object as `self._version_service` -- a named view, not a second implementation."""
        return self._version_service

    @property
    def view(self) -> ViewService:
        """Same object as `self._view_service` -- a named view, not a second implementation."""
        return self._view_service

    @property
    def watcher(self) -> WatcherService:
        """Same object as `self._watcher_service` -- a named view, not a second implementation."""
        return self._watcher_service

    @property
    def wiki_page(self) -> WikiPageService:
        """Same object as `self._wiki_page_service` -- a named view, not a second implementation."""
        return self._wiki_page_service

    @property
    def wiki_page_link(self) -> WikiPageLinkService:
        """Same object as `self._wiki_page_link_service` -- a named view, not a second implementation."""
        return self._wiki_page_link_service

    @property
    def work_package(self) -> WorkPackageService:
        """Same object as `self._work_package_service` -- a named view, not a second implementation."""
        return self._work_package_service

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
        result = await self._project_service.create(
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
        self._remember_project_identifier(result)
        return result

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
        result = await self._project_service.update(
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
        self._remember_project_identifier(result)
        return result

    async def get_my_project_access(self, project_ref: str) -> ProjectAccessSummary:
        self._ensure_read_enabled("project")
        self._ensure_read_enabled("membership")
        self._ensure_read_enabled("principal")
        current_user = await self.current_user.get_current_user()
        project_payload = await self._resolve_project_ref(project_ref, write=False)
        project_summary = _hidden_fields_policy.apply_hidden_fields(
            "project",
            _normalize_project(project_payload, text_limit=self.settings.text_limit),
            settings=self.settings,
        )
        memberships = await self.membership.list_for_project(project_ref)
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
            _normalize_option_value(item) for item in types_payload.get("_embedded", {}).get("elements", [])
        ]

        selected_type_id: int | None = None
        selected_type_name: str | None = None
        fields: list[WorkPackageFieldSchema] = []
        custom_fields: list[WorkPackageFieldSchema] = []
        available_statuses: list[OptionValue] = [
            _normalize_option_value(item)
            for item in (await self._get("statuses")).get("_embedded", {}).get("elements", [])
        ]
        available_priorities: list[OptionValue] = [
            _normalize_option_value(item)
            for item in (await self._get("priorities")).get("_embedded", {}).get("elements", [])
        ]
        available_categories: list[OptionValue] = [
            _normalize_option_value(item)
            for item in (await self._get(f"projects/{project_id}/categories")).get("_embedded", {}).get("elements", [])
        ]
        available_project_phases: list[OptionValue] = []
        versions = await self.version.list(project=str(project_id), offset=1, limit=self.settings.max_results)

        if type is not None:
            selected_type_id = int(await self._type_resolver.resolve_id(type, project=str(project_id)))
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
        return await self._work_package_service.get_batch(ids=ids, text_limit=text_limit)

    async def _set_project_favorite(self, project: str, *, favorite: bool, confirm: bool) -> FavoriteWriteResult:
        return await self._project_service.set_favorite(project, favorite=favorite, confirm=confirm)

    async def add_project_favorite(self, *, project: str, confirm: bool = False) -> FavoriteWriteResult:
        return await self._set_project_favorite(project, favorite=True, confirm=confirm)

    async def remove_project_favorite(self, *, project: str, confirm: bool = False) -> FavoriteWriteResult:
        return await self._set_project_favorite(project, favorite=False, confirm=confirm)

    # --- Statuses ---

    # --- Text Rendering ---

    async def render_text(self, *, text: str, format: str = "markdown") -> RenderedText:
        """Render plain or markdown text to HTML via the OpenProject API."""
        return await self._extended_metadata_service.render_text(text=text, format=format)

    # --- Help Texts ---

    async def list_working_days(self) -> WorkingDayListResult:
        """List the Mon–Sun working-day configuration (7 entries)."""
        return await self._extended_metadata_service.list_working_days()

    async def list_non_working_days(self, *, year: int | None = None) -> NonWorkingDayListResult:
        """List non-working days (public holidays / closures) for the given year."""
        return await self._extended_metadata_service.list_non_working_days(year=year)

    # --- Custom Options ---

    async def get_custom_option(self, custom_option_id: int) -> CustomOptionSummary:
        """Fetch a single custom field option value by id."""
        return await self._extended_metadata_service.get_custom_option(custom_option_id)

    # --- Relations (update + global list) ---

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

    def _normalize_field_schema(self, key: str, payload: dict[str, Any]) -> WorkPackageFieldSchema:
        allowed_values = payload.get("_embedded", {}).get("allowedValues", [])
        normalized_allowed_values = [_normalize_option_value(item) for item in allowed_values if isinstance(item, dict)]
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

    def _ensure_read_enabled(self, scope: str) -> None:
        _access_policy.ensure_read_enabled(scope, settings=self.settings)

    def _normalize_hide_token(self, value: str) -> str:
        return _hidden_fields_policy.normalize_hide_token(value)

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

    def _apply_hidden_fields(self, entity: str, value: Any) -> Any:
        """Tag a result dataclass with the field names hidden for its entity.

        The names are stamped as a private ``_hidden_keys`` attribute (not a
        dataclass field, so it never appears in the schema/output). The
        serialization seam (presentation._to_payload) reads it and drops those
        keys entirely from the response — hidden fields cost neither their key
        name nor a null value. Stamping is possible because the response
        dataclasses are not frozen.
        """
        return _hidden_fields_policy.apply_hidden_fields(entity, value, settings=self.settings)

    def _api_href(self, relative_path: str) -> str:
        return f"/{self._api_prefix.lstrip('/')}{relative_path.lstrip('/')}"

    async def _resolve_project_id(self, project_ref: str, *, write: bool = False) -> str:
        return await self._project_resolver.resolve_id(project_ref, write=write)

    async def _resolve_principal_id(self, principal_ref: str) -> str:
        return await self._principal_resolver.resolve_id(principal_ref)

    async def _resolve_version_id(
        self, version_ref: str, *, project: str | None = None, context: ProjectResolutionContext | None = None
    ) -> str:
        return await self._version_resolver.resolve_id(version_ref, project=project, context=context)


def _origin_from_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _trim_text(value: Any, *, limit: int) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _parse_response_json(response: httpx.Response) -> dict[str, Any]:
    try:
        return normalize_links(response.json())
    except ValueError as exc:
        raise OpenProjectServerError("OpenProject returned invalid JSON.") from exc


# _scope_allows_all/_scope_matches_candidates: relocated to app/policies/scope.py.
# Rebound here rather than rewritten as wrapper
# functions since both are pure module-level functions with no `self` — a direct
# name rebind is behaviorally identical and requires zero changes at any of the
# ~30 existing call sites across every domain.
_scope_allows_all = _scope_policy.scope_allows_all
_scope_matches_candidates = _scope_policy.scope_matches_candidates
