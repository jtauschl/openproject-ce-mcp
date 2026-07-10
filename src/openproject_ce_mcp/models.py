from __future__ import annotations

from dataclasses import dataclass
from typing import Any, NamedTuple


class SortCriterion(NamedTuple):
    """A validated sort criterion with field name and direction.

    Used to ensure type safety between tool validation and client execution.
    """

    field: str
    direction: str  # "asc" or "desc"


@dataclass
class ProjectSummary:
    id: int
    name: str
    identifier: str | None
    active: bool | None
    description: str | None
    url: str
    public: bool | None = None
    status: str | None = None
    status_explanation: str | None = None
    parent_id: int | None = None
    parent_name: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    can_update: bool = False
    can_delete: bool = False


@dataclass
class ProjectListResult:
    offset: int
    limit: int
    total: int
    count: int
    next_offset: int | None
    truncated: bool
    results: list[ProjectSummary]


@dataclass
class RoleSummary:
    id: int
    name: str
    url: str


@dataclass
class RoleListResult:
    count: int
    results: list[RoleSummary]


@dataclass
class MembershipSummary:
    id: int
    principal_id: int | None
    principal_name: str | None
    project_id: int | None
    project_name: str | None
    role_ids: list[int]
    role_names: list[str]
    can_update: bool
    can_update_immediately: bool
    url: str


@dataclass
class MembershipListResult:
    count: int
    results: list[MembershipSummary]


@dataclass
class ProjectWriteResult:
    action: str
    confirmed: bool
    requires_confirmation: bool
    ready: bool
    message: str
    project_id: int | None
    project: str | None
    payload: dict[str, Any]
    validation_errors: dict[str, str]
    result: ProjectSummary | None


@dataclass
class ProjectCopyResult:
    action: str
    confirmed: bool
    requires_confirmation: bool
    ready: bool
    message: str
    source_project_id: int | None
    source_project: str | None
    payload: dict[str, Any]
    validation_errors: dict[str, str]
    job_status_id: int | None
    job_status_url: str | None


@dataclass
class JobStatusDetail:
    id: int | None
    type: str | None
    status: str | None
    message: str | None
    created_at: str | None
    updated_at: str | None
    percentage_complete: int | float | None
    project_id: int | None
    project: str | None
    created_resource_type: str | None
    created_resource_id: int | None
    created_resource_name: str | None
    links: list[str]
    url: str | None


@dataclass
class MembershipWriteResult:
    action: str
    confirmed: bool
    requires_confirmation: bool
    ready: bool
    message: str
    membership_id: int | None
    project: str | None
    payload: dict[str, Any]
    validation_errors: dict[str, str]
    result: MembershipSummary | None


@dataclass
class ProjectAccessSummary:
    project_id: int
    project_name: str
    project_identifier: str | None
    current_user_id: int
    current_user_name: str | None
    membership: MembershipSummary | None
    project_links: list[str]
    inferred_is_project_admin: bool
    inferred_can_edit_project: bool
    inferred_can_manage_memberships: bool
    inference_basis: str


@dataclass
class PrincipalSummary:
    id: int
    type: str | None
    name: str
    login: str | None
    email: str | None
    status: str | None
    url: str


@dataclass
class PrincipalListResult:
    offset: int
    limit: int
    total: int
    count: int
    next_offset: int | None
    truncated: bool
    results: list[PrincipalSummary]


@dataclass
class UserSummary:
    id: int
    name: str | None
    login: str | None
    email: str | None
    status: str | None
    admin: bool | None
    locked: bool | None
    avatar_url: str | None
    created_at: str | None
    updated_at: str | None
    url: str


@dataclass
class UserDetail:
    id: int
    name: str | None
    login: str | None
    email: str | None
    status: str | None
    admin: bool | None
    locked: bool | None
    avatar_url: str | None
    created_at: str | None
    updated_at: str | None
    language: str | None
    identity_url: str | None
    auth_source: str | None
    groups: list[str]
    url: str


@dataclass
class UserListResult:
    offset: int
    limit: int
    total: int
    count: int
    next_offset: int | None
    truncated: bool
    results: list[UserSummary]


@dataclass
class GroupSummary:
    id: int
    name: str | None
    member_count: int
    created_at: str | None
    updated_at: str | None
    can_update: bool
    can_delete: bool
    url: str


@dataclass
class GroupDetail:
    id: int
    name: str | None
    member_count: int
    members: list[str]
    memberships_url: str | None
    created_at: str | None
    updated_at: str | None
    can_update: bool
    can_delete: bool
    url: str


@dataclass
class GroupListResult:
    offset: int
    limit: int
    total: int
    count: int
    next_offset: int | None
    truncated: bool
    results: list[GroupSummary]


@dataclass
class ActionSummary:
    id: str
    name: str | None
    description: str | None
    modules: list[str]
    url: str | None


@dataclass
class ActionListResult:
    offset: int
    limit: int
    total: int
    count: int
    next_offset: int | None
    truncated: bool
    results: list[ActionSummary]


@dataclass
class CapabilitySummary:
    id: str
    name: str | None
    action_id: str | None
    action_name: str | None
    principal_id: int | None
    principal_name: str | None
    context: str | None
    url: str | None


@dataclass
class CapabilityListResult:
    offset: int
    limit: int
    total: int
    count: int
    next_offset: int | None
    truncated: bool
    results: list[CapabilitySummary]


@dataclass
class OptionValue:
    id: int | None
    title: str
    href: str | None


@dataclass
class ProjectFieldSchema:
    key: str
    name: str
    type: str | None
    required: bool
    writable: bool
    has_default: bool
    location: str | None
    allowed_values: list[OptionValue]


@dataclass
class ProjectAdminContext:
    project: ProjectSummary | None
    available_statuses: list[OptionValue]
    available_parent_projects: list[ProjectSummary]
    fields: list[ProjectFieldSchema]
    project_links: list[str]


@dataclass
class ProjectConfiguration:
    project_id: int
    project_name: str
    maximum_attachment_file_size: int | None
    maximum_api_v3_page_size: int | None
    per_page_options: list[int]
    duration_format: str | None
    hours_per_day: int | float | None
    days_per_month: int | float | None
    active_feature_flags: list[str]
    available_features: list[str]
    trialling_features: list[str]
    enabled_internal_comments: bool | None
    url: str


@dataclass
class WorkPackageFieldSchema:
    key: str
    name: str
    type: str | None
    required: bool
    writable: bool
    has_default: bool
    placeholder: str | None
    location: str | None
    allowed_values: list[OptionValue]


@dataclass
class ProjectWorkPackageContext:
    project_id: int
    project_name: str
    project_identifier: str | None
    selected_type_id: int | None
    selected_type_name: str | None
    available_types: list[OptionValue]
    available_statuses: list[OptionValue]
    available_priorities: list[OptionValue]
    available_categories: list[OptionValue]
    available_project_phases: list[OptionValue]
    available_versions: list[VersionSummary]
    fields: list[WorkPackageFieldSchema]
    custom_fields: list[WorkPackageFieldSchema]


@dataclass
class WorkPackageSummary:
    id: int
    display_id: str | None
    subject: str
    type: str | None
    status: str | None
    priority: str | None
    project_phase: str | None
    assignee: str | None
    responsible: str | None
    project: str | None
    version: str | None
    sprint: str | None
    start_date: str | None
    due_date: str | None
    percentage_complete: int | None
    description: str | None
    has_description: bool
    url: str
    description_truncated: bool = False
    description_length: int | None = None
    estimated_time: str | None = None
    derived_estimated_time: str | None = None
    spent_time: str | None = None
    remaining_time: str | None = None
    derived_remaining_time: str | None = None
    duration: str | None = None
    parent_id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None
    author: str | None = None
    category: str | None = None
    schedule_manually: bool | None = None
    ignore_non_working_days: bool | None = None
    derived_start_date: str | None = None
    derived_due_date: str | None = None
    percentage_done: int | None = None
    derived_percentage_done: int | None = None
    readonly: bool | None = None


@dataclass
class WorkPackageDetail:
    id: int
    display_id: str | None
    subject: str
    type: str | None
    status: str | None
    priority: str | None
    project_phase: str | None
    assignee: str | None
    responsible: str | None
    project: str | None
    version: str | None
    sprint: str | None
    parent_id: int | None
    parent_display_id: str | None
    start_date: str | None
    due_date: str | None
    percentage_complete: int | None
    lock_version: int | None
    description: str | None
    url: str
    activities_url: str | None
    relations_url: str | None
    description_truncated: bool = False
    description_length: int | None = None
    estimated_time: str | None = None
    derived_estimated_time: str | None = None
    spent_time: str | None = None
    remaining_time: str | None = None
    derived_remaining_time: str | None = None
    duration: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    author: str | None = None
    category: str | None = None
    children: list[dict[str, str]] | None = None
    children_truncated: bool = False
    ancestors: list[dict[str, str]] | None = None
    ancestors_truncated: bool = False
    schedule_manually: bool | None = None
    ignore_non_working_days: bool | None = None
    derived_start_date: str | None = None
    derived_due_date: str | None = None
    percentage_done: int | None = None
    derived_percentage_done: int | None = None
    readonly: bool | None = None


@dataclass
class WorkPackageWriteResult:
    action: str
    confirmed: bool
    requires_confirmation: bool
    ready: bool
    message: str
    work_package_id: int | None
    project: str | None
    payload: dict[str, Any]
    validation_errors: dict[str, str]
    result: WorkPackageDetail | None


@dataclass
class BulkWorkPackageItemResult:
    index: int
    success: bool
    error: str | None
    result: WorkPackageWriteResult | None


@dataclass
class BulkWorkPackageWriteResult:
    action: str
    confirmed: bool
    requires_confirmation: bool
    total: int
    succeeded: int
    failed: int
    message: str
    items: list[BulkWorkPackageItemResult]


@dataclass
class ActivityWriteResult:
    action: str
    confirmed: bool
    requires_confirmation: bool
    ready: bool
    message: str
    work_package_id: int
    payload: dict[str, Any]
    validation_errors: dict[str, str]
    result: ActivitySummary | None


@dataclass
class RelationWriteResult:
    action: str
    confirmed: bool
    requires_confirmation: bool
    ready: bool
    message: str
    relation_id: int | None
    work_package_id: int | None
    payload: dict[str, Any]
    validation_errors: dict[str, str]
    result: RelationSummary | None


@dataclass
class WorkPackageListResult:
    offset: int
    limit: int
    total: int
    count: int
    next_offset: int | None
    truncated: bool
    results: list[WorkPackageSummary]


@dataclass
class BatchWorkPackageReadItemResult:
    """Single item result from batch read operation."""

    id: int | str
    success: bool
    work_package: WorkPackageDetail | None
    error: str | None


@dataclass
class BatchWorkPackageReadResult:
    """Result of batch read operation, mirroring BulkWorkPackageWriteResult pattern."""

    action: str  # Always "batch_read"
    total: int
    succeeded: int
    failed: int
    message: str  # User-facing summary
    results: list[BatchWorkPackageReadItemResult]


@dataclass
class VersionSummary:
    id: int
    name: str
    status: str | None
    sharing: str | None
    start_date: str | None
    end_date: str | None
    defining_project: str | None
    description: str | None
    url: str


@dataclass
class VersionDetail:
    id: int
    name: str
    status: str | None
    sharing: str | None
    start_date: str | None
    end_date: str | None
    defining_project: str | None
    description: str | None
    url: str


@dataclass
class VersionWriteResult:
    action: str
    confirmed: bool
    requires_confirmation: bool
    ready: bool
    message: str
    version_id: int | None
    project: str | None
    payload: dict[str, Any]
    validation_errors: dict[str, str]
    result: VersionDetail | None


@dataclass
class VersionListResult:
    offset: int
    limit: int
    total: int
    count: int
    next_offset: int | None
    truncated: bool
    results: list[VersionSummary]


@dataclass
class SprintSummary:
    id: int
    name: str
    status: str | None
    status_href: str | None
    start_date: str | None
    finish_date: str | None
    defining_workspace_id: int | None
    defining_workspace: str | None
    created_at: str | None
    updated_at: str | None
    url: str


@dataclass
class SprintDetail:
    id: int
    name: str
    status: str | None
    status_href: str | None
    start_date: str | None
    finish_date: str | None
    defining_workspace_id: int | None
    defining_workspace: str | None
    created_at: str | None
    updated_at: str | None
    url: str


@dataclass
class SprintListResult:
    offset: int
    limit: int
    total: int
    count: int
    next_offset: int | None
    truncated: bool
    results: list[SprintSummary]


@dataclass
class BoardFilter:
    key: str | None
    name: str | None
    operator: str | None
    values: list[str]


@dataclass
class BoardSummary:
    id: int
    name: str
    project_id: int | None
    project: str | None
    public: bool
    hidden: bool
    starred: bool
    include_subprojects: bool
    show_hierarchies: bool
    timeline_visible: bool
    filter_count: int
    can_update: bool
    can_delete: bool
    url: str


@dataclass
class BoardDetail:
    id: int
    name: str
    project_id: int | None
    project: str | None
    public: bool
    hidden: bool
    starred: bool
    include_subprojects: bool
    show_hierarchies: bool
    timeline_visible: bool
    timeline_zoom_level: str | None
    highlighting_mode: str | None
    group_by: str | None
    columns: list[str]
    sort_by: list[str]
    highlighted_attributes: list[str]
    timestamps: list[str]
    filters: list[BoardFilter]
    created_at: str | None
    updated_at: str | None
    can_update: bool
    can_delete: bool
    url: str


@dataclass
class BoardWriteResult:
    action: str
    confirmed: bool
    requires_confirmation: bool
    ready: bool
    message: str
    board_id: int | None
    project: str | None
    payload: dict[str, Any]
    validation_errors: dict[str, str]
    result: BoardDetail | None


@dataclass
class BoardListResult:
    offset: int
    limit: int
    total: int
    count: int
    next_offset: int | None
    truncated: bool
    results: list[BoardSummary]


@dataclass
class ViewSummary:
    id: int
    type: str | None
    name: str
    project_id: int | None
    project: str | None
    query_id: int | None
    query: str | None
    public: bool
    starred: bool
    created_at: str | None
    updated_at: str | None
    url: str


@dataclass
class ViewDetail:
    id: int
    type: str | None
    name: str
    project_id: int | None
    project: str | None
    query_id: int | None
    query: str | None
    public: bool
    starred: bool
    created_at: str | None
    updated_at: str | None
    links: list[str]
    url: str


@dataclass
class ViewListResult:
    offset: int
    limit: int
    total: int
    count: int
    next_offset: int | None
    truncated: bool
    results: list[ViewSummary]


@dataclass
class QueryFilterSummary:
    id: str
    name: str | None
    url: str | None


@dataclass
class QueryColumnSummary:
    id: str
    name: str | None
    type: str | None
    relation_type: str | None
    url: str | None


@dataclass
class QueryOperatorSummary:
    id: str
    name: str | None
    url: str | None


@dataclass
class QuerySortBySummary:
    id: str
    name: str | None
    column: str | None
    direction: str | None
    url: str | None


@dataclass
class QueryFilterInstanceSchemaSummary:
    id: str
    name: str | None
    filter: str | None
    operator_count: int
    url: str | None


@dataclass
class QueryFilterInstanceSchemaListResult:
    count: int
    results: list[QueryFilterInstanceSchemaSummary]


@dataclass
class CategorySummary:
    id: int
    name: str
    project_id: int | None
    project: str | None
    is_default: bool
    url: str


@dataclass
class CategoryListResult:
    count: int
    results: list[CategorySummary]


@dataclass
class DocumentSummary:
    id: int
    title: str
    project_id: int | None
    project: str | None
    description: str | None
    created_at: str | None
    attachment_count: int
    can_update: bool
    url: str


@dataclass
class DocumentDetail:
    id: int
    title: str
    project_id: int | None
    project: str | None
    description: str | None
    created_at: str | None
    attachment_count: int
    attachments_url: str | None
    can_update: bool
    url: str


@dataclass
class DocumentWriteResult:
    action: str
    confirmed: bool
    requires_confirmation: bool
    ready: bool
    message: str
    document_id: int | None
    project: str | None
    payload: dict[str, Any]
    validation_errors: dict[str, str]
    result: DocumentDetail | None


@dataclass
class DocumentListResult:
    offset: int
    limit: int
    total: int
    count: int
    next_offset: int | None
    truncated: bool
    results: list[DocumentSummary]


@dataclass
class AttachmentSummary:
    id: int
    title: str
    file_name: str | None
    file_size: int | None
    description: str | None
    content_type: str | None
    status: str | None
    author: str | None
    container_type: str | None
    container_id: int | None
    created_at: str | None
    download_url: str | None
    url: str


@dataclass
class AttachmentListResult:
    count: int
    results: list[AttachmentSummary]


@dataclass
class AttachmentWriteResult:
    action: str
    confirmed: bool
    requires_confirmation: bool
    ready: bool
    message: str
    attachment_id: int | None
    work_package_id: int | None
    payload: dict[str, Any]
    validation_errors: dict[str, str]
    result: AttachmentSummary | None


@dataclass
class InstanceConfiguration:
    host_name: str | None
    maximum_attachment_file_size: int | None
    maximum_api_v3_page_size: int | None
    per_page_options: list[int]
    duration_format: str | None
    hours_per_day: int | float | None
    days_per_month: int | float | None
    active_feature_flags: list[str]
    available_features: list[str]
    trialling_features: list[str]


@dataclass
class ProjectPhaseDefinition:
    id: int
    name: str
    start_gate: str | None
    finish_gate: str | None
    created_at: str | None
    updated_at: str | None
    url: str


@dataclass
class ProjectPhaseDefinitionListResult:
    count: int
    results: list[ProjectPhaseDefinition]


@dataclass
class ProjectPhase:
    id: int
    name: str
    project_id: int | None
    project: str | None
    phase_definition_id: int | None
    phase_definition: str | None
    start_date: str | None
    finish_date: str | None
    created_at: str | None
    updated_at: str | None
    url: str


@dataclass
class TimeEntryActivitySummary:
    id: int
    name: str
    position: int | None
    is_default: bool
    projects: list[str]
    url: str


@dataclass
class TimeEntryActivityListResult:
    count: int
    results: list[TimeEntryActivitySummary]


@dataclass
class TimeEntrySummary:
    id: int
    project: str | None
    entity_type: str | None
    entity_id: int | None
    entity_name: str | None
    user: str | None
    activity: str | None
    hours: str | None
    spent_on: str | None
    start_time: str | None
    end_time: str | None
    ongoing: bool
    comment: str | None
    created_at: str | None
    updated_at: str | None
    url: str


@dataclass
class TimeEntryWriteResult:
    action: str
    confirmed: bool
    requires_confirmation: bool
    ready: bool
    message: str
    time_entry_id: int | None
    project: str | None
    payload: dict[str, Any]
    validation_errors: dict[str, str]
    result: TimeEntrySummary | None


@dataclass
class TimeEntryListResult:
    offset: int
    limit: int
    total: int
    count: int
    next_offset: int | None
    truncated: bool
    results: list[TimeEntrySummary]


@dataclass
class CurrentUser:
    id: int
    name: str | None
    login: str | None
    url: str


@dataclass
class RelationSummary:
    id: int
    type: str | None
    description: str | None
    from_id: int | None
    from_subject: str | None
    to_id: int | None
    to_subject: str | None


@dataclass
class RelationListResult:
    count: int
    results: list[RelationSummary]


@dataclass
class ActivitySummary:
    id: int
    type: str | None
    version: int | None
    user: str | None
    comment: str | None
    created_at: str | None
    comment_truncated: bool = False
    comment_length: int | None = None
    details: list[dict[str, Any]] | None = None
    details_truncated: bool = False


@dataclass
class ActivityListResult:
    count: int
    results: list[ActivitySummary]


@dataclass
class NewsSummary:
    id: int
    title: str
    summary: str | None
    description: str | None
    project_id: int | None
    project: str | None
    author: str | None
    created_at: str | None
    can_update: bool
    can_delete: bool
    url: str


@dataclass
class NewsDetail:
    id: int
    title: str
    summary: str | None
    description: str | None
    project_id: int | None
    project: str | None
    author: str | None
    created_at: str | None
    can_update: bool
    can_delete: bool
    url: str


@dataclass
class NewsWriteResult:
    action: str
    confirmed: bool
    requires_confirmation: bool
    ready: bool
    message: str
    news_id: int | None
    project: str | None
    payload: dict[str, Any]
    validation_errors: dict[str, str]
    result: NewsDetail | None


@dataclass
class NewsListResult:
    offset: int
    limit: int
    total: int
    count: int
    next_offset: int | None
    truncated: bool
    results: list[NewsSummary]


@dataclass
class WikiPageDetail:
    id: int
    title: str
    project_id: int | None
    project: str | None
    content: str | None
    attachments_url: str | None
    url: str


@dataclass
class WikiPageListResult:
    count: int
    total: int
    results: list[WikiPageDetail]


@dataclass
class StatusSummary:
    id: int
    name: str
    is_default: bool
    is_closed: bool
    color: str | None
    position: int | None
    url: str
    is_readonly: bool | None = None
    default_done_ratio: int | None = None
    excluded_from_totals: bool | None = None


@dataclass
class StatusListResult:
    count: int
    results: list[StatusSummary]


@dataclass
class PrioritySummary:
    id: int
    name: str
    is_default: bool
    is_active: bool
    color: str | None
    position: int | None


@dataclass
class PriorityListResult:
    count: int
    results: list[PrioritySummary]


@dataclass
class TypeSummary:
    id: int
    name: str
    color: str | None
    position: int | None
    is_default: bool
    is_milestone: bool
    url: str
    created_at: str | None = None
    updated_at: str | None = None


@dataclass
class TypeListResult:
    count: int
    results: list[TypeSummary]


@dataclass
class WatcherSummary:
    id: int
    name: str
    login: str | None
    url: str


@dataclass
class WatcherListResult:
    count: int
    results: list[WatcherSummary]


@dataclass
class WatcherWriteResult:
    action: str
    confirmed: bool
    requires_confirmation: bool
    ready: bool
    message: str
    work_package_id: int
    watcher_user_id: int | None
    validation_errors: dict
    result: WatcherSummary | None


@dataclass
class NotificationSummary:
    id: int
    subject: str
    reason: str | None
    read: bool
    project_id: int | None
    project_name: str | None
    work_package_id: int | None
    work_package_subject: str | None
    created_at: str
    url: str


@dataclass
class NotificationListResult:
    count: int
    total: int
    results: list[NotificationSummary]


@dataclass
class UserWriteResult:
    action: str
    confirmed: bool
    requires_confirmation: bool
    ready: bool
    message: str
    user_id: int | None
    payload: dict
    validation_errors: dict
    result: UserDetail | None


@dataclass
class GroupWriteResult:
    action: str
    confirmed: bool
    requires_confirmation: bool
    ready: bool
    message: str
    group_id: int | None
    payload: dict
    validation_errors: dict
    result: GroupSummary | None


@dataclass
class FileLinkSummary:
    id: int
    title: str
    storage_id: int | None
    storage_name: str | None
    created_at: str | None
    updated_at: str | None
    url: str


@dataclass
class FileLinkListResult:
    count: int
    results: list[FileLinkSummary]


@dataclass
class FileLinkWriteResult:
    action: str
    confirmed: bool
    requires_confirmation: bool
    ready: bool
    message: str
    file_link_id: int | None
    work_package_id: int
    validation_errors: dict
    result: FileLinkSummary | None


@dataclass
class GridSummary:
    id: int
    row_count: int | None
    column_count: int | None
    scope: str | None
    created_at: str | None
    updated_at: str | None
    url: str


@dataclass
class GridListResult:
    count: int
    results: list[GridSummary]


@dataclass
class GridWriteResult:
    action: str
    confirmed: bool
    requires_confirmation: bool
    ready: bool
    message: str
    grid_id: int | None
    scope: str | None
    payload: dict[str, Any]
    validation_errors: dict[str, str]
    result: GridSummary | None


@dataclass
class UserPreferences:
    id: int | None
    lang: str | None
    time_zone: str | None
    comment_sort_descending: bool | None
    warn_on_leaving_unsaved: bool | None
    auto_hide_popups: bool | None
    notifications_reminder_time: str | None
    updated_at: str | None


@dataclass
class UserPreferencesWriteResult:
    action: str
    confirmed: bool
    requires_confirmation: bool
    ready: bool
    message: str
    payload: dict[str, Any]
    result: UserPreferences | None


@dataclass
class RenderedText:
    format: str
    raw: str
    html: str


@dataclass
class HelpTextSummary:
    id: int
    attribute_name: str | None
    attribute_caption: str | None
    help_text: str | None


@dataclass
class HelpTextListResult:
    count: int
    results: list[HelpTextSummary]


@dataclass
class WorkingDay:
    name: str
    day_of_week: int
    working: bool


@dataclass
class WorkingDayListResult:
    count: int
    results: list[WorkingDay]


@dataclass
class NonWorkingDay:
    date: str
    name: str | None


@dataclass
class NonWorkingDayListResult:
    count: int
    results: list[NonWorkingDay]


@dataclass
class CustomOptionSummary:
    id: int
    value: str | None


@dataclass
class RelationUpdateResult:
    action: str
    confirmed: bool
    requires_confirmation: bool
    ready: bool
    message: str
    relation_id: int | None
    payload: dict[str, Any]
    result: RelationSummary | None


@dataclass
class EmojiReactionSummary:
    reaction: str
    emoji: str | None
    count: int
    users: list[str]


@dataclass
class EmojiReactionListResult:
    count: int
    results: list[EmojiReactionSummary]


@dataclass
class ReminderSummary:
    id: int
    remind_at: str | None
    note: str | None
    work_package_id: int | None
    creator: str | None
    url: str | None


@dataclass
class ReminderListResult:
    count: int
    results: list[ReminderSummary]


@dataclass
class ReminderWriteResult:
    action: str
    confirmed: bool
    requires_confirmation: bool
    ready: bool
    message: str
    reminder_id: int | None
    payload: dict[str, Any]
    validation_errors: dict[str, str]
    result: ReminderSummary | None


@dataclass
class FavoriteWriteResult:
    action: str
    confirmed: bool
    requires_confirmation: bool
    ready: bool
    message: str
    project_id: int | None
    project: str | None
