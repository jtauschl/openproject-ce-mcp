from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import NotFoundError, PermissionDeniedError
from openproject_ce_mcp.app.ports.category_api import CategoryRecord
from openproject_ce_mcp.app.services.category_service import CategoryService
from openproject_ce_mcp.models import CategorySummary
from openproject_ce_mcp.tools import _to_payload


def _summary(
    category_id: int = 1,
    *,
    project_id: int = 6,
    project: str = "Demo Project",
    name: str = "Bugs",
    default_assignee_id: int | None = 9,
    default_assignee: str | None = "Ada Lovelace",
) -> CategorySummary:
    return CategorySummary(
        id=category_id,
        name=name,
        project_id=project_id,
        project=project,
        is_default=False,
        url=f"https://op.example.com/api/v3/categories/{category_id}",
        default_assignee_id=default_assignee_id,
        default_assignee=default_assignee,
    )


def _record(**kwargs: object) -> CategoryRecord:
    return CategoryRecord(summary=_summary(**kwargs))  # type: ignore[arg-type]


class _FakeCategoryApi:
    def __init__(self, records: list[CategoryRecord] | None = None) -> None:
        self._records = records if records is not None else [_record()]
        self.list_for_project_calls: list[tuple[int, str | None]] = []

    async def list_for_project(self, project_id: int, *, project_name: str | None) -> list[CategoryRecord]:
        self.list_for_project_calls.append((project_id, project_name))
        return list(self._records)


async def _resolve_project_ref(project_ref: str, *, write: bool = False, context=None) -> dict:
    return {"id": 6, "identifier": project_ref, "name": "Demo Project", "_links": {}}


def _denying_resolve_project_ref(message: str):
    async def _resolve(project_ref: str, *, write: bool = False, context=None) -> dict:
        raise PermissionDeniedError(message)

    return _resolve


def _service(
    api: _FakeCategoryApi | None = None, *, settings=None, resolve_project_ref=_resolve_project_ref
) -> CategoryService:
    api = api or _FakeCategoryApi()
    return CategoryService(
        api=api,
        settings=settings or make_settings(),
        resolve_project_ref=resolve_project_ref,
    )


@pytest.mark.asyncio
async def test_list_returns_stamped_summaries() -> None:
    api = _FakeCategoryApi()
    service = _service(api)

    result = await service.list("demo")

    assert result.count == 1
    assert result.results[0].id == 1
    assert api.list_for_project_calls == [(6, "Demo Project")]


@pytest.mark.asyncio
async def test_list_applies_hidden_field_masking() -> None:
    # defaultAssignee is exposed as a HAL-link pair (id/name), same pattern as
    # parent_id/parent_name on Project. Respects OPENPROJECT_HIDE_CATEGORY_FIELDS.
    # Re-anchored here at the Service layer -- the pre-migration version of this
    # test lived in tests/unit/test_hidden_fields.py and called
    # client.normalize_category directly, which no longer exists post-migration.
    settings = dataclasses.replace(make_settings(), hidden_fields={"category": ("default_assignee",)})
    api = _FakeCategoryApi()
    service = _service(api, settings=settings)

    result = await service.list("demo")
    category = result.results[0]

    assert category._hidden_keys == frozenset({"default_assignee"})
    assert category.default_assignee == "Ada Lovelace"  # preserved on the dataclass
    assert category.default_assignee_id == 9
    serialized = _to_payload(category)
    assert "default_assignee" not in serialized
    assert serialized["default_assignee_id"] == 9


@pytest.mark.asyncio
async def test_default_assignee_hidden_by_category_scope_not_project_scope() -> None:
    """Regression test for the entity="category" vs "project" hide-field bug
    class (same bug class as the OPM-266 News hotfix and OPM-306's Documents/
    TimeEntry findings). client.py's original normalize_category already used
    the correct "category" entity string (verified against source before this
    migration), so this test only guards against a regression, not a fix.
    """
    settings_project_hidden = dataclasses.replace(make_settings(), hide_project_fields=("default_assignee",))
    service_project_hidden = _service(settings=settings_project_hidden)
    result_project_hidden = await service_project_hidden.list("demo")
    assert getattr(result_project_hidden.results[0], "_hidden_keys", frozenset()) == frozenset()

    settings_category_hidden = dataclasses.replace(make_settings(), hidden_fields={"category": ("default_assignee",)})
    service_category_hidden = _service(settings=settings_category_hidden)
    result_category_hidden = await service_category_hidden.list("demo")
    assert getattr(result_category_hidden.results[0], "_hidden_keys", frozenset()) == {"default_assignee"}


@pytest.mark.asyncio
async def test_list_propagates_project_read_allowlist_denial() -> None:
    """Categories has no per-record project link to check (established during
    the migration) -- the read allowlist is enforced entirely inside
    resolve_project_ref (the real _get_project_payload/ProjectResolver in
    production, already covered by its own tests). The Service's only
    obligation here is to propagate that denial, not re-implement the check.
    """
    api = _FakeCategoryApi()
    service = _service(api, resolve_project_ref=_denying_resolve_project_ref("OPENPROJECT_READ_PROJECTS"))

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await service.list("demo")

    assert api.list_for_project_calls == []


@pytest.mark.asyncio
async def test_list_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_project_read=False)
    api = _FakeCategoryApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.list("demo")

    assert api.list_for_project_calls == []


@pytest.mark.asyncio
async def test_list_passes_write_false_to_resolve_project_ref() -> None:
    """list() must ask its injected resolve_project_ref for a READ-checked
    (write=False) resolution -- found missing during this domain's own
    step-6 self-audit; no domain previously pinned the write=False argument
    on any read-path resolver call, only the write=True side (e.g.
    MembershipService's create()) was covered anywhere in this codebase.
    """
    calls: list[bool] = []

    async def resolve_project_ref_tracking_write(project_ref: str, *, write: bool = False, context=None) -> dict:
        calls.append(write)
        return await _resolve_project_ref(project_ref, write=write, context=context)

    api = _FakeCategoryApi()
    service = _service(api, resolve_project_ref=resolve_project_ref_tracking_write)

    await service.list("demo")

    assert calls == [False]


@pytest.mark.asyncio
async def test_get_returns_matching_category() -> None:
    api = _FakeCategoryApi(records=[_record(category_id=1), _record(category_id=2, name="Feature")])
    service = _service(api)

    result = await service.get(project_ref="demo", category_id=2)

    assert result.id == 2
    assert result.name == "Feature"


@pytest.mark.asyncio
async def test_get_raises_not_found_when_category_absent_from_project() -> None:
    api = _FakeCategoryApi(records=[_record(category_id=1)])
    service = _service(api)

    with pytest.raises(NotFoundError, match="category not found"):
        await service.get(project_ref="demo", category_id=999)


@pytest.mark.asyncio
async def test_get_delegates_the_read_allowlist_check_to_list() -> None:
    api = _FakeCategoryApi()
    service = _service(api, resolve_project_ref=_denying_resolve_project_ref("OPENPROJECT_READ_PROJECTS"))

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await service.get(project_ref="demo", category_id=1)
