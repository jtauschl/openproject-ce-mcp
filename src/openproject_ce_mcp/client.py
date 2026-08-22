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
from .app.ports.project_resolution import ProjectResolutionContext, WorkPackageResolutionContext
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
# preserved by Python's normal import semantics, so tools.py's existing
# `from .client import CLEAR, CLEAR_PARENT, CLEAR_VERSION` keeps working
# without any change. `CLEAR` is also still used internally below (Projects'
# write path, a DIFFERENT, unrelated sentinel from the same-named
# CLEAR_PARENT here -- Projects' own is aliased to _PROJECT_CLEAR_PARENT
# above, never conflated with this one). `_narrow_cleared` is NOT re-exported
# -- it was client.py-internal only, never imported by tools.py, and the
# Service now has its own copy.
from .app.services.work_package_service import CLEAR, CLEAR_PARENT, CLEAR_VERSION, WorkPackageService  # noqa: F401
from .app.transport.errors import raise_for_status as _map_status_to_error
from .app.transport.httpx_transport import HttpxTransport
from .config import Settings
from .hal import normalize_links
from .models import (
    ActionListResult,
    ActivityListResult,
    ActivityWriteResult,
    AttachmentListResult,
    AttachmentSummary,
    AttachmentWriteResult,
    BacklogBucketDetail,
    BacklogBucketListResult,
    BatchWorkPackageReadResult,
    BoardDetail,
    BoardListResult,
    BoardWriteResult,
    BulkWorkPackageWriteResult,
    CapabilityListResult,
    CategoryListResult,
    CategorySummary,
    CostEntryListResult,
    CostEntrySummary,
    CostTypeSummary,
    CurrentUser,
    CustomOptionSummary,
    DocumentDetail,
    DocumentListResult,
    DocumentWriteResult,
    EmojiReactionListResult,
    EmojiReactionWriteResult,
    FavoriteWriteResult,
    FileLinkListResult,
    FileLinkWriteResult,
    GithubPullRequestListResult,
    GithubPullRequestSummary,
    GitlabIssueListResult,
    GitlabMergeRequestListResult,
    GridListResult,
    GridSummary,
    GridWriteResult,
    GroupDetail,
    GroupListResult,
    GroupWriteResult,
    HelpTextListResult,
    HelpTextSummary,
    InstanceConfiguration,
    JobStatusDetail,
    MeetingAgendaItemListResult,
    MeetingAgendaItemSummary,
    MeetingAgendaItemWriteResult,
    MeetingListResult,
    MeetingOutcomeListResult,
    MeetingOutcomeSummary,
    MeetingOutcomeWriteResult,
    MeetingSectionListResult,
    MeetingSectionSummary,
    MeetingSectionWriteResult,
    MeetingSummary,
    MeetingWriteResult,
    MembershipListResult,
    MembershipSummary,
    MembershipWriteResult,
    NewsDetail,
    NewsListResult,
    NewsWriteResult,
    NonWorkingDayListResult,
    NotificationListResult,
    NotificationMarkResult,
    OptionValue,
    PostDetail,
    PrincipalListResult,
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
    ProjectStorageDetail,
    ProjectStorageListResult,
    ProjectWorkPackageContext,
    ProjectWriteResult,
    QueryColumnSummary,
    QueryFilterInstanceSchemaListResult,
    QueryFilterInstanceSchemaSummary,
    QueryFilterSummary,
    QueryOperatorSummary,
    QuerySortBySummary,
    RecurringMeetingListResult,
    RecurringMeetingOccurrenceListResult,
    RecurringMeetingOccurrenceWriteResult,
    RecurringMeetingSummary,
    RecurringMeetingWriteResult,
    RelationListResult,
    RelationUpdateResult,
    RelationWriteResult,
    ReminderListResult,
    ReminderWriteResult,
    RenderedText,
    RoleListResult,
    SortCriterion,
    SprintDetail,
    SprintListResult,
    StatusListResult,
    StatusSummary,
    StorageDetail,
    StorageListResult,
    StorageWriteResult,
    TimeEntryActivityListResult,
    TimeEntryListResult,
    TimeEntrySummary,
    TimeEntryWriteResult,
    TypeListResult,
    TypeSummary,
    UserDetail,
    UserListResult,
    UserNonWorkingTimeListResult,
    UserNonWorkingTimeWriteResult,
    UserPreferences,
    UserPreferencesWriteResult,
    UserWorkingHoursListResult,
    UserWorkingHoursSummary,
    UserWorkingHoursWriteResult,
    UserWriteResult,
    VersionDetail,
    VersionListResult,
    VersionWriteResult,
    ViewDetail,
    ViewListResult,
    WatcherListResult,
    WatcherWriteResult,
    WikiPageDetail,
    WikiPageLinkListResult,
    WikiPageLinkWriteResult,
    WorkingDayListResult,
    WorkPackageCostsByTypeResult,
    WorkPackageDetail,
    WorkPackageFieldSchema,
    WorkPackageListResult,
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

    async def get_job_status(self, job_status_id: str) -> JobStatusDetail:
        return await self._job_status_service.get(job_status_id)

    async def list_roles(self, *, offset: int = 1, limit: int | None = None) -> RoleListResult:
        return await self._role_service.list_roles(offset=offset, limit=limit)

    async def list_principals(
        self,
        *,
        search: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> PrincipalListResult:
        return await self._principal_service.list_principals(search=search, offset=offset, limit=limit)

    async def list_users(
        self,
        *,
        search: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> UserListResult:
        return await self._user_service.list_users(search=search, offset=offset, limit=limit)

    async def get_user(self, user_ref: str) -> UserDetail:
        return await self._user_service.get_user(user_ref)

    async def list_groups(
        self,
        *,
        search: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> GroupListResult:
        return await self._group_service.list_groups(search=search, offset=offset, limit=limit)

    async def get_group(self, group_id: int) -> GroupDetail:
        return await self._group_service.get_group(group_id)

    async def list_storages(self, *, offset: int = 1, limit: int | None = None) -> StorageListResult:
        return await self._storage_service.list_storages(offset=offset, limit=limit)

    async def get_storage(self, storage_id: int) -> StorageDetail:
        return await self._storage_service.get_storage(storage_id)

    async def list_project_storages(
        self, *, project: str | None = None, offset: int = 1, limit: int | None = None
    ) -> ProjectStorageListResult:
        return await self._project_storage_service.list_project_storages(project=project, offset=offset, limit=limit)

    async def get_project_storage(self, project_storage_id: int) -> ProjectStorageDetail:
        return await self._project_storage_service.get_project_storage(project_storage_id)

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
        return await self._query_metadata_service.get_filter(filter_id)

    async def get_query_column(self, column_id: str) -> QueryColumnSummary:
        return await self._query_metadata_service.get_column(column_id)

    async def get_query_operator(self, operator_id: str) -> QueryOperatorSummary:
        return await self._query_metadata_service.get_operator(operator_id)

    async def get_query_sort_by(self, sort_by_id: str) -> QuerySortBySummary:
        return await self._query_metadata_service.get_sort_by(sort_by_id)

    async def list_query_filter_instance_schemas(
        self,
        *,
        project: str | None = None,
    ) -> QueryFilterInstanceSchemaListResult:
        return await self._query_metadata_service.list_filter_instance_schemas(project=project)

    async def get_query_filter_instance_schema(self, schema_id: str) -> QueryFilterInstanceSchemaSummary:
        return await self._query_metadata_service.get_filter_instance_schema(schema_id)

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

    # --- Cross-service coordinator -------------------------------------------
    # get_my_project_access and get_project_work_package_context (further below)
    # are the ONLY public methods on this class that are not pure one-line
    # delegations to a single Service. Each combines several already-migrated
    # Services/policies into one response shape that no single Service owns.
    # Every other public method here stays a pure
    # `return await self._x_service.method(...)` delegation -- a new method
    # needing more than that belongs alongside these two, explicitly, not
    # silently mixed into the delegation methods around it.
    async def get_my_project_access(self, project_ref: str) -> ProjectAccessSummary:
        self._ensure_read_enabled("project")
        self._ensure_read_enabled("membership")
        self._ensure_read_enabled("principal")
        current_user = await self.get_current_user()
        project_payload = await self._resolve_project_ref(project_ref, write=False)
        project_summary = _hidden_fields_policy.apply_hidden_fields(
            "project",
            _normalize_project(project_payload, text_limit=self.settings.text_limit),
            settings=self.settings,
        )
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
        return await self._instance_configuration_service.get_instance_configuration()

    async def list_project_phase_definitions(self) -> ProjectPhaseDefinitionListResult:
        return await self._project_service.list_phase_definitions()

    async def get_project_phase_definition(self, phase_definition_id: int) -> ProjectPhaseDefinition:
        return await self._project_service.get_phase_definition(phase_definition_id)

    async def get_project_phase(self, phase_id: int) -> ProjectPhase:
        return await self._project_service.get_phase(phase_id)

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
        text_limit: int | None = None,
    ) -> DocumentListResult:
        return await self._document_service.list(
            project=project, search=search, offset=offset, limit=limit, text_limit=text_limit
        )

    async def get_document(self, document_id: int, *, text_limit: int | None = None) -> DocumentDetail:
        return await self._document_service.get(document_id, text_limit=text_limit)

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
        text_limit: int | None = None,
    ) -> NewsListResult:
        return await self._news_service.list(
            project=project, search=search, offset=offset, limit=limit, text_limit=text_limit
        )

    async def get_news(self, news_id: int, *, text_limit: int | None = None) -> NewsDetail:
        return await self._news_service.get(news_id, text_limit=text_limit)

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

    async def get_post(self, post_id: int) -> PostDetail:
        return await self._post_service.get(post_id)

    async def list_work_package_wiki_links(
        self, work_package_id: int | str, *, offset: int = 1, limit: int | None = None
    ) -> WikiPageLinkListResult:
        return await self._wiki_page_link_service.list_for_work_package(work_package_id, offset=offset, limit=limit)

    async def create_work_package_wiki_link(
        self,
        work_package_id: int | str,
        *,
        identifier: str,
        provider: str,
        confirm: bool = False,
    ) -> WikiPageLinkWriteResult:
        return await self._wiki_page_link_service.create(
            work_package_id, identifier=identifier, provider=provider, confirm=confirm
        )

    async def delete_work_package_wiki_link(
        self, work_package_id: int | str, link_id: int, *, confirm: bool = False
    ) -> WikiPageLinkWriteResult:
        return await self._wiki_page_link_service.delete(work_package_id, link_id, confirm=confirm)

    # --- Meetings ---

    async def list_meetings(
        self, *, project: str | None = None, offset: int = 1, limit: int | None = None
    ) -> MeetingListResult:
        return await self._meeting_service.list_all(project=project, offset=offset, limit=limit)

    async def get_meeting(self, meeting_id: int) -> MeetingSummary:
        return await self._meeting_service.get(meeting_id)

    async def create_meeting(
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
        return await self._meeting_service.create(
            project=project,
            title=title,
            location=location,
            start_time=start_time,
            duration=duration,
            state=state,
            sharing=sharing,
            notify=notify,
            participant_user_refs=participant_user_refs,
            confirm=confirm,
        )

    async def update_meeting(
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
        return await self._meeting_service.update(
            meeting_id=meeting_id,
            title=title,
            location=location,
            start_time=start_time,
            duration=duration,
            state=state,
            sharing=sharing,
            notify=notify,
            participant_user_refs=participant_user_refs,
            lock_version=lock_version,
            confirm=confirm,
        )

    async def delete_meeting(self, *, meeting_id: int, confirm: bool = False) -> MeetingWriteResult:
        return await self._meeting_service.delete(meeting_id=meeting_id, confirm=confirm)

    async def list_meeting_agenda_items(
        self, meeting_id: int, *, offset: int = 1, limit: int | None = None, text_limit: int | None = None
    ) -> MeetingAgendaItemListResult:
        return await self._meeting_agenda_item_service.list_for_meeting(
            meeting_id, offset=offset, limit=limit, text_limit=text_limit
        )

    async def list_work_package_meeting_agenda_items(
        self,
        work_package_id: int | str,
        *,
        offset: int = 1,
        limit: int | None = None,
        text_limit: int | None = None,
    ) -> MeetingAgendaItemListResult:
        return await self._meeting_agenda_item_service.list_for_work_package(
            work_package_id, offset=offset, limit=limit, text_limit=text_limit
        )

    async def get_meeting_agenda_item(self, agenda_item_id: int) -> MeetingAgendaItemSummary:
        return await self._meeting_agenda_item_service.get(agenda_item_id)

    async def create_meeting_agenda_item(
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
        return await self._meeting_agenda_item_service.create(
            meeting_id=meeting_id,
            title=title,
            notes=notes,
            duration_in_minutes=duration_in_minutes,
            item_type=item_type,
            work_package_id=work_package_id,
            meeting_section_id=meeting_section_id,
            confirm=confirm,
        )

    async def update_meeting_agenda_item(
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
        return await self._meeting_agenda_item_service.update(
            agenda_item_id=agenda_item_id,
            title=title,
            notes=notes,
            duration_in_minutes=duration_in_minutes,
            item_type=item_type,
            work_package_id=work_package_id,
            meeting_section_id=meeting_section_id,
            confirm=confirm,
        )

    async def delete_meeting_agenda_item(
        self, *, agenda_item_id: int, confirm: bool = False
    ) -> MeetingAgendaItemWriteResult:
        return await self._meeting_agenda_item_service.delete(agenda_item_id=agenda_item_id, confirm=confirm)

    async def list_meeting_outcomes(
        self, agenda_item_id: int, *, offset: int = 1, limit: int | None = None, text_limit: int | None = None
    ) -> MeetingOutcomeListResult:
        return await self._meeting_outcome_service.list_for_agenda_item(
            agenda_item_id, offset=offset, limit=limit, text_limit=text_limit
        )

    async def get_meeting_outcome(self, outcome_id: int) -> MeetingOutcomeSummary:
        return await self._meeting_outcome_service.get(outcome_id)

    async def create_meeting_outcome(
        self,
        *,
        agenda_item_id: int,
        kind: str,
        notes: str | None = None,
        work_package_id: int | None = None,
        confirm: bool = False,
    ) -> MeetingOutcomeWriteResult:
        return await self._meeting_outcome_service.create(
            agenda_item_id=agenda_item_id, kind=kind, notes=notes, work_package_id=work_package_id, confirm=confirm
        )

    async def update_meeting_outcome(
        self,
        *,
        outcome_id: int,
        kind: str | None = None,
        notes: str | None = None,
        work_package_id: int | None = None,
        confirm: bool = False,
    ) -> MeetingOutcomeWriteResult:
        return await self._meeting_outcome_service.update(
            outcome_id=outcome_id, kind=kind, notes=notes, work_package_id=work_package_id, confirm=confirm
        )

    async def delete_meeting_outcome(self, *, outcome_id: int, confirm: bool = False) -> MeetingOutcomeWriteResult:
        return await self._meeting_outcome_service.delete(outcome_id=outcome_id, confirm=confirm)

    async def list_meeting_sections(
        self, meeting_id: int, *, offset: int = 1, limit: int | None = None
    ) -> MeetingSectionListResult:
        return await self._meeting_section_service.list_for_meeting(meeting_id, offset=offset, limit=limit)

    async def get_meeting_section(self, section_id: int) -> MeetingSectionSummary:
        return await self._meeting_section_service.get(section_id)

    async def create_meeting_section(
        self,
        *,
        meeting_id: int,
        title: str,
        position: int | None = None,
        backlog: bool | None = None,
        confirm: bool = False,
    ) -> MeetingSectionWriteResult:
        return await self._meeting_section_service.create(
            meeting_id=meeting_id, title=title, position=position, backlog=backlog, confirm=confirm
        )

    async def update_meeting_section(
        self,
        *,
        section_id: int,
        title: str | None = None,
        position: int | None = None,
        confirm: bool = False,
    ) -> MeetingSectionWriteResult:
        return await self._meeting_section_service.update(
            section_id=section_id, title=title, position=position, confirm=confirm
        )

    async def delete_meeting_section(self, *, section_id: int, confirm: bool = False) -> MeetingSectionWriteResult:
        return await self._meeting_section_service.delete(section_id=section_id, confirm=confirm)

    async def list_recurring_meetings(
        self, *, project: str | None = None, offset: int = 1, limit: int | None = None
    ) -> RecurringMeetingListResult:
        return await self._recurring_meeting_service.list_all(project=project, offset=offset, limit=limit)

    async def get_recurring_meeting(self, recurring_meeting_id: int) -> RecurringMeetingSummary:
        return await self._recurring_meeting_service.get(recurring_meeting_id)

    async def create_recurring_meeting(
        self,
        *,
        project: str,
        title: str,
        frequency: str,
        start_time: str,
        interval: int | None = None,
        end_after: str | None = None,
        end_date: str | None = None,
        iterations: int | None = None,
        monthly_day: int | None = None,
        monthly_ordinal: str | None = None,
        monthly_weekday: str | None = None,
        confirm: bool = False,
    ) -> RecurringMeetingWriteResult:
        return await self._recurring_meeting_service.create(
            project=project,
            title=title,
            frequency=frequency,
            start_time=start_time,
            interval=interval,
            end_after=end_after,
            end_date=end_date,
            iterations=iterations,
            monthly_day=monthly_day,
            monthly_ordinal=monthly_ordinal,
            monthly_weekday=monthly_weekday,
            confirm=confirm,
        )

    async def update_recurring_meeting(
        self,
        *,
        recurring_meeting_id: int,
        title: str | None = None,
        frequency: str | None = None,
        start_time: str | None = None,
        interval: int | None = None,
        end_after: str | None = None,
        end_date: str | None = None,
        iterations: int | None = None,
        confirm: bool = False,
    ) -> RecurringMeetingWriteResult:
        return await self._recurring_meeting_service.update(
            recurring_meeting_id=recurring_meeting_id,
            title=title,
            frequency=frequency,
            start_time=start_time,
            interval=interval,
            end_after=end_after,
            end_date=end_date,
            iterations=iterations,
            confirm=confirm,
        )

    async def delete_recurring_meeting(
        self, *, recurring_meeting_id: int, confirm: bool = False
    ) -> RecurringMeetingWriteResult:
        return await self._recurring_meeting_service.delete(recurring_meeting_id=recurring_meeting_id, confirm=confirm)

    async def list_recurring_meeting_occurrences(
        self, recurring_meeting_id: int, *, filter: str = "upcoming", limit: int | None = None
    ) -> RecurringMeetingOccurrenceListResult:
        return await self._recurring_meeting_service.list_occurrences(recurring_meeting_id, filter=filter, limit=limit)

    async def init_recurring_meeting_occurrence(
        self, *, recurring_meeting_id: int, start_time: str, confirm: bool = False
    ) -> RecurringMeetingOccurrenceWriteResult:
        return await self._recurring_meeting_service.init_occurrence(
            recurring_meeting_id=recurring_meeting_id, start_time=start_time, confirm=confirm
        )

    async def cancel_recurring_meeting_occurrence(
        self, *, recurring_meeting_id: int, start_time: str, confirm: bool = False
    ) -> RecurringMeetingOccurrenceWriteResult:
        return await self._recurring_meeting_service.cancel_occurrence(
            recurring_meeting_id=recurring_meeting_id, start_time=start_time, confirm=confirm
        )

    async def list_user_non_working_times(
        self, user_ref: str, *, year: int | None = None, offset: int = 1, limit: int | None = None
    ) -> UserNonWorkingTimeListResult:
        return await self._user_non_working_time_service.list_for_user(user_ref, year=year, offset=offset, limit=limit)

    async def create_user_non_working_time(
        self, user_ref: str, *, start_date: str, end_date: str, confirm: bool = False
    ) -> UserNonWorkingTimeWriteResult:
        return await self._user_non_working_time_service.create(
            user_ref, start_date=start_date, end_date=end_date, confirm=confirm
        )

    async def update_user_non_working_time(
        self,
        user_ref: str,
        non_working_time_id: int,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        confirm: bool = False,
    ) -> UserNonWorkingTimeWriteResult:
        return await self._user_non_working_time_service.update(
            user_ref, non_working_time_id, start_date=start_date, end_date=end_date, confirm=confirm
        )

    async def delete_user_non_working_time(
        self, user_ref: str, non_working_time_id: int, *, confirm: bool = False
    ) -> UserNonWorkingTimeWriteResult:
        return await self._user_non_working_time_service.delete(user_ref, non_working_time_id, confirm=confirm)

    async def list_user_working_hours(
        self, user_ref: str, *, offset: int = 1, limit: int | None = None
    ) -> UserWorkingHoursListResult:
        return await self._user_working_hours_service.list_for_user(user_ref, offset=offset, limit=limit)

    async def get_user_working_hours(self, user_ref: str, working_hours_id: int) -> UserWorkingHoursSummary:
        return await self._user_working_hours_service.get(user_ref, working_hours_id)

    async def create_user_working_hours(
        self,
        user_ref: str,
        *,
        valid_from: str,
        monday_hours: float | None = None,
        tuesday_hours: float | None = None,
        wednesday_hours: float | None = None,
        thursday_hours: float | None = None,
        friday_hours: float | None = None,
        saturday_hours: float | None = None,
        sunday_hours: float | None = None,
        availability_factor: float | None = None,
        confirm: bool = False,
    ) -> UserWorkingHoursWriteResult:
        return await self._user_working_hours_service.create(
            user_ref,
            valid_from=valid_from,
            monday_hours=monday_hours,
            tuesday_hours=tuesday_hours,
            wednesday_hours=wednesday_hours,
            thursday_hours=thursday_hours,
            friday_hours=friday_hours,
            saturday_hours=saturday_hours,
            sunday_hours=sunday_hours,
            availability_factor=availability_factor,
            confirm=confirm,
        )

    async def update_user_working_hours(
        self,
        user_ref: str,
        working_hours_id: int,
        *,
        valid_from: str | None = None,
        monday_hours: float | None = None,
        tuesday_hours: float | None = None,
        wednesday_hours: float | None = None,
        thursday_hours: float | None = None,
        friday_hours: float | None = None,
        saturday_hours: float | None = None,
        sunday_hours: float | None = None,
        availability_factor: float | None = None,
        confirm: bool = False,
    ) -> UserWorkingHoursWriteResult:
        return await self._user_working_hours_service.update(
            user_ref,
            working_hours_id,
            valid_from=valid_from,
            monday_hours=monday_hours,
            tuesday_hours=tuesday_hours,
            wednesday_hours=wednesday_hours,
            thursday_hours=thursday_hours,
            friday_hours=friday_hours,
            saturday_hours=saturday_hours,
            sunday_hours=sunday_hours,
            availability_factor=availability_factor,
            confirm=confirm,
        )

    async def delete_user_working_hours(
        self, user_ref: str, working_hours_id: int, *, confirm: bool = False
    ) -> UserWorkingHoursWriteResult:
        return await self._user_working_hours_service.delete(user_ref, working_hours_id, confirm=confirm)

    async def execute_query(self, query_id: int, *, offset: int = 1, limit: int | None = None) -> WorkPackageListResult:
        return await self._query_execution_service.execute(query_id, offset=offset, limit=limit)

    async def list_categories(self, project_ref: str) -> CategoryListResult:
        return await self._category_service.list(project_ref)

    async def get_category(self, *, category_id: int, project_ref: str | None = None) -> CategorySummary:
        return await self._category_service.get(category_id=category_id, project_ref=project_ref)

    async def list_work_package_attachments(
        self,
        work_package_id: int | str,
        *,
        offset: int = 1,
        limit: int | None = None,
        include_total_size: bool = False,
    ) -> AttachmentListResult:
        return await self._attachment_service.list_for_work_package(
            work_package_id, offset=offset, limit=limit, include_total_size=include_total_size
        )

    async def get_attachment(self, attachment_id: int) -> AttachmentSummary:
        return await self._attachment_service.get(attachment_id)

    async def create_work_package_attachment(
        self,
        *,
        work_package_id: int | str,
        file_path: str,
        description: str | None = None,
        confirm: bool = False,
    ) -> AttachmentWriteResult:
        return await self._attachment_service.create(
            work_package_id=work_package_id, file_path=file_path, description=description, confirm=confirm
        )

    async def delete_attachment(
        self,
        *,
        attachment_id: int,
        confirm: bool = False,
    ) -> AttachmentWriteResult:
        return await self._attachment_service.delete(attachment_id, confirm=confirm)

    async def list_time_entry_activities(self) -> TimeEntryActivityListResult:
        return await self._time_entry_service.list_activities()

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
        include_total_hours: bool = False,
    ) -> TimeEntryListResult:
        return await self._time_entry_service.list_all(
            project=project,
            work_package_id=work_package_id,
            user=user,
            spent_on_from=spent_on_from,
            spent_on_to=spent_on_to,
            offset=offset,
            limit=limit,
            include_total_hours=include_total_hours,
        )

    async def get_time_entry(self, time_entry_id: int, *, text_limit: int | None = None) -> TimeEntrySummary:
        return await self._time_entry_service.get(time_entry_id, text_limit=text_limit)

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
        comment: str | None = None,
        ongoing: bool | None = None,
        confirm: bool = False,
    ) -> TimeEntryWriteResult:
        return await self._time_entry_service.create(
            project=project,
            work_package_id=work_package_id,
            user=user,
            activity=activity,
            hours=hours,
            spent_on=spent_on,
            start_time=start_time,
            comment=comment,
            ongoing=ongoing,
            confirm=confirm,
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
        comment: str | None = None,
        ongoing: bool | None = None,
        confirm: bool = False,
    ) -> TimeEntryWriteResult:
        return await self._time_entry_service.update(
            time_entry_id=time_entry_id,
            user=user,
            activity=activity,
            hours=hours,
            spent_on=spent_on,
            start_time=start_time,
            comment=comment,
            ongoing=ongoing,
            confirm=confirm,
        )

    async def delete_time_entry(
        self,
        *,
        time_entry_id: int,
        confirm: bool = False,
    ) -> TimeEntryWriteResult:
        return await self._time_entry_service.delete(time_entry_id=time_entry_id, confirm=confirm)

    async def get_cost_entry(self, cost_entry_id: int) -> CostEntrySummary:
        return await self._cost_service.get_cost_entry(cost_entry_id)

    async def list_work_package_cost_entries(self, work_package_id: int | str) -> CostEntryListResult:
        return await self._cost_service.list_work_package_cost_entries(work_package_id)

    async def get_work_package_costs_by_type(self, work_package_id: int | str) -> WorkPackageCostsByTypeResult:
        return await self._cost_service.get_work_package_costs_by_type(work_package_id)

    async def get_cost_type(self, cost_type_id: int) -> CostTypeSummary:
        return await self._cost_service.get_cost_type(cost_type_id)

    async def get_github_pull_request(self, github_pull_request_id: int) -> GithubPullRequestSummary:
        return await self._github_gitlab_link_service.get_github_pull_request(github_pull_request_id)

    async def list_work_package_github_pull_requests(self, work_package_id: int | str) -> GithubPullRequestListResult:
        return await self._github_gitlab_link_service.list_work_package_github_pull_requests(work_package_id)

    async def list_work_package_gitlab_issues(self, work_package_id: int | str) -> GitlabIssueListResult:
        return await self._github_gitlab_link_service.list_work_package_gitlab_issues(work_package_id)

    async def list_work_package_gitlab_merge_requests(self, work_package_id: int | str) -> GitlabMergeRequestListResult:
        return await self._github_gitlab_link_service.list_work_package_gitlab_merge_requests(work_package_id)

    # The other cross-service coordinator -- see get_my_project_access's
    # header comment above.
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
        versions = await self.list_versions(project=str(project_id), offset=1, limit=self.settings.max_results)

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
        overdue_only: bool = False,
        due_within_days: int | None = None,
        sort_by: list[SortCriterion] | None = None,
        group_by: str | None = None,
        offset: int = 1,
        limit: int | None = None,
        include_sums: bool = False,
        custom_field_filters: dict[str, dict[str, Any]] | None = None,
    ) -> WorkPackageListResult:
        return await self._work_package_service.search(
            search=search,
            project=project,
            status=status,
            open_only=open_only,
            assignee_me=assignee_me,
            assignee=assignee,
            priority=priority,
            created_on=created_on,
            created_between=created_between,
            updated_on=updated_on,
            updated_between=updated_between,
            due_on=due_on,
            due_between=due_between,
            overdue_only=overdue_only,
            due_within_days=due_within_days,
            sort_by=sort_by,
            group_by=group_by,
            offset=offset,
            limit=limit,
            include_sums=include_sums,
            custom_field_filters=custom_field_filters,
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
        overdue_only: bool = False,
        due_within_days: int | None = None,
        sort_by: list[SortCriterion] | None = None,
        group_by: str | None = None,
        offset: int = 1,
        limit: int | None = None,
        include_sums: bool = False,
        custom_field_filters: dict[str, dict[str, Any]] | None = None,
    ) -> WorkPackageListResult:
        return await self._work_package_service.list(
            project=project,
            type=type,
            version=version,
            version_status=version_status,
            open_only=open_only,
            assignee_me=assignee_me,
            assignee=assignee,
            status=status,
            priority=priority,
            created_on=created_on,
            created_between=created_between,
            updated_on=updated_on,
            updated_between=updated_between,
            due_on=due_on,
            due_between=due_between,
            overdue_only=overdue_only,
            due_within_days=due_within_days,
            sort_by=sort_by,
            group_by=group_by,
            offset=offset,
            limit=limit,
            include_sums=include_sums,
            custom_field_filters=custom_field_filters,
        )

    async def get_work_package(self, work_package_id: int | str, *, text_limit: int | None = None) -> WorkPackageDetail:
        return await self._work_package_service.get(work_package_id, text_limit=text_limit)

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
        return await self._work_package_service.create(
            project=project,
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
            confirm=confirm,
            wp_context=wp_context,
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
        return await self._work_package_service.create_subtask(
            parent_work_package_id=parent_work_package_id,
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
            start_date=start_date,
            due_date=due_date,
            confirm=confirm,
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
        return await self._work_package_service.update(
            work_package_id=work_package_id,
            subject=subject,
            description=description,
            type=type,
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
            confirm=confirm,
            wp_context=wp_context,
        )

    async def bulk_create_work_packages(
        self,
        *,
        items: list[dict[str, Any]],
        confirm: bool = False,
    ) -> BulkWorkPackageWriteResult:
        return await self._work_package_service.bulk_create(items=items, confirm=confirm)

    async def bulk_update_work_packages(
        self,
        *,
        items: list[dict[str, Any]],
        confirm: bool = False,
    ) -> BulkWorkPackageWriteResult:
        return await self._work_package_service.bulk_update(items=items, confirm=confirm)

    async def add_work_package_comment(
        self,
        *,
        work_package_id: int | str,
        comment: str,
        internal: bool = False,
        notify: bool = False,
        confirm: bool = False,
    ) -> ActivityWriteResult:
        return await self._work_package_service.add_comment(
            work_package_id=work_package_id, comment=comment, internal=internal, notify=notify, confirm=confirm
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
        return await self._relation_service.create(
            work_package_id=work_package_id,
            related_to_work_package_id=related_to_work_package_id,
            relation_type=relation_type,
            description=description,
            lag=lag,
            confirm=confirm,
        )

    async def delete_work_package(
        self,
        *,
        work_package_id: int | str,
        confirm: bool = False,
    ) -> WorkPackageWriteResult:
        return await self._work_package_service.delete(work_package_id=work_package_id, confirm=confirm)

    async def delete_relation(
        self,
        *,
        relation_id: int,
        confirm: bool = False,
    ) -> RelationWriteResult:
        return await self._relation_service.delete(relation_id=relation_id, confirm=confirm)

    async def list_my_open_work_packages(
        self,
        *,
        offset: int = 1,
        limit: int | None = None,
    ) -> WorkPackageListResult:
        return await self._work_package_service.list_my_open(offset=offset, limit=limit)

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

    async def list_backlog_buckets(
        self,
        *,
        search: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> BacklogBucketListResult:
        return await self._backlog_bucket_service.list(search=search, offset=offset, limit=limit)

    async def list_project_backlog_buckets(
        self,
        project: str,
        *,
        search: str | None = None,
        offset: int = 1,
        limit: int | None = None,
        context: ProjectResolutionContext | None = None,
    ) -> BacklogBucketListResult:
        return await self._backlog_bucket_service.list_for_project(
            project, search=search, offset=offset, limit=limit, context=context
        )

    async def get_backlog_bucket(self, backlog_bucket_id: int) -> BacklogBucketDetail:
        return await self._backlog_bucket_service.get(backlog_bucket_id)

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
        return await self._relation_service.list_for_work_package(work_package_id, offset=offset, limit=limit)

    async def get_work_package_activities(
        self, work_package_id: int | str, *, limit: int | None = None, text_limit: int | None = None
    ) -> ActivityListResult:
        return await self._activity_service.list_for_work_package(work_package_id, limit=limit, text_limit=text_limit)

    # --- Emoji reactions (on work-package comment activities) ---

    async def list_work_package_reactions(self, work_package_id: int | str) -> EmojiReactionListResult:
        return await self._emoji_reaction_service.list_for_work_package(work_package_id)

    async def toggle_activity_emoji_reaction(
        self, activity_id: int, reaction: str, *, confirm: bool = False
    ) -> EmojiReactionWriteResult:
        return await self._emoji_reaction_service.toggle(activity_id, reaction, confirm=confirm)

    # --- Reminders (personal, on work packages) ---

    async def list_reminders(self, *, offset: int = 1, limit: int | None = None) -> ReminderListResult:
        return await self._reminder_service.list_all(offset=offset, limit=limit)

    async def create_work_package_reminder(
        self,
        *,
        work_package_id: int | str,
        remind_at: str,
        note: str | None = None,
        confirm: bool = False,
    ) -> ReminderWriteResult:
        return await self._reminder_service.create(
            work_package_id=work_package_id, remind_at=remind_at, note=note, confirm=confirm
        )

    async def update_reminder(
        self,
        *,
        reminder_id: int,
        remind_at: str | None = None,
        note: str | None = None,
        confirm: bool = False,
    ) -> ReminderWriteResult:
        return await self._reminder_service.update(
            reminder_id=reminder_id, remind_at=remind_at, note=note, confirm=confirm
        )

    async def delete_reminder(self, *, reminder_id: int, confirm: bool = False) -> ReminderWriteResult:
        return await self._reminder_service.delete(reminder_id=reminder_id, confirm=confirm)

    # --- Project favorites (via the workspaces endpoint) ---

    async def _set_project_favorite(self, project: str, *, favorite: bool, confirm: bool) -> FavoriteWriteResult:
        return await self._project_service.set_favorite(project, favorite=favorite, confirm=confirm)

    async def add_project_favorite(self, *, project: str, confirm: bool = False) -> FavoriteWriteResult:
        return await self._set_project_favorite(project, favorite=True, confirm=confirm)

    async def remove_project_favorite(self, *, project: str, confirm: bool = False) -> FavoriteWriteResult:
        return await self._set_project_favorite(project, favorite=False, confirm=confirm)

    async def get_current_user(self) -> CurrentUser:
        return await self._current_user_service.get_current_user()

    # --- Statuses ---

    async def list_statuses(self) -> StatusListResult:
        return await self._status_priority_type_service.list_statuses()

    async def get_status(self, status_id: int) -> StatusSummary:
        return await self._status_priority_type_service.get_status(status_id)

    # --- Priorities ---

    async def list_priorities(self) -> PriorityListResult:
        return await self._status_priority_type_service.list_priorities()

    async def get_priority(self, priority_id: int) -> PrioritySummary:
        return await self._status_priority_type_service.get_priority(priority_id)

    # --- Types ---

    async def list_types(self, *, project: str | None = None) -> TypeListResult:
        return await self._status_priority_type_service.list_types(project=project)

    async def get_type(self, type_id: int) -> TypeSummary:
        return await self._status_priority_type_service.get_type(type_id)

    # --- Work Package Watchers ---

    async def list_work_package_watchers(self, work_package_id: int | str) -> WatcherListResult:
        return await self._watcher_service.list_for_work_package(work_package_id)

    async def add_work_package_watcher(
        self,
        work_package_id: int | str,
        user_id: int,
        *,
        confirm: bool = False,
    ) -> WatcherWriteResult:
        return await self._watcher_service.add(work_package_id, user_id, confirm=confirm)

    async def remove_work_package_watcher(
        self,
        work_package_id: int | str,
        user_id: int,
        *,
        confirm: bool = False,
    ) -> WatcherWriteResult:
        return await self._watcher_service.remove(work_package_id, user_id, confirm=confirm)

    # --- Notifications ---

    async def list_notifications(
        self,
        *,
        unread_only: bool = False,
        limit: int | None = None,
        offset: int = 1,
    ) -> NotificationListResult:
        return await self._notification_service.list_all(unread_only=unread_only, limit=limit, offset=offset)

    async def mark_notification_read(self, notification_id: int, *, confirm: bool = False) -> NotificationMarkResult:
        return await self._notification_service.mark_read(notification_id, confirm=confirm)

    async def mark_all_notifications_read(self, *, confirm: bool = False) -> NotificationMarkResult:
        return await self._notification_service.mark_all_read(confirm=confirm)

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
        return await self._user_service.create(
            login=login,
            email=email,
            firstname=firstname,
            lastname=lastname,
            password=password,
            admin=admin,
            status=status,
            language=language,
            confirm=confirm,
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
        return await self._user_service.update(
            user_id=user_id,
            login=login,
            email=email,
            firstname=firstname,
            lastname=lastname,
            admin=admin,
            language=language,
            confirm=confirm,
        )

    async def delete_user(
        self,
        user_id: int,
        *,
        confirm: bool = False,
    ) -> UserWriteResult:
        return await self._user_service.delete(user_id, confirm=confirm)

    async def lock_user(
        self,
        user_id: int,
        *,
        confirm: bool = False,
    ) -> UserWriteResult:
        return await self._user_service.lock(user_id, confirm=confirm)

    async def unlock_user(
        self,
        user_id: int,
        *,
        confirm: bool = False,
    ) -> UserWriteResult:
        return await self._user_service.unlock(user_id, confirm=confirm)

    # --- Group CRUD ---

    async def create_group(
        self,
        *,
        name: str,
        user_ids: list[int] | None = None,
        confirm: bool = False,
    ) -> GroupWriteResult:
        return await self._group_service.create(name=name, user_ids=user_ids, confirm=confirm)

    async def update_group(
        self,
        group_id: int,
        *,
        name: str | None = None,
        add_user_ids: list[int] | None = None,
        remove_user_ids: list[int] | None = None,
        confirm: bool = False,
    ) -> GroupWriteResult:
        return await self._group_service.update(
            group_id,
            name=name,
            add_user_ids=add_user_ids,
            remove_user_ids=remove_user_ids,
            confirm=confirm,
        )

    async def delete_group(
        self,
        group_id: int,
        *,
        confirm: bool = False,
    ) -> GroupWriteResult:
        return await self._group_service.delete(group_id, confirm=confirm)

    # --- Storage CRUD ---

    async def create_storage(
        self,
        *,
        name: str,
        provider_type: str,
        host: str | None = None,
        authentication_method: str | None = None,
        tenant_id: str | None = None,
        drive_id: str | None = None,
        confirm: bool = False,
    ) -> StorageWriteResult:
        return await self._storage_service.create(
            name=name,
            provider_type=provider_type,
            host=host,
            authentication_method=authentication_method,
            tenant_id=tenant_id,
            drive_id=drive_id,
            confirm=confirm,
        )

    async def update_storage(
        self,
        *,
        storage_id: int,
        name: str | None = None,
        host: str | None = None,
        confirm: bool = False,
    ) -> StorageWriteResult:
        return await self._storage_service.update(storage_id=storage_id, name=name, host=host, confirm=confirm)

    async def delete_storage(self, storage_id: int, *, confirm: bool = False) -> StorageWriteResult:
        return await self._storage_service.delete(storage_id, confirm=confirm)

    # --- File Links ---

    async def list_work_package_file_links(
        self, work_package_id: int | str, *, offset: int = 1, limit: int | None = None
    ) -> FileLinkListResult:
        return await self._file_link_service.list_for_work_package(work_package_id, offset=offset, limit=limit)

    async def delete_file_link(
        self,
        file_link_id: int,
        *,
        confirm: bool = False,
    ) -> FileLinkWriteResult:
        return await self._file_link_service.delete(file_link_id, confirm=confirm)

    # --- Grids ---

    async def list_grids(
        self, *, scope: str | None = None, offset: int = 1, limit: int | None = None
    ) -> GridListResult:
        return await self._grid_service.list(scope=scope, offset=offset, limit=limit)

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
        return await self._user_preferences_service.get()

    async def update_my_preferences(
        self,
        *,
        time_zone: str | None = None,
        comment_sort_descending: bool | None = None,
        warn_on_leaving_unsaved: bool | None = None,
        auto_hide_popups: bool | None = None,
        confirm: bool = False,
    ) -> UserPreferencesWriteResult:
        return await self._user_preferences_service.update(
            time_zone=time_zone,
            comment_sort_descending=comment_sort_descending,
            warn_on_leaving_unsaved=warn_on_leaving_unsaved,
            auto_hide_popups=auto_hide_popups,
            confirm=confirm,
        )

    # --- Text Rendering ---

    async def render_text(self, *, text: str, format: str = "markdown") -> RenderedText:
        """Render plain or markdown text to HTML via the OpenProject API."""
        return await self._extended_metadata_service.render_text(text=text, format=format)

    # --- Help Texts ---

    async def list_help_texts(self) -> HelpTextListResult:
        return await self._extended_metadata_service.list_help_texts()

    async def get_help_text(self, help_text_id: int) -> HelpTextSummary:
        return await self._extended_metadata_service.get_help_text(help_text_id)

    # --- Work Schedule / Days ---

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

    async def list_relations(
        self,
        *,
        relation_type: str | None = None,
        offset: int = 1,
        limit: int | None = None,
    ) -> RelationListResult:
        return await self._relation_service.list_all(relation_type=relation_type, offset=offset, limit=limit)

    async def update_relation(
        self,
        *,
        relation_id: int,
        relation_type: str | None = None,
        description: str | None = None,
        confirm: bool = False,
    ) -> RelationUpdateResult:
        return await self._relation_service.update(
            relation_id=relation_id, relation_type=relation_type, description=description, confirm=confirm
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
        serialization seam (tools._to_payload) reads it and drops those keys
        entirely from the response — hidden fields cost neither their key name nor
        a null value. Stamping is possible because the response dataclasses
        are not frozen.
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
