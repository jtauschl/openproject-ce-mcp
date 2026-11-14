"""The version floors of this server, each with the OpenProject source that says it, in one place.

A floor is the first OpenProject release a feature can be used on. It is stated in four places that must agree:
the `call_version_gated` calls (and the hand-built "requires OpenProject X.Y" messages) in `app/`, the tool
descriptions, `docs/tools.md` and this catalog. `check_api.py` proves each entry's routes against the pinned OpenProject
sources (offline); `tests/unit/test_version_floor_catalog.py` ties the other places to the entries (in CI, no sources).

Pure data: no imports from the package, so the checker and the tests import it as a plain module.
"""

from __future__ import annotations

from dataclasses import dataclass

GATE = "gate"  # a `call_version_gated(call, feature=..., floor=...)` call
MESSAGE = "message"  # a hand-built "requires OpenProject X.Y" message, no gate call

_MEETING_API = "modules/meeting/lib/api/v3"
_WIKI_LINKS = "modules/wikis/lib/api/v3/page_links"


@dataclass(frozen=True)
class Route:
    """One route (or symbol) behind a floor and the first release whose source has it.

    `pattern` is a fixed string the checker greps for under `subtree`; it is absent before `release` and present
    from then on, in every pinned version."""

    symbol: str
    subtree: str
    pattern: str
    release: str


@dataclass(frozen=True)
class Floor:
    """One floor: `feature` and `floor` as the code states them, the tools that carry it, the routes behind it.

    `floor` equals the newest release among `routes` (a gate for several routes needs them all). A floor higher than
    that is a decision, and `reason` says why (the route exists earlier, the tool starts later)."""

    feature: str
    floor: str
    kind: str
    tools: tuple[str, ...]
    routes: tuple[Route, ...]
    files: tuple[str, ...] = ()  # MESSAGE entries: the files under app/ whose message states the floor
    reason: str = ""
    note: str = ""  # context that changes no rule: why a tool starts where it does


FLOORS: tuple[Floor, ...] = (
    Floor(
        "Reminders",
        "16.1",
        GATE,
        ("list_reminders", "create_work_package_reminder", "update_reminder", "delete_reminder"),
        (
            Route(
                "reminders by work package",
                "lib/api/v3/reminders/reminders_by_work_package_api.rb",
                "resource :reminders",
                "16.1",
            ),
        ),
    ),
    Floor(
        "version_status",
        "16.4",
        GATE,
        ("list_work_packages",),
        (
            Route(
                "version status filter operators",
                "app/models/queries/operators/versions",
                "open_status.rb",
                "16.4",
            ),
        ),
    ),
    Floor(
        "Project favorites",
        "17.0",
        GATE,
        ("set_project_favorite",),
        (
            Route(
                "workspaces favorite actions",
                "lib/api/v3/workspaces/nested_apis.rb",
                "FavoriteActionsAPI",
                "17.0",
            ),
        ),
    ),
    Floor(
        "User working hours",
        "17.3",
        GATE,
        (
            "list_user_working_hours",
            "get_user_working_hours",
            "create_user_working_hours",
            "update_user_working_hours",
            "delete_user_working_hours",
        ),
        (
            Route(
                "working hours by user",
                "lib/api/v3/user_working_hours/working_hours_by_user_api.rb",
                "resource :working_hours",
                "17.3",
            ),
        ),
    ),
    Floor(
        "User non-working times",
        "17.3",
        GATE,
        (
            "list_user_non_working_times",
            "create_user_non_working_time",
            "update_user_non_working_time",
            "delete_user_non_working_time",
        ),
        (
            Route(
                "non-working times by user",
                "lib/api/v3/user_non_working_times/non_working_times_by_user_api.rb",
                "resource :non_working_times",
                "17.3",
            ),
        ),
    ),
    Floor(
        "Meetings",
        "17.4",
        GATE,
        ("list_meetings", "get_meeting", "create_meeting", "update_meeting", "delete_meeting"),
        (
            Route("meetings read", f"{_MEETING_API}/meetings/meetings_api.rb", "resources :meetings", "16.0"),
            Route("meetings write", f"{_MEETING_API}/meetings/meetings_api.rb", "post &", "17.4"),
        ),
        note="list and get exist from 16.0 with a legacy representation (16.0 to 17.3); the tools start at 17.4, the "
        "first release with the representation they use and with the write routes",
    ),
    Floor(
        "Recurring meetings",
        "17.4",
        GATE,
        (
            "list_recurring_meetings",
            "get_recurring_meeting",
            "create_recurring_meeting",
            "update_recurring_meeting",
            "delete_recurring_meeting",
        ),
        (
            Route(
                "recurring meetings",
                f"{_MEETING_API}/recurring_meetings/recurring_meetings_api.rb",
                "resources :recurring_meetings",
                "17.4",
            ),
        ),
    ),
    Floor(
        "Recurring meeting occurrences",
        "17.4",
        GATE,
        (
            "list_recurring_meeting_occurrences",
            "init_recurring_meeting_occurrence",
            "cancel_recurring_meeting_occurrence",
        ),
        (
            Route(
                "occurrences by recurring meeting",
                f"{_MEETING_API}/recurring_meetings/occurrences_by_recurring_meeting_api.rb",
                "namespace :upcoming",
                "17.4",
            ),
        ),
    ),
    Floor(
        "Ending a recurring meeting series",
        "17.8",
        GATE,
        ("end_recurring_meeting",),
        (Route("end a series", f"{_MEETING_API}/recurring_meetings/recurring_meetings_api.rb", 'post "end"', "17.8"),),
    ),
    Floor(
        "Meeting sections",
        "17.4",
        GATE,
        ("list_meeting_sections",),
        (
            Route(
                "sections by meeting",
                f"{_MEETING_API}/meeting_sections/sections_by_meeting_api.rb",
                "resources :sections",
                "17.4",
            ),
        ),
    ),
    Floor(
        "Meeting sections",
        "17.6",
        GATE,
        ("get_meeting_section", "create_meeting_section", "update_meeting_section", "delete_meeting_section"),
        (
            Route(
                "meeting sections",
                f"{_MEETING_API}/meeting_sections/meeting_sections_api.rb",
                "resources :meeting_sections",
                "17.6",
            ),
        ),
    ),
    Floor(
        "Meeting agenda items",
        "17.4",
        GATE,
        ("list_meeting_agenda_items",),
        (
            Route(
                "agenda items by meeting",
                f"{_MEETING_API}/meeting_agenda_items/agenda_items_by_meeting_api.rb",
                "resources :agenda_items",
                "17.4",
            ),
        ),
    ),
    Floor(
        "Meeting agenda items",
        "17.6",
        GATE,
        (
            "get_meeting_agenda_item",
            "create_meeting_agenda_item",
            "update_meeting_agenda_item",
            "delete_meeting_agenda_item",
        ),
        (
            Route(
                "meeting agenda items",
                f"{_MEETING_API}/meeting_agenda_items/meeting_agenda_items_api.rb",
                "resources :meeting_agenda_items",
                "17.6",
            ),
        ),
    ),
    Floor(
        "Work package meeting agenda items",
        "17.7",
        GATE,
        ("list_work_package_meeting_agenda_items",),
        (
            Route(
                "agenda items by work package",
                f"{_MEETING_API}/meeting_agenda_items/meeting_agenda_items_by_work_package_api.rb",
                "resources :meeting_agenda_items",
                "17.7",
            ),
        ),
    ),
    Floor(
        "Meeting outcomes",
        "17.6",
        GATE,
        (
            "list_meeting_outcomes",
            "get_meeting_outcome",
            "create_meeting_outcome",
            "update_meeting_outcome",
            "delete_meeting_outcome",
        ),
        (
            Route(
                "meeting outcomes",
                f"{_MEETING_API}/meeting_outcomes/meeting_outcomes_api.rb",
                "resources :meeting_outcomes",
                "17.6",
            ),
        ),
    ),
    Floor(
        "Listing wiki page links",
        "17.5",
        GATE,
        ("list_work_package_wiki_links",),
        (
            Route(
                "wiki page links of a work package",
                f"{_WIKI_LINKS}/work_package_wiki_page_links_api.rb",
                "resources :wiki_page_links",
                "17.5",
            ),
        ),
    ),
    Floor(
        "Deleting wiki page links",
        "17.6",
        GATE,
        ("delete_work_package_wiki_link",),
        (Route("delete a wiki page link", f"{_WIKI_LINKS}/page_links_api.rb", "delete &", "17.6"),),
    ),
    Floor(
        "Creating wiki page links",
        "17.7",
        GATE,
        ("create_work_package_wiki_link",),
        (Route("create a wiki page link", f"{_WIKI_LINKS}/work_package_wiki_page_links_api.rb", "post &", "17.7"),),
    ),
    Floor(
        "Sprints",
        "17.3",
        MESSAGE,
        ("list_sprints", "get_sprint", "update_work_package", "bulk_update_work_packages"),
        (Route("sprints", "modules/backlogs/lib/api/v3/sprints/sprints_api.rb", "resources :sprints", "17.3"),),
        files=("app/services/sprint_service.py", "app/resolvers/sprint_resolver.py"),
    ),
    Floor(
        "Backlog buckets",
        "17.6",
        MESSAGE,
        ("list_backlog_buckets", "get_backlog_bucket"),
        (
            Route(
                "backlog buckets",
                "modules/backlogs/lib/api/v3/backlog_buckets/backlog_buckets_api.rb",
                "resources :backlog_buckets",
                "17.6",
            ),
        ),
        files=("app/services/backlog_bucket_service.py",),
    ),
    Floor(
        "observed_in_versions",
        "17.9",
        MESSAGE,
        (
            "create_work_package",
            "update_work_package",
            "create_subtask",
            "bulk_create_work_packages",
            "bulk_update_work_packages",
            "list_work_packages",
        ),
        (
            Route(
                "observed in versions filter",
                "app/models/queries/work_packages/filter/observed_in_versions_filter.rb",
                "ObservedInVersionsFilter",
                "17.9",
            ),
            Route(
                "observed in versions attribute",
                "lib/api/v3/work_packages/work_package_representer.rb",
                "observed_in_versions",
                "17.9",
            ),
        ),
        files=("app/services/work_package_service.py",),
    ),
    Floor(
        "Semantic work package references",
        "17.5",
        MESSAGE,
        (),
        (Route("semantic identifier model", "app/models/work_package", "semantic_id?", "17.4"),),
        files=("app/resolvers/work_package_resolver.py",),
        reason="17.4 needs a feature decision besides the setting; from 17.5 the setting alone activates it",
    ),
)


@dataclass(frozen=True)
class ColumnFloor:
    """The first release a sort or group column exists in (`COLUMN_FLOORS` of `project_columns.py` and
    `work_package_columns.py`). `routes` is empty for a column no source check reaches yet; `gap` says why."""

    entity: str
    column: str
    floor: str
    routes: tuple[Route, ...] = ()
    reason: str = ""
    gap: str = ""


_WP_SELECTS = "app/models/queries/work_packages/selects"

COLUMNS: tuple[ColumnFloor, ...] = (
    ColumnFloor(
        "project",
        "updated_at",
        "16.5",
        (Route("project updated_at order", "app/models/queries/projects/orders", "updated_at_order.rb", "16.5"),),
    ),
    ColumnFloor(
        "work_package",
        "project_phase",
        "16.1",
        (Route("project phase select", _WP_SELECTS, "project_phase_select.rb", "16.1"),),
    ),
    ColumnFloor(
        "work_package",
        "sprint",
        "17.4",
        gap="the engine of the backlogs module registers the column; no source symbol checked yet",
        reason="writing a sprint is possible from 17.3, the query column came one release later",
    ),
    ColumnFloor(
        "work_package",
        "backlog_bucket",
        "17.6",
        gap="the engine of the backlogs module registers the column; no source symbol checked yet",
    ),
    ColumnFloor(
        "work_package",
        "target_versions",
        "17.8",
        (Route("target_versions property select", f"{_WP_SELECTS}/property_select.rb", "target_versions:", "17.7"),),
        reason="the property exists from 17.7, and 17.8 translates either name to the one the instance uses",
    ),
    ColumnFloor(
        "work_package",
        "observed_in_versions",
        "17.9",
        (
            Route(
                "observed_in_versions property select",
                f"{_WP_SELECTS}/property_select.rb",
                "observed_in_versions:",
                "17.9",
            ),
        ),
    ),
)

# A behaviour version the sources can prove, by the symbol that appears in that release.
BEHAVIOUR_ROUTES: dict[tuple[str, str], Route] = {
    ("list_meetings", "17.9"): Route(
        "meeting title filter",
        "modules/meeting/app/models/queries/meetings/filters/title_filter.rb",
        "TitleFilter",
        "17.9",
    ),
    ("create_recurring_meeting", "17.5"): Route(
        "monthly recurrence frequencies",
        "modules/meeting/app/models/recurring_meeting.rb",
        "monthly_day_of_month",
        "17.5",
    ),
    ("delete_version", "17.8"): Route(
        "version delete counts the found-in work packages",
        "app/contracts/versions/delete_contract.rb",
        "work_package_versions.exists?",
        "17.8",
    ),
}

# A description that repeats the floor of another feature: (tool, release) -> that feature.
DESCRIPTION_MENTIONS: dict[tuple[str, str], str] = {
    ("delete_meeting", "17.8"): "Ending a recurring meeting series",
}

# The tools whose sort_by and group_by descriptions list the column floors of an entity (`describe_floors()`).
COLUMN_TOOLS: dict[str, str] = {
    "list_work_packages": "work_package",
    "search_work_packages": "work_package",
    "list_projects": "project",
}

# A hand-built message that names the floor of another feature: (file under app/, release) -> that feature.
MENTIONS: dict[tuple[str, str], str] = {
    ("app/services/meeting_service.py", "17.8"): "Ending a recurring meeting series",
}

# A version a tool description names that is no route floor: what the tool does differently from that release on.
# Keyed by tool and release, the value says what the release changes.
NOT_A_ROUTE_FLOOR: dict[tuple[str, str], str] = {
    ("delete_work_package", "17.6"): "up to 17.6 all descendants are deleted too",
    ("delete_work_package_wiki_link", "17.4"): "on 17.4 and older the route is absent and the tool names 17.6",
    ("delete_work_package_wiki_link", "17.5"): "on 17.5 the link check before the delete usually fails first",
    ("create_work_package_wiki_link", "17.6"): "17.6 has only the GET on the work package route",
    ("init_recurring_meeting_occurrence", "17.5"): "17.4 and 17.5 fail on an occurrence that already exists",
    ("init_recurring_meeting_occurrence", "17.6"): "from 17.6 an existing occurrence is returned, and templates open",
    ("list_meeting_outcomes", "17.4"): "the meeting_outcomes endpoint does not exist on 17.4 and 17.5",
    ("list_meeting_outcomes", "17.5"): "the meeting_outcomes endpoint does not exist on 17.4 and 17.5",
    ("list_meetings", "16.6"): "16.6 exposes an incompatible legacy meeting representation, so the tools start at 17.4",
    ("list_user_working_hours", "17.6"): "feature-flag-gated through 17.6",
    ("list_user_non_working_times", "17.6"): "feature-flag-gated through 17.6",
    ("list_work_package_wiki_links", "17.6"): "a server bug on 17.5 and 17.6 also hides a work package without links",
    ("update_meeting", "17.5"): "17.4 and 17.5 add a participant a second time",
    (
        "create_recurring_meeting",
        "17.5",
    ): "the monthly_day_of_month and monthly_nth_weekday frequencies exist from 17.5 (recurring_meeting.rb)",
    ("update_meeting", "17.7"): "17.4 to 17.7 send no invitations on update",
    ("update_meeting", "17.8"): "from 17.8 an update out of draft or with notifications on sends the invitations",
    ("update_recurring_meeting", "17.8"): "on 17.4 to 17.8 a time-of-day change rewrites the slots of past occurrences",
    ("update_document", "16.6"): "on 16.6 the server rejects every update with a generic permission error",
    ("delete_user", "17.1"): "the last active admin cannot be deleted from 17.1",
    ("delete_group", "17.7"): "groups synchronised from LDAP are rejected from 17.7",
    ("delete_grid", "17.0"): "from 17.0 a board's column queries are deleted with it",
    ("get_project", "17.2"): "custom_comments is filled from 17.2 (a project attribute can have a comment)",
    ("delete_version", "17.8"): "from 17.8 a version used as a work package's found-in version also blocks the delete",
    ("delete_work_package", "17.7"): "up to 17.6 all descendants are deleted too, from 17.7 only those you may delete",
    ("list_meetings", "17.9"): "the title substring filter exists from 17.9",
    (
        "list_user_working_hours",
        "17.7",
    ): "the schedule feature is generally available from 17.7, feature-flagged before",
    ("list_user_non_working_times", "17.7"): "the feature is generally available from 17.7, feature-flagged before",
    ("list_work_package_available_relation_candidates", "17.8"): "the project sequence number as the id needs 17.8",
    ("list_work_packages", "17.5"): "parent_display_id is filled from 17.5 (semantic mode)",
}
