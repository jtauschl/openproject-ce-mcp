"""Write/delete-tool behavioral-contract cases for the user_schedule scope
(User Non-Working Times, User Working Hours).

Sibling modules import this as `from _write_contract_cases_user_schedule import
...` (no package prefix) -- same rootless-import convention as
`_client_test_helpers.py`/`_tools_test_helpers.py` (see the comment at the top
of those files).
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
        "enable_user_schedule_read": True,
        "enable_user_schedule_write": True,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _unexpected(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"Unexpected request: {request.method} {request.url}")


# --- User Non-Working Times --------------------------------------------------


def _non_working_time_payload(record_id: int = 5) -> dict:
    return {
        "id": record_id,
        "startDate": "2026-08-01",
        "endDate": "2026-08-10",
        "_links": {"user": {"href": "/api/v3/users/3", "title": "Alice"}},
    }


def _create_user_non_working_time_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/users/me/non_working_times" and request.method == "POST":
        return httpx.Response(201, json=_non_working_time_payload(9), request=request)
    return _unexpected(request)


def _update_user_non_working_time_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/users/me/non_working_times" and request.method == "GET":
        return httpx.Response(
            200, json={"_embedded": {"elements": [_non_working_time_payload(5)]}, "total": 1}, request=request
        )
    if request.url.path == "/api/v3/users/me/non_working_times/5" and request.method == "PATCH":
        body = json.loads(request.content)
        payload = _non_working_time_payload(5)
        payload.update(body)
        return httpx.Response(200, json=payload, request=request)
    return _unexpected(request)


def _delete_user_non_working_time_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/users/me/non_working_times" and request.method == "GET":
        return httpx.Response(
            200, json={"_embedded": {"elements": [_non_working_time_payload(5)]}, "total": 1}, request=request
        )
    if request.url.path == "/api/v3/users/me/non_working_times/5" and request.method == "DELETE":
        return httpx.Response(204, request=request)
    return _unexpected(request)


# --- User Working Hours ------------------------------------------------------


def _working_hours_payload(record_id: int = 5) -> dict:
    return {
        "id": record_id,
        "validFrom": "2026-08-01",
        "mondayHours": 8,
        "tuesdayHours": 8,
        "wednesdayHours": 8,
        "thursdayHours": 8,
        "fridayHours": 8,
        "saturdayHours": None,
        "sundayHours": None,
        "availabilityFactor": 1.0,
        "_links": {"user": {"href": "/api/v3/users/3", "title": "Alice"}},
    }


def _create_user_working_hours_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/users/me/working_hours" and request.method == "POST":
        return httpx.Response(201, json=_working_hours_payload(9), request=request)
    return _unexpected(request)


def _update_user_working_hours_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/users/me/working_hours/5" and request.method == "GET":
        return httpx.Response(200, json=_working_hours_payload(5), request=request)
    if request.url.path == "/api/v3/users/me/working_hours/5" and request.method == "PATCH":
        body = json.loads(request.content)
        payload = _working_hours_payload(5)
        payload.update(body)
        return httpx.Response(200, json=payload, request=request)
    return _unexpected(request)


def _delete_user_working_hours_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/users/me/working_hours/5" and request.method == "GET":
        return httpx.Response(200, json=_working_hours_payload(5), request=request)
    if request.url.path == "/api/v3/users/me/working_hours/5" and request.method == "DELETE":
        return httpx.Response(204, request=request)
    return _unexpected(request)


USER_SCHEDULE_CASES: dict[str, WriteToolCase] = {
    "create_user_non_working_time": WriteToolCase(
        tool="create_user_non_working_time",
        kwargs={"user_ref": "me", "start_date": "2026-08-01", "end_date": "2026-08-10"},
        settings=_settings(),
        write_scope="user_schedule",
        handler=_create_user_non_working_time_handler,
        write_request=("POST", "/api/v3/users/me/non_working_times"),
    ),
    "update_user_non_working_time": WriteToolCase(
        tool="update_user_non_working_time",
        kwargs={"user_ref": "me", "non_working_time_id": 5, "end_date": "2026-08-15"},
        settings=_settings(),
        write_scope="user_schedule",
        handler=_update_user_non_working_time_handler,
        write_request=("PATCH", "/api/v3/users/me/non_working_times/5"),
    ),
    "delete_user_non_working_time": WriteToolCase(
        tool="delete_user_non_working_time",
        kwargs={"user_ref": "me", "non_working_time_id": 5},
        settings=_settings(),
        write_scope="user_schedule",
        handler=_delete_user_non_working_time_handler,
        write_request=("DELETE", "/api/v3/users/me/non_working_times/5"),
    ),
    "create_user_working_hours": WriteToolCase(
        tool="create_user_working_hours",
        kwargs={"user_ref": "me", "valid_from": "2026-08-01", "monday_hours": 8.0},
        settings=_settings(),
        write_scope="user_schedule",
        handler=_create_user_working_hours_handler,
        write_request=("POST", "/api/v3/users/me/working_hours"),
    ),
    "update_user_working_hours": WriteToolCase(
        tool="update_user_working_hours",
        kwargs={"user_ref": "me", "working_hours_id": 5, "monday_hours": 6.0},
        settings=_settings(),
        write_scope="user_schedule",
        handler=_update_user_working_hours_handler,
        write_request=("PATCH", "/api/v3/users/me/working_hours/5"),
    ),
    "delete_user_working_hours": WriteToolCase(
        tool="delete_user_working_hours",
        kwargs={"user_ref": "me", "working_hours_id": 5},
        settings=_settings(),
        write_scope="user_schedule",
        handler=_delete_user_working_hours_handler,
        write_request=("DELETE", "/api/v3/users/me/working_hours/5"),
    ),
}
