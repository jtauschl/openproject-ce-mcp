"""Write/delete-tool behavioral-contract cases for the Meetings domain
(5 sub-resources, OPM-154): Meetings, Meeting Agenda Items, Meeting
Outcomes, Meeting Sections, Recurring Meetings + Occurrences.

Sibling modules import this as `from _write_contract_cases_meeting import
...` (no package prefix) -- same rootless-import convention as
`_client_test_helpers.py`/`_tools_test_helpers.py`.
"""

from __future__ import annotations

import json

import httpx
from _write_contract_cases_types import WriteToolCase

from openproject_ce_mcp.config import Settings


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "base_url": "https://op.example.com",
        "api_token": "token",
        "timeout": 12,
        "verify_ssl": True,
        "default_page_size": 20,
        "max_page_size": 50,
        "max_results": 100,
        "log_level": "WARNING",
        "read_projects": ("*",),
        "write_projects": ("*",),
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _unexpected(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"Unexpected request: {request.method} {request.url}")


def _meeting_payload(*, meeting_id: int = 12, title: str = "Sprint Planning") -> dict:
    return {
        "id": meeting_id,
        "title": title,
        "location": None,
        "lockVersion": 0,
        "startTime": "2026-09-01T09:00:00Z",
        "endTime": "2026-09-01T10:00:00Z",
        "duration": "PT1H",
        "state": "open",
        "sharing": "invited",
        "template": False,
        "notify": True,
        "_links": {
            "project": {"href": "/api/v3/projects/6", "title": "Demo"},
            "author": {"href": "/api/v3/users/1", "title": "Alice"},
        },
        "_embedded": {"participants": []},
    }


# --- Meetings -----------------------------------------------------------


def _create_meeting_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/projects/demo" and request.method == "GET":
        return httpx.Response(
            200, json={"_type": "Project", "id": 6, "name": "Demo", "identifier": "demo"}, request=request
        )
    if request.url.path == "/api/v3/meetings/form" and request.method == "POST":
        body = json.loads(request.content)
        return httpx.Response(200, json={"_embedded": {"payload": body, "validationErrors": {}}}, request=request)
    if request.url.path == "/api/v3/meetings" and request.method == "POST":
        return httpx.Response(201, json=_meeting_payload(), request=request)
    return _unexpected(request)


def _update_meeting_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/meetings/12" and request.method == "GET":
        return httpx.Response(200, json=_meeting_payload(), request=request)
    if request.url.path == "/api/v3/meetings/12/form" and request.method == "POST":
        body = json.loads(request.content)
        return httpx.Response(200, json={"_embedded": {"payload": body, "validationErrors": {}}}, request=request)
    if request.url.path == "/api/v3/meetings/12" and request.method == "PATCH":
        return httpx.Response(200, json=_meeting_payload(title="Sprint Planning Updated"), request=request)
    return _unexpected(request)


def _delete_meeting_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/meetings/12" and request.method == "GET":
        return httpx.Response(200, json=_meeting_payload(), request=request)
    if request.url.path == "/api/v3/meetings/12" and request.method == "DELETE":
        return httpx.Response(204, request=request)
    return _unexpected(request)


# --- Meeting Agenda Items --------------------------------------------------


def _agenda_item_payload(*, item_id: int = 21, title: str = "Discuss roadmap") -> dict:
    return {
        "id": item_id,
        "title": title,
        "notes": None,
        "position": 1,
        "durationInMinutes": 10,
        "itemType": "simple",
        "lockVersion": 0,
        "_links": {
            "meeting": {"href": "/api/v3/meetings/12", "title": "Sprint Planning"},
            "author": {"href": "/api/v3/users/1", "title": "Alice"},
        },
        "_embedded": {"outcomes": []},
    }


def _create_meeting_agenda_item_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/meetings/12" and request.method == "GET":
        return httpx.Response(200, json=_meeting_payload(), request=request)
    if request.url.path == "/api/v3/meeting_agenda_items" and request.method == "POST":
        return httpx.Response(201, json=_agenda_item_payload(), request=request)
    return _unexpected(request)


def _update_meeting_agenda_item_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/meeting_agenda_items/21" and request.method == "GET":
        return httpx.Response(200, json=_agenda_item_payload(), request=request)
    if request.url.path == "/api/v3/meetings/12" and request.method == "GET":
        return httpx.Response(200, json=_meeting_payload(), request=request)
    if request.url.path == "/api/v3/meeting_agenda_items/21" and request.method == "PATCH":
        return httpx.Response(200, json=_agenda_item_payload(title="Discuss roadmap v2"), request=request)
    return _unexpected(request)


def _delete_meeting_agenda_item_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/meeting_agenda_items/21" and request.method == "GET":
        return httpx.Response(200, json=_agenda_item_payload(), request=request)
    if request.url.path == "/api/v3/meetings/12" and request.method == "GET":
        return httpx.Response(200, json=_meeting_payload(), request=request)
    if request.url.path == "/api/v3/meeting_agenda_items/21" and request.method == "DELETE":
        return httpx.Response(204, request=request)
    return _unexpected(request)


# --- Meeting Outcomes -------------------------------------------------------


def _outcome_payload(*, outcome_id: int = 31, kind: str = "info") -> dict:
    return {
        "id": outcome_id,
        "kind": kind,
        "notes": None,
        "_links": {
            "agendaItem": {"href": "/api/v3/meeting_agenda_items/21", "title": "Discuss roadmap"},
            "author": {"href": "/api/v3/users/1", "title": "Alice"},
        },
    }


def _create_meeting_outcome_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/meeting_agenda_items/21" and request.method == "GET":
        return httpx.Response(200, json=_agenda_item_payload(), request=request)
    if request.url.path == "/api/v3/meetings/12" and request.method == "GET":
        return httpx.Response(200, json=_meeting_payload(), request=request)
    if request.url.path == "/api/v3/meeting_outcomes" and request.method == "POST":
        return httpx.Response(201, json=_outcome_payload(), request=request)
    return _unexpected(request)


def _update_meeting_outcome_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/meeting_outcomes/31" and request.method == "GET":
        return httpx.Response(200, json=_outcome_payload(), request=request)
    if request.url.path == "/api/v3/meeting_agenda_items/21" and request.method == "GET":
        return httpx.Response(200, json=_agenda_item_payload(), request=request)
    if request.url.path == "/api/v3/meetings/12" and request.method == "GET":
        return httpx.Response(200, json=_meeting_payload(), request=request)
    if request.url.path == "/api/v3/meeting_outcomes/31" and request.method == "PATCH":
        return httpx.Response(200, json=_outcome_payload(kind="action"), request=request)
    return _unexpected(request)


def _delete_meeting_outcome_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/meeting_outcomes/31" and request.method == "GET":
        return httpx.Response(200, json=_outcome_payload(), request=request)
    if request.url.path == "/api/v3/meeting_agenda_items/21" and request.method == "GET":
        return httpx.Response(200, json=_agenda_item_payload(), request=request)
    if request.url.path == "/api/v3/meetings/12" and request.method == "GET":
        return httpx.Response(200, json=_meeting_payload(), request=request)
    if request.url.path == "/api/v3/meeting_outcomes/31" and request.method == "DELETE":
        return httpx.Response(204, request=request)
    return _unexpected(request)


# --- Meeting Sections -------------------------------------------------------


def _section_payload(*, section_id: int = 41, title: str = "Backlog") -> dict:
    return {
        "id": section_id,
        "title": title,
        "position": 1,
        "backlog": False,
        "_links": {"meeting": {"href": "/api/v3/meetings/12", "title": "Sprint Planning"}},
    }


def _create_meeting_section_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/meetings/12" and request.method == "GET":
        return httpx.Response(200, json=_meeting_payload(), request=request)
    if request.url.path == "/api/v3/meeting_sections" and request.method == "POST":
        return httpx.Response(201, json=_section_payload(), request=request)
    return _unexpected(request)


def _update_meeting_section_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/meeting_sections/41" and request.method == "GET":
        return httpx.Response(200, json=_section_payload(), request=request)
    if request.url.path == "/api/v3/meetings/12" and request.method == "GET":
        return httpx.Response(200, json=_meeting_payload(), request=request)
    if request.url.path == "/api/v3/meeting_sections/41" and request.method == "PATCH":
        return httpx.Response(200, json=_section_payload(title="Backlog v2"), request=request)
    return _unexpected(request)


def _delete_meeting_section_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/meeting_sections/41" and request.method == "GET":
        return httpx.Response(200, json=_section_payload(), request=request)
    if request.url.path == "/api/v3/meetings/12" and request.method == "GET":
        return httpx.Response(200, json=_meeting_payload(), request=request)
    if request.url.path == "/api/v3/meeting_sections/41" and request.method == "DELETE":
        return httpx.Response(204, request=request)
    return _unexpected(request)


# --- Recurring Meetings + Occurrences ---------------------------------------


def _recurring_meeting_payload(*, recurring_meeting_id: int = 51, title: str = "Weekly Standup") -> dict:
    return {
        "id": recurring_meeting_id,
        "title": title,
        "frequency": "weekly",
        "monthlyDay": None,
        "monthlyOrdinal": None,
        "monthlyWeekday": None,
        "interval": 1,
        "endAfter": "never",
        "endDate": None,
        "iterations": None,
        "timeZone": "UTC",
        "startTime": "2026-09-01T09:00:00Z",
        "location": None,
        "duration": 0.5,
        "notify": True,
        "_links": {
            "project": {"href": "/api/v3/projects/6", "title": "Demo"},
            "author": {"href": "/api/v3/users/1", "title": "Alice"},
        },
    }


def _create_recurring_meeting_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/projects/demo" and request.method == "GET":
        return httpx.Response(
            200, json={"_type": "Project", "id": 6, "name": "Demo", "identifier": "demo"}, request=request
        )
    if request.url.path == "/api/v3/recurring_meetings" and request.method == "POST":
        return httpx.Response(201, json=_recurring_meeting_payload(), request=request)
    return _unexpected(request)


def _update_recurring_meeting_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/recurring_meetings/51" and request.method == "GET":
        return httpx.Response(200, json=_recurring_meeting_payload(), request=request)
    if request.url.path == "/api/v3/recurring_meetings/51" and request.method == "PATCH":
        return httpx.Response(200, json=_recurring_meeting_payload(title="Weekly Standup Updated"), request=request)
    return _unexpected(request)


def _delete_recurring_meeting_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/recurring_meetings/51" and request.method == "GET":
        return httpx.Response(200, json=_recurring_meeting_payload(), request=request)
    if request.url.path == "/api/v3/recurring_meetings/51" and request.method == "DELETE":
        return httpx.Response(204, request=request)
    return _unexpected(request)


def _init_occurrence_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/recurring_meetings/51" and request.method == "GET":
        return httpx.Response(200, json=_recurring_meeting_payload(), request=request)
    if (
        request.url.path == "/api/v3/recurring_meetings/51/occurrences/2026-09-08T09:00:00Z/init"
        and request.method == "POST"
    ):
        return httpx.Response(201, json=_meeting_payload(meeting_id=13, title="Weekly Standup"), request=request)
    return _unexpected(request)


def _cancel_occurrence_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/recurring_meetings/51" and request.method == "GET":
        return httpx.Response(200, json=_recurring_meeting_payload(), request=request)
    if (
        request.url.path == "/api/v3/recurring_meetings/51/occurrences/2026-09-08T09:00:00Z"
        and request.method == "DELETE"
    ):
        return httpx.Response(204, request=request)
    return _unexpected(request)


MEETING_CASES: dict[str, WriteToolCase] = {
    "create_meeting": WriteToolCase(
        tool="create_meeting",
        kwargs={"project": "demo", "title": "Sprint Planning"},
        settings=_settings(),
        write_scope="meeting",
        handler=_create_meeting_handler,
        write_request=("POST", "/api/v3/meetings"),
    ),
    "update_meeting": WriteToolCase(
        tool="update_meeting",
        kwargs={"meeting_id": 12, "title": "Sprint Planning Updated"},
        settings=_settings(),
        write_scope="meeting",
        handler=_update_meeting_handler,
        write_request=("PATCH", "/api/v3/meetings/12"),
    ),
    "delete_meeting": WriteToolCase(
        tool="delete_meeting",
        kwargs={"meeting_id": 12},
        settings=_settings(),
        write_scope="meeting",
        handler=_delete_meeting_handler,
        write_request=("DELETE", "/api/v3/meetings/12"),
    ),
    "create_meeting_agenda_item": WriteToolCase(
        tool="create_meeting_agenda_item",
        kwargs={"meeting_id": 12, "title": "Discuss roadmap"},
        settings=_settings(),
        write_scope="meeting",
        handler=_create_meeting_agenda_item_handler,
        write_request=("POST", "/api/v3/meeting_agenda_items"),
    ),
    "update_meeting_agenda_item": WriteToolCase(
        tool="update_meeting_agenda_item",
        kwargs={"agenda_item_id": 21, "title": "Discuss roadmap v2"},
        settings=_settings(),
        write_scope="meeting",
        handler=_update_meeting_agenda_item_handler,
        write_request=("PATCH", "/api/v3/meeting_agenda_items/21"),
    ),
    "delete_meeting_agenda_item": WriteToolCase(
        tool="delete_meeting_agenda_item",
        kwargs={"agenda_item_id": 21},
        settings=_settings(),
        write_scope="meeting",
        handler=_delete_meeting_agenda_item_handler,
        write_request=("DELETE", "/api/v3/meeting_agenda_items/21"),
    ),
    "create_meeting_outcome": WriteToolCase(
        tool="create_meeting_outcome",
        kwargs={"agenda_item_id": 21, "kind": "info"},
        settings=_settings(),
        write_scope="meeting",
        handler=_create_meeting_outcome_handler,
        write_request=("POST", "/api/v3/meeting_outcomes"),
    ),
    "update_meeting_outcome": WriteToolCase(
        tool="update_meeting_outcome",
        kwargs={"outcome_id": 31, "kind": "action"},
        settings=_settings(),
        write_scope="meeting",
        handler=_update_meeting_outcome_handler,
        write_request=("PATCH", "/api/v3/meeting_outcomes/31"),
    ),
    "delete_meeting_outcome": WriteToolCase(
        tool="delete_meeting_outcome",
        kwargs={"outcome_id": 31},
        settings=_settings(),
        write_scope="meeting",
        handler=_delete_meeting_outcome_handler,
        write_request=("DELETE", "/api/v3/meeting_outcomes/31"),
    ),
    "create_meeting_section": WriteToolCase(
        tool="create_meeting_section",
        kwargs={"meeting_id": 12, "title": "Backlog"},
        settings=_settings(),
        write_scope="meeting",
        handler=_create_meeting_section_handler,
        write_request=("POST", "/api/v3/meeting_sections"),
    ),
    "update_meeting_section": WriteToolCase(
        tool="update_meeting_section",
        kwargs={"section_id": 41, "title": "Backlog v2"},
        settings=_settings(),
        write_scope="meeting",
        handler=_update_meeting_section_handler,
        write_request=("PATCH", "/api/v3/meeting_sections/41"),
    ),
    "delete_meeting_section": WriteToolCase(
        tool="delete_meeting_section",
        kwargs={"section_id": 41},
        settings=_settings(),
        write_scope="meeting",
        handler=_delete_meeting_section_handler,
        write_request=("DELETE", "/api/v3/meeting_sections/41"),
    ),
    "create_recurring_meeting": WriteToolCase(
        tool="create_recurring_meeting",
        kwargs={
            "project": "demo",
            "title": "Weekly Standup",
            "frequency": "weekly",
            "start_time": "2026-09-01T09:00:00Z",
        },
        settings=_settings(),
        write_scope="meeting",
        handler=_create_recurring_meeting_handler,
        write_request=("POST", "/api/v3/recurring_meetings"),
    ),
    "update_recurring_meeting": WriteToolCase(
        tool="update_recurring_meeting",
        kwargs={"recurring_meeting_id": 51, "title": "Weekly Standup Updated"},
        settings=_settings(),
        write_scope="meeting",
        handler=_update_recurring_meeting_handler,
        write_request=("PATCH", "/api/v3/recurring_meetings/51"),
    ),
    "delete_recurring_meeting": WriteToolCase(
        tool="delete_recurring_meeting",
        kwargs={"recurring_meeting_id": 51},
        settings=_settings(),
        write_scope="meeting",
        handler=_delete_recurring_meeting_handler,
        write_request=("DELETE", "/api/v3/recurring_meetings/51"),
    ),
    "init_recurring_meeting_occurrence": WriteToolCase(
        tool="init_recurring_meeting_occurrence",
        kwargs={"recurring_meeting_id": 51, "start_time": "2026-09-08T09:00:00Z"},
        settings=_settings(),
        write_scope="meeting",
        handler=_init_occurrence_handler,
        write_request=("POST", "/api/v3/recurring_meetings/51/occurrences/2026-09-08T09:00:00Z/init"),
    ),
    "cancel_recurring_meeting_occurrence": WriteToolCase(
        tool="cancel_recurring_meeting_occurrence",
        kwargs={"recurring_meeting_id": 51, "start_time": "2026-09-08T09:00:00Z"},
        settings=_settings(),
        write_scope="meeting",
        handler=_cancel_occurrence_handler,
        write_request=("DELETE", "/api/v3/recurring_meetings/51/occurrences/2026-09-08T09:00:00Z"),
    ),
}
