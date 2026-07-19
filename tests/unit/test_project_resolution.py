from __future__ import annotations

import json

import httpx
import pytest
from _client_test_helpers import (
    _base_settings,
    _make_grid_payload,
    _make_grid_settings,
    _make_project_response,
    _make_wp_form_response,
    _projects_search_handler,
    make_settings,
)

from openproject_ce_mcp.client import (
    InvalidInputError,
    NotFoundError,
    OpenProjectClient,
    PermissionDeniedError,
)


@pytest.mark.asyncio
async def test_get_grid_denies_disallowed_project_scope() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/grids/55" and request.method == "GET":
            return httpx.Response(200, json=_make_grid_payload(), request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _make_grid_settings({"read_projects": ("other",), "write_projects": ("other",)})
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await client.get_grid(55)

    await client.aclose()


@pytest.mark.asyncio
async def test_create_work_package_denies_disallowed_parent_project() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo" and request.method == "GET":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 1, "identifier": "demo", "name": "Demo", "_links": {}},
                request=request,
            )
        if request.url.path == "/api/v3/work_packages/999" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 999, "_links": {"project": {"title": "Other", "href": "/api/v3/projects/2"}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(read_projects=("demo",), write_projects=("demo",), enable_work_package_write=True)
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await client.create_work_package(
            project="demo", type="Task", subject="Child", parent_work_package_id=999, confirm=True
        )
    await client.aclose()


@pytest.mark.asyncio
async def test_update_work_package_denies_disallowed_parent_project() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/999" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 999, "_links": {"project": {"title": "Other", "href": "/api/v3/projects/2"}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(read_projects=("demo",), write_projects=("demo",), enable_work_package_write=True)
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await client.update_work_package(work_package_id=42, parent_work_package_id=999, confirm=True)
    await client.aclose()


@pytest.mark.asyncio
async def test_create_work_package_relation_denies_disallowed_target_project() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/999" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": 999, "_links": {"project": {"title": "Other", "href": "/api/v3/projects/2"}}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(read_projects=("demo",), write_projects=("demo",), enable_work_package_write=True)
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await client.create_work_package_relation(
            work_package_id=42, related_to_work_package_id=999, relation_type="blocks", confirm=True
        )
    await client.aclose()


@pytest.mark.asyncio
async def test_update_work_package_denies_disallowed_sprint_project() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/work_packages/42" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "lockVersion": 1,
                    "_links": {"project": {"title": "Demo", "href": "/api/v3/projects/1"}},
                },
                request=request,
            )
        if request.url.path == "/api/v3/sprints/700" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 700,
                    "name": "Sprint 1",
                    "_links": {"definingWorkspace": {"title": "Other", "href": "/api/v3/projects/2"}},
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(read_projects=("demo",), write_projects=("demo",), enable_work_package_write=True)
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await client.update_work_package(work_package_id=42, sprint="700", confirm=True)
    await client.aclose()


@pytest.mark.asyncio
async def test_update_project_denies_disallowed_parent_project() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo" and request.method == "GET":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 1, "identifier": "demo", "name": "Demo", "_links": {}},
                request=request,
            )
        if request.url.path == "/api/v3/projects/1/form" and request.method == "POST":
            return httpx.Response(200, json={"_embedded": {"schema": {}}}, request=request)
        if request.url.path == "/api/v3/projects/999" and request.method == "GET":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 999, "identifier": "other", "name": "Other"},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(read_projects=("demo",), write_projects=("demo",), enable_project_write=True)
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await client.update_project(project_ref="demo", parent="999", confirm=True)
    await client.aclose()


# OPM-117: systematic project-reference-type x access-type x expectation matrix.
# Underlying invariant: no project-specific follow-up request may occur before the
# target project has been resolved and checked against the required read/write
# policy. Each case asserts both the outcome (success/denied) and the exact number
# of requests made, so a regression that fires an extra request after a denial (or
# skips the write check after an allowed read) fails loudly. Numeric-id and
# identifier refs are covered here; name refs (a different, search-based code path)
# are covered by the dedicated tests around them (e.g.
# test_get_project_resolves_by_exact_name_when_unique,
# test_create_work_package_by_display_name_still_enforces_write_allowlist) plus the
# ambiguous-name write-path test directly below this matrix.
#
# OPM-209 extended this matrix with "membership"/"board"/"version" operations
# (previously only "read"/"write" against project itself), specifically to prove
# the property holds through domains beyond project, and -- for "version" -- through
# the app/-layer delegation (VersionService/project-ref resolution wiring), not
# just legacy client.py code. This proves the *stronger* zero-follow-up-requests
# guarantee for a representative handful of domains; the complementary, exhaustive
# but weaker (authorization-precedes-only-the-mutating-call) check across all 55
# registered write tools lives in
# test_write_confirm_contracts.py::test_write_tool_denies_when_its_write_scope_is_disabled.
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "project_ref,read_projects,write_projects,operation,expect_error,expected_request_count",
    [
        pytest.param("1", ("*",), ("*",), "read", None, 1, id="numeric_id-read_allowed"),
        pytest.param("1", ("other",), ("*",), "read", "READ", 1, id="numeric_id-read_denied"),
        pytest.param("demo", ("*",), ("*",), "read", None, 1, id="identifier-read_allowed"),
        pytest.param("demo", ("other",), ("*",), "read", "READ", 1, id="identifier-read_denied"),
        pytest.param("1", ("*",), ("other",), "write", "WRITE", 1, id="numeric_id-read_only-write_denied"),
        # 3, not 2: update_project() with no fields still fetches the project schema
        # once (via _build_project_write_payload -> _get_project_schema) and then
        # posts the write-preview form separately — an incidental implementation
        # detail of the no-op-edit path, not a policy-check request.
        pytest.param("1", ("*",), ("*",), "write", None, 3, id="numeric_id-write_allowed"),
        pytest.param("demo", ("*",), ("other",), "write", "WRITE", 1, id="identifier-read_only-write_denied"),
        pytest.param("demo", ("*",), ("*",), "write", None, 3, id="identifier-write_allowed"),
        # membership: create_membership resolves+write-checks the project first (1
        # request, and where it fails on denial), then resolves role hrefs (GET
        # /api/v3/roles, unconditional even for a numeric role ref) and posts the
        # membership preview form — 3 requests when allowed.
        pytest.param("demo", ("*",), ("other",), "membership", "WRITE", 1, id="membership-write_denied"),
        pytest.param("demo", ("*",), ("*",), "membership", None, 3, id="membership-write_allowed"),
        # board: create_board resolves+write-checks the project (1 request, and
        # where it fails on denial), then _build_board_write_payload separately
        # resolves the project id again (same URL, a second request) before posting
        # the board preview form — 3 requests when allowed.
        pytest.param("1", ("*",), ("other",), "board", "WRITE", 1, id="board-write_denied"),
        pytest.param("1", ("*",), ("*",), "board", None, 3, id="board-write_allowed"),
        # version: routed through app/services/version_service.py (the OPM-153
        # pilot's app/-layer delegation, not legacy client.py code) — resolves+
        # write-checks the project (1 request, and where it fails on denial), then
        # posts the version preview form — 2 requests when allowed.
        pytest.param("demo", ("*",), ("other",), "version", "WRITE", 1, id="version-write_denied"),
        pytest.param("demo", ("*",), ("*",), "version", None, 2, id="version-write_allowed"),
    ],
)
async def test_project_resolution_policy_matrix(
    project_ref: str,
    read_projects: tuple[str, ...],
    write_projects: tuple[str, ...],
    operation: str,
    expect_error: str | None,
    expected_request_count: int,
) -> None:
    import dataclasses

    requests_seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(f"{request.method} {request.url.path}")
        if request.url.path == f"/api/v3/projects/{project_ref}" and request.method == "GET":
            return _make_project_response(request, project_id=1)
        if request.url.path == "/api/v3/projects/1/form" and request.method == "POST":
            return httpx.Response(200, json={"_embedded": {"schema": {}}}, request=request)
        if request.url.path == "/api/v3/roles" and request.method == "GET":
            return httpx.Response(200, json={"_embedded": {"elements": []}}, request=request)
        if request.url.path == "/api/v3/memberships/form" and request.method == "POST":
            return httpx.Response(
                200,
                json={"_embedded": {"payload": {"_links": {"roles": [{"href": "/api/v3/roles/2"}]}}}},
                request=request,
            )
        if request.url.path == "/api/v3/queries/form" and request.method == "POST":
            return httpx.Response(
                200, json={"_embedded": {"payload": {"name": "Board"}, "validationErrors": {}}}, request=request
            )
        if request.url.path == "/api/v3/versions/form" and request.method == "POST":
            return httpx.Response(
                200, json={"_embedded": {"payload": {"name": "v1.0"}, "validationErrors": {}}}, request=request
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = dataclasses.replace(make_settings(), read_projects=read_projects, write_projects=write_projects)
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    async def call() -> None:
        if operation == "read":
            project = await client.get_project(project_ref)
            assert project.id == 1
        elif operation == "write":
            result = await client.update_project(project_ref=project_ref, confirm=False)
            assert result.ready
        elif operation == "membership":
            result = await client.create_membership(project=project_ref, principal="5", roles=["2"], confirm=False)
            assert result.ready
        elif operation == "board":
            result = await client.create_board(name="Board", project=project_ref, confirm=False)
            assert result.ready
        else:
            assert operation == "version"
            result = await client.create_version(project=project_ref, name="v1.0", confirm=False)
            assert result.ready

    if expect_error is None:
        await call()
    else:
        env_var = "OPENPROJECT_READ_PROJECTS" if expect_error == "READ" else "OPENPROJECT_WRITE_PROJECTS"
        with pytest.raises(PermissionDeniedError, match=env_var):
            await call()

    assert len(requests_seen) == expected_request_count, (
        f"expected {expected_request_count} request(s), got {requests_seen}"
    )
    await client.aclose()


@pytest.mark.asyncio
async def test_update_project_denies_write_when_name_ref_is_ambiguous() -> None:
    """A write-path project ref that resolves ambiguously by name must never reach a
    mutating request — the ambiguity is raised inside the name search itself, before
    any per-candidate GET or form POST is attempted."""
    search_handler = _projects_search_handler(
        [
            {"id": 5, "name": "Website", "identifier": "web-1"},
            {"id": 6, "name": "Website", "identifier": "web-2"},
        ]
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/Website":
            return httpx.Response(404, json={"message": "not found"}, request=request)
        if request.url.path == "/api/v3/projects" and request.method == "GET":
            return search_handler(request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_base_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(InvalidInputError, match="ambiguous"):
        await client.update_project(project_ref="Website", confirm=False)
    await client.aclose()


@pytest.mark.asyncio
async def test_update_project_clears_description_and_status_explanation() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo" and request.method == "GET":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 1, "identifier": "demo", "name": "Demo", "_links": {}},
                request=request,
            )
        if request.url.path == "/api/v3/projects/1/form" and request.method == "POST":
            body = json.loads(request.content)
            if not body:
                # _build_project_write_payload first fetches the schema with an
                # empty draft payload, before the real fields are filled in.
                return httpx.Response(200, json={"_embedded": {"schema": {}}}, request=request)
            assert body["description"] == {"format": "markdown", "raw": ""}
            assert body["statusExplanation"] == {"format": "markdown", "raw": ""}
            return httpx.Response(
                200,
                json={"_embedded": {"schema": {}, "payload": body, "validationErrors": {}}},
                request=request,
            )
        if request.url.path == "/api/v3/projects/1" and request.method == "PATCH":
            body = json.loads(request.content)
            assert body["description"] == {"format": "markdown", "raw": ""}
            assert body["statusExplanation"] == {"format": "markdown", "raw": ""}
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 1, "identifier": "demo", "name": "Demo", "_links": {}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(enable_project_write=True)
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.update_project(
        project_ref="demo",
        description="",
        status_explanation="",
        confirm=True,
    )

    assert result.confirmed is True
    await client.aclose()


@pytest.mark.asyncio
async def test_update_project_none_description_leaves_field_untouched() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo" and request.method == "GET":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 1, "identifier": "demo", "name": "Demo", "_links": {}},
                request=request,
            )
        if request.url.path == "/api/v3/projects/1/form" and request.method == "POST":
            body = json.loads(request.content)
            assert "description" not in body
            return httpx.Response(
                200,
                json={"_embedded": {"schema": {}, "payload": body, "validationErrors": {}}},
                request=request,
            )
        if request.url.path == "/api/v3/projects/1" and request.method == "PATCH":
            body = json.loads(request.content)
            assert "description" not in body
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 1, "identifier": "demo", "name": "Demo", "_links": {}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(enable_project_write=True)
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    result = await client.update_project(project_ref="demo", name="New Name", confirm=True)

    assert result.confirmed is True
    await client.aclose()


@pytest.mark.parametrize("project_ref", ["secret", "99"])
@pytest.mark.asyncio
async def test_resolve_type_id_denies_disallowed_project(project_ref: str) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/api/v3/projects/{project_ref}":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 99, "identifier": "secret", "name": "Secret"},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(read_projects=("demo",))  # neither "secret" nor "99" is allowed
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await client._resolve_type_id("Bug", project=project_ref)
    await client.aclose()


@pytest.mark.asyncio
async def test_resolve_type_id_rejects_ambiguous_name() -> None:
    # OpenProject does not enforce unique type names within a project. Two types
    # sharing a name (case-insensitively) must be rejected, not silently resolved
    # to whichever one happened to come first in the list — matching the
    # ambiguity guard every sibling resolver (_resolve_principal_id,
    # _resolve_sprint_id) already has.
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 1, "identifier": "demo", "name": "Demo"},
                request=request,
            )
        if request.url.path == "/api/v3/projects/1/types":
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "elements": [
                            {"id": 1, "name": "Bug"},
                            {"id": 2, "name": "bug"},
                        ]
                    }
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_base_settings(), transport=httpx.MockTransport(handler))

    with pytest.raises(InvalidInputError, match="ambiguous"):
        await client._resolve_type_id("Bug", project="demo")
    await client.aclose()


@pytest.mark.asyncio
async def test_resolve_version_id_numeric_project_ref_is_allowlist_checked_first() -> None:
    # A numeric, disallowed project ref must be denied via _get_project_payload
    # before any version-listing request is ever made.
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/999" and request.method == "GET":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 999, "identifier": "other", "name": "Other"},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(read_projects=("demo",))
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await client._resolve_version_id("500", project="999")
    await client.aclose()


@pytest.mark.asyncio
async def test_resolve_version_id_project_scoped_shared_version_found_on_second_page() -> None:
    # A version defined in a disallowed project, but shared into the (allowed) target
    # project, must resolve by numeric id AND by name, even when it only appears on
    # page 2 of the target project's own version list.
    def page_1() -> dict:
        elements = [{"id": i, "name": f"v{i}", "_links": {}} for i in range(1, 51)]
        return {"_embedded": {"elements": elements}}

    def page_2() -> dict:
        return {
            "_embedded": {
                "elements": [{"id": 999, "name": "Shared Release", "_links": {}}],
            }
        }

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo" and request.method == "GET":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 1, "identifier": "demo", "name": "Demo", "active": True},
                request=request,
            )
        if request.url.path == "/api/v3/projects/1/versions" and request.method == "GET":
            offset = request.url.params["offset"]
            assert request.url.params["pageSize"] == "50"
            if offset == "1":
                return httpx.Response(200, json={**page_1(), "total": 51}, request=request)
            if offset == "2":
                return httpx.Response(200, json={**page_2(), "total": 51}, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))

    by_id = await client._resolve_version_id("999", project="demo")
    assert by_id == "999"

    by_name = await client._resolve_version_id("Shared Release", project="demo")
    assert by_name == "999"

    await client.aclose()


@pytest.mark.asyncio
async def test_resolve_version_id_project_scoped_unrelated_version_denied() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo" and request.method == "GET":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 1, "identifier": "demo", "name": "Demo", "active": True},
                request=request,
            )
        if request.url.path == "/api/v3/projects/1/versions" and request.method == "GET":
            return httpx.Response(
                200,
                json={"total": 1, "_embedded": {"elements": [{"id": 1, "name": "v1", "_links": {}}]}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))

    with pytest.raises(InvalidInputError, match="not available"):
        await client._resolve_version_id("999", project="demo")
    await client.aclose()


@pytest.mark.asyncio
async def test_resolve_version_id_no_project_falls_back_to_defining_project_check() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/versions/500" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 500,
                    "name": "v500",
                    "_links": {"definingProject": {"title": "Other", "href": "/api/v3/projects/2"}},
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    settings = _base_settings(read_projects=("demo",))
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await client._resolve_version_id("500", project=None)
    await client.aclose()


@pytest.mark.asyncio
async def test_resolve_version_id_project_less_name_match_beyond_first_filtered_page() -> None:
    # 50 substring-matching-but-not-exact names, then the real exact match — must be
    # found even though it's beyond page 1 of the search-filtered survivors.
    def raw_elements() -> list[dict]:
        decoys = [{"id": i, "name": f"Release Candidate {i}", "_links": {}} for i in range(1, 51)]
        exact = {"id": 999, "name": "Release", "_links": {}}
        return [*decoys, exact]

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/versions" and request.method == "GET":
            assert request.url.params["pageSize"] == str(make_settings().max_results)
            return httpx.Response(200, json={"_embedded": {"elements": raw_elements()}}, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(make_settings(), transport=httpx.MockTransport(handler))

    matched = await client._resolve_version_id("Release", project=None)
    assert matched == "999"

    await client.aclose()


async def test_get_project_resolves_by_exact_identifier_without_search() -> None:
    """Numeric id / identifier input never triggers the name-search fallback."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/demo":
            return _make_project_response(request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_base_settings(), transport=httpx.MockTransport(handler))
    project = await client.get_project("demo")
    assert project.identifier == "demo"
    await client.aclose()


async def test_get_project_resolves_by_exact_name_when_unique() -> None:
    """A display name with no matching identifier falls back to a unique name search hit."""
    search_handler = _projects_search_handler([{"id": 5, "name": "Website", "identifier": "web-1"}])

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/Website":
            return httpx.Response(404, json={"message": "not found"}, request=request)
        if request.url.path == "/api/v3/projects" and request.method == "GET":
            return search_handler(request)
        if request.url.path == "/api/v3/projects/5":
            return _make_project_response(request, project_id=5)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_base_settings(), transport=httpx.MockTransport(handler))
    project = await client.get_project("Website")
    assert project.id == 5
    await client.aclose()


async def test_create_work_package_resolves_project_by_display_name() -> None:
    """A representative write-path tool (create_work_package) resolving `project` by name."""
    search_handler = _projects_search_handler([{"id": 1, "name": "My Project", "identifier": "demo"}])

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/My Project":
            return httpx.Response(404, json={"message": "not found"}, request=request)
        if request.url.path == "/api/v3/projects" and request.method == "GET":
            return search_handler(request)
        if request.url.path in {"/api/v3/projects/1", "/api/v3/projects/demo"}:
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 1, "name": "My Project", "identifier": "demo", "_links": {}},
                request=request,
            )
        if request.url.path == "/api/v3/projects/1/types":
            return httpx.Response(
                200, json={"_embedded": {"elements": [{"id": 7, "name": "Feature"}]}}, request=request
            )
        if request.url.path == "/api/v3/projects/1/work_packages/form":
            body = json.loads(request.content)
            assert body["subject"] == "New idea"
            return _make_wp_form_response(request, body)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_base_settings(), transport=httpx.MockTransport(handler))
    result = await client.create_work_package(project="My Project", type="Feature", subject="New idea", confirm=False)
    assert result.ready
    await client.aclose()


async def test_create_work_package_by_display_name_still_enforces_write_allowlist() -> None:
    """Resolving `project` by name must apply _ensure_project_write_allowed, not just read."""
    search_handler = _projects_search_handler([{"id": 1, "name": "My Project", "identifier": "demo"}])

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/My Project":
            return httpx.Response(404, json={"message": "not found"}, request=request)
        if request.url.path == "/api/v3/projects" and request.method == "GET":
            return search_handler(request)
        if request.url.path == "/api/v3/projects/1":
            return httpx.Response(
                200,
                json={"_type": "Project", "id": 1, "name": "My Project", "identifier": "demo", "_links": {}},
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    # "demo" is readable (so the name search can find it) but not writable.
    settings = _base_settings(read_projects=("*",), write_projects=("other-project",))
    client = OpenProjectClient(settings, transport=httpx.MockTransport(handler))
    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await client.create_work_package(project="My Project", type="Feature", subject="New idea", confirm=False)
    await client.aclose()


async def test_get_project_ambiguous_when_two_projects_share_exact_name() -> None:
    """Two projects with the identical display name must not resolve silently."""
    search_handler = _projects_search_handler(
        [
            {"id": 5, "name": "Website", "identifier": "web-1"},
            {"id": 6, "name": "Website", "identifier": "web-2"},
        ]
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/Website":
            return httpx.Response(404, json={"message": "not found"}, request=request)
        if request.url.path == "/api/v3/projects" and request.method == "GET":
            return search_handler(request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_base_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(InvalidInputError, match="ambiguous"):
        await client.get_project("Website")
    await client.aclose()


async def test_get_project_not_found_when_no_name_match() -> None:
    search_handler = _projects_search_handler([])

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/Nonexistent":
            return httpx.Response(404, json={"message": "not found"}, request=request)
        if request.url.path == "/api/v3/projects" and request.method == "GET":
            return search_handler(request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_base_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(NotFoundError):
        await client.get_project("Nonexistent")
    await client.aclose()


async def test_get_project_resolves_exact_name_past_earlier_substring_matches() -> None:
    """Earlier substring-only hits must not short-circuit the scan before the exact match."""
    search_handler = _projects_search_handler(
        [
            {"id": 1, "name": "Website Redesign", "identifier": "web-redesign"},
            {"id": 2, "name": "Website Migration", "identifier": "web-migration"},
            {"id": 5, "name": "Website", "identifier": "web-1"},
        ]
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/Website":
            return httpx.Response(404, json={"message": "not found"}, request=request)
        if request.url.path == "/api/v3/projects" and request.method == "GET":
            return search_handler(request)
        if request.url.path == "/api/v3/projects/5":
            return _make_project_response(request, project_id=5)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_base_settings(), transport=httpx.MockTransport(handler))
    project = await client.get_project("Website")
    assert project.id == 5
    await client.aclose()


async def test_get_project_ambiguous_when_search_capped_before_exhaustion() -> None:
    """Hitting the page cap while still truncated must never fabricate uniqueness."""
    # 300 substring-only matches (none exact), far more than max_page_size(50) * the
    # search's page cap (5) can exhaust — every page stays truncated=True.
    matches = [{"id": i, "name": f"Website Clone {i}", "identifier": f"web-clone-{i}"} for i in range(300)]
    search_handler = _projects_search_handler(matches)

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/projects/Website":
            return httpx.Response(404, json={"message": "not found"}, request=request)
        if request.url.path == "/api/v3/projects" and request.method == "GET":
            return search_handler(request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = OpenProjectClient(_base_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(InvalidInputError, match="ambiguous"):
        await client.get_project("Website")
    await client.aclose()
