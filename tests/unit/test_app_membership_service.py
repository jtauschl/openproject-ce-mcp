from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import InvalidInputError, PermissionDeniedError
from openproject_ce_mcp.app.ports.membership_api import MembershipFormResult, MembershipPage, MembershipRecord
from openproject_ce_mcp.app.services.membership_service import MembershipService
from openproject_ce_mcp.models import MembershipSummary, RoleListResult, RoleSummary

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


async def _list_roles() -> RoleListResult:
    return RoleListResult(count=1, results=[RoleSummary(id=1, name="Member", url=f"{BASE_URL}/roles/1")])


def _service(
    api: _FakeMembershipApi | None = None,
    *,
    settings=None,
    resolve_project_ref=_resolve_project_ref,
    resolve_principal_ref=_resolve_principal_ref,
    list_roles=_list_roles,
) -> MembershipService:
    api = api or _FakeMembershipApi()
    return MembershipService(
        api=api,
        settings=settings or make_settings(),
        project_id_to_identifier={},
        resolve_project_ref=resolve_project_ref,
        resolve_principal_ref=resolve_principal_ref,
        list_roles=list_roles,
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
    async def list_roles_with_duplicate() -> RoleListResult:
        return RoleListResult(
            count=2,
            results=[
                RoleSummary(id=1, name="Member", url=f"{BASE_URL}/roles/1"),
                RoleSummary(id=2, name="Member", url=f"{BASE_URL}/roles/2"),
            ],
        )

    api = _FakeMembershipApi()
    service = _service(api, list_roles=list_roles_with_duplicate)

    with pytest.raises(InvalidInputError, match="ambiguous"):
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
