from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import InvalidInputError, PermissionDeniedError
from openproject_ce_mcp.app.ports.group_api import GroupRecord
from openproject_ce_mcp.app.services.group_service import GroupService
from openproject_ce_mcp.models import GroupDetail, GroupSummary
from openproject_ce_mcp.tools import _to_payload

BASE_URL = "https://op.example.com"
API_PREFIX = "/api/v3/"


def _summary(group_id: int = 3, *, name: str = "Backend", member_count: int = 2) -> GroupSummary:
    return GroupSummary(
        id=group_id,
        name=name,
        member_count=member_count,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-06-01T00:00:00Z",
        can_update=True,
        can_delete=True,
        url=f"{BASE_URL}/groups/{group_id}",
    )


def _detail(group_id: int = 3, **kwargs: object) -> GroupDetail:
    summary = _summary(group_id, **kwargs)  # type: ignore[arg-type]
    return GroupDetail(
        id=summary.id,
        name=summary.name,
        member_count=summary.member_count,
        members=["Ada Lovelace", "Bob Builder"],
        memberships_url=f"{BASE_URL}/memberships",
        created_at=summary.created_at,
        updated_at=summary.updated_at,
        can_update=summary.can_update,
        can_delete=summary.can_delete,
        url=summary.url,
    )


def _record(**kwargs: object) -> GroupRecord:
    detail = _detail(**kwargs)  # type: ignore[arg-type]
    return GroupRecord(summary=_summary(**kwargs), to_detail=lambda: detail)  # type: ignore[arg-type]


class _FakeGroupApi:
    def __init__(self, records: list[GroupRecord] | None = None, *, member_ids: set[int] | None = None) -> None:
        self._records = {r.summary.id: r for r in (records or [_record()])}
        self._member_ids = member_ids if member_ids is not None else {1, 2}
        self.list_groups_calls: list[tuple[int, int]] = []
        self.list_groups_search_calls: list[int] = []
        self.get_group_calls: list[int] = []
        self.get_member_ids_calls: list[int] = []
        self.commit_create_calls: list[dict] = []
        self.commit_update_calls: list[tuple[int, dict]] = []
        self.commit_delete_calls: list[int] = []

    async def list_groups(self, *, offset: int, page_size: int) -> tuple[list[GroupRecord], int]:
        self.list_groups_calls.append((offset, page_size))
        records = list(self._records.values())
        return records, len(records)

    async def list_groups_search(self, *, page_size: int) -> list[GroupRecord]:
        self.list_groups_search_calls.append(page_size)
        return list(self._records.values())

    async def get_group(self, group_id: int) -> GroupRecord:
        self.get_group_calls.append(group_id)
        record = self._records.get(group_id)
        if record is None:
            raise AssertionError(f"no fake record for group_id {group_id}")
        return record

    async def get_member_ids(self, group_id: int) -> set[int]:
        self.get_member_ids_calls.append(group_id)
        return set(self._member_ids)

    async def commit_create(self, payload: dict) -> GroupSummary:
        self.commit_create_calls.append(payload)
        return _summary(group_id=42)

    async def commit_update(self, group_id: int, payload: dict) -> GroupSummary:
        self.commit_update_calls.append((group_id, payload))
        return _summary(group_id=group_id)

    async def commit_delete(self, group_id: int) -> None:
        self.commit_delete_calls.append(group_id)


def _admin_settings(**overrides: object):
    # admin read/write both default False (config.py) -- unlike most other
    # scopes, so every positive-path test needs enable_admin_read=True
    # explicitly, not just make_settings()'s permissive project scope.
    return dataclasses.replace(make_settings(), enable_admin_read=True, **overrides)


def _admin_write_settings(**overrides: object):
    return _admin_settings(enable_admin_write=True, **overrides)


def _service(api: _FakeGroupApi | None = None, *, settings=None) -> GroupService:
    return GroupService(api=api or _FakeGroupApi(), settings=settings or _admin_settings(), api_prefix=API_PREFIX)


# --- list_groups ---------------------------------------------------------


@pytest.mark.asyncio
async def test_list_groups_returns_stamped_summaries() -> None:
    api = _FakeGroupApi()
    service = _service(api)

    result = await service.list_groups()

    assert result.count == 1
    assert result.results[0].id == 3
    assert result.results[0].name == "Backend"
    assert api.list_groups_calls == [(1, make_settings().default_page_size)]
    assert api.list_groups_search_calls == []


@pytest.mark.asyncio
async def test_list_groups_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_admin_read=False)
    api = _FakeGroupApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.list_groups()

    assert api.list_groups_calls == []
    assert api.list_groups_search_calls == []


@pytest.mark.asyncio
async def test_list_groups_applies_hidden_field_masking() -> None:
    settings = _admin_settings(hidden_fields={"group": ("member_count",)})
    api = _FakeGroupApi()
    service = _service(api, settings=settings)

    result = await service.list_groups()
    group = result.results[0]

    assert group._hidden_keys == frozenset({"member_count"})
    serialized = _to_payload(group)
    assert "member_count" not in serialized
    assert serialized["id"] == 3


@pytest.mark.asyncio
async def test_list_groups_search_overfetches_and_filters_then_paginates() -> None:
    records = [
        _record(group_id=1, name="Backend"),
        _record(group_id=2, name="Frontend"),
        _record(group_id=3, name="Backend Ops"),
    ]
    api = _FakeGroupApi(records)
    service = _service(api)

    result = await service.list_groups(search="back", limit=1, offset=2)

    # 2 survivors match "back" (Backend, Backend Ops); page 2 with limit=1 is the 2nd survivor.
    assert result.total == 2
    assert result.count == 1
    assert result.results[0].name == "Backend Ops"
    assert api.list_groups_search_calls == [make_settings().max_results]
    assert api.list_groups_calls == []


@pytest.mark.asyncio
async def test_list_groups_search_matches_name_case_insensitively() -> None:
    records = [_record(group_id=1, name="BACKEND")]
    api = _FakeGroupApi(records)
    service = _service(api)

    result = await service.list_groups(search="backend")

    assert result.count == 1


# --- get_group -------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_group_returns_stamped_detail() -> None:
    api = _FakeGroupApi()
    service = _service(api)

    detail = await service.get_group(3)

    assert detail.id == 3
    assert detail.name == "Backend"
    assert api.get_group_calls == [3]


@pytest.mark.asyncio
async def test_get_group_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_admin_read=False)
    api = _FakeGroupApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get_group(3)

    assert api.get_group_calls == []


# --- create ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_returns_preview_without_committing() -> None:
    # Preview still requires admin write enabled: create_group's
    # write-enablement check runs unconditionally, before the confirm
    # branch, verbatim port of client.py's own behavior.
    api = _FakeGroupApi()
    service = _service(api, settings=_admin_write_settings())

    result = await service.create(name="Backend")

    assert result.confirmed is False
    assert result.requires_confirmation is True
    assert result.result is None
    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_commits_when_confirmed_and_admin_write_enabled() -> None:
    api = _FakeGroupApi()
    service = _service(api, settings=_admin_write_settings())

    result = await service.create(name="Backend", confirm=True)

    assert result.confirmed is True
    assert result.group_id == 42
    assert api.commit_create_calls == [{"name": "Backend"}]
    assert result.payload == {"name": "Backend", "user_ids": []}


@pytest.mark.asyncio
async def test_create_builds_member_links_when_user_ids_given() -> None:
    api = _FakeGroupApi()
    service = _service(api, settings=_admin_write_settings())

    result = await service.create(name="Backend", user_ids=[5, 6], confirm=True)

    assert result.confirmed is True
    assert api.commit_create_calls == [
        {"name": "Backend", "_links": {"members": [{"href": "/api/v3/users/5"}, {"href": "/api/v3/users/6"}]}}
    ]
    assert result.payload == {"name": "Backend", "user_ids": [5, 6]}


@pytest.mark.asyncio
async def test_create_confirm_denied_without_admin_write_enabled() -> None:
    api = _FakeGroupApi()
    service = _service(api)  # admin_write defaults False

    with pytest.raises(PermissionDeniedError):
        await service.create(name="Backend", confirm=True)

    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_preview_also_denied_without_admin_write_enabled() -> None:
    # Verbatim port of client.py's unconditional _ensure_write_enabled check
    # -- even a pure preview (confirm=False) is rejected.
    api = _FakeGroupApi()
    service = _service(api)

    with pytest.raises(PermissionDeniedError):
        await service.create(name="Backend", confirm=False)

    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_rejects_when_name_field_is_hidden() -> None:
    settings = dataclasses.replace(_admin_write_settings(), hidden_fields={"group": ("name",)})
    api = _FakeGroupApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.create(name="Backend", confirm=True)

    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_rejects_when_members_field_is_hidden() -> None:
    settings = dataclasses.replace(_admin_write_settings(), hidden_fields={"group": ("members",)})
    api = _FakeGroupApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.create(name="Backend", user_ids=[5], confirm=True)

    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_does_not_check_members_hidden_when_no_user_ids_given() -> None:
    settings = dataclasses.replace(_admin_write_settings(), hidden_fields={"group": ("members",)})
    api = _FakeGroupApi()
    service = _service(api, settings=settings)

    result = await service.create(name="Backend", confirm=True)

    assert result.confirmed is True


# --- update ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_commits_when_confirmed() -> None:
    api = _FakeGroupApi()
    service = _service(api, settings=_admin_write_settings())

    result = await service.update(3, name="Backend Team", confirm=True)

    assert result.confirmed is True
    assert result.group_id == 3
    assert api.commit_update_calls == [(3, {"name": "Backend Team"})]
    assert api.get_member_ids_calls == []


@pytest.mark.asyncio
async def test_update_confirm_denied_without_admin_write_enabled() -> None:
    api = _FakeGroupApi()
    service = _service(api)

    with pytest.raises(PermissionDeniedError):
        await service.update(3, name="Backend Team", confirm=True)

    assert api.commit_update_calls == []


@pytest.mark.asyncio
async def test_update_preview_also_denied_without_admin_write_enabled() -> None:
    # Same unconditional-check tradeoff as create(): update() has a prior GET
    # for the member diff but the write-enablement check still runs before
    # it and before the confirm branch, so even a preview is rejected.
    api = _FakeGroupApi()
    service = _service(api)

    with pytest.raises(PermissionDeniedError):
        await service.update(3, add_user_ids=[7], confirm=False)

    assert api.get_member_ids_calls == []
    assert api.commit_update_calls == []


@pytest.mark.asyncio
async def test_update_member_diff_adds_and_removes_against_current_members() -> None:
    api = _FakeGroupApi(member_ids={1, 2, 3})
    service = _service(api, settings=_admin_write_settings())

    result = await service.update(3, add_user_ids=[4], remove_user_ids=[2], confirm=True)

    assert result.confirmed is True
    assert api.get_member_ids_calls == [3]
    assert api.commit_update_calls == [
        (
            3,
            {
                "_links": {
                    "members": [
                        {"href": "/api/v3/users/1"},
                        {"href": "/api/v3/users/3"},
                        {"href": "/api/v3/users/4"},
                    ]
                }
            },
        )
    ]
    assert result.payload == {"add_user_ids": [4], "remove_user_ids": [2]}


@pytest.mark.asyncio
async def test_update_member_diff_preview_reflects_current_members_without_committing() -> None:
    # The GET-and-diff happens even on the preview branch (outside `if not
    # confirm`), so the preview accurately reflects the resulting
    # membership -- verbatim port of client.py's update_group.
    api = _FakeGroupApi(member_ids={1, 2})
    service = _service(api, settings=_admin_write_settings())

    result = await service.update(3, add_user_ids=[9], confirm=False)

    assert result.confirmed is False
    assert api.get_member_ids_calls == [3]
    assert api.commit_update_calls == []


@pytest.mark.asyncio
async def test_update_rejects_when_name_field_is_hidden() -> None:
    settings = dataclasses.replace(_admin_write_settings(), hidden_fields={"group": ("name",)})
    api = _FakeGroupApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.update(3, name="Backend Team", confirm=True)

    assert api.commit_update_calls == []


@pytest.mark.asyncio
async def test_update_rejects_when_members_field_is_hidden() -> None:
    settings = dataclasses.replace(_admin_write_settings(), hidden_fields={"group": ("members",)})
    api = _FakeGroupApi()
    service = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden by"):
        await service.update(3, add_user_ids=[5], confirm=True)

    assert api.commit_update_calls == []


@pytest.mark.asyncio
async def test_update_does_not_check_fields_the_caller_did_not_set() -> None:
    # A field hidden in config but NOT part of this update call must not
    # block it -- only fields actually present in the call are checked.
    settings = dataclasses.replace(_admin_write_settings(), hidden_fields={"group": ("members",)})
    api = _FakeGroupApi()
    service = _service(api, settings=settings)

    result = await service.update(3, name="Backend Team", confirm=True)

    assert result.confirmed is True
    assert api.commit_update_calls == [(3, {"name": "Backend Team"})]


# --- delete ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_denies_target_outside_admin_write_and_never_calls_commit() -> None:
    api = _FakeGroupApi()
    service = _service(api)  # admin_write defaults False

    with pytest.raises(PermissionDeniedError):
        await service.delete(3, confirm=True)

    assert api.commit_delete_calls == []


@pytest.mark.asyncio
async def test_delete_preview_does_not_call_commit() -> None:
    api = _FakeGroupApi()
    service = _service(api, settings=_admin_write_settings())

    result = await service.delete(3, confirm=False)

    assert result.confirmed is False
    assert result.requires_confirmation is True
    assert result.result is None
    assert api.commit_delete_calls == []


@pytest.mark.asyncio
async def test_delete_commits_when_confirmed_with_no_result() -> None:
    api = _FakeGroupApi()
    service = _service(api, settings=_admin_write_settings())

    result = await service.delete(3, confirm=True)

    assert result.confirmed is True
    assert result.group_id == 3
    assert result.result is None
    assert api.commit_delete_calls == [3]
