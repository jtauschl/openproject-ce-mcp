"""Write/delete-tool behavioral-contract cases (OPM-209 / Phase D) for the
membership, version, board, and admin (user/group) scopes.

Sibling modules import this as `from
_write_contract_cases_membership_version_board_admin import ...` (no package
prefix) -- same rootless-import convention as `_client_test_helpers.py` /
`_tools_test_helpers.py` (see the comment at the top of those files).
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


def _admin_settings(**overrides: object) -> Settings:
    return _settings(enable_admin_write=True, **overrides)


def _unexpected(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"Unexpected request: {request.method} {request.url}")


# --- Membership -------------------------------------------------------------


def _create_membership_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/projects/demo" and request.method == "GET":
        return httpx.Response(
            200,
            json={"_type": "Project", "id": 6, "name": "Demo", "identifier": "demo"},
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
        body = json.loads(request.content)
        return httpx.Response(200, json={"_embedded": {"payload": body, "validationErrors": {}}}, request=request)
    if request.url.path == "/api/v3/memberships" and request.method == "POST":
        return httpx.Response(
            201,
            json={
                "id": 14,
                "_links": {
                    "project": {"href": "/api/v3/projects/6", "title": "Demo"},
                    "principal": {"href": "/api/v3/users/5", "title": "Alice"},
                    "roles": [{"href": "/api/v3/roles/2", "title": "Member"}],
                },
            },
            request=request,
        )
    return _unexpected(request)


def _update_membership_handler(request: httpx.Request) -> httpx.Response:
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
    if request.url.path == "/api/v3/roles" and request.method == "GET":
        return httpx.Response(200, json={"_embedded": {"elements": []}}, request=request)
    if request.url.path == "/api/v3/memberships/3/form" and request.method == "POST":
        body = json.loads(request.content)
        return httpx.Response(200, json={"_embedded": {"payload": body, "validationErrors": {}}}, request=request)
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
    return _unexpected(request)


def _delete_membership_handler(request: httpx.Request) -> httpx.Response:
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
    if request.url.path == "/api/v3/memberships/3" and request.method == "DELETE":
        return httpx.Response(204, request=request)
    return _unexpected(request)


# --- Version ------------------------------------------------------------


def _create_version_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/projects/demo" and request.method == "GET":
        return httpx.Response(
            200,
            json={"_type": "Project", "id": 6, "name": "Demo", "identifier": "demo"},
            request=request,
        )
    if request.url.path == "/api/v3/versions/form" and request.method == "POST":
        body = json.loads(request.content)
        return httpx.Response(200, json={"_embedded": {"payload": body, "validationErrors": {}}}, request=request)
    if request.url.path == "/api/v3/versions" and request.method == "POST":
        return httpx.Response(
            201,
            json={
                "id": 8,
                "name": "v2.0",
                "status": "open",
                "sharing": "none",
                "_links": {"definingProject": {"title": "Demo"}},
            },
            request=request,
        )
    return _unexpected(request)


def _update_version_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/versions/8" and request.method == "GET":
        return httpx.Response(
            200,
            json={
                "id": 8,
                "name": "Release 1",
                "status": "open",
                "sharing": "none",
                "_links": {"definingProject": {"title": "Demo"}},
            },
            request=request,
        )
    if request.url.path == "/api/v3/versions/8/form" and request.method == "POST":
        body = json.loads(request.content)
        return httpx.Response(200, json={"_embedded": {"payload": body, "validationErrors": {}}}, request=request)
    if request.url.path == "/api/v3/versions/8" and request.method == "PATCH":
        return httpx.Response(
            200,
            json={
                "id": 8,
                "name": "Release 1.1",
                "status": "locked",
                "sharing": "none",
                "_links": {"definingProject": {"title": "Demo"}},
            },
            request=request,
        )
    return _unexpected(request)


def _delete_version_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/versions/8" and request.method == "GET":
        return httpx.Response(
            200,
            json={
                "id": 8,
                "name": "Release 1",
                "status": "open",
                "sharing": "none",
                "_links": {"definingProject": {"title": "Demo"}},
            },
            request=request,
        )
    if request.url.path == "/api/v3/versions/8" and request.method == "DELETE":
        return httpx.Response(204, request=request)
    return _unexpected(request)


# --- Board ----------------------------------------------------------------


def _create_board_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/projects/demo" and request.method == "GET":
        return httpx.Response(
            200,
            json={"_type": "Project", "id": 6, "name": "Demo", "identifier": "demo"},
            request=request,
        )
    if request.url.path == "/api/v3/queries/form" and request.method == "POST":
        body = json.loads(request.content)
        return httpx.Response(200, json={"_embedded": {"payload": body, "validationErrors": {}}}, request=request)
    if request.url.path == "/api/v3/queries" and request.method == "POST":
        return httpx.Response(
            201,
            json={
                "_type": "Query",
                "id": 14,
                "name": "Sprint Board",
                "_links": {
                    "self": {"href": "/api/v3/queries/14"},
                    "project": {"href": "/api/v3/projects/6", "title": "Demo"},
                },
            },
            request=request,
        )
    return _unexpected(request)


def _board_payload(*, board_id: int = 12, name: str = "Sprint Board", public: bool = False) -> dict:
    return {
        "_type": "Query",
        "id": board_id,
        "name": name,
        "public": public,
        "hidden": False,
        "starred": False,
        "includeSubprojects": False,
        "showHierarchies": False,
        "timelineVisible": False,
        "_links": {
            "self": {"href": f"/api/v3/queries/{board_id}", "title": name},
            "project": {"href": "/api/v3/projects/6", "title": "Demo"},
            "update": {"href": f"/api/v3/queries/{board_id}/form", "method": "post"},
            "updateImmediately": {"href": f"/api/v3/queries/{board_id}", "method": "patch"},
            "delete": {"href": f"/api/v3/queries/{board_id}", "method": "delete"},
        },
    }


def _update_board_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/queries/12" and request.method == "GET":
        return httpx.Response(200, json=_board_payload(), request=request)
    if request.url.path == "/api/v3/queries/12/form" and request.method == "POST":
        body = json.loads(request.content)
        return httpx.Response(200, json={"_embedded": {"payload": body, "validationErrors": {}}}, request=request)
    if request.url.path == "/api/v3/queries/12" and request.method == "PATCH":
        return httpx.Response(200, json=_board_payload(name="Sprint Board Updated", public=True), request=request)
    return _unexpected(request)


def _delete_board_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/queries/12" and request.method == "GET":
        return httpx.Response(200, json=_board_payload(), request=request)
    if request.url.path == "/api/v3/queries/12" and request.method == "DELETE":
        return httpx.Response(204, request=request)
    return _unexpected(request)


# --- Admin: users -----------------------------------------------------------


def _create_user_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/users/form" and request.method == "POST":
        body = json.loads(request.content)
        return httpx.Response(200, json={"_embedded": {"payload": body, "validationErrors": {}}}, request=request)
    if request.url.path == "/api/v3/users" and request.method == "POST":
        body = json.loads(request.content)
        return httpx.Response(201, json={"id": 9, "login": body.get("login"), "_links": {}}, request=request)
    return _unexpected(request)


def _update_user_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/users/9/form" and request.method == "POST":
        body = json.loads(request.content)
        return httpx.Response(200, json={"_embedded": {"payload": body, "validationErrors": {}}}, request=request)
    if request.url.path == "/api/v3/users/9" and request.method == "PATCH":
        body = json.loads(request.content)
        return httpx.Response(200, json={"id": 9, "email": body.get("email"), "_links": {}}, request=request)
    return _unexpected(request)


def _delete_user_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/users/9" and request.method == "DELETE":
        return httpx.Response(204, request=request)
    return _unexpected(request)


def _lock_user_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/users/9/lock" and request.method == "POST":
        return httpx.Response(200, json={"id": 9, "login": "ada", "locked": True, "_links": {}}, request=request)
    return _unexpected(request)


def _unlock_user_handler(request: httpx.Request) -> httpx.Response:
    # OpenProject's user_transition helper (verified against .op-sources)
    # responds 200 + the full updated UserRepresenter body for both the POST
    # and DELETE lock transitions -- no follow-up GET needed or issued.
    if request.url.path == "/api/v3/users/9/lock" and request.method == "DELETE":
        return httpx.Response(200, json={"id": 9, "login": "ada", "locked": False, "_links": {}}, request=request)
    return _unexpected(request)


# --- Admin: groups ----------------------------------------------------------


def _create_group_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/groups" and request.method == "POST":
        body = json.loads(request.content)
        return httpx.Response(201, json={"id": 3, "name": body.get("name"), "_links": {}}, request=request)
    return _unexpected(request)


def _update_group_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/groups/3" and request.method == "PATCH":
        body = json.loads(request.content)
        return httpx.Response(200, json={"id": 3, "name": body.get("name"), "_links": {}}, request=request)
    return _unexpected(request)


def _delete_group_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v3/groups/3" and request.method == "DELETE":
        return httpx.Response(204, request=request)
    return _unexpected(request)


MEMBERSHIP_VERSION_BOARD_ADMIN_CASES: dict[str, WriteToolCase] = {
    "create_membership": WriteToolCase(
        tool="create_membership",
        kwargs={"project": "demo", "principal": "5", "roles": ["2"]},
        settings=_settings(),
        write_scope="membership",
        handler=_create_membership_handler,
        write_request=("POST", "/api/v3/memberships"),
    ),
    "update_membership": WriteToolCase(
        tool="update_membership",
        kwargs={"membership_id": 3, "roles": ["2"]},
        settings=_settings(),
        write_scope="membership",
        handler=_update_membership_handler,
        write_request=("PATCH", "/api/v3/memberships/3"),
    ),
    "delete_membership": WriteToolCase(
        tool="delete_membership",
        kwargs={"membership_id": 3},
        settings=_settings(),
        write_scope="membership",
        handler=_delete_membership_handler,
        write_request=("DELETE", "/api/v3/memberships/3"),
    ),
    "create_version": WriteToolCase(
        tool="create_version",
        kwargs={"project": "demo", "name": "v2.0"},
        settings=_settings(),
        write_scope="version",
        handler=_create_version_handler,
        write_request=("POST", "/api/v3/versions"),
    ),
    "update_version": WriteToolCase(
        tool="update_version",
        kwargs={"version_id": 8, "name": "Release 1.1"},
        settings=_settings(),
        write_scope="version",
        handler=_update_version_handler,
        write_request=("PATCH", "/api/v3/versions/8"),
    ),
    "delete_version": WriteToolCase(
        tool="delete_version",
        kwargs={"version_id": 8},
        settings=_settings(),
        write_scope="version",
        handler=_delete_version_handler,
        write_request=("DELETE", "/api/v3/versions/8"),
    ),
    "create_board": WriteToolCase(
        tool="create_board",
        kwargs={"name": "Sprint Board", "project": "demo"},
        settings=_settings(),
        write_scope="board",
        handler=_create_board_handler,
        write_request=("POST", "/api/v3/queries"),
    ),
    "update_board": WriteToolCase(
        tool="update_board",
        kwargs={"board_id": 12, "name": "Sprint Board Updated"},
        settings=_settings(),
        write_scope="board",
        handler=_update_board_handler,
        write_request=("PATCH", "/api/v3/queries/12"),
    ),
    "delete_board": WriteToolCase(
        tool="delete_board",
        kwargs={"board_id": 12},
        settings=_settings(),
        write_scope="board",
        handler=_delete_board_handler,
        write_request=("DELETE", "/api/v3/queries/12"),
    ),
    "create_user": WriteToolCase(
        tool="create_user",
        kwargs={"login": "ada", "email": "ada@example.com", "firstname": "Ada", "lastname": "Lovelace"},
        settings=_admin_settings(),
        write_scope="admin",
        handler=_create_user_handler,
        write_request=("POST", "/api/v3/users"),
    ),
    "update_user": WriteToolCase(
        tool="update_user",
        kwargs={"user_id": 9, "email": "new@example.com"},
        settings=_admin_settings(),
        write_scope="admin",
        handler=_update_user_handler,
        write_request=("PATCH", "/api/v3/users/9"),
    ),
    "delete_user": WriteToolCase(
        tool="delete_user",
        kwargs={"user_id": 9},
        settings=_admin_settings(),
        write_scope="admin",
        handler=_delete_user_handler,
        write_request=("DELETE", "/api/v3/users/9"),
    ),
    "lock_user": WriteToolCase(
        tool="lock_user",
        kwargs={"user_id": 9},
        settings=_admin_settings(),
        write_scope="admin",
        handler=_lock_user_handler,
        write_request=("POST", "/api/v3/users/9/lock"),
    ),
    "unlock_user": WriteToolCase(
        tool="unlock_user",
        kwargs={"user_id": 9},
        settings=_admin_settings(),
        write_scope="admin",
        handler=_unlock_user_handler,
        write_request=("DELETE", "/api/v3/users/9/lock"),
    ),
    "create_group": WriteToolCase(
        tool="create_group",
        kwargs={"name": "Developers"},
        settings=_admin_settings(),
        write_scope="admin",
        handler=_create_group_handler,
        write_request=("POST", "/api/v3/groups"),
    ),
    "update_group": WriteToolCase(
        tool="update_group",
        kwargs={"group_id": 3, "name": "Backend"},
        settings=_admin_settings(),
        write_scope="admin",
        handler=_update_group_handler,
        write_request=("PATCH", "/api/v3/groups/3"),
    ),
    "delete_group": WriteToolCase(
        tool="delete_group",
        kwargs={"group_id": 3},
        settings=_admin_settings(),
        write_scope="admin",
        handler=_delete_group_handler,
        write_request=("DELETE", "/api/v3/groups/3"),
    ),
}
