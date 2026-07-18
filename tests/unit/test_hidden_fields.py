from __future__ import annotations

import json

import httpx
import pytest
from _client_test_helpers import _base_settings

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
    assert client._project_name_allowed("Demo") is True
    assert client._project_name_allowed("Other") is False

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


@pytest.mark.asyncio
async def test_hidden_sprint_fields_are_tagged_and_dropped_from_payload() -> None:
    # Sprints support OPENPROJECT_HIDE_SPRINT_FIELDS like every other entity.
    client = OpenProjectClient(
        _base_settings(hidden_fields={"sprint": ("defining_workspace",)}),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}, request=request)),
    )

    sprint = client.normalize_sprint(
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
        }
    )

    assert sprint._hidden_keys == frozenset({"defining_workspace"})
    assert sprint.defining_workspace == "Demo"  # value preserved on the dataclass
    serialized = _to_payload(sprint)
    assert "defining_workspace" not in serialized
    assert serialized["name"] == "Cleanup"

    await client.aclose()


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
    client = OpenProjectClient(
        _base_settings(hidden_fields={"status": ("default_done_ratio",)}),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}, request=request)),
    )

    status = client.normalize_status(
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
        }
    )

    assert status._hidden_keys == frozenset({"default_done_ratio"})
    assert status.default_done_ratio == 30  # value preserved on the dataclass
    assert status.is_readonly is False
    assert status.excluded_from_totals is False
    serialized = _to_payload(status)
    assert "default_done_ratio" not in serialized
    assert serialized["name"] == "In progress"

    await client.aclose()


@pytest.mark.asyncio
async def test_hidden_type_fields_are_tagged_and_dropped_from_payload() -> None:
    # Type supports OPENPROJECT_HIDE_TYPE_FIELDS, like every other entity.
    client = OpenProjectClient(
        _base_settings(hidden_fields={"type": ("updated_at",)}),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}, request=request)),
    )

    work_package_type = client.normalize_type(
        {
            "id": 1,
            "name": "Task",
            "color": "#1A67A3",
            "position": 1,
            "isDefault": True,
            "isMilestone": False,
            "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-06-01T00:00:00Z",
        }
    )

    assert work_package_type._hidden_keys == frozenset({"updated_at"})
    assert work_package_type.updated_at == "2026-06-01T00:00:00Z"  # preserved on the dataclass
    assert work_package_type.created_at == "2026-01-01T00:00:00Z"
    serialized = _to_payload(work_package_type)
    assert "updated_at" not in serialized
    assert serialized["name"] == "Task"

    await client.aclose()


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
async def test_hidden_membership_fields_are_tagged_and_dropped_from_payload() -> None:
    # createdAt/updatedAt on MembershipSummary respect the
    # existing OPENPROJECT_HIDE_MEMBERSHIP_FIELDS wiring.
    client = OpenProjectClient(
        _base_settings(hidden_fields={"membership": ("created_at",)}),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}, request=request)),
    )

    membership = client.normalize_membership(
        {
            "id": 1,
            "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-06-01T00:00:00Z",
            "_links": {},
        }
    )

    assert membership._hidden_keys == frozenset({"created_at"})
    assert membership.created_at == "2026-01-01T00:00:00Z"  # preserved on the dataclass
    assert membership.updated_at == "2026-06-01T00:00:00Z"
    serialized = _to_payload(membership)
    assert "created_at" not in serialized

    await client.aclose()


@pytest.mark.asyncio
async def test_hidden_watcher_fields_are_tagged_and_dropped_from_payload() -> None:
    # normalize_watcher applies OPENPROJECT_HIDE_WATCHER_FIELDS,
    # like every other normalize_* method for user-identifying data.
    client = OpenProjectClient(
        _base_settings(hidden_fields={"watcher": ("login",)}),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}, request=request)),
    )

    watcher = client.normalize_watcher(
        {
            "id": 1,
            "name": "Ada Lovelace",
            "login": "ada",
        }
    )

    assert watcher._hidden_keys == frozenset({"login"})
    assert watcher.login == "ada"  # preserved on the dataclass
    assert watcher.name == "Ada Lovelace"
    serialized = _to_payload(watcher)
    assert "login" not in serialized
    assert serialized["name"] == "Ada Lovelace"

    await client.aclose()


@pytest.mark.asyncio
async def test_hidden_user_fields_are_tagged_and_dropped_from_payload() -> None:
    # firstName/lastName are exposed as read fields, echoing what create_user/
    # update_user already write. Respects existing OPENPROJECT_HIDE_USER_FIELDS wiring.
    client = OpenProjectClient(
        _base_settings(hidden_fields={"user": ("firstname",)}),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}, request=request)),
    )

    user = client.normalize_user(
        {
            "id": 1,
            "name": "Ada Lovelace",
            "firstName": "Ada",
            "lastName": "Lovelace",
            "_links": {},
        }
    )

    assert user._hidden_keys == frozenset({"firstname"})
    assert user.firstname == "Ada"  # preserved on the dataclass
    assert user.lastname == "Lovelace"
    serialized = _to_payload(user)
    assert "firstname" not in serialized
    assert serialized["lastname"] == "Lovelace"

    await client.aclose()


@pytest.mark.asyncio
async def test_hidden_category_fields_are_tagged_and_dropped_from_payload() -> None:
    # defaultAssignee is exposed as a HAL-link pair (id/name), same pattern as
    # parent_id/parent_name on Project. Respects existing OPENPROJECT_HIDE_CATEGORY_FIELDS.
    client = OpenProjectClient(
        _base_settings(hidden_fields={"category": ("default_assignee",)}),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}, request=request)),
    )

    category = client.normalize_category(
        {
            "id": 1,
            "name": "Bugs",
            "isDefault": False,
            "_links": {
                "defaultAssignee": {"href": "/api/v3/users/9", "title": "Ada Lovelace"},
            },
        },
        project_id=7,
        project_name="Demo",
    )

    assert category._hidden_keys == frozenset({"default_assignee"})
    assert category.default_assignee == "Ada Lovelace"  # preserved on the dataclass
    assert category.default_assignee_id == 9
    serialized = _to_payload(category)
    assert "default_assignee" not in serialized
    assert serialized["default_assignee_id"] == 9

    await client.aclose()


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
