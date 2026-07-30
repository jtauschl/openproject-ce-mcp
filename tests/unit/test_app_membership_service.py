from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import InvalidInputError, PermissionDeniedError
from openproject_ce_mcp.app.ports.membership_api import MembershipFormResult, MembershipPage, MembershipRecord
from openproject_ce_mcp.app.ports.role_api import RoleRecord
from openproject_ce_mcp.app.services.membership_service import MembershipService
from openproject_ce_mcp.models import MembershipSummary, RoleSummary

BASE_URL = "https://op.example.com"


def _summary(
    membership_id: int = 1,
    *,
    project_id: int = 6,
    project_name: str = "Demo Project",
    principal_id: int = 9,
    principal_name: str = "Ada Lovelace",
    role_names: list[str] | None = None,
) -> MembershipSummary:
    return MembershipSummary(
        id=membership_id,
        principal_id=principal_id,
        principal_name=principal_name,
        project_id=project_id,
        project_name=project_name,
        role_ids=[1],
        role_names=role_names or ["Member"],
        can_update=True,
        can_update_immediately=False,
        url=f"{BASE_URL}/memberships/{membership_id}",
    )


def _record(**kwargs: object) -> MembershipRecord:
    summary = _summary(**kwargs)  # type: ignore[arg-type]
    return MembershipRecord(summary=summary, project_link={"href": f"/api/v3/projects/{summary.project_id}"})


class _FakeMembershipApi:
    def __init__(self, records: list[MembershipRecord] | None = None) -> None:
        self._records = {r.summary.id: r for r in (records or [_record()])}
        self.list_calls: list[tuple[str, int, int]] = []
        self.get_calls: list[int] = []
        self.create_form_calls: list[dict] = []
        self.update_form_calls: list[tuple[int, dict]] = []
        self.commit_create_calls: list[dict] = []
        self.commit_update_calls: list[tuple[int, dict]] = []
        self.delete_calls: list[int] = []
        self.validation_errors: dict[str, str] = {}
        self.commit_result_project_name: str = "Demo Project"

    async def list_for_project(self, project_memberships_href: str, *, offset: int, page_size: int) -> MembershipPage:
        self.list_calls.append((project_memberships_href, offset, page_size))
        records = list(self._records.values())
        return MembershipPage(records=records, server_total=len(records))

    async def get(self, membership_id: int) -> MembershipRecord:
        self.get_calls.append(membership_id)
        if membership_id not in self._records:
            raise AssertionError(f"no fake record for membership_id {membership_id}")
        return self._records[membership_id]

    async def create_form(self, payload: dict) -> MembershipFormResult:
        self.create_form_calls.append(payload)
        return MembershipFormResult(payload=payload, validation_errors=self.validation_errors)

    async def update_form(self, membership_id: int, payload: dict) -> MembershipFormResult:
        self.update_form_calls.append((membership_id, payload))
        return MembershipFormResult(payload=payload, validation_errors=self.validation_errors)

    async def commit_create(self, payload: dict) -> MembershipSummary:
        self.commit_create_calls.append(payload)
        return _summary(membership_id=42, project_name=self.commit_result_project_name)

    async def commit_update(self, membership_id: int, payload: dict) -> MembershipSummary:
        self.commit_update_calls.append((membership_id, payload))
        return _summary(membership_id=membership_id, project_name=self.commit_result_project_name)

    async def delete(self, membership_id: int) -> None:
        self.delete_calls.append(membership_id)


async def _resolve_project_ref(project_ref: str, *, write: bool = False, context=None) -> dict:
    return {
        "id": 6,
        "identifier": project_ref,
        "name": "Demo Project",
        "_links": {
            "memberships": {
                "href": "/api/v3/memberships?filters=%5B%7B%22project%22%3A%7B%22operator%22%3A%22%3D%22%2C%22values%22%3A%5B%226%22%5D%7D%7D%5D"
            }
        },
    }


async def _resolve_principal_ref(principal_ref: str) -> str:
    return "9"


class _FakeRoleApi:
    def __init__(self, records: list[RoleRecord] | None = None) -> None:
        self._records = records or [RoleRecord(summary=RoleSummary(id=1, name="Member", url=f"{BASE_URL}/roles/1"))]
        self.list_calls: list[tuple[int, int]] = []

    async def list_roles(self, *, offset: int, page_size: int) -> tuple[list[RoleRecord], int]:
        self.list_calls.append((offset, page_size))
        start = (offset - 1) * page_size
        end = start + page_size
        return self._records[start:end], len(self._records)


def _service(
    api: _FakeMembershipApi | None = None,
    *,
    settings=None,
    resolve_project_ref=_resolve_project_ref,
    resolve_principal_ref=_resolve_principal_ref,
    role_api: _FakeRoleApi | None = None,
) -> MembershipService:
    api = api or _FakeMembershipApi()
    return MembershipService(
        api=api,
        settings=settings or make_settings(),
        project_id_to_identifier={},
        resolve_project_ref=resolve_project_ref,
        resolve_principal_ref=resolve_principal_ref,
        role_api=role_api or _FakeRoleApi(),
        api_prefix="/api/v3/",
    )


@pytest.mark.asyncio
async def test_list_for_project_returns_stamped_summaries() -> None:
    api = _FakeMembershipApi()
    service = _service(api)

    result = await service.list_for_project("demo")

    assert result.count == 1
    assert result.results[0].id == 1
    assert len(api.list_calls) == 1


@pytest.mark.asyncio
async def test_list_for_project_returns_empty_result_without_http_call_when_href_missing() -> None:
    async def resolve_no_memberships_link(project_ref: str, *, write: bool = False, context=None) -> dict:
        return {"id": 6, "identifier": project_ref, "name": "Demo Project", "_links": {}}

    api = _FakeMembershipApi()
    service = _service(api, resolve_project_ref=resolve_no_memberships_link)

    result = await service.list_for_project("demo")

    assert result == type(result)(offset=1, limit=20, total=0, count=0, next_offset=None, truncated=False, results=[])
    assert api.list_calls == []


@pytest.mark.asyncio
async def test_get_applies_hidden_field_masking() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"membership": ("principal_name",)})
    api = _FakeMembershipApi()
    service = _service(api, settings=settings)

    result = await service.get(1)

    assert getattr(result, "_hidden_keys", frozenset()) == {"principal_name"}
    assert api.get_calls == [1]


@pytest.mark.asyncio
async def test_get_checks_project_read_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    api = _FakeMembershipApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await service.get(1)


@pytest.mark.asyncio
async def test_get_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_membership_read=False)
    api = _FakeMembershipApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get(1)

    assert api.get_calls == []


@pytest.mark.asyncio
async def test_list_for_project_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_membership_read=False)
    api = _FakeMembershipApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.list_for_project("demo")

    assert api.list_calls == []


@pytest.mark.asyncio
async def test_list_for_project_propagates_project_read_allowlist_denial() -> None:
    """list_for_project() resolves the project via resolve_project_ref before
    fetching -- the read allowlist is enforced entirely inside that resolver
    (the real _get_project_payload/ProjectResolver in production), same as
    Categories' list(). This gap (list_for_project had no allowlist-denial
    test, unlike get()'s test_get_checks_project_read_allowlist above) was
    found during Categories' step-6 cross-domain self-audit.
    """

    async def denying_resolve_project_ref(project_ref: str, *, write: bool = False, context=None) -> dict:
        raise PermissionDeniedError("OPENPROJECT_READ_PROJECTS")

    api = _FakeMembershipApi()
    service = _service(api, resolve_project_ref=denying_resolve_project_ref)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await service.list_for_project("demo")

    assert api.list_calls == []


@pytest.mark.asyncio
async def test_list_for_project_passes_write_false_to_resolve_project_ref() -> None:
    """list_for_project() must ask its injected resolve_project_ref for a
    READ-checked (write=False) resolution, mirroring create()'s existing
    test_create_passes_write_true_to_resolve_project_ref pin for the write
    side below. Found missing during Categories' step-6 cross-domain
    self-audit -- no domain previously pinned the write=False argument on
    any read-path resolver call, only the write=True side was covered.
    """
    calls: list[bool] = []

    async def resolve_project_ref_tracking_write(project_ref: str, *, write: bool = False, context=None) -> dict:
        calls.append(write)
        return await _resolve_project_ref(project_ref, write=write, context=context)

    api = _FakeMembershipApi()
    service = _service(api, resolve_project_ref=resolve_project_ref_tracking_write)

    await service.list_for_project("demo")

    assert calls == [False]


@pytest.mark.asyncio
async def test_get_created_at_hidden_by_membership_scope_not_project_scope() -> None:
    """Regression test for the entity-scope class of bug found via News'
    OPM-266 hotfix and Documents' equivalent: a field must only be masked by
    its OWN domain's OPENPROJECT_HIDE_<ENTITY>_FIELDS scope, never by a
    same-named field under a different (e.g. project) scope.
    """
    settings_project_hidden = dataclasses.replace(make_settings(), hide_project_fields=("created_at",))
    api_project_hidden = _FakeMembershipApi()
    service_project_hidden = _service(api_project_hidden, settings=settings_project_hidden)
    result_project_hidden = await service_project_hidden.get(1)
    assert getattr(result_project_hidden, "_hidden_keys", frozenset()) == frozenset()

    settings_membership_hidden = dataclasses.replace(make_settings(), hidden_fields={"membership": ("created_at",)})
    api_membership_hidden = _FakeMembershipApi()
    service_membership_hidden = _service(api_membership_hidden, settings=settings_membership_hidden)
    result_membership_hidden = await service_membership_hidden.get(1)
    assert getattr(result_membership_hidden, "_hidden_keys", frozenset()) == {"created_at"}


@pytest.mark.asyncio
async def test_create_returns_preview_without_committing() -> None:
    api = _FakeMembershipApi()
    service = _service(api)

    result = await service.create(project="demo", principal="me", roles=["Member"], confirm=False)

    assert result.requires_confirmation is True
    assert result.confirmed is False
    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_preview_trims_project_name_to_subject_limit() -> None:
    """Regression: the pre-migration original capped the preview's project
    name at SUBJECT_LIMIT (`_trim_text(project_payload.get("name"),
    limit=SUBJECT_LIMIT)`) -- a prior port returned the raw, untrimmed name
    in the confirm=False preview response instead."""
    api = _FakeMembershipApi()
    long_name = "x" * 300

    async def resolve_project_ref_long_name(project_ref: str, *, write: bool = False, context=None) -> dict:
        return {**await _resolve_project_ref(project_ref, write=write, context=context), "name": long_name}

    service = _service(api, resolve_project_ref=resolve_project_ref_long_name)

    result = await service.create(project="demo", principal="me", roles=["Member"], confirm=False)

    assert result.project is not None
    assert len(result.project) <= 255


@pytest.mark.asyncio
async def test_create_passes_write_true_to_resolve_project_ref() -> None:
    """create() must ask its injected resolve_project_ref for a WRITE-checked
    resolution (write=True), not a read-only one -- the actual write-
    allowlist enforcement for create() lives inside the real
    _get_project_payload/ProjectResolver.resolve_record (see
    project_resolver.py's `if write: ensure_project_write_allowed(...)`),
    not inside MembershipService itself, so this only pins the contract at
    the seam; the enforcement itself is covered by
    test_project_resolution.py's "membership-write_denied" policy-matrix
    case against the real client.
    """
    write_flags: list[bool] = []

    async def resolve_project_ref_tracking_write(project_ref: str, *, write: bool = False, context=None) -> dict:
        write_flags.append(write)
        return await _resolve_project_ref(project_ref, write=write, context=context)

    api = _FakeMembershipApi()
    service = _service(api, resolve_project_ref=resolve_project_ref_tracking_write)

    await service.create(project="demo", principal="me", roles=["Member"], confirm=True)

    assert write_flags == [True]


@pytest.mark.asyncio
async def test_create_passes_the_actual_principal_ref_to_resolve_principal_ref() -> None:
    """create() must forward the caller-supplied principal reference to
    resolve_principal_ref verbatim, not some transformed/default value --
    pins the seam's actual argument, matching the resolve_project_ref
    argument-correctness tests above for the same domain."""
    principal_refs: list[str] = []

    async def resolve_principal_ref_tracking(principal_ref: str) -> str:
        principal_refs.append(principal_ref)
        return await _resolve_principal_ref(principal_ref)

    api = _FakeMembershipApi()
    service = _service(api, resolve_principal_ref=resolve_principal_ref_tracking)

    await service.create(project="demo", principal="me", roles=["Member"], confirm=True)

    assert principal_refs == ["me"]


@pytest.mark.asyncio
async def test_create_commits_and_stamps_hidden_fields_when_confirmed() -> None:
    # created_at is hidden here rather than a field create() itself writes
    # (project_name/principal_name/role_names) -- hiding one of those would be
    # rejected by ensure_field_writable() before the commit even happens,
    # which tests a different code path (see test_create_rejects_when_hidden_
    # field_is_being_written below).
    settings = dataclasses.replace(make_settings(), hidden_fields={"membership": ("created_at",)})
    api = _FakeMembershipApi()
    service = _service(api, settings=settings)

    result = await service.create(project="demo", principal="me", roles=["Member"], confirm=True)

    assert result.confirmed is True
    assert len(api.commit_create_calls) == 1
    assert result.result is not None
    assert getattr(result.result, "_hidden_keys", frozenset()) == {"created_at"}


@pytest.mark.asyncio
async def test_create_rejects_when_hidden_field_is_being_written() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"membership": ("principal_name",)})
    api = _FakeMembershipApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.create(project="demo", principal="me", roles=["Member"], confirm=True)

    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_rejects_when_validation_errors_present() -> None:
    api = _FakeMembershipApi()
    api.validation_errors = {"roles": "is invalid"}
    service = _service(api)

    result = await service.create(project="demo", principal="me", roles=["Member"], confirm=True)

    assert result.ready is False
    assert result.result is None


@pytest.mark.asyncio
async def test_create_role_not_found_raises() -> None:
    api = _FakeMembershipApi()
    service = _service(api)

    with pytest.raises(InvalidInputError, match="was not found"):
        await service.create(project="demo", principal="me", roles=["NoSuchRole"], confirm=False)


@pytest.mark.asyncio
async def test_create_role_ambiguous_raises() -> None:
    role_api = _FakeRoleApi(
        records=[
            RoleRecord(summary=RoleSummary(id=1, name="Member", url=f"{BASE_URL}/roles/1")),
            RoleRecord(summary=RoleSummary(id=2, name="Member", url=f"{BASE_URL}/roles/2")),
        ]
    )
    api = _FakeMembershipApi()
    service = _service(api, role_api=role_api)

    with pytest.raises(InvalidInputError, match="ambiguous"):
        await service.create(project="demo", principal="me", roles=["Member"], confirm=False)


@pytest.mark.asyncio
async def test_create_role_lookup_calls_role_api_once_not_page_walking() -> None:
    """Regression test (found via an independent Codex review): _resolve_role_hrefs
    must call RoleApi.list_roles ONCE, not page-walk via app.pagination.paginate_all
    -- /api/v3/roles' RoleCollectionRepresenter is a real UnpaginatedCollection
    (OPM-324), so the server ignores offset/pageSize and always returns the
    complete collection in a single response. Feeding that into paginate_all
    (which assumes a genuinely server-paginated fetcher) misreads
    `total > page_size` as "more pages exist" and duplicates every record --
    an earlier version of this method did exactly that. The fake here mirrors
    the real API's actual behavior (always returns everything, regardless of
    offset/page_size), unlike a genuinely paginated fake -- this pins the real
    bug, not a page-walk that shouldn't happen at all.
    """
    role_api = _FakeRoleApi(
        records=[
            RoleRecord(summary=RoleSummary(id=1, name="Reader", url=f"{BASE_URL}/roles/1")),
            RoleRecord(summary=RoleSummary(id=2, name="Member", url=f"{BASE_URL}/roles/2")),
        ]
    )
    settings = dataclasses.replace(make_settings(), default_page_size=1, max_page_size=1)
    api = _FakeMembershipApi()
    service = _service(api, settings=settings, role_api=role_api)

    result = await service.create(project="demo", principal="me", roles=["Member"], confirm=True)

    assert result.confirmed is True
    assert len(role_api.list_calls) == 1


@pytest.mark.asyncio
async def test_create_role_lookup_uses_max_results_not_max_page_size() -> None:
    """_resolve_role_hrefs's single call must ask for page_size=max_results
    (matching RoleService.list_roles' OPM-324 pattern: fetch everything in
    one call, bounded by max_results, not max_page_size), since the server
    ignores this value's exact size anyway but a stale max_page_size-sized
    request would (incorrectly, per the fix above) look like a page walk
    is needed."""
    role_api = _FakeRoleApi(records=[RoleRecord(summary=RoleSummary(id=1, name="Member", url=f"{BASE_URL}/roles/1"))])
    settings = dataclasses.replace(make_settings(), default_page_size=1, max_page_size=20, max_results=100)
    api = _FakeMembershipApi()
    service = _service(api, settings=settings, role_api=role_api)

    await service.create(project="demo", principal="me", roles=["Member"], confirm=True)

    assert role_api.list_calls == [(1, 100)]


@pytest.mark.asyncio
async def test_create_with_numeric_role_id_skips_the_role_list_fetch() -> None:
    """Efficiency regression test, found during the 19th (Extended Metadata)
    domain's step-6 self-audit: the full role-collection page-walk is only
    needed to resolve a BY-NAME reference. When every role ref is already a
    numeric id (the common case), _resolve_role_hrefs must not fetch the
    role collection at all -- it previously did, unconditionally, wasting a
    round trip whose result was never used.
    """
    role_api = _FakeRoleApi()
    api = _FakeMembershipApi()
    service = _service(api, role_api=role_api)

    result = await service.create(project="demo", principal="me", roles=["8"], confirm=True)

    assert result.confirmed is True
    assert role_api.list_calls == []


@pytest.mark.asyncio
async def test_create_with_mixed_numeric_and_named_roles_still_fetches_once() -> None:
    """A mix of numeric and by-name refs must still trigger exactly one
    page-walk (for the by-name ref), not skip it entirely."""
    role_api = _FakeRoleApi(records=[RoleRecord(summary=RoleSummary(id=2, name="Member", url=f"{BASE_URL}/roles/2"))])
    api = _FakeMembershipApi()
    service = _service(api, role_api=role_api)

    result = await service.create(project="demo", principal="me", roles=["8", "Member"], confirm=True)

    assert result.confirmed is True
    assert len(role_api.list_calls) == 1


@pytest.mark.asyncio
async def test_create_role_lookup_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_membership_read=False)
    role_api = _FakeRoleApi()
    api = _FakeMembershipApi()
    service = _service(api, settings=settings, role_api=role_api)

    with pytest.raises(PermissionDeniedError):
        await service.create(project="demo", principal="me", roles=["Member"], confirm=False)

    assert role_api.list_calls == []


@pytest.mark.asyncio
async def test_create_role_lookup_propagates_role_api_failure() -> None:
    class _FailingRoleApi:
        async def list_roles(self, *, offset: int, page_size: int) -> tuple[list, int]:
            raise RuntimeError("role listing unavailable")

    api = _FakeMembershipApi()
    service = _service(api, role_api=_FailingRoleApi())

    with pytest.raises(RuntimeError, match="role listing unavailable"):
        await service.create(project="demo", principal="me", roles=["Member"], confirm=False)


@pytest.mark.asyncio
async def test_update_commits_and_stamps_when_confirmed() -> None:
    # created_at is hidden here rather than role_names (which update() itself
    # writes and would be rejected by ensure_field_writable() before the
    # commit -- a different code path, not the masking-of-the-result path
    # this test targets).
    settings = dataclasses.replace(make_settings(), hidden_fields={"membership": ("created_at",)})
    api = _FakeMembershipApi()
    service = _service(api, settings=settings)

    result = await service.update(membership_id=1, roles=["Member"], confirm=True)

    assert result.confirmed is True
    assert api.commit_update_calls == [(1, {"_links": {"roles": [{"href": "/api/v3/roles/1"}]}})]
    assert getattr(result.result, "_hidden_keys", frozenset()) == {"created_at"}


@pytest.mark.asyncio
async def test_update_checks_project_write_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("other",))
    api = _FakeMembershipApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await service.update(membership_id=1, roles=["Member"], confirm=False)

    assert api.commit_update_calls == []


@pytest.mark.asyncio
async def test_delete_checks_project_write_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("other",))
    api = _FakeMembershipApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await service.delete(membership_id=1, confirm=False)

    assert api.delete_calls == []


@pytest.mark.asyncio
async def test_delete_preview_returns_result_none_and_does_not_call_delete() -> None:
    api = _FakeMembershipApi()
    service = _service(api)

    preview = await service.delete(membership_id=1, confirm=False)

    assert preview.confirmed is False
    assert preview.requires_confirmation is True
    assert preview.result is None
    assert api.delete_calls == []


@pytest.mark.asyncio
async def test_delete_commits_and_stamps_result_when_confirmed() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"membership": ("principal_name",)})
    api = _FakeMembershipApi()
    service = _service(api, settings=settings)

    committed = await service.delete(membership_id=1, confirm=True)

    assert committed.confirmed is True
    assert api.delete_calls == [1]
    assert committed.result is not None
    assert getattr(committed.result, "_hidden_keys", frozenset()) == {"principal_name"}
