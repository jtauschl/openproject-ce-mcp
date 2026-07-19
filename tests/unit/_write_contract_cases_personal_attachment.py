"""Personal-scope + attachment-upload write/delete-tool behavioral-contract cases
(OPM-209 / Phase D). Split out from `_write_contract_cases.py` -- see that module's
docstring. Covers the smallest group of the four builder modules, but the one
that needs dynamic per-test setup (`create_work_package_attachment`'s local file +
matching `Settings.attachment_root`).

Imported bare (no package prefix) -- this directory has no `__init__.py` and
relies on pytest's default rootless import mode, matching the existing
`_client_test_helpers.py`/`_tools_test_helpers.py` convention.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import httpx
from _write_contract_cases_types import MaterializedWriteToolCase, WriteToolCase

from openproject_ce_mcp.config import Settings


def _unexpected(request: httpx.Request) -> None:
    raise AssertionError(f"Unexpected request: {request.method} {request.url}")


# --- update_my_preferences ------------------------------------------------
#
# Client method (client.py:4735, `update_my_preferences`) does a direct PATCH with
# no prerequisite GET -- the preview (confirm=False) branch returns before issuing
# any HTTP call at all.


def _base_personal_settings(**overrides: object) -> Settings:
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
        # Registration of these three tools in tools.py additionally ANDs
        # enable_personal_read on top of the "personal" write_scope gate the
        # shared denial test flips -- both must be True for a realistic
        # preview-then-confirm run.
        "enable_personal_read": True,
        "enable_personal_write": True,
    }
    base.update(overrides)
    return Settings(**base)


def _update_my_preferences_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/my_preferences" and request.method == "PATCH":
        return httpx.Response(
            200,
            json={
                "id": 1,
                "lang": "de",
                "timeZone": "America/New_York",
                "commentSortDescending": False,
                "warnOnLeavingUnsaved": True,
                "autoHidePopups": False,
                "updatedAt": "2026-03-20T11:00:00Z",
            },
            request=request,
        )
    _unexpected(request)
    raise AssertionError  # unreachable, satisfies type-checkers


# --- mark_notification_read / mark_all_notifications_read -----------------
#
# Both client methods (client.py:4160, client.py:4192) have a real client-side
# preview branch: confirm=False returns a NotificationMarkResult
# (requires_confirmation=True, ready=True) without issuing any HTTP call, and
# confirm=True POSTs to notifications/{id}/read_ian or notifications/read_ian
# respectively. Neither is a rubber-stamp/always-executes tool.


def _mark_notification_read_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/notifications/10/read_ian" and request.method == "POST":
        return httpx.Response(204, request=request)
    _unexpected(request)
    raise AssertionError


def _mark_all_notifications_read_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/notifications/read_ian" and request.method == "POST":
        return httpx.Response(204, request=request)
    _unexpected(request)
    raise AssertionError


# --- create_work_package_attachment ----------------------------------------
#
# Needs a real local file under tmp_path and a matching Settings.attachment_root
# known only at test time -- Settings is frozen, so this can't be a static
# kwargs/settings pair like the other three; see `materialize` below.


def _base_settings_for_attachment(**overrides: object) -> Settings:
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
        # enable_work_package_write already defaults True; kept explicit for
        # readability since this is the flag the shared denial test flips.
        "enable_work_package_write": True,
        "attachment_root": "",  # placeholder; materialize() replaces this with tmp_path
    }
    base.update(overrides)
    return Settings(**base)


def _create_work_package_attachment_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
        return httpx.Response(
            200,
            json={
                "id": 42,
                "subject": "Upload target",
                "_links": {
                    "self": {"href": "/api/v3/work_packages/42"},
                    "project": {"href": "/api/v3/projects/1", "title": "Demo"},
                    "activities": {"href": "/api/v3/work_packages/42/activities"},
                    "relations": {"href": "/api/v3/work_packages/42/relations"},
                },
            },
            request=request,
        )
    if request.url.path == "/api/v3/configuration" and request.method == "GET":
        return httpx.Response(200, json={"maximumAttachmentFileSize": 5000}, request=request)
    if request.url.path == "/api/v3/work_packages/42/attachments" and request.method == "POST":
        assert request.headers["content-type"].startswith("multipart/form-data")
        body = request.content
        assert b'name="metadata"' in body
        assert b'name="metadata"; filename=' not in body
        assert b'"fileName": "note.txt"' in body
        assert b'name="file"; filename="note.txt"' in body
        return httpx.Response(
            200,
            json={
                "id": 99,
                "title": "note.txt",
                "fileName": "note.txt",
                "fileSize": 19,
                "status": "uploaded",
                "_links": {
                    "self": {"href": "/api/v3/attachments/99"},
                    "container": {"href": "/api/v3/work_packages/42"},
                    "author": {"href": "/api/v3/users/1", "title": "Bot"},
                    "downloadLocation": {"href": "https://op.example.com/files/note.txt"},
                },
            },
            request=request,
        )
    _unexpected(request)
    raise AssertionError


def _materialize_attachment_case(tmp_path: Path) -> MaterializedWriteToolCase:
    file_path = tmp_path / "note.txt"
    file_path.write_text("hello from OPM-209")
    return MaterializedWriteToolCase(
        kwargs={"work_package_id": 42, "file_path": str(file_path), "description": "Spec"},
        settings=dataclasses.replace(_base_settings_for_attachment(), attachment_root=str(tmp_path)),
    )


PERSONAL_ATTACHMENT_CASES: dict[str, WriteToolCase] = {
    "update_my_preferences": WriteToolCase(
        tool="update_my_preferences",
        kwargs={"lang": "de", "time_zone": "America/New_York"},
        settings=_base_personal_settings(),
        write_scope="personal",
        handler=_update_my_preferences_handler,
        write_request=("PATCH", "/api/v3/my_preferences"),
    ),
    "mark_notification_read": WriteToolCase(
        tool="mark_notification_read",
        kwargs={"notification_id": 10},
        settings=_base_personal_settings(),
        write_scope="personal",
        handler=_mark_notification_read_handler,
        write_request=("POST", "/api/v3/notifications/10/read_ian"),
    ),
    "mark_all_notifications_read": WriteToolCase(
        tool="mark_all_notifications_read",
        kwargs={},
        settings=_base_personal_settings(),
        write_scope="personal",
        handler=_mark_all_notifications_read_handler,
        write_request=("POST", "/api/v3/notifications/read_ian"),
    ),
    "create_work_package_attachment": WriteToolCase(
        tool="create_work_package_attachment",
        # Non-None placeholders so callers that read these fields without
        # materializing don't trip on Optional-looking values; the real
        # invocation always goes through `materialize(tmp_path)` below.
        kwargs={"work_package_id": 42, "file_path": "", "description": None},
        settings=_base_settings_for_attachment(),
        write_scope="work_package",
        handler=_create_work_package_attachment_handler,
        write_request=("POST", "/api/v3/work_packages/42/attachments"),
        materialize=_materialize_attachment_case,
    ),
}
