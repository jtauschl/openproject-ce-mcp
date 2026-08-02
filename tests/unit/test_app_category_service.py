from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import NotFoundError, PermissionDeniedError
from openproject_ce_mcp.app.ports.category_api import CategoryRecord
from openproject_ce_mcp.app.services.category_service import CategoryService
from openproject_ce_mcp.models import CategorySummary
from openproject_ce_mcp.tools import _to_payload

PROJECT_ID_TO_IDENTIFIER = {6: "demo", 7: "other"}


def _summary(
    category_id: int = 1,
    *,
    project_id: int | None = 6,
    project: str | None = "Demo Project",
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


_DEFAULT_PROJECT_LINK = {"href": "/api/v3/projects/6", "title": "Demo Project"}


def _record(*, project_link: dict | None = None, **kwargs: object) -> CategoryRecord:
    if project_link is None:
        project_link = _DEFAULT_PROJECT_LINK
    return CategoryRecord(summary=_summary(**kwargs), project_link=project_link)  # type: ignore[arg-type]


class _FakeCategoryApi:
    def __init__(
        self, records: list[CategoryRecord] | None = None, *, by_id: dict[int, CategoryRecord] | None = None
    ) -> None:
        self._records = records if records is not None else [_record()]
        self._by_id = by_id if by_id is not None else {r.summary.id: r for r in self._records}
        self.list_for_project_calls: list[tuple[int, str | None]] = []
        self.get_calls: list[int] = []

    async def list_for_project(self, project_id: int, *, project_name: str | None) -> list[CategoryRecord]:
        self.list_for_project_calls.append((project_id, project_name))
        return list(self._records)

    async def get(self, category_id: int) -> CategoryRecord:
        self.get_calls.append(category_id)
        if category_id not in self._by_id:
            raise NotFoundError("OpenProject category not found.")
        return self._by_id[category_id]


async def _resolve_project_ref(project_ref: str, *, write: bool = False, context=None) -> dict:
    return {"id": 6, "identifier": project_ref, "name": "Demo Project", "_links": {}}


def _denying_resolve_project_ref(message: str):
    async def _resolve(project_ref: str, *, write: bool = False, context=None) -> dict:
        raise PermissionDeniedError(message)

    return _resolve


def _service(
    api: _FakeCategoryApi | None = None,
    *,
    settings=None,
    project_id_to_identifier: dict[int, str] | None = None,
    resolve_project_ref=_resolve_project_ref,
) -> CategoryService:
    api = api or _FakeCategoryApi()
    return CategoryService(
        api=api,
        settings=settings or make_settings(),
        project_id_to_identifier=project_id_to_identifier or PROJECT_ID_TO_IDENTIFIER,
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
    class (same bug class as the News hotfix and Documents'/
    TimeEntry's findings). client.py's original normalize_category already used
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
    """Categories' list() has no per-record project link to check -- the read
    allowlist is enforced entirely inside resolve_project_ref (the real
    _get_project_payload/ProjectResolver in production, already covered by
    its own tests). The Service's only obligation here is to propagate that
    denial, not re-implement the check.
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
    (write=False) resolution, not the write=True side (e.g.
    MembershipService's create() covers that side).
    """
    calls: list[bool] = []

    async def resolve_project_ref_tracking_write(project_ref: str, *, write: bool = False, context=None) -> dict:
        calls.append(write)
        return await _resolve_project_ref(project_ref, write=write, context=context)

    api = _FakeCategoryApi()
    service = _service(api, resolve_project_ref=resolve_project_ref_tracking_write)

    await service.list("demo")

    assert calls == [False]


# --- get -----------------------------------------------------------------
#
# OpenProject's v3 API has a real single-category GET, and an individual
# category payload carries its own project link (verified against
# OpenProject's own API implementation). get() calls
# CategoryApi.get() directly and checks the read allowlist against the
# category's REAL project_link, with project_ref as an optional additional
# cross-check rather than the sole source of authorization.


@pytest.mark.asyncio
async def test_get_calls_the_api_directly_not_list() -> None:
    api = _FakeCategoryApi(records=[_record(category_id=2, name="Feature")])
    service = _service(api)

    result = await service.get(category_id=2)

    assert result.id == 2
    assert result.name == "Feature"
    assert api.get_calls == [2]
    assert api.list_for_project_calls == []


@pytest.mark.asyncio
async def test_get_raises_not_found_when_category_does_not_exist() -> None:
    api = _FakeCategoryApi(records=[_record(category_id=1)])
    service = _service(api)

    with pytest.raises(NotFoundError):
        await service.get(category_id=999)


@pytest.mark.asyncio
async def test_get_checks_read_allowlist_against_the_categorys_real_project_link() -> None:
    api = _FakeCategoryApi(
        records=[_record(category_id=1, project_link={"href": "/api/v3/projects/7", "title": "Other"})]
    )
    settings = dataclasses.replace(make_settings(), read_projects=("demo",))
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await service.get(category_id=1)


@pytest.mark.asyncio
async def test_get_with_matching_project_ref_succeeds() -> None:
    api = _FakeCategoryApi(records=[_record(category_id=2, name="Feature", project_id=6)])
    service = _service(api)

    result = await service.get(category_id=2, project_ref="demo")

    assert result.id == 2


@pytest.mark.asyncio
async def test_get_with_mismatched_project_ref_raises_not_found() -> None:
    """project_ref, when given, is a cross-check against the category's real
    project -- a caller claiming the wrong project must not get the category
    back just because they can read it."""
    api = _FakeCategoryApi(records=[_record(category_id=2, project_id=6)])
    service = _service(api)

    async def resolve_other_project(project_ref: str, *, write: bool = False, context=None) -> dict:
        return {"id": 7, "identifier": project_ref, "name": "Other", "_links": {}}

    service = _service(api, resolve_project_ref=resolve_other_project)

    with pytest.raises(NotFoundError, match="category not found"):
        await service.get(category_id=2, project_ref="other")


@pytest.mark.asyncio
async def test_get_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_project_read=False)
    api = _FakeCategoryApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get(category_id=1)

    assert api.get_calls == []
