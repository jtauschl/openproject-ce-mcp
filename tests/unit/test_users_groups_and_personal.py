from __future__ import annotations

import json

import httpx
import pytest
from _client_test_helpers import _base_settings, _membership_settings, _personal_write_enabled_settings, make_settings

from openproject_ce_mcp.client import (
    OpenProjectClient,
    PermissionDeniedError,
)
from openproject_ce_mcp.config import Settings


@pytest.mark.asyncio
async def test_update_membership_returns_preview_when_not_confirmed() -> None:
    """Characterization test for update_membership's preview/commit shape — locks in
    its identity fields (membership_id, project) and preview message so future
    refactors of the underlying write helper don't change them silently."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/memberships/3" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 3,
                    "_links": {
                        "project": {"href": "/api/v3/projects/demo-id", "title": "Demo"},
                        "principal": {"href": "/api/v3/users/5", "title": "Alice"},
                        "roles": [{"href": "/api/v3/roles/2", "title": "Developer"}],
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/roles":
            return httpx.Response(200, json={"_embedded": {"elements": []}}, request=request)
        if request.url.path == "/api/v3/memberships/3/form" and request.method == "POST":
            return httpx.Response(
                200,
                json={"_embedded": {"payload": {"_links": {"roles": [{"href": "/api/v3/roles/2"}]}}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_membership_settings(), transport=httpx.MockTransport(handler))

    result = await client.update_membership(membership_id=3, roles=["2"], confirm=False)

    assert result.confirmed is False
    assert result.requires_confirmation is True
    assert result.ready is True
    assert result.membership_id == 3
    assert result.project == "Demo"
    assert result.result is None

    await client.aclose()


@pytest.mark.asyncio
async def test_update_membership_writes_after_confirmation_when_enabled() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/memberships/3" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 3,
                    "_links": {
                        "project": {"href": "/api/v3/projects/demo-id", "title": "Demo"},
                        "principal": {"href": "/api/v3/users/5", "title": "Alice"},
                        "roles": [{"href": "/api/v3/roles/2", "title": "Developer"}],
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/roles":
            return httpx.Response(200, json={"_embedded": {"elements": []}}, request=request)
        if request.url.path == "/api/v3/memberships/3/form" and request.method == "POST":
            return httpx.Response(
                200,
                json={"_embedded": {"payload": {"_links": {"roles": [{"href": "/api/v3/roles/2"}]}}}},
                request=request,
            )
        if request.url.path == "/api/v3/memberships/3" and request.method == "PATCH":
            return httpx.Response(
                200,
                json={
                    "id": 3,
                    "_links": {
                        "project": {"href": "/api/v3/projects/demo-id", "title": "Demo"},
                        "principal": {"href": "/api/v3/users/5", "title": "Alice"},
                        "roles": [{"href": "/api/v3/roles/2", "title": "Developer"}],
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_membership_settings(), transport=httpx.MockTransport(handler))

    result = await client.update_membership(membership_id=3, roles=["2"], confirm=True)

    assert result.confirmed is True
    assert result.requires_confirmation is False
    assert result.membership_id == 3
    assert result.project == "Demo"
    assert result.result is not None

    await client.aclose()


@pytest.mark.asyncio
async def test_user_and_group_endpoints_normalize_results() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/users":
            return httpx.Response(
                200,
                json={
                    "total": 1,
                    "_embedded": {
                        "elements": [
                            {
                                "id": 5,
                                "name": "Alice Example",
                                "login": "alice",
                                "email": "alice@example.com",
                                "status": "active",
                                "admin": True,
                                "locked": False,
                                "createdAt": "2026-01-01T00:00:00Z",
                                "updatedAt": "2026-01-02T00:00:00Z",
                                "_links": {"avatar": {"href": "/avatars/5.png"}},
                            }
                        ]
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/users/5":
            return httpx.Response(
                200,
                json={
                    "id": 5,
                    "name": "Alice Example",
                    "login": "alice",
                    "email": "alice@example.com",
                    "status": "active",
                    "admin": True,
                    "locked": False,
                    "language": "en",
                    "createdAt": "2026-01-01T00:00:00Z",
                    "updatedAt": "2026-01-02T00:00:00Z",
                    "_links": {
                        "avatar": {"href": "/avatars/5.png"},
                        "showUser": {"href": "/users/5"},
                        "authSource": {"title": "LDAP"},
                        "groups": [{"title": "Admins"}],
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/groups":
            return httpx.Response(
                200,
                json={
                    "total": 1,
                    "_embedded": {
                        "elements": [
                            {
                                "id": 7,
                                "name": "Platform Team",
                                "createdAt": "2026-01-01T00:00:00Z",
                                "updatedAt": "2026-01-02T00:00:00Z",
                                # Real API embeds members as a flat array (OPM-1452),
                                # not a {count, ...} collection object.
                                "_embedded": {"members": [{"name": "Alice"}, {"name": "Bob"}]},
                                "_links": {
                                    "update": {"href": "/api/v3/groups/7"},
                                    "delete": {"href": "/api/v3/groups/7"},
                                },
                            }
                        ]
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/groups/7":
            return httpx.Response(
                200,
                json={
                    "id": 7,
                    "name": "Platform Team",
                    "createdAt": "2026-01-01T00:00:00Z",
                    "updatedAt": "2026-01-02T00:00:00Z",
                    # Real API embeds group-detail members as a flat array, not a
                    # {count, elements} collection object.
                    "_embedded": {"members": [{"name": "Alice"}, {"name": "Bob"}]},
                    "_links": {
                        "memberships": {"href": "/api/v3/groups/7/memberships"},
                        "update": {"href": "/api/v3/groups/7"},
                        "delete": {"href": "/api/v3/groups/7"},
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    import dataclasses

    settings = dataclasses.replace(make_settings(), enable_admin_read=True)
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    users = await client.list_users(search="alice")
    user = await client.get_user("5")
    groups = await client.list_groups(search="platform")
    group = await client.get_group(7)

    assert users.count == 1
    assert users.results[0].email == "alice@example.com"
    assert user.language == "en"
    assert user.groups == ["Admins"]
    assert groups.count == 1
    assert groups.results[0].member_count == 2
    assert group.members == ["Alice", "Bob"]

    await client.aclose()


@pytest.mark.asyncio
async def test_admin_scoped_reads_are_denied_before_any_http_call_without_admin_read() -> None:
    """The 5 tools that moved to the "admin" scope must all raise
    PermissionDeniedError from their own gate check, before issuing any
    request — a handler that raises on any call proves no HTTP request was
    even attempted."""

    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_ENABLE_ADMIN_READ"):
        await client.list_principals()
    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_ENABLE_ADMIN_READ"):
        await client.list_users()
    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_ENABLE_ADMIN_READ"):
        await client.get_user("5")
    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_ENABLE_ADMIN_READ"):
        await client.list_groups()
    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_ENABLE_ADMIN_READ"):
        await client.get_group(7)

    await client.aclose()


@pytest.mark.asyncio
async def test_internal_principal_resolution_bypasses_admin_read_gate() -> None:
    """create_membership resolves a name-based principal via
    _resolve_principal_id -> _list_principals_unchecked, which deliberately
    has no OPENPROJECT_ENABLE_ADMIN_READ gate (see the comment on
    _list_principals_unchecked in client.py): the caller is already
    authorized through create_membership's own membership-write scope check,
    and only a single resolved id is used internally, never the full
    PrincipalSummary list. This must keep working even with admin_read off —
    the negative case (the public list_principals tool itself staying
    gated) is covered by
    test_admin_scoped_reads_are_denied_before_any_http_call_without_admin_read."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo-id" and request.method == "GET":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 1, "name": "Demo", "identifier": "demo-id", "_links": {}},
                request=request,
            )
        if request.url.path == "/api/v3/principals" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            {"id": 5, "name": "Alice", "login": "alice", "_type": "User"},
                        ]
                    },
                    "total": 1,
                },
                request=request,
            )
        if request.url.path == "/api/v3/roles" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [{"id": 2, "name": "Member", "_links": {"self": {"href": "/api/v3/roles/2"}}}]
                    }
                },
                request=request,
            )
        if request.url.path == "/api/v3/memberships/form" and request.method == "POST":
            return httpx.Response(200, json={"_embedded": {"payload": {}}}, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _membership_settings()
    assert settings.enable_admin_read is False  # the case this test exists to cover
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.create_membership(project="demo-id", principal="Alice", roles=["Member"], confirm=False)

    assert result.ready is True

    await client.aclose()


@pytest.mark.asyncio
async def test_actions_capabilities_and_query_metadata_endpoints_normalize_results() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 1, "name": "Demo", "identifier": "demo", "_links": {}},
                request=request,
            )
        if request.url.path == "/api/v3/actions":
            return httpx.Response(
                200,
                json={
                    "total": 1,
                    "_embedded": {
                        "elements": [
                            {
                                "name": "update",
                                "description": "Update resource",
                                "_links": {"self": {"href": "/api/v3/actions/update"}},
                            }
                        ]
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/capabilities":
            assert request.url.params.get("filters") == '[{"context":{"operator":"=","values":["p1"]}}]'
            return httpx.Response(
                200,
                json={
                    "total": 1,
                    "_embedded": {
                        "elements": [
                            {
                                "name": "canUpdate",
                                "_links": {
                                    "self": {"href": "/api/v3/capabilities/update-project"},
                                    "action": {"href": "/api/v3/actions/update", "title": "update"},
                                    "principal": {"href": "/api/v3/users/5", "title": "Alice"},
                                    "context": {"title": "Demo"},
                                },
                            }
                        ]
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/queries/filters/assignee":
            return httpx.Response(
                200,
                json={"name": "Assignee", "_links": {"self": {"href": "/api/v3/queries/filters/assignee"}}},
                request=request,
            )
        if request.url.path == "/api/v3/queries/columns/subject":
            return httpx.Response(
                200,
                json={"name": "Subject", "_links": {"self": {"href": "/api/v3/queries/columns/subject"}}},
                request=request,
            )
        if request.url.path in {"/api/v3/queries/operators/%3D", "/api/v3/queries/operators/="}:
            return httpx.Response(
                200,
                json={"name": "Equals", "_links": {"self": {"href": "/api/v3/queries/operators/%3D"}}},
                request=request,
            )
        if request.url.path in {"/api/v3/queries/sort_bys/subject%3Aasc", "/api/v3/queries/sort_bys/subject:asc"}:
            return httpx.Response(
                200,
                json={
                    "name": "Subject asc",
                    "direction": "asc",
                    "_links": {
                        "self": {"href": "/api/v3/queries/sort_bys/subject:asc"},
                        "column": {"title": "Subject"},
                    },
                },
                request=request,
            )
        if request.url.path == "/api/v3/queries/filter_instance_schemas":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            {
                                "_links": {
                                    "self": {"href": "/api/v3/queries/filter_instance_schemas/assignee"},
                                    "filter": {"title": "Assignee"},
                                },
                                "_dependencies": [{"dependencies": {"=": {}, "!": {}}}],
                            }
                        ]
                    }
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))

    actions = await client.list_actions()
    capabilities = await client.list_capabilities(project="demo")
    filter_ = await client.get_query_filter("assignee")
    column = await client.get_query_column("subject")
    operator = await client.get_query_operator("=")
    sort_by = await client.get_query_sort_by("subject:asc")
    schemas = await client.list_query_filter_instance_schemas()

    assert actions.count == 1
    assert actions.results[0].id == "update"
    assert capabilities.count == 1
    assert capabilities.results[0].principal_name == "Alice"
    assert filter_.id == "assignee"
    assert column.id == "subject"
    assert operator.id == "="
    assert sort_by.direction == "asc"
    assert schemas.count == 1
    assert schemas.results[0].operator_count == 2

    await client.aclose()


@pytest.mark.asyncio
async def test_create_user_returns_preview_when_not_confirmed() -> None:
    # create_user must round-trip through the real users/form endpoint,
    # even with admin writes disabled locally — form validation is a read-only
    # preview, same as every other form-based create_*/update_* tool.
    calls: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/v3/users/form" and request.method == "POST":
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={"_embedded": {"schema": {}, "payload": body, "validationErrors": {}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_base_settings(enable_admin_write=False), transport=httpx.MockTransport(handler))

    result = await client.create_user(
        login="ada", email="ada@example.com", firstname="Ada", lastname="Lovelace", confirm=False
    )

    assert calls == [("POST", "/api/v3/users/form")]
    assert result.confirmed is False
    assert result.requires_confirmation is True
    assert result.ready is True
    assert result.validation_errors == {}
    assert result.user_id is None

    await client.aclose()


@pytest.mark.asyncio
async def test_create_user_rejects_validation_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/users/form" and request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "schema": {},
                        "payload": {},
                        "validationErrors": {"login": {"message": "Login has already been taken."}},
                    }
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(
        _base_settings(enable_admin_write=True, enable_admin_read=True), transport=httpx.MockTransport(handler)
    )

    result = await client.create_user(
        login="ada", email="ada@example.com", firstname="Ada", lastname="Lovelace", confirm=True
    )

    assert result.ready is False
    assert result.confirmed is False
    assert "login" in result.validation_errors
    # A rejected form must short-circuit before ever reaching the write endpoint.

    await client.aclose()


@pytest.mark.asyncio
async def test_create_user_confirm_denied_without_admin_write_enabled() -> None:
    # The form preview call is always allowed (no local gate); only the actual
    # write requires OPENPROJECT_ENABLE_ADMIN_WRITE=true.
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/users/form" and request.method == "POST":
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={"_embedded": {"schema": {}, "payload": body, "validationErrors": {}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_base_settings(enable_admin_write=False), transport=httpx.MockTransport(handler))

    with pytest.raises(PermissionDeniedError):
        await client.create_user(
            login="ada", email="ada@example.com", firstname="Ada", lastname="Lovelace", confirm=True
        )

    await client.aclose()


@pytest.mark.asyncio
async def test_create_user_commits_using_form_payload_after_validation() -> None:
    calls: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/v3/users/form" and request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "schema": {},
                        # OpenProject-normalized payload differs from the raw input
                        # (e.g. login lower-cased) — the write must use this, not
                        # the original input payload.
                        "payload": {"login": "ada", "email": "ada@example.com"},
                        "validationErrors": {},
                    }
                },
                request=request,
            )
        if request.url.path == "/api/v3/users" and request.method == "POST":
            body = json.loads(request.content)
            assert body == {"login": "ada", "email": "ada@example.com"}
            return httpx.Response(201, json={"id": 9, "login": "ada", "_links": {}}, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(
        _base_settings(enable_admin_write=True, enable_admin_read=True), transport=httpx.MockTransport(handler)
    )

    result = await client.create_user(
        login="Ada", email="ada@example.com", firstname="Ada", lastname="Lovelace", confirm=True
    )

    assert calls == [("POST", "/api/v3/users/form"), ("POST", "/api/v3/users")]
    assert result.confirmed is True
    assert result.requires_confirmation is False
    assert result.ready is True
    assert result.user_id == 9  # from the normalized write response, not the input

    await client.aclose()


@pytest.mark.asyncio
async def test_update_user_preview_echoes_caller_supplied_user_id() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/users/9/form" and request.method == "POST":
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={"_embedded": {"schema": {}, "payload": body, "validationErrors": {}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_base_settings(enable_admin_write=False), transport=httpx.MockTransport(handler))

    result = await client.update_user(9, email="new@example.com", confirm=False)

    assert result.user_id == 9
    assert result.confirmed is False
    assert result.requires_confirmation is True

    await client.aclose()


@pytest.mark.asyncio
async def test_update_user_confirm_denied_without_admin_write_enabled() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/users/9/form" and request.method == "POST":
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={"_embedded": {"schema": {}, "payload": body, "validationErrors": {}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_base_settings(enable_admin_write=False), transport=httpx.MockTransport(handler))

    with pytest.raises(PermissionDeniedError):
        await client.update_user(9, email="new@example.com", confirm=True)

    await client.aclose()


@pytest.mark.asyncio
async def test_update_user_commits_using_form_payload_after_validation() -> None:
    calls: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/v3/users/9/form" and request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "schema": {},
                        "payload": {"email": "new@example.com"},
                        "validationErrors": {},
                    }
                },
                request=request,
            )
        if request.url.path == "/api/v3/users/9" and request.method == "PATCH":
            body = json.loads(request.content)
            assert body == {"email": "new@example.com"}
            return httpx.Response(200, json={"id": 9, "email": "new@example.com", "_links": {}}, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(
        _base_settings(enable_admin_write=True, enable_admin_read=True), transport=httpx.MockTransport(handler)
    )

    result = await client.update_user(9, email="new@example.com", confirm=True)

    assert calls == [("POST", "/api/v3/users/9/form"), ("PATCH", "/api/v3/users/9")]
    assert result.confirmed is True
    assert result.requires_confirmation is False
    assert result.user_id == 9  # from the normalized write response

    await client.aclose()


@pytest.mark.asyncio
async def test_user_preferences_get_and_update() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/my_preferences" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 1,
                    "lang": "en",
                    "timeZone": "Europe/Berlin",
                    "commentSortDescending": False,
                    "warnOnLeavingUnsaved": True,
                    "autoHidePopups": False,
                    "updatedAt": "2026-03-20T10:00:00Z",
                },
                request=request,
            )
        if request.url.path == "/api/v3/my_preferences" and request.method == "PATCH":
            body = json.loads(request.content)
            assert body["lang"] == "de"
            assert body["timeZone"] == "America/New_York"
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
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = make_settings()
    settings = Settings(
        read_projects=("*",),
        write_projects=("*",),
        base_url=settings.base_url,
        api_token=settings.api_token,
        timeout=settings.timeout,
        verify_ssl=settings.verify_ssl,
        default_page_size=settings.default_page_size,
        max_page_size=settings.max_page_size,
        max_results=settings.max_results,
        log_level=settings.log_level,
        enable_personal_read=True,
        enable_personal_write=True,
    )
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    prefs = await client.get_my_preferences()
    assert prefs.lang == "en"
    assert prefs.time_zone == "Europe/Berlin"
    assert prefs.comment_sort_descending is False

    preview = await client.update_my_preferences(lang="de", time_zone="America/New_York", confirm=False)
    assert preview.requires_confirmation is True

    updated = await client.update_my_preferences(lang="de", time_zone="America/New_York", confirm=True)
    assert updated.result is not None
    assert updated.result.lang == "de"
    assert updated.result.time_zone == "America/New_York"

    await client.aclose()


@pytest.mark.asyncio
async def test_get_my_preferences_denied_without_personal_read() -> None:
    """get_my_preferences has a client-side gate matching its
    registry-level "personal" gate."""

    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request must be issued without personal read enabled")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(PermissionDeniedError, match="personal"):
        await client.get_my_preferences()
    await client.aclose()


@pytest.mark.asyncio
async def test_update_my_preferences_denied_without_personal_write() -> None:
    """update_my_preferences is gated by "personal" write."""

    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request must be issued without personal write enabled")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_ENABLE_PERSONAL_WRITE"):
        await client.update_my_preferences(lang="de", confirm=True)
    await client.aclose()


@pytest.mark.asyncio
async def test_update_my_preferences_succeeds_with_personal_write_enabled() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/my_preferences" and request.method == "PATCH":
            return httpx.Response(200, json={"_type": "UserPreferences"}, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_personal_write_enabled_settings(), transport=httpx.MockTransport(handler))
    result = await client.update_my_preferences(lang="de", confirm=True)
    assert result.confirmed
    await client.aclose()


@pytest.mark.asyncio
async def test_list_users_no_search_uses_exact_server_pagination() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/users" and request.method == "GET":
            assert request.url.params["offset"] == "1"
            assert request.url.params["pageSize"] == "2"
            return httpx.Response(
                200,
                json={
                    "total": 5,
                    "_embedded": {
                        "elements": [
                            {"id": 1, "name": "Alice", "login": "alice", "email": "alice@example.com"},
                            {"id": 2, "name": "Bob", "login": "bob", "email": "bob@example.com"},
                        ]
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    import dataclasses

    settings = dataclasses.replace(make_settings(), enable_admin_read=True)
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))
    page = await client.list_users(limit=2)

    assert [u.id for u in page.results] == [1, 2]
    assert page.total == 5
    assert page.truncated is True
    assert page.next_offset == 2

    await client.aclose()


@pytest.mark.asyncio
async def test_list_users_search_overfetches_and_filters_then_paginates() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/users" and request.method == "GET":
            assert request.url.params["offset"] == "1"
            assert request.url.params["pageSize"] == str(make_settings().max_results)
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            {"id": 1, "name": "Alice Smith", "login": "alice", "email": "alice@example.com"},
                            {"id": 2, "name": "Bob Jones", "login": "bob", "email": "bob@acme.io"},
                            {"id": 3, "name": "Carol Diaz", "login": "carol", "email": "carol@example.com"},
                            {"id": 4, "name": "Dana Alicente", "login": "dana", "email": "dana@example.com"},
                        ]
                    }
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    import dataclasses

    settings = dataclasses.replace(make_settings(), enable_admin_read=True)
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))
    page = await client.list_users(search="ali")

    # "ali" substring-matches ids 1 (name+login) and 4 (name "Alicente"); 2 and 3 don't match.
    assert {u.id for u in page.results} == {1, 4}
    assert page.total == 2

    # Filter-then-paginate ordering: limit=1/offset=2 must return the 2nd filtered
    # survivor (id=4), not slice the raw 4-item page first.
    second_page = await client.list_users(search="ali", limit=1, offset=2)
    assert [u.id for u in second_page.results] == [4]
    assert second_page.total == 2
    assert second_page.truncated is False
    assert second_page.next_offset is None

    await client.aclose()


@pytest.mark.asyncio
async def test_list_groups_no_search_uses_exact_server_pagination() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/groups" and request.method == "GET":
            assert request.url.params["offset"] == "1"
            assert request.url.params["pageSize"] == "2"
            return httpx.Response(
                200,
                json={
                    "total": 5,
                    "_embedded": {
                        "elements": [
                            {"id": 1, "name": "Alpha"},
                            {"id": 2, "name": "Beta"},
                        ]
                    },
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    import dataclasses

    settings = dataclasses.replace(make_settings(), enable_admin_read=True)
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))
    page = await client.list_groups(limit=2)

    assert [g.id for g in page.results] == [1, 2]
    assert page.total == 5
    assert page.truncated is True
    assert page.next_offset == 2

    await client.aclose()


@pytest.mark.asyncio
async def test_list_groups_search_overfetches_and_filters_then_paginates() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/groups" and request.method == "GET":
            assert request.url.params["offset"] == "1"
            assert request.url.params["pageSize"] == str(make_settings().max_results)
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            {"id": 1, "name": "Engineering Alpha"},
                            {"id": 2, "name": "Sales"},
                            {"id": 3, "name": "Support"},
                            {"id": 4, "name": "Alpha Squad"},
                        ]
                    }
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    import dataclasses

    settings = dataclasses.replace(make_settings(), enable_admin_read=True)
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))
    page = await client.list_groups(search="alpha")

    assert {g.id for g in page.results} == {1, 4}
    assert page.total == 2

    second_page = await client.list_groups(search="alpha", limit=1, offset=2)
    assert [g.id for g in second_page.results] == [4]
    assert second_page.total == 2
    assert second_page.truncated is False
    assert second_page.next_offset is None

    await client.aclose()
