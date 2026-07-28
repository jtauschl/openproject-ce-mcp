from __future__ import annotations

import json

import httpx
import pytest
from _client_test_helpers import _base_settings

from openproject_ce_mcp.app.adapters.httpx_membership_api import normalize_membership
from openproject_ce_mcp.app.adapters.httpx_sprint_api import normalize_sprint
from openproject_ce_mcp.app.adapters.httpx_status_priority_type_api import normalize_status, normalize_type
from openproject_ce_mcp.app.adapters.httpx_user_api import normalize_user
from openproject_ce_mcp.app.origin import origin_from_url as _origin_from_url
from openproject_ce_mcp.app.policies import hidden_fields
from openproject_ce_mcp.client import (
    InvalidInputError,
    OpenProjectClient,
)
from openproject_ce_mcp.config import Settings
from openproject_ce_mcp.tools import _to_payload


@pytest.mark.asyncio
async def test_allowed_projects_and_hidden_fields_filter_read_outputs() -> None:
    settings = Settings(
        base_url="https://op.example.com",
        api_token="token",
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
        read_projects=("demo",),
        hide_project_fields=("description",),
        hide_work_package_fields=("description",),
        hide_activity_fields=("comment",),
    )
    client = OpenProjectClient(
        settings, transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}, request=request))
    )

    visible_project = client.normalize_project(
        {
            "id": 1,
            "name": "Demo",
            "identifier": "demo",
            "description": {"raw": "secret"},
            "_links": {},
        }
    )
    hidden_description_wp = client.normalize_work_package_detail(
        {
            "id": 42,
            "subject": "Test",
            "description": {"raw": "hidden"},
            "_links": {
                "project": {"href": "/api/v3/projects/1", "title": "Demo"},
                "activities": {"href": "/api/v3/work_packages/42/activities"},
                "relations": {"href": "/api/v3/work_packages/42/relations"},
            },
        }
    )
    activity = client.normalize_activity(
        {
            "id": 7,
            "_type": "Activity",
            "comment": {"raw": "hidden"},
            "_links": {"user": {"title": "Bot"}},
        }
    )

    assert visible_project.description is None
    assert hidden_description_wp.description is None
    assert activity.comment is None

    await client.aclose()


@pytest.mark.asyncio
async def test_hidden_fields_support_wildcards_for_principal_reads() -> None:
    client = OpenProjectClient(
        Settings(
            base_url="https://op.example.com",
            api_token="token",
            timeout=12,
            verify_ssl=True,
            default_page_size=20,
            max_page_size=50,
            max_results=100,
            log_level="WARNING",
            hidden_fields={"principal": ("n*", "*mail", "url")},
        ),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}, request=request)),
    )

    principal = client.normalize_principal(
        {"id": 5, "_type": "User", "name": "Alice", "login": "alice", "email": "alice@example.com"}
    )

    # Hidden fields are tagged (not nulled). The wildcard patterns match
    # name/email/url; the values remain on the dataclass, and the serialization seam
    # removes exactly these keys from the response.
    assert principal._hidden_keys == frozenset({"name", "email", "url"})
    assert principal.name == "Alice"  # value preserved on the dataclass
    assert principal.login == "alice"
    serialized = _to_payload(principal)
    assert "name" not in serialized
    assert "email" not in serialized
    assert "url" not in serialized
    assert serialized["login"] == "alice"

    await client.aclose()


@pytest.mark.asyncio
async def test_hidden_project_field_is_rejected_on_write() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/form":
            return httpx.Response(
                200,
                json={"_type": "Form", "_embedded": {"schema": {}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings(
        read_projects=("*",),
        write_projects=("*",),
        base_url="https://op.example.com",
        api_token="token",
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
        hide_project_fields=("description",),
        enable_project_write=True,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(InvalidInputError, match="hidden by OPENPROJECT_HIDE_PROJECT_FIELDS"):
        await client.create_project(name="Demo", identifier="demo", description="secret", confirm=False)

    await client.aclose()


@pytest.mark.asyncio
async def test_hidden_document_field_is_rejected_on_write() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/documents/5" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 5,
                    "title": "Architecture",
                    "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}},
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings(
        read_projects=("*",),
        write_projects=("*",),
        base_url="https://op.example.com",
        api_token="token",
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
        hidden_fields={"document": ("title",)},
        enable_project_write=True,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(InvalidInputError, match="hidden by OPENPROJECT_HIDE_DOCUMENT_FIELDS"):
        await client.update_document(document_id=5, title="Blocked", confirm=False)

    await client.aclose()


@pytest.mark.asyncio
async def test_hidden_work_package_field_is_rejected_on_write() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 1, "name": "Demo", "identifier": "demo", "_links": {}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings(
        read_projects=("*",),
        write_projects=("*",),
        base_url="https://op.example.com",
        api_token="token",
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
        hide_work_package_fields=("description",),
        enable_work_package_write=True,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(InvalidInputError, match="hidden by OPENPROJECT_HIDE_WORK_PACKAGE_FIELDS"):
        await client.create_work_package(
            project="demo",
            type="Task",
            subject="Blocked",
            description="secret",
            confirm=False,
        )

    await client.aclose()


@pytest.mark.asyncio
async def test_hidden_activity_field_is_rejected_on_write() -> None:
    client = OpenProjectClient(
        Settings(
            base_url="https://op.example.com",
            api_token="token",
            timeout=12,
            verify_ssl=True,
            default_page_size=20,
            max_page_size=50,
            max_results=100,
            log_level="WARNING",
            hide_activity_fields=("comment",),
            enable_work_package_write=True,
        ),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}, request=request)),
    )

    with pytest.raises(InvalidInputError, match="hidden by OPENPROJECT_HIDE_ACTIVITY_FIELDS"):
        await client.create_time_entry(
            activity="Development",
            hours="PT1H",
            spent_on="2026-03-20",
            comment="secret",
            confirm=False,
        )

    await client.aclose()


@pytest.mark.asyncio
async def test_hidden_time_entry_field_is_rejected_on_write() -> None:
    client = OpenProjectClient(
        Settings(
            base_url="https://op.example.com",
            api_token="token",
            timeout=12,
            verify_ssl=True,
            default_page_size=20,
            max_page_size=50,
            max_results=100,
            log_level="WARNING",
            hidden_fields={"time_entry": ("hours",)},
            enable_work_package_write=True,
        ),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}, request=request)),
    )

    with pytest.raises(InvalidInputError, match="hidden by OPENPROJECT_HIDE_TIME_ENTRY_FIELDS"):
        await client.create_time_entry(
            activity="Development",
            hours="PT1H",
            spent_on="2026-03-20",
            confirm=False,
        )

    await client.aclose()


@pytest.mark.asyncio
async def test_hidden_custom_field_is_rejected_on_write() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 1, "name": "Demo", "identifier": "demo", "_links": {}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = Settings(
        read_projects=("*",),
        write_projects=("*",),
        base_url="https://op.example.com",
        api_token="token",
        timeout=12,
        verify_ssl=True,
        default_page_size=20,
        max_page_size=50,
        max_results=100,
        log_level="WARNING",
        hide_custom_fields=("Story points",),
        enable_work_package_write=True,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(InvalidInputError, match="hidden by OPENPROJECT_HIDE_CUSTOM_FIELDS"):
        await client.create_work_package(
            project="demo",
            type="Task",
            subject="Blocked",
            custom_fields={"Story points": 8},
            confirm=False,
        )

    await client.aclose()


def test_hidden_sprint_fields_are_tagged_and_dropped_from_payload() -> None:
    # Sprints support OPENPROJECT_HIDE_SPRINT_FIELDS like every other entity.
    # normalize_sprint (the adapter's pure HAL->model function) no longer
    # applies masking itself (ADR 0001 -- masking moved to SprintService);
    # this test applies it via the same hidden_fields.apply_hidden_fields the
    # Service calls, mirroring test_hidden_membership_fields_are_tagged_and_dropped_from_payload.
    settings = _base_settings(hidden_fields={"sprint": ("defining_workspace",)})

    sprint = hidden_fields.apply_hidden_fields(
        "sprint",
        normalize_sprint(
            {
                "_type": "Sprint",
                "id": 1,
                "name": "Cleanup",
                "_embedded": {
                    "definingWorkspace": {
                        "_type": "Project",
                        "id": 7,
                        "identifier": "demo",
                        "name": "Demo",
                        "_links": {"self": {"href": "/api/v3/projects/7", "title": "Demo"}},
                    }
                },
                "_links": {},
            },
            base_url=settings.base_url,
        ),
        settings=settings,
    )

    assert sprint._hidden_keys == frozenset({"defining_workspace"})
    assert sprint.defining_workspace == "Demo"  # value preserved on the dataclass
    serialized = _to_payload(sprint)
    assert "defining_workspace" not in serialized
    assert serialized["name"] == "Cleanup"


@pytest.mark.asyncio
async def test_hidden_work_package_scheduling_fields_are_tagged_and_dropped_from_payload() -> None:
    # Scheduling/derived fields (scheduleManually, ignoreNonWorkingDays,
    # derivedStartDate, derivedDueDate, percentageDone, derivedPercentageDone, readonly)
    # respect OPENPROJECT_HIDE_WORK_PACKAGE_FIELDS like every other work_package field.
    client = OpenProjectClient(
        _base_settings(hidden_fields={"work_package": ("schedule_manually",)}),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}, request=request)),
    )

    payload = {
        "id": 1,
        "subject": "Plan sprint",
        "scheduleManually": True,
        "ignoreNonWorkingDays": False,
        "derivedStartDate": "2026-07-01",
        "derivedDueDate": "2026-07-15",
        "percentageDone": 40,
        "derivedPercentageDone": 55,
        "readonly": False,
        "_links": {},
    }

    summary = client.normalize_work_package_summary(payload)
    assert summary._hidden_keys == frozenset({"schedule_manually"})
    assert summary.schedule_manually is True  # value preserved on the dataclass
    assert summary.ignore_non_working_days is False
    assert summary.derived_start_date == "2026-07-01"
    assert summary.derived_due_date == "2026-07-15"
    assert summary.percentage_done == 40
    assert summary.derived_percentage_done == 55
    assert summary.readonly is False
    serialized = _to_payload(summary)
    assert "schedule_manually" not in serialized
    assert serialized["derived_due_date"] == "2026-07-15"

    detail = client.normalize_work_package_detail(payload, text_limit=None)
    assert detail._hidden_keys == frozenset({"schedule_manually"})
    assert detail.derived_percentage_done == 55
    assert detail.readonly is False

    await client.aclose()


@pytest.mark.asyncio
async def test_hidden_status_fields_are_tagged_and_dropped_from_payload() -> None:
    # Status supports OPENPROJECT_HIDE_STATUS_FIELDS, like every other entity.
    # normalize_status now lives in app/adapters/httpx_status_priority_type_api.py
    # (16th migrated domain) and no longer applies hidden-field masking itself --
    # that moved to the Service layer, so this test calls the adapter's pure
    # normalizer, then applies masking explicitly via hidden_fields.apply_hidden_fields,
    # mirroring test_hidden_membership_fields_are_tagged_and_dropped_from_payload.
    settings = _base_settings(hidden_fields={"status": ("default_done_ratio",)})

    status = normalize_status(
        {
            "id": 1,
            "name": "In progress",
            "isDefault": False,
            "isClosed": False,
            "color": "#1A67A3",
            "position": 2,
            "isReadonly": False,
            "defaultDoneRatio": 30,
            "excludedFromTotals": False,
        },
        api_prefix="/api/v3/",
    )
    status = hidden_fields.apply_hidden_fields("status", status, settings=settings)

    assert status._hidden_keys == frozenset({"default_done_ratio"})
    assert status.default_done_ratio == 30  # value preserved on the dataclass
    assert status.is_readonly is False
    assert status.excluded_from_totals is False
    serialized = _to_payload(status)
    assert "default_done_ratio" not in serialized
    assert serialized["name"] == "In progress"


@pytest.mark.asyncio
async def test_hidden_type_fields_are_tagged_and_dropped_from_payload() -> None:
    # Type supports OPENPROJECT_HIDE_TYPE_FIELDS, like every other entity.
    # normalize_type now lives in app/adapters/httpx_status_priority_type_api.py
    # (16th migrated domain) -- see test_hidden_status_fields_... above.
    settings = _base_settings(hidden_fields={"type": ("updated_at",)})

    work_package_type = normalize_type(
        {
            "id": 1,
            "name": "Task",
            "color": "#1A67A3",
            "position": 1,
            "isDefault": True,
            "isMilestone": False,
            "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-06-01T00:00:00Z",
        },
        base_url="https://op.example.com",
    )
    work_package_type = hidden_fields.apply_hidden_fields("type", work_package_type, settings=settings)

    assert work_package_type._hidden_keys == frozenset({"updated_at"})
    assert work_package_type.updated_at == "2026-06-01T00:00:00Z"  # preserved on the dataclass
    assert work_package_type.created_at == "2026-01-01T00:00:00Z"
    serialized = _to_payload(work_package_type)
    assert "updated_at" not in serialized
    assert serialized["name"] == "Task"


@pytest.mark.asyncio
async def test_hidden_version_fields_are_tagged_and_dropped_from_payload() -> None:
    # createdAt/updatedAt on VersionSummary/Detail respect the
    # existing OPENPROJECT_HIDE_VERSION_FIELDS wiring.
    client = OpenProjectClient(
        _base_settings(hidden_fields={"version": ("updated_at",)}),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}, request=request)),
    )

    payload = {
        "id": 1,
        "name": "1.0",
        "status": "open",
        "sharing": "none",
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-06-01T00:00:00Z",
        "_links": {},
    }

    summary = client.normalize_version(payload)
    assert summary._hidden_keys == frozenset({"updated_at"})
    assert summary.updated_at == "2026-06-01T00:00:00Z"  # preserved on the dataclass
    assert summary.created_at == "2026-01-01T00:00:00Z"
    serialized = _to_payload(summary)
    assert "updated_at" not in serialized

    detail = client.normalize_version_detail(payload)
    assert detail._hidden_keys == frozenset({"updated_at"})
    assert detail.created_at == "2026-01-01T00:00:00Z"

    await client.aclose()


@pytest.mark.asyncio
async def test_hidden_version_description_also_suppresses_truncation_metadata() -> None:
    # A hidden "description" must also blank description_truncated/description_length
    # -- otherwise the real length of hidden content would still leak through those
    # two sibling fields even though "description" itself is dropped.
    # The adapter computes them before hidden-field masking exists (masking is a
    # VersionService concern, per ADR 0001), so this can only be caught end-to-end
    # through get_version/list_versions, not via a direct normalize_version() call.
    long_description = "d" * 900

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/versions/1" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 1, "name": "1.0", "description": {"raw": long_description}, "_links": {}},
                request=request,
            )
        if request.url.path == "/api/v3/versions" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [{"id": 1, "name": "1.0", "description": {"raw": long_description}, "_links": {}}]
                    }
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(
        _base_settings(hidden_fields={"version": ("description",)}),
        transport=httpx.MockTransport(handler),
    )

    detail = await client.get_version(1)
    # description_truncated/description_length are blanked on the object itself
    # (not just dropped at serialization, since their field NAMES don't match
    # the "description" hide pattern -- without the fix they'd still carry the
    # real truncation state of hidden content).
    assert detail.description_truncated is False
    assert detail.description_length is None
    serialized_detail = _to_payload(detail)
    assert "description" not in serialized_detail  # dropped by name, like updated_at above
    assert serialized_detail["description_truncated"] is False
    assert serialized_detail["description_length"] is None

    page = await client.list_versions()
    summary = page.results[0]
    assert summary.description_truncated is False
    assert summary.description_length is None

    await client.aclose()


def test_hidden_membership_fields_are_tagged_and_dropped_from_payload() -> None:
    # createdAt/updatedAt on MembershipSummary respect the existing
    # OPENPROJECT_HIDE_MEMBERSHIP_FIELDS wiring. normalize_membership (the
    # adapter's pure HAL->model function) no longer applies masking itself
    # (ADR 0001 -- masking moved to MembershipService); this test applies it
    # via the same hidden_fields.apply_hidden_fields the Service calls.
    settings = _base_settings(hidden_fields={"membership": ("created_at",)})

    membership = hidden_fields.apply_hidden_fields(
        "membership",
        normalize_membership(
            {
                "id": 1,
                "createdAt": "2026-01-01T00:00:00Z",
                "updatedAt": "2026-06-01T00:00:00Z",
                "_links": {},
            },
            base_url=settings.base_url,
        ),
        settings=settings,
    )

    assert membership._hidden_keys == frozenset({"created_at"})
    assert membership.created_at == "2026-01-01T00:00:00Z"  # preserved on the dataclass
    assert membership.updated_at == "2026-06-01T00:00:00Z"
    serialized = _to_payload(membership)
    assert "created_at" not in serialized


# File Link's hidden-field-masking regression coverage (originally
# test_hidden_file_link_fields_are_tagged_and_dropped_from_payload, added for
# OPM-1627's config-map gap fix) moved to
# tests/unit/test_app_httpx_file_link_api.py (normalize_file_link's pure
# HAL->model shape) and tests/unit/test_app_file_link_service.py
# (test_list_for_work_package_masks_hidden_storage_name,
# test_delete_preview_masks_hidden_storage_name,
# test_storage_name_hidden_by_file_link_scope_not_grid_scope) after the File
# Links domain migration (OPM-296) -- client.normalize_file_link no longer
# exists. The real env-var-driven path (OPENPROJECT_HIDE_FILE_LINK_FIELDS)
# is exercised by
# test_settings_from_env_loads_priority_notification_file_link_emoji_reaction_hidden_fields
# in tests/test_config.py, unaffected by this migration.


@pytest.mark.asyncio
async def test_hidden_notification_fields_are_tagged_and_dropped_from_payload() -> None:
    # Regression test for a real gap found during the Statuses/Priorities/Types
    # migration's broader audit (OPM-1627): normalize_notification previously
    # never called _apply_hidden_fields at all, and config.py's
    # HIDE_FIELD_ENV_BY_ENTITY had no "notification" entry either --
    # OPENPROJECT_HIDE_NOTIFICATION_FIELDS never existed as a real env var.
    # Notifications is still a flat, unmigrated client.py domain (OPM-1629).
    client = OpenProjectClient(
        _base_settings(hidden_fields={"notification": ("project_name",)}),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}, request=request)),
    )

    notification = client.normalize_notification(
        {
            "id": 1,
            "subject": "Work package updated",
            "readIAN": False,
            "createdAt": "2026-01-01T00:00:00Z",
            "_links": {
                "project": {"href": "/api/v3/projects/6", "title": "Demo Project"},
            },
        }
    )

    assert notification._hidden_keys == frozenset({"project_name"})
    assert notification.project_name == "Demo Project"  # preserved on the dataclass
    assert notification.project_id == 6
    serialized = _to_payload(notification)
    assert "project_name" not in serialized
    assert serialized["project_id"] == 6

    await client.aclose()


@pytest.mark.asyncio
# Emoji Reactions' hidden-field-masking regression coverage (originally
# test_hidden_emoji_reaction_fields_are_tagged_and_dropped_from_payload,
# added for OPM-1627's config-map gap fix) moved to
# tests/unit/test_app_httpx_emoji_reaction_api.py (normalize_emoji_reaction's
# pure HAL->model shape) and tests/unit/test_app_emoji_reaction_service.py
# (test_list_for_work_package_masks_hidden_users,
# test_toggle_masks_hidden_users_in_commit_result,
# test_users_hidden_by_emoji_reaction_scope_not_watcher_scope) after the
# Emoji Reactions domain migration (OPM-290, scoped to
# list_work_package_reactions + toggle_activity_emoji_reaction only) --
# client.normalize_emoji_reaction no longer exists. The real env-var-driven
# path (OPENPROJECT_HIDE_EMOJI_REACTION_FIELDS) is unaffected by this
# migration and continues to be exercised via config.py's
# HIDE_FIELD_ENV_BY_ENTITY map.


# Watchers' hidden-field-masking regression coverage (originally
# test_hidden_watcher_fields_are_tagged_and_dropped_from_payload) moved to
# tests/unit/test_app_httpx_watcher_api.py (normalize_watcher's pure
# HAL->model shape) and tests/unit/test_app_watcher_service.py
# (test_list_for_work_package_masks_hidden_login,
# test_add_masks_hidden_login_in_preview_and_commit,
# test_login_hidden_by_watcher_scope_not_user_scope) after the Watchers
# domain migration (OPM-294) -- client.normalize_watcher no longer exists.
# The real env-var-driven path (OPENPROJECT_HIDE_WATCHER_FIELDS) is
# unaffected by this migration and continues to be exercised via
# config.py's HIDE_FIELD_ENV_BY_ENTITY map.


def test_hidden_user_fields_are_tagged_and_dropped_from_payload() -> None:
    # firstName/lastName are exposed as read fields, echoing what create_user/
    # update_user already write. Respects existing OPENPROJECT_HIDE_USER_FIELDS
    # wiring. normalize_user (the adapter's pure HAL->model function) no
    # longer applies masking itself (ADR 0001 -- masking moved to
    # UserService); this test applies it via the same
    # hidden_fields.apply_hidden_fields the Service calls, mirroring
    # test_hidden_membership_fields_are_tagged_and_dropped_from_payload.
    settings = _base_settings(hidden_fields={"user": ("firstname",)})

    user = hidden_fields.apply_hidden_fields(
        "user",
        normalize_user(
            {
                "id": 1,
                "name": "Ada Lovelace",
                "firstName": "Ada",
                "lastName": "Lovelace",
                "_links": {},
            },
            base_url=settings.base_url,
            origin=_origin_from_url(settings.base_url),
        ),
        settings=settings,
    )

    assert user._hidden_keys == frozenset({"firstname"})
    assert user.firstname == "Ada"  # preserved on the dataclass
    assert user.lastname == "Lovelace"
    serialized = _to_payload(user)
    assert "firstname" not in serialized
    assert serialized["lastname"] == "Lovelace"


@pytest.mark.asyncio
async def test_hidden_project_favorited_field_is_tagged_and_dropped_from_payload() -> None:
    # favorited is exposed as a per-token read field on ProjectSummary. Not a
    # write-behavior change — add_project_favorite/remove_project_favorite already
    # own the write side. Respects existing OPENPROJECT_HIDE_PROJECT_FIELDS wiring.
    client = OpenProjectClient(
        _base_settings(hidden_fields={"project": ("favorited",)}),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}, request=request)),
    )

    project = client.normalize_project(
        {
            "id": 1,
            "name": "Demo",
            "identifier": "demo",
            "favorited": True,
            "_links": {},
        }
    )

    assert project._hidden_keys == frozenset({"favorited"})
    assert project.favorited is True  # preserved on the dataclass
    serialized = _to_payload(project)
    assert "favorited" not in serialized
    assert serialized["name"] == "Demo"

    await client.aclose()


async def test_update_work_package_close_with_hidden_progress_fields_still_succeeds() -> None:
    """A locally hidden percentage_done/remaining_time must not turn a plain close into an error."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "lockVersion": 1,
                    "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}},
                },
                request=request,
            )
        if request.url.path == "/api/v3/statuses":
            return httpx.Response(200, json={"_embedded": {"elements": [{"id": 9, "name": "Closed"}]}}, request=request)
        if request.url.path == "/api/v3/statuses/9":
            return httpx.Response(200, json={"id": 9, "name": "Closed", "isClosed": True}, request=request)
        if request.url.path == "/api/v3/work_packages/42/form":
            body = json.loads(request.content)
            assert "percentageDone" not in body
            assert "remainingTime" not in body
            return httpx.Response(
                200,
                json={
                    "_type": "Form",
                    "_embedded": {
                        "payload": body,
                        "validationErrors": {},
                        "schema": {
                            "percentageDone": {"writable": True},
                            "remainingTime": {"writable": True},
                        },
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(hidden_fields={"work_package": ("percentage_done", "remaining_time")})
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))
    result = await client.update_work_package(work_package_id=42, status="Closed", confirm=False)
    assert result.ready
    await client.aclose()


@pytest.mark.asyncio
async def test_hidden_attachment_field_is_rejected_on_write() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(
        hidden_fields={"attachment": ("description",)},
        enable_work_package_write=True,
        attachment_root="/tmp",
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(InvalidInputError, match="hidden by OPENPROJECT_HIDE_ATTACHMENT_FIELDS"):
        await client.create_work_package_attachment(
            work_package_id=42, file_path="/tmp/note.txt", description="secret", confirm=False
        )

    await client.aclose()


@pytest.mark.asyncio
async def test_hidden_reminder_field_is_rejected_on_create() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(hidden_fields={"reminder": ("note",)}, enable_work_package_write=True)
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(InvalidInputError, match="hidden by OPENPROJECT_HIDE_REMINDER_FIELDS"):
        await client.create_work_package_reminder(
            work_package_id=42, remind_at="2026-08-01T09:00:00Z", note="secret", confirm=False
        )

    await client.aclose()


@pytest.mark.asyncio
async def test_hidden_reminder_field_is_rejected_on_update() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/reminders/9" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 9, "_links": {"remindable": {"href": "/api/v3/work_packages/42"}}},
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(hidden_fields={"reminder": ("note",)}, enable_work_package_write=True)
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(InvalidInputError, match="hidden by OPENPROJECT_HIDE_REMINDER_FIELDS"):
        await client.update_reminder(reminder_id=9, note="secret", confirm=False)

    await client.aclose()


@pytest.mark.asyncio
async def test_hidden_relation_type_field_is_rejected_on_create() -> None:
    """Regression test (found via Codex review): create_work_package_relation's
    relation_type is a mandatory field written unconditionally, unlike
    description -- it needs its own guard, not just description's."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/43" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 43, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(hidden_fields={"relation": ("type",)}, enable_work_package_write=True)
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(InvalidInputError, match="hidden by OPENPROJECT_HIDE_RELATION_FIELDS"):
        await client.create_work_package_relation(
            work_package_id=42, related_to_work_package_id=43, relation_type="blocks", confirm=False
        )

    await client.aclose()


@pytest.mark.asyncio
async def test_hidden_relation_type_field_is_rejected_on_update() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/relations/3" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 3,
                    "type": "blocks",
                    "_links": {
                        "from": {"href": "/api/v3/work_packages/42"},
                        "to": {"href": "/api/v3/work_packages/43"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(hidden_fields={"relation": ("type",)}, enable_work_package_write=True)
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(InvalidInputError, match="hidden by OPENPROJECT_HIDE_RELATION_FIELDS"):
        await client.update_relation(relation_id=3, relation_type="follows", confirm=False)

    await client.aclose()


@pytest.mark.asyncio
async def test_hidden_attachment_file_name_field_is_rejected_on_write() -> None:
    """Regression test (found via Codex review): create_work_package_attachment
    always writes file_name (a mandatory field), unlike description -- it
    needs its own guard, not just description's."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(
        hidden_fields={"attachment": ("file_name",)}, enable_work_package_write=True, attachment_root="/tmp"
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(InvalidInputError, match="hidden by OPENPROJECT_HIDE_ATTACHMENT_FIELDS"):
        await client.create_work_package_attachment(work_package_id=42, file_path="/tmp/note.txt", confirm=False)

    await client.aclose()


@pytest.mark.asyncio
async def test_hidden_relation_field_is_rejected_on_update() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/relations/3" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 3,
                    "type": "blocks",
                    "_links": {
                        "from": {"href": "/api/v3/work_packages/42"},
                        "to": {"href": "/api/v3/work_packages/43"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 42, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(hidden_fields={"relation": ("description",)}, enable_work_package_write=True)
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(InvalidInputError, match="hidden by OPENPROJECT_HIDE_RELATION_FIELDS"):
        await client.update_relation(relation_id=3, description="secret", confirm=False)

    await client.aclose()
