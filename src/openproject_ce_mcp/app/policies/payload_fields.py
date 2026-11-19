"""Which model fields each key of a write form's `payload` carries. Pure data, no I/O.

The server's form answer echoes every attribute the contract lets the caller write, whether the caller
sent it or not (`lib/api/utilities/payload_representer.rb`), so a hidden field's value can sit in a
preview under another name. `PAYLOAD_KEYS` names, per entity, the keys the payload representer can
render (top level, and `_links.<rel>` for a link) and the model fields that carry each one; a key that
carries a hidden field is not shown (`hidden_fields.payload_key_hidden`).

`NO_FIELD` lists keys that carry no field and are worth nothing to hide. A key in neither table is
unknown: it is hidden as soon as the entity has any hide pattern. `NOT_IN_PAYLOAD` lists the model fields
no key carries, each with its reason; a test requires every field of the entity's summary and detail
models to be carried or listed here. Custom field keys are judged by
`services._custom_field_masking`, never here.
"""

from __future__ import annotations

PAYLOAD_KEYS: dict[str, dict[str, tuple[str, ...]]] = {
    "user": {
        "id": ("id",),
        "login": ("login",),
        "admin": ("admin",),
        "firstName": ("firstname", "name"),
        "lastName": ("lastname", "name"),
        "email": ("email",),
        "status": ("status", "locked"),
        "identityUrl": ("identity_url",),
        "language": ("language",),
    },
    "project": {
        "name": ("name",),
        "identifier": ("identifier",),
        "description": ("description",),
        "public": ("public",),
        "active": ("active",),
        "statusExplanation": ("status_explanation",),
        "createdAt": ("created_at",),
        "_links.parent": ("parent_id", "parent_name"),
        "_links.status": ("status",),
    },
    "version": {
        "name": ("name",),
        "description": ("description",),
        "startDate": ("start_date",),
        "endDate": ("end_date",),
        "status": ("status",),
        "sharing": ("sharing",),
        "_links.definingProject": ("defining_project",),
    },
    "membership": {
        "_links.project": ("project_id", "project_name"),
        "_links.principal": ("principal_id", "principal_name"),
        "_links.roles": ("role_ids", "role_names"),
    },
    "board": {
        "name": ("name",),
        "public": ("public",),
        "starred": ("starred",),
        "includeSubprojects": ("include_subprojects",),
        "showHierarchies": ("show_hierarchies",),
        "timelineVisible": ("timeline_visible",),
        "timelineZoomLevel": ("timeline_zoom_level",),
        "highlightingMode": ("highlighting_mode",),
        "timestamps": ("timestamps",),
        "filters": ("filters",),
        "_links.project": ("project_id", "project"),
        "_links.columns": ("columns",),
        "_links.sortBy": ("sort_by",),
        "_links.groupBy": ("group_by",),
        "_links.highlightedAttributes": ("highlighted_attributes",),
    },
    "grid": {
        "id": ("id",),
        "rowCount": ("row_count",),
        "columnCount": ("column_count",),
        "_links.scope": ("scope",),
    },
    "meeting": {
        "title": ("title",),
        "location": ("location",),
        "duration": ("duration",),
        "state": ("state",),
        "startTime": ("start_time",),
        "template": ("template",),
        "notify": ("notify",),
        "sharing": ("sharing",),
        "lockVersion": ("lock_version",),
        "_links.author": ("author",),
        "_links.project": ("project_id", "project"),
        "_links.recurringMeeting": ("recurring_meeting_id",),
        "_links.participants": ("participants",),
    },
    "time_entry": {
        "ongoing": ("ongoing",),
        "comment": ("comment",),
        "spentOn": ("spent_on",),
        "hours": ("hours",),
        "startTime": ("start_time",),
        "_links.project": ("project",),
        "_links.entity": ("entity_type", "entity_id", "entity_name"),
        "_links.workPackage": ("entity_type", "entity_id", "entity_name"),
        "_links.user": ("user", "user_id"),
        "_links.activity": ("activity",),
    },
    "relation": {
        "type": ("type",),
        "description": ("description",),
        "_links.to": ("to_id", "from_id"),
        "to_work_package_id": ("to_id", "from_id"),
    },
    "work_package": {
        "subject": ("subject",),
        "description": ("description",),
        "scheduleManually": ("schedule_manually",),
        "startDate": ("start_date",),
        "dueDate": ("due_date",),
        "date": ("start_date", "due_date"),
        "estimatedTime": ("estimated_time",),
        "remainingTime": ("remaining_time",),
        "duration": ("duration",),
        "ignoreNonWorkingDays": ("ignore_non_working_days",),
        "percentageDone": ("percentage_done",),
        "lockVersion": ("lock_version",),
        "createdAt": ("created_at",),
        "_links.type": ("type",),
        "_links.status": ("status",),
        "_links.priority": ("priority",),
        "_links.category": ("category",),
        "_links.project": ("project",),
        "_links.parent": ("parent_id", "parent_display_id"),
        "_links.assignee": ("assignee",),
        "_links.responsible": ("responsible",),
        "_links.version": ("version",),
        "_links.targetVersions": ("target_versions",),
        "_links.projectPhase": ("project_phase",),
        "_links.author": ("author",),
        "_links.sprint": ("sprint",),
    },
}

# Keys the representer can render that carry no model field and are worth nothing to hide (`_meta` of a
# project copy holds the copy options and `sendNotifications`)
NO_FIELD: dict[str, frozenset[str]] = {
    "user": frozenset(),
    "project": frozenset({"_meta"}),
    "version": frozenset(),
    "membership": frozenset({"_meta"}),
    "board": frozenset(),
    "grid": frozenset({"_type"}),
    "relation": frozenset({"lag"}),
    "meeting": frozenset(),
    "time_entry": frozenset(),
    "work_package": frozenset({"_meta"}),
}

_READ_ONLY = "read-only on the server, never part of a payload"
_COMPUTED = "computed by this client from a link or a text, not a server attribute"
_CUSTOM = "custom field keys are judged by without_hidden_custom_fields"

NOT_IN_PAYLOAD: dict[str, dict[str, str]] = {
    "user": {
        "avatar_url": _READ_ONLY,
        "created_at": _READ_ONLY,
        "updated_at": _READ_ONLY,
        "auth_source": "the link rel is auth_source, not a writable attribute the representer renders",
    },
    "project": {
        "id": _READ_ONLY,
        "updated_at": _READ_ONLY,
        "favorited": "user specific, read-only",
        "can_update": _COMPUTED,
        "can_delete": _COMPUTED,
        "ancestors": "read-only link",
        "ancestors_truncated": _COMPUTED,
        "description_truncated": _COMPUTED,
        "description_length": _COMPUTED,
        "status_explanation_truncated": _COMPUTED,
        "status_explanation_length": _COMPUTED,
        "custom_fields": _CUSTOM,
        "custom_fields_truncated": _CUSTOM,
        "custom_comments": _CUSTOM,
        "custom_comments_truncated": _CUSTOM,
    },
    "version": {
        "id": _READ_ONLY,
        "created_at": _READ_ONLY,
        "updated_at": _READ_ONLY,
        "description_truncated": _COMPUTED,
        "description_length": _COMPUTED,
    },
    "membership": {
        "id": _READ_ONLY,
        "can_update": _COMPUTED,
        "can_update_immediately": _COMPUTED,
        "created_at": _READ_ONLY,
        "updated_at": _READ_ONLY,
    },
    "board": {
        "id": _READ_ONLY,
        "hidden": "deprecated, no contract attribute",
        "filter_count": "derived: the number of filters",
        "created_at": _READ_ONLY,
        "updated_at": _READ_ONLY,
        "can_update": _COMPUTED,
        "can_delete": _COMPUTED,
    },
    "grid": {
        "created_at": _READ_ONLY,
        "updated_at": _READ_ONLY,
    },
    "meeting": {
        "id": _READ_ONLY,
        "end_time": "derived from start time and duration, not writable",
        "created_at": _READ_ONLY,
        "updated_at": _READ_ONLY,
    },
    "time_entry": {
        "id": _READ_ONLY,
        "end_time": "derived, not writable",
        "created_at": _READ_ONLY,
        "updated_at": _READ_ONLY,
        "comment_truncated": _COMPUTED,
        "comment_length": _COMPUTED,
    },
    "relation": {
        "id": _READ_ONLY,
        "from_subject": _COMPUTED,
        "to_subject": _COMPUTED,
        "description_truncated": _COMPUTED,
        "description_length": _COMPUTED,
        "queried_perspective": _COMPUTED,
    },
    "work_package": {
        "id": _READ_ONLY,
        "display_id": "not writable",
        "derived_estimated_time": "derived",
        "derived_remaining_time": "derived",
        "derived_start_date": "derived",
        "derived_due_date": "derived",
        "derived_percentage_done": "derived",
        "spent_time": "computed from the time entries",
        "updated_at": _READ_ONLY,
        "children": "read-only link",
        "children_truncated": _COMPUTED,
        "ancestors": "read-only link",
        "ancestors_truncated": _COMPUTED,
        "has_description": _COMPUTED,
        "description_truncated": _COMPUTED,
        "description_length": _COMPUTED,
        "has_project_attributes": "computed by the server, not writable",
        "custom_fields": _CUSTOM,
        "custom_fields_truncated": _CUSTOM,
        "custom_comments": _CUSTOM,
        "custom_comments_truncated": _CUSTOM,
    },
}

# Fields that state one fact under two names: hiding either hides both. The services' own alias dicts
# (`user_service._LOCK_STATE_ALIASES`, `_work_package_presentation._VERSION_ALIASES`,
# `time_entry_service._USER_ALIASES`) name the same groups; a test ties them.
COUPLED_FIELDS: dict[str, tuple[frozenset[str], ...]] = {
    "user": (frozenset({"status", "locked"}),),
    "work_package": (frozenset({"version", "target_versions"}),),
    "time_entry": (frozenset({"user", "user_id"}),),
    "attachment": (frozenset({"title", "file_name"}),),
}
