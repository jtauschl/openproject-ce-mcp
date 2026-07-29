from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import InvalidInputError, OpenProjectServerError, PermissionDeniedError
from openproject_ce_mcp.app.ports.relation_api import RelationRecord
from openproject_ce_mcp.app.services.relation_service import RelationService
from openproject_ce_mcp.models import RelationSummary

PROJECT_ID_TO_IDENTIFIER = {1: "demo", 20: "other"}


def _summary(
    relation_id: int = 7,
    *,
    relation_type: str = "blocks",
    description: str | None = None,
    from_id: int | None = 1,
    from_subject: str | None = "Task A",
    to_id: int | None = 2,
    to_subject: str | None = "Task B",
) -> RelationSummary:
    return RelationSummary(
        id=relation_id,
        type=relation_type,
        description=description,
        from_id=from_id,
        from_subject=from_subject,
        to_id=to_id,
        to_subject=to_subject,
    )


def _record(
    relation_id: int = 7,
    *,
    from_href: str | None = "/api/v3/work_packages/1",
    to_href: str | None = "/api/v3/work_packages/2",
    summary: RelationSummary | None = None,
) -> RelationRecord:
    resolved_summary = summary or _summary(relation_id)
    from_link = {"href": from_href} if from_href is not None else None
    to_link = {"href": to_href} if to_href is not None else None
    return RelationRecord(summary=lambda: resolved_summary, from_link=from_link, to_link=to_link)


def _record_that_crashes_if_normalized(
    relation_id: int, *, from_href: str | None, to_href: str | None
) -> RelationRecord:
    """A record whose .summary() raises -- for proving list methods never
    normalize a record they have already decided to filter out. Mirrors the
    real HttpxRelationApi's actual failure mode: normalize_relation crashes
    with a KeyError on a payload missing "id", not a made-up test-only
    exception type."""

    def _boom() -> RelationSummary:
        raise AssertionError(
            f"summary() must never be called for relation {relation_id} once "
            "it has been filtered out by the allowlist check"
        )

    from_link = {"href": from_href} if from_href is not None else None
    to_link = {"href": to_href} if to_href is not None else None
    return RelationRecord(summary=_boom, from_link=from_link, to_link=to_link)


class _FakeRelationApi:
    def __init__(self, records: list[RelationRecord] | None = None, *, relation_id: int = 7) -> None:
        self._list_records = records if records is not None else [_record(relation_id)]
        self._by_id = {relation_id: self._list_records[0]} if len(self._list_records) == 1 else None
        self.fetch_page_calls: list[tuple[int, int, str | None]] = []
        self.get_calls: list[int] = []
        self.create_calls: list[tuple[str, dict]] = []
        self.update_calls: list[tuple[int, dict]] = []
        self.delete_calls: list[int] = []

    def to_record(self, payload: dict) -> RelationRecord:
        # Only used by the Service to re-derive a record from a raw page
        # element -- tests drive fetch_page's raw payloads directly, so this
        # must round-trip whatever _record()-shaped dict fetch_page returns.
        return payload["__record__"]

    async def fetch_page(self, *, offset: int, page_size: int, filters: str | None) -> dict:
        self.fetch_page_calls.append((offset, page_size, filters))
        # fetch_bounded_and_paginate's seen-ids guard reads element["id"]
        # directly off the raw dict, before to_record ever runs -- give each
        # element a distinct id. to_record (below) unwraps "__record__" back
        # to the real RelationRecord, ignoring "id" entirely.
        elements = [{"id": i, "__record__": r} for i, r in enumerate(self._list_records)]
        return {"_embedded": {"elements": elements}}

    async def get(self, relation_id: int) -> RelationRecord:
        self.get_calls.append(relation_id)
        assert self._by_id is not None, "get() needs a single-record fake"
        return self._by_id[relation_id]

    async def create(self, work_package_ref: str, payload: dict) -> RelationRecord:
        self.create_calls.append((work_package_ref, payload))
        return _record(650, summary=_summary(650, to_id=55))

    async def update(self, relation_id: int, payload: dict) -> RelationRecord:
        self.update_calls.append((relation_id, payload))
        assert self._by_id is not None, "update() needs a single-record fake constructed with relation_id="
        return self._by_id[relation_id]

    async def delete(self, relation_id: int) -> None:
        self.delete_calls.append(relation_id)


class _FakeWorkPackageLookupApi:
    def __init__(self, project_link: dict | None = None, *, by_id: dict[str, dict] | None = None) -> None:
        self._project_link = project_link or {"href": "/api/v3/projects/1"}
        self._by_id = by_id
        self.get_calls: list[str] = []
        self.get_by_href_calls: list[str] = []

    async def get(self, work_package_ref: str) -> dict:
        self.get_calls.append(work_package_ref)
        if self._by_id is not None:
            return self._by_id[work_package_ref]
        return {"id": 42, "_links": {"project": self._project_link}}

    async def get_by_href(self, href: str) -> dict:
        self.get_by_href_calls.append(href)
        return {"_links": {"project": self._project_link}}


def _resolve_work_package_id_ok(resolved_id: int = 55):
    calls: list[tuple[int | str, bool]] = []

    async def resolve(work_package_ref: int | str, *, write: bool = False) -> int:
        calls.append((work_package_ref, write))
        return resolved_id

    resolve.calls = calls  # type: ignore[attr-defined]
    return resolve


def _work_package_project_allowed_from(allowed_hrefs: set[str]):
    calls: list[str] = []

    async def check(href: str, *, context=None) -> bool:
        calls.append(href)
        return href in allowed_hrefs

    check.calls = calls  # type: ignore[attr-defined]
    return check


def _service(
    *,
    api: _FakeRelationApi | None = None,
    work_package_lookup_api: _FakeWorkPackageLookupApi | None = None,
    settings=None,
    resolve_work_package_id=None,
    work_package_project_allowed=None,
) -> RelationService:
    return RelationService(
        api=api or _FakeRelationApi(),
        work_package_lookup_api=work_package_lookup_api or _FakeWorkPackageLookupApi(),
        settings=settings or make_settings(),
        project_id_to_identifier=PROJECT_ID_TO_IDENTIFIER,
        resolve_work_package_id=resolve_work_package_id or _resolve_work_package_id_ok(),
        work_package_project_allowed=work_package_project_allowed
        or _work_package_project_allowed_from({"/api/v3/work_packages/1", "/api/v3/work_packages/2"}),
        api_prefix="/api/v3/",
    )


# --- list_all / list_for_work_package ------------------------------------------


@pytest.mark.asyncio
async def test_list_all_returns_relations_under_wide_open_allowlist() -> None:
    api = _FakeRelationApi()
    settings = dataclasses.replace(make_settings(), read_projects=("*",))
    service = _service(api=api, settings=settings)

    result = await service.list_all()

    assert result.count == 1
    assert result.results[0].id == 7


@pytest.mark.asyncio
async def test_list_all_filters_by_read_allowlist_both_sides() -> None:
    """Drops a relation if EITHER linked work package is outside the allowlist."""
    kept = _record(1, from_href="/api/v3/work_packages/10", to_href="/api/v3/work_packages/11")
    dropped_source = _record_that_crashes_if_normalized(
        2, from_href="/api/v3/work_packages/20", to_href="/api/v3/work_packages/10"
    )
    dropped_target = _record_that_crashes_if_normalized(
        3, from_href="/api/v3/work_packages/30", to_href="/api/v3/work_packages/31"
    )
    api = _FakeRelationApi(records=[kept, dropped_source, dropped_target])
    settings = dataclasses.replace(make_settings(), read_projects=("allowed",))
    check = _work_package_project_allowed_from(
        {"/api/v3/work_packages/10", "/api/v3/work_packages/11", "/api/v3/work_packages/30"}
    )
    service = _service(api=api, settings=settings, work_package_project_allowed=check)

    result = await service.list_all()

    assert [r.id for r in result.results] == [1]


@pytest.mark.asyncio
async def test_list_for_work_package_resolves_anchor_and_sends_involved_filter() -> None:
    api = _FakeRelationApi()
    resolve = _resolve_work_package_id_ok(10)
    settings = dataclasses.replace(make_settings(), read_projects=("*",))
    service = _service(api=api, settings=settings, resolve_work_package_id=resolve)

    result = await service.list_for_work_package("PROJ-10")

    assert resolve.calls == [("PROJ-10", False)]
    assert api.fetch_page_calls[0][2] == '[{"involved": {"operator": "=", "values": ["10"]}}]'
    assert result.count == 1


@pytest.mark.asyncio
async def test_list_all_hides_wp_subject_when_wp_subject_hidden() -> None:
    """from_subject/to_subject honor the work_package subject hide list, and
    stamping order must not lose relation-level hidden fields (verified
    together, per the Codex-found dataclasses.replace-vs-apply_hidden_fields
    ordering risk)."""
    record = _record(5, summary=_summary(5, description="secret note", from_subject="Secret A", to_subject="Secret B"))
    api = _FakeRelationApi(records=[record])
    settings = dataclasses.replace(
        make_settings(),
        read_projects=("*",),
        hidden_fields={"work_package": ("subject",), "relation": ("description",)},
    )
    service = _service(api=api, settings=settings)

    result = await service.list_all()

    relation = result.results[0]
    assert relation.from_subject is None
    assert relation.to_subject is None
    assert relation._hidden_keys == frozenset({"description"})


# --- create ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_previews_without_confirm() -> None:
    api = _FakeRelationApi()
    lookup = _FakeWorkPackageLookupApi()
    resolve = _resolve_work_package_id_ok(55)
    service = _service(api=api, work_package_lookup_api=lookup, resolve_work_package_id=resolve)

    result = await service.create(
        work_package_id=42, related_to_work_package_id=55, relation_type="blocks", confirm=False
    )

    assert result.confirmed is False
    assert result.requires_confirmation is True
    assert api.create_calls == []
    assert resolve.calls == [(55, True)]


@pytest.mark.asyncio
async def test_create_commits_when_confirmed() -> None:
    api = _FakeRelationApi()
    lookup = _FakeWorkPackageLookupApi()
    resolve = _resolve_work_package_id_ok(55)
    service = _service(api=api, work_package_lookup_api=lookup, resolve_work_package_id=resolve)

    result = await service.create(
        work_package_id=42,
        related_to_work_package_id=55,
        relation_type="blocks",
        description="Blocked until API rollout finishes",
        confirm=True,
    )

    assert result.confirmed is True
    assert result.result is not None
    assert result.result.to_id == 55
    work_package_ref, payload = api.create_calls[0]
    assert work_package_ref == "42"
    assert payload["_links"]["to"]["href"] == "/api/v3/work_packages/55"


@pytest.mark.asyncio
async def test_create_validates_source_reference_before_resolving_target() -> None:
    """Regression (Codex-found): the source reference must be validated
    (traversal-segment rejection) BEFORE the target is resolved -- otherwise
    an invalid source reference could trigger unnecessary I/O against the
    target before the error is raised."""
    resolve_calls: list[str] = []

    async def resolve(work_package_ref, *, write: bool = False) -> int:
        resolve_calls.append(str(work_package_ref))
        return 55

    api = _FakeRelationApi()
    service = _service(api=api, resolve_work_package_id=resolve)

    with pytest.raises(InvalidInputError):
        await service.create(
            work_package_id="../work_packages/1",
            related_to_work_package_id=55,
            relation_type="blocks",
            confirm=True,
        )

    assert resolve_calls == [], "target must not be resolved before the source reference is validated"


# --- update -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_previews_without_confirm() -> None:
    api = _FakeRelationApi()
    service = _service(api=api)

    result = await service.update(relation_id=7, description="updated", confirm=False)

    assert result.requires_confirmation is True
    assert api.update_calls == []


@pytest.mark.asyncio
async def test_update_commits_when_confirmed() -> None:
    api = _FakeRelationApi()
    service = _service(api=api)

    result = await service.update(relation_id=7, description="updated", confirm=True)

    assert result.result is not None
    assert api.update_calls == [(7, {"description": "updated"})]


@pytest.mark.asyncio
async def test_update_allows_an_empty_body_preview() -> None:
    """Original client.py's update_relation has no 'at least one field
    required' constraint -- an empty preview body must be allowed."""
    api = _FakeRelationApi()
    service = _service(api=api)

    result = await service.update(relation_id=7, confirm=False)

    assert result.payload == {}


@pytest.mark.asyncio
async def test_update_denies_write_outside_source_project_allowlist() -> None:
    api = _FakeRelationApi()
    lookup = _FakeWorkPackageLookupApi(project_link={"href": "/api/v3/projects/1"})
    settings = dataclasses.replace(make_settings(), write_projects=("other",))
    service = _service(api=api, work_package_lookup_api=lookup, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.update(relation_id=7, description="updated", confirm=True)


@pytest.mark.asyncio
async def test_update_raises_when_source_link_is_missing() -> None:
    record = _record(7, from_href=None)
    api = _FakeRelationApi(records=[record])
    service = _service(api=api)

    with pytest.raises(OpenProjectServerError):
        await service.update(relation_id=7, description="updated", confirm=True)


# --- delete -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_previews_without_confirm() -> None:
    api = _FakeRelationApi()
    service = _service(api=api)

    result = await service.delete(relation_id=7, confirm=False)

    assert result.requires_confirmation is True
    assert result.result is not None
    assert api.delete_calls == []


@pytest.mark.asyncio
async def test_delete_commits_when_confirmed() -> None:
    api = _FakeRelationApi()
    service = _service(api=api)

    result = await service.delete(relation_id=7, confirm=True)

    assert result.confirmed is True
    assert result.result is None
    assert api.delete_calls == [7]


@pytest.mark.asyncio
async def test_delete_denies_write_outside_source_project_allowlist() -> None:
    api = _FakeRelationApi()
    lookup = _FakeWorkPackageLookupApi(project_link={"href": "/api/v3/projects/1"})
    settings = dataclasses.replace(make_settings(), write_projects=("other",))
    service = _service(api=api, work_package_lookup_api=lookup, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.delete(relation_id=7, confirm=True)
