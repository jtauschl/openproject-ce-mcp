"""The owner of every identity member and payload copy, written down a second time.

The tables in `app/policies/identity_fields.py` decide what leaves a write result, so a changed owner is a changed
promise: every row is repeated here and compared as a whole, so an added, removed or swapped owner fails until it is
changed in both places on purpose. The scans of `test_write_results_hide_values_everywhere.py` check the owners
against the values the fakes return; this file pins the rows themselves.
"""

from __future__ import annotations

from openproject_ce_mcp.app.policies.identity_fields import IDENTITY_BY_ACTION, IDENTITY_FIELDS, PAYLOAD_COPIES

EXPECTED_IDENTITY_FIELDS = {
    "ActivityWriteResult": {
        "work_package_id": [("work_package", "display_id"), ("work_package", "id")],
    },
    "AttachmentWriteResult": {
        "attachment_id": [("attachment", "id")],
        "target": [("attachment", "container_id")],
        "work_package_id": [("attachment", "container_id")],
    },
    "BoardWriteResult": {
        "board_id": [("board", "id")],
        "project": [("board", "project")],
    },
    "DocumentWriteResult": {
        "document_id": [("document", "id")],
        "project": [("document", "project")],
    },
    "EmojiReactionWriteResult": {
        "activity_id": [("activity", "id")],
        "reaction": [("emoji_reaction", "reaction")],
    },
    "FavoriteWriteResult": {
        "project": [("project", "name")],
        "project_id": [("project", "id")],
    },
    "FileLinkWriteResult": {
        "file_link_id": [("file_link", "id")],
        "work_package_id": [("work_package", "display_id"), ("work_package", "id")],
    },
    "GridWriteResult": {
        "grid_id": [("grid", "id")],
        "scope": [("grid", "scope")],
    },
    "GroupWriteResult": {
        "group_id": [("group", "id")],
    },
    "MeetingAgendaItemWriteResult": {
        "agenda_item_id": [("meeting_agenda_item", "id")],
        "meeting_id": [("meeting_agenda_item", "meeting_id")],
        "target": [("meeting_agenda_item", "work_package_id")],
    },
    "MeetingOutcomeWriteResult": {
        "meeting_agenda_item_id": [("meeting_outcome", "meeting_agenda_item_id")],
        "outcome_id": [("meeting_outcome", "id")],
        "target": [("meeting_outcome", "work_package_id")],
    },
    "MeetingSectionWriteResult": {
        "meeting_id": [("meeting_section", "meeting_id")],
        "section_id": [("meeting_section", "id")],
    },
    "MeetingWriteResult": {
        "meeting_id": [("meeting", "id")],
        "project": [("meeting", "project")],
    },
    "MembershipWriteResult": {
        "membership_id": [("membership", "id")],
        "project": [("membership", "project_name")],
    },
    "NewsWriteResult": {
        "news_id": [("news", "id")],
        "project": [("news", "project")],
    },
    "NotificationMarkResult": {
        "notification_id": [("notification", "id")],
    },
    "ProjectCopyResult": {
        "job_status_id": [("job_status", "id")],
        "parent_target": [("project", "parent_id"), ("project", "parent_name")],
        "source_project": [("project", "name")],
        "source_project_id": [("project", "id")],
    },
    "ProjectWriteResult": {
        "parent_target": [("project", "parent_id"), ("project", "parent_name")],
        "project": [("project", "name")],
        "project_id": [("project", "id")],
    },
    "RecurringMeetingOccurrenceWriteResult": {
        "recurring_meeting_id": [("meeting", "recurring_meeting_id"), ("recurring_meeting", "id")],
        "start_time": [("meeting", "start_time"), ("recurring_meeting", "start_time")],
    },
    "RecurringMeetingWriteResult": {
        "project": [("recurring_meeting", "project")],
        "recurring_meeting_id": [("recurring_meeting", "id")],
    },
    "RelationUpdateResult": {
        "relation_id": [("relation", "id")],
    },
    "RelationWriteResult": {
        "related_target": [
            ("relation", "from_id"),
            ("relation", "from_subject"),
            ("relation", "to_id"),
            ("relation", "to_subject"),
        ],
        "relation_id": [("relation", "id")],
        "target": [
            ("relation", "from_id"),
            ("relation", "from_subject"),
            ("relation", "to_id"),
            ("relation", "to_subject"),
        ],
        "work_package_id": [("relation", "from_id"), ("relation", "to_id")],
    },
    "ReminderWriteResult": {
        "reminder_id": [("reminder", "id")],
        "target": [("reminder", "work_package_id")],
    },
    "StorageWriteResult": {
        "storage_id": [("storage", "id")],
    },
    "TimeEntryWriteResult": {
        "project": [("time_entry", "project")],
        "target": [("time_entry", "entity_id"), ("time_entry", "entity_name")],
        "time_entry_id": [("time_entry", "id")],
    },
    "UserNonWorkingTimeWriteResult": {
        "non_working_time_id": [("user_non_working_time", "id")],
        "user_id": [("user_non_working_time", "user_id")],
    },
    "UserWorkingHoursWriteResult": {
        "user_id": [("user_working_hours", "user_id")],
        "working_hours_id": [("user_working_hours", "id")],
    },
    "UserWriteResult": {
        "user_id": [("user", "id")],
    },
    "VersionWriteResult": {
        "project": [("version", "defining_project")],
        "version_id": [("version", "id")],
    },
    "WatcherWriteResult": {
        "watcher_user_id": [("watcher", "id")],
        "work_package_id": [("work_package", "display_id"), ("work_package", "id")],
    },
    "WikiPageLinkWriteResult": {
        "link_id": [("wiki_page_link", "id")],
        "target": [("wiki_page_link", "work_package_id")],
        "work_package_id": [("wiki_page_link", "work_package_id")],
    },
    "WorkPackageWriteResult": {
        "parent_target": [("work_package", "parent_display_id"), ("work_package", "parent_id")],
        "project": [("work_package", "project")],
        "work_package_id": [("work_package", "display_id"), ("work_package", "id")],
    },
}

EXPECTED_PAYLOAD_COPIES = {
    "AttachmentWriteResult": {
        "description": [("attachment", "description")],
        "fileName": [("attachment", "file_name"), ("attachment", "title")],
        "fileSize": [("attachment", "file_size_bytes")],
    },
    "GroupWriteResult": {
        "id": [("group", "id")],
    },
    "MeetingAgendaItemWriteResult": {
        "_links.meeting": [("meeting_agenda_item", "meeting_id")],
        "_links.section": [("meeting_agenda_item", "meeting_section_id")],
        "_links.workPackage": [("meeting_agenda_item", "work_package_id")],
    },
    "MeetingOutcomeWriteResult": {
        "_links.agendaItem": [("meeting_outcome", "meeting_agenda_item_id")],
        "_links.workPackage": [("meeting_outcome", "work_package_id")],
    },
    "MeetingSectionWriteResult": {
        "_links.meeting": [("meeting_section", "meeting_id")],
    },
    "NewsWriteResult": {
        "_links.project": [("news", "project"), ("news", "project_id")],
    },
    "RecurringMeetingOccurrenceWriteResult": {
        "recurring_meeting_id": [("meeting", "recurring_meeting_id"), ("recurring_meeting", "id")],
        "start_time": [("meeting", "start_time"), ("recurring_meeting", "start_time")],
    },
    "RecurringMeetingWriteResult": {
        "_links.project": [("recurring_meeting", "project"), ("recurring_meeting", "project_id")],
    },
    "StorageWriteResult": {
        "id": [("storage", "id")],
    },
    "UserNonWorkingTimeWriteResult": {
        "id": [("user_non_working_time", "id")],
    },
    "UserWorkingHoursWriteResult": {
        "id": [("user_working_hours", "id")],
    },
    "WikiPageLinkWriteResult": {
        "id": [("wiki_page_link", "id")],
    },
}

EXPECTED_BY_ACTION = {
    ("WorkPackageWriteResult", "create"): {
        "target": [("work_package", "parent_display_id"), ("work_package", "parent_id")]
    }
}


def _as_sets(table):
    return {key: {member: set(owners) for member, owners in members.items()} for key, members in table.items()}


def test_the_identity_owners_are_the_pinned_ones() -> None:
    assert _as_sets(IDENTITY_FIELDS) == _as_sets(EXPECTED_IDENTITY_FIELDS)


def test_the_payload_copy_owners_are_the_pinned_ones() -> None:
    assert _as_sets(PAYLOAD_COPIES) == _as_sets(EXPECTED_PAYLOAD_COPIES)


def test_the_action_dependent_owners_are_the_pinned_ones() -> None:
    assert _as_sets(IDENTITY_BY_ACTION) == _as_sets(EXPECTED_BY_ACTION)
