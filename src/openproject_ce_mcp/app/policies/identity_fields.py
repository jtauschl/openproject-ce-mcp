"""Which model field each top-level member of a write result repeats. Pure data, no I/O.

A write result carries, beside its `payload` and its stamped `result`, members that repeat the value of one field of
one entity: the identity fields (`project`, `meeting_id`, `grid_id` ...) and the work package `target` and
`related_target` that name a work package through an association field (`time_entry.entity_id`,
`relation.from_id`). When the operator hides that field the member leaves the result as well
(`hidden_fields.hidden_identity_keys`). Each member has one owner: no value is judged by two entities.

`IDENTITY_FIELDS[result class][member]` lists the (entity, model field) pairs that own the member; a member that can
hold a work package reference in two spellings (the id or the display id the caller typed) lists both fields and is
hidden when either is. `NOT_AN_IDENTITY[result class]` lists the other members with their reason; a test requires
every member of every write result class to be in one of the two tables or in `STAMPED_BY_THEIR_OWN_ENTITY`.
"""

from __future__ import annotations

_WORK_PACKAGE_REFERENCE = (("work_package", "id"), ("work_package", "display_id"))
# OpenProject stores `precedes` as `follows` with the ends swapped, so which end a member repeats depends on the
# direction the caller typed: hiding either end hides every member that names an end.
_RELATION_ENDS = (("relation", "from_id"), ("relation", "to_id"))
_OCCURRENCE_START = (("recurring_meeting", "start_time"), ("meeting", "start_time"))
_OCCURRENCE_SERIES = (("recurring_meeting", "id"), ("meeting", "recurring_meeting_id"))
_RELATION_TARGETS = _RELATION_ENDS + (("relation", "from_subject"), ("relation", "to_subject"))
_PARENT = (("work_package", "parent_id"), ("work_package", "parent_display_id"))
_PROJECT_PARENT = (("project", "parent_id"), ("project", "parent_name"))

IDENTITY_FIELDS: dict[str, dict[str, tuple[tuple[str, str], ...]]] = {
    "ActivityWriteResult": {"work_package_id": _WORK_PACKAGE_REFERENCE},
    "AttachmentWriteResult": {
        "attachment_id": (("attachment", "id"),),
        "work_package_id": (("attachment", "container_id"),),
        "target": (("attachment", "container_id"),),
    },
    "BoardWriteResult": {"board_id": (("board", "id"),), "project": (("board", "project"),)},
    "ContainerAttachmentWriteResult": {
        "attachment_id": (("attachment", "id"),),
        "container_type": (("attachment", "container_type"),),
        "container_id": (("attachment", "container_id"),),
    },
    "DocumentWriteResult": {"document_id": (("document", "id"),), "project": (("document", "project"),)},
    "EmojiReactionWriteResult": {
        "activity_id": (("activity", "id"),),
        "reaction": (("emoji_reaction", "reaction"),),
    },
    "FavoriteWriteResult": {"project_id": (("project", "id"),), "project": (("project", "name"),)},
    "FileLinkWriteResult": {
        "file_link_id": (("file_link", "id"),),
        "work_package_id": _WORK_PACKAGE_REFERENCE,
    },
    "GridWriteResult": {"grid_id": (("grid", "id"),), "scope": (("grid", "scope"),)},
    "GroupWriteResult": {"group_id": (("group", "id"),)},
    "MeetingAgendaItemWriteResult": {
        "agenda_item_id": (("meeting_agenda_item", "id"),),
        "meeting_id": (("meeting_agenda_item", "meeting_id"),),
        "target": (("meeting_agenda_item", "work_package_id"),),
    },
    "MeetingOutcomeWriteResult": {
        "outcome_id": (("meeting_outcome", "id"),),
        "meeting_agenda_item_id": (("meeting_outcome", "meeting_agenda_item_id"),),
        "target": (("meeting_outcome", "work_package_id"),),
    },
    "MeetingSectionWriteResult": {
        "section_id": (("meeting_section", "id"),),
        "meeting_id": (("meeting_section", "meeting_id"),),
    },
    "MeetingWriteResult": {"meeting_id": (("meeting", "id"),), "project": (("meeting", "project"),)},
    "MembershipWriteResult": {
        "membership_id": (("membership", "id"),),
        "project": (("membership", "project_name"),),
    },
    "NotificationMarkResult": {"notification_id": (("notification", "id"),)},
    "NewsWriteResult": {"news_id": (("news", "id"),), "project": (("news", "project"),)},
    "ProjectCopyResult": {
        "source_project_id": (("project", "id"),),
        "source_project": (("project", "name"),),
        "job_status_id": (("job_status", "id"),),
        "parent_target": _PROJECT_PARENT,
    },
    "ProjectWriteResult": {
        "project_id": (("project", "id"),),
        "project": (("project", "name"),),
        "parent_target": _PROJECT_PARENT,
    },
    "RecurringMeetingOccurrenceWriteResult": {
        "recurring_meeting_id": _OCCURRENCE_SERIES,
        "start_time": _OCCURRENCE_START,
    },
    "RecurringMeetingWriteResult": {
        "recurring_meeting_id": (("recurring_meeting", "id"),),
        "project": (("recurring_meeting", "project"),),
    },
    "QueryStarResult": {"query_id": (("view", "id"),)},
    "RelationUpdateResult": {"relation_id": (("relation", "id"),)},
    "RelationWriteResult": {
        "relation_id": (("relation", "id"),),
        "work_package_id": _RELATION_ENDS,
        "target": _RELATION_TARGETS,
        "related_target": _RELATION_TARGETS,
    },
    "ReminderWriteResult": {
        "reminder_id": (("reminder", "id"),),
        "target": (("reminder", "work_package_id"),),
    },
    "StorageWriteResult": {"storage_id": (("storage", "id"),)},
    "TimeEntryWriteResult": {
        "time_entry_id": (("time_entry", "id"),),
        "project": (("time_entry", "project"),),
        "target": (("time_entry", "entity_id"), ("time_entry", "entity_name")),
    },
    "UserNonWorkingTimeWriteResult": {
        "non_working_time_id": (("user_non_working_time", "id"),),
        "user_id": (("user_non_working_time", "user_id"),),
    },
    "UserWorkingHoursWriteResult": {
        "working_hours_id": (("user_working_hours", "id"),),
        "user_id": (("user_working_hours", "user_id"),),
    },
    "UserWriteResult": {"user_id": (("user", "id"),)},
    "VersionWriteResult": {"version_id": (("version", "id"),), "project": (("version", "defining_project"),)},
    "WatcherWriteResult": {
        "work_package_id": _WORK_PACKAGE_REFERENCE,
        "watcher_user_id": (("watcher", "id"),),
    },
    "WikiPageLinkWriteResult": {
        "link_id": (("wiki_page_link", "id"),),
        "work_package_id": (("wiki_page_link", "work_package_id"),),
        "target": (("wiki_page_link", "work_package_id"),),
    },
    "WorkPackageWriteResult": {
        "work_package_id": _WORK_PACKAGE_REFERENCE,
        "project": (("work_package", "project"),),
        "parent_target": _PARENT,
    },
}

# Members whose owner depends on the action: the `target` of a work package create is its parent.
IDENTITY_BY_ACTION: dict[tuple[str, str], dict[str, tuple[tuple[str, str], ...]]] = {
    ("WorkPackageWriteResult", "create"): {"target": _PARENT},
}

# Keys of a hand-built `payload` that copy the value of a field (a key, or `_links.<rel>`), per write result class.
# The payloads that are the server's form echo are judged by `payload_fields.PAYLOAD_KEYS`; these are the ones the
# service builds from what the caller passed or from the record it read.
PAYLOAD_COPIES: dict[str, dict[str, tuple[tuple[str, str], ...]]] = {
    "AttachmentWriteResult": {
        "fileName": (("attachment", "file_name"), ("attachment", "title")),
        "fileSize": (("attachment", "file_size_bytes"),),
        "description": (("attachment", "description"),),
    },
    "ContainerAttachmentWriteResult": {
        "fileName": (("attachment", "file_name"), ("attachment", "title")),
        "fileSize": (("attachment", "file_size_bytes"),),
        "description": (("attachment", "description"),),
    },
    "GroupWriteResult": {"id": (("group", "id"),)},
    "MeetingAgendaItemWriteResult": {
        "_links.meeting": (("meeting_agenda_item", "meeting_id"),),
        "_links.section": (("meeting_agenda_item", "meeting_section_id"),),
        "_links.workPackage": (("meeting_agenda_item", "work_package_id"),),
    },
    "MeetingOutcomeWriteResult": {
        "_links.agendaItem": (("meeting_outcome", "meeting_agenda_item_id"),),
        "_links.workPackage": (("meeting_outcome", "work_package_id"),),
    },
    "NewsWriteResult": {"_links.project": (("news", "project_id"), ("news", "project"))},
    "RecurringMeetingWriteResult": {
        "id": (("recurring_meeting", "id"),),
        "_links.project": (("recurring_meeting", "project_id"), ("recurring_meeting", "project")),
    },
    "MeetingSectionWriteResult": {"_links.meeting": (("meeting_section", "meeting_id"),)},
    "RecurringMeetingOccurrenceWriteResult": {
        "recurring_meeting_id": _OCCURRENCE_SERIES,
        "start_time": _OCCURRENCE_START,
    },
    "StorageWriteResult": {"id": (("storage", "id"),)},
    "UserNonWorkingTimeWriteResult": {"id": (("user_non_working_time", "id"),)},
    "UserWorkingHoursWriteResult": {"id": (("user_working_hours", "id"),)},
    "WikiPageLinkWriteResult": {"id": (("wiki_page_link", "id"),)},
}

# Members that carry no field value of the result's own entity, and the members that are stamped by their own
# entity's settings (`result`, a work package `target` or `parent_target`).
STAMPED_BY_THEIR_OWN_ENTITY = frozenset({"result", "target", "parent_target", "related_target"})
HEADER = frozenset({"action", "state", "ready", "message", "payload", "validation_errors"})

NOT_AN_IDENTITY: dict[str, dict[str, str]] = {
    "QueryStarResult": {"starred": "the flag the caller passed: an action argument, not a stored field value"},
    "BulkWorkPackageWriteResult": {
        "confirmed": "a flag of the batch",
        "requires_confirmation": "a flag of the batch",
        "total": "a count",
        "succeeded": "a count",
        "failed": "a count",
        "items": "each item's result is stamped like a single write result",
    },
}
