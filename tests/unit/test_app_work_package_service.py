from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import InvalidInputError, NotFoundError, PermissionDeniedError
from openproject_ce_mcp.app.ports.work_package_api import WorkPackagePage, WorkPackageRecord
from openproject_ce_mcp.app.ports.work_package_resolution import WorkPackageAllowedContext
from openproject_ce_mcp.app.services.work_package_service import WorkPackageService
from openproject_ce_mcp.models import CurrentUser, WorkPackageDetail, WorkPackageSummary

PROJECT_ID_TO_IDENTIFIER = {1: "demo", 20: "other"}


def _summary(
    wp_id: int = 6,
    *,
    subject: str = "Demo WP",
    project: str | None = "Demo",
    description: str | None = "Some description",
    description_truncated: bool = False,
    description_length: int | None = None,
) -> WorkPackageSummary:
    return WorkPackageSummary(
        id=wp_id,
        display_id=None,
        subject=subject,
        type="Task",
        status="New",
        priority=None,
        project_phase=None,
        assignee=None,
        responsible=None,
        project=project,
        version=None,
        sprint=None,
        start_date=None,
        due_date=None,
        description=description,
        has_description=description is not None,
        url=f"https://op.example.com/work_packages/{wp_id}",
        description_truncated=description_truncated,
        description_length=description_length,
    )


def _detail(wp_id: int = 6, *, children=None, ancestors=None) -> WorkPackageDetail:
    return WorkPackageDetail(
        id=wp_id,
        display_id=None,
        subject="Demo WP",
        type="Task",
        status="New",
        priority=None,
        project_phase=None,
        assignee=None,
        responsible=None,
        project="Demo",
        version=None,
        sprint=None,
        parent_id=None,
        parent_display_id=None,
        start_date=None,
        due_date=None,
        lock_version=1,
        description="Some description",
        url=f"https://op.example.com/work_packages/{wp_id}",
        activities_url=None,
        relations_url=None,
        children=children,
        ancestors=ancestors,
    )


def _payload(wp_id: int = 6, *, project_href: str = "/api/v3/projects/1", project_title: str = "Demo") -> dict:
    return {
        "id": wp_id,
        "subject": "Demo WP",
        "_links": {"project": {"href": project_href, "title": project_title}},
    }


def _record(wp_id: int = 6, *, summary=None, detail=None, payload=None) -> WorkPackageRecord:
    s = summary or _summary(wp_id)
    d = detail or _detail(wp_id)
    return WorkPackageRecord(summary=s, to_detail=lambda: d, payload=payload or _payload(wp_id))


class _FakeWorkPackageApi:
    def __init__(self, *, raw_elements: list[dict] | None = None, server_total: int | None = None) -> None:
        self._raw_elements = raw_elements if raw_elements is not None else [_payload()]
        self._server_total = server_total if server_total is not None else len(self._raw_elements)
        self._records_by_id: dict[int, WorkPackageRecord] = {6: _record(6)}
        self.list_calls: list[dict] = []
        self.get_calls: list[str] = []

    async def list(self, *, filters, offset, limit, sort_by, group_by) -> WorkPackagePage:
        self.list_calls.append({"filters": filters, "offset": offset, "limit": limit})
        return WorkPackagePage(raw_elements=self._raw_elements, server_total=self._server_total)

    def to_record(self, payload: dict, *, text_limit: int | None) -> WorkPackageRecord:
        wp_id = payload["id"]
        if wp_id in self._records_by_id:
            return self._records_by_id[wp_id]
        return _record(wp_id, payload=payload)

    async def get(self, work_package_ref: str, *, text_limit: int | None = None) -> WorkPackageRecord:
        self.get_calls.append(work_package_ref)
        wp_id = int(work_package_ref)
        if wp_id in self._records_by_id:
            return self._records_by_id[wp_id]
        raise NotFoundError(f"OpenProject work package {wp_id} was not found.")


async def _no_project_allowed(href: str, *, context: WorkPackageAllowedContext | None = None) -> bool:
    return False


async def _all_project_allowed(href: str, *, context: WorkPackageAllowedContext | None = None) -> bool:
    return True


def _service(
    api: _FakeWorkPackageApi | None = None,
    *,
    settings=None,
    project_id_to_identifier: dict[int, str] | None = None,
    work_package_project_allowed=None,
) -> tuple[WorkPackageService, _FakeWorkPackageApi]:
    fake_api = api or _FakeWorkPackageApi()

    async def resolve_project_ref(project_ref, *, write=False, context=None):
        return {"id": 1, "identifier": "demo", "name": "Demo"}

    async def resolve_type_id(type_ref, *, project=None, context=None):
        return "3"

    async def resolve_version_id(version_ref, *, project=None, context=None):
        return "4"

    async def resolve_status_id(status_ref):
        return "5"

    async def resolve_priority_id(priority_ref):
        return "7"

    async def resolve_principal_id(principal_ref):
        return "8"

    async def current_user():
        return CurrentUser(id=42, name="Admin", login="admin", url="https://op.example.com/users/42")

    service = WorkPackageService(
        api=fake_api,
        settings=settings or make_settings(),
        project_id_to_identifier=project_id_to_identifier
        if project_id_to_identifier is not None
        else dict(PROJECT_ID_TO_IDENTIFIER),
        resolve_project_ref=resolve_project_ref,
        resolve_type_id=resolve_type_id,
        resolve_version_id=resolve_version_id,
        resolve_status_id=resolve_status_id,
        resolve_priority_id=resolve_priority_id,
        resolve_principal_id=resolve_principal_id,
        current_user=current_user,
        work_package_project_allowed=work_package_project_allowed or _all_project_allowed,
    )
    return service, fake_api


@pytest.mark.asyncio
async def test_list_returns_stamped_summaries() -> None:
    service, _ = _service()

    result = await service.list()

    assert result.total == 1
    assert result.results[0].id == 6


@pytest.mark.asyncio
async def test_search_requires_search_term_builds_filter() -> None:
    service, api = _service()

    await service.search(search="foo")

    assert {"subject_or_id": {"operator": "**", "values": ["foo"]}} in api.list_calls[0]["filters"]


@pytest.mark.asyncio
async def test_list_checks_read_enabled_before_any_resolution_or_request() -> None:
    settings = dataclasses.replace(make_settings(), enable_work_package_read=False)
    service, api = _service(settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.list(project="demo")

    assert api.list_calls == []


@pytest.mark.asyncio
async def test_search_checks_read_enabled_before_any_resolution_or_request() -> None:
    settings = dataclasses.replace(make_settings(), enable_work_package_read=False)
    service, api = _service(settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.search(search="foo")

    assert api.list_calls == []


@pytest.mark.asyncio
async def test_list_my_open_checks_read_enabled_before_current_user_lookup() -> None:
    settings = dataclasses.replace(make_settings(), enable_work_package_read=False)
    service, api = _service(settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.list_my_open()

    assert api.list_calls == []


@pytest.mark.asyncio
async def test_get_checks_read_enabled_before_fetching() -> None:
    settings = dataclasses.replace(make_settings(), enable_work_package_read=False)
    service, api = _service(settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get(6)

    assert api.get_calls == []


@pytest.mark.asyncio
async def test_list_exposes_real_total_when_scope_unrestricted() -> None:
    api = _FakeWorkPackageApi(
        raw_elements=[_payload(1), _payload(2)],
        server_total=5,
    )
    service, _ = _service(api, settings=dataclasses.replace(make_settings(), read_projects=("*",)))

    result = await service.list(limit=2)

    assert result.total == 5
    assert result.count == 2
    assert result.next_offset == 2
    assert result.truncated is True


@pytest.mark.asyncio
async def test_list_denies_when_project_cache_empty_under_restricted_scope() -> None:
    """Restricted scope, no explicit project, and the allowed-project-id cache
    is empty -- there is no way to send a server-side project filter that
    provably restricts the query, so this must fail closed with an explicit
    error rather than silently narrow to an untrustworthy page-count total."""
    service, api = _service(
        settings=dataclasses.replace(make_settings(), read_projects=("demo",)),
        project_id_to_identifier={},
    )

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await service.list(limit=2)

    assert api.list_calls == []


@pytest.mark.asyncio
async def test_list_exposes_real_total_when_restricted_scope_filter_sent() -> None:
    """Restricted scope, no explicit project, but the allowed-project-id cache
    IS populated -- a server-side project_id filter covering exactly the
    allowed projects is sent, so the query is provably restricted and the
    server's real total is safe to expose."""
    api = _FakeWorkPackageApi(raw_elements=[_payload(1), _payload(2)], server_total=5)
    service, _ = _service(
        api,
        settings=dataclasses.replace(make_settings(), read_projects=("demo",)),
        project_id_to_identifier={1: "demo"},
    )

    result = await service.list(limit=2)

    assert result.total == 5
    assert result.count == 2
    assert {"project_id": {"operator": "=", "values": ["1"]}} in api.list_calls[0]["filters"]


@pytest.mark.asyncio
async def test_search_pagination_hints_do_not_leak_untrusted_total() -> None:
    """search() has no restricted-scope project_id filter branch at all --
    next_offset/truncated must NOT be derived from the server's secret total,
    only from whether the raw page came back full."""
    api = _FakeWorkPackageApi(raw_elements=[_payload(1)], server_total=50)
    service, _ = _service(api, settings=dataclasses.replace(make_settings(), read_projects=("demo",)))

    result = await service.search(search="foo", limit=5)

    assert result.total == 1  # NOT the server's secret total of 50
    assert result.next_offset is None
    assert result.truncated is False


@pytest.mark.asyncio
async def test_list_filters_out_disallowed_project_before_normalizing() -> None:
    """A raw element outside the read allowlist must be dropped BEFORE
    normalization (not just masked after) -- proven here by an element whose
    project_id (99) isn't in project_id_to_identifier, so
    work_package_payload_allowed denies it under a restricted, non-wildcard
    scope."""
    allowed = _payload(1, project_href="/api/v3/projects/1")
    disallowed = _payload(2, project_href="/api/v3/projects/99", project_title="Other Project")
    api = _FakeWorkPackageApi(raw_elements=[allowed, disallowed], server_total=2)
    service, _ = _service(
        api,
        settings=dataclasses.replace(make_settings(), read_projects=("demo",)),
        project_id_to_identifier={1: "demo"},
    )

    result = await service.list(limit=10)

    assert result.count == 1
    assert result.results[0].id == 1


@pytest.mark.asyncio
async def test_get_returns_detail_with_full_text() -> None:
    service, _ = _service()

    detail = await service.get(6)

    assert detail.id == 6


@pytest.mark.asyncio
async def test_get_denies_when_project_not_in_read_allowlist() -> None:
    record = _record(6, payload=_payload(6, project_href="/api/v3/projects/99", project_title="Other Project"))
    api = _FakeWorkPackageApi()
    api._records_by_id[6] = record
    service, _ = _service(
        api,
        settings=dataclasses.replace(make_settings(), read_projects=("demo",)),
        project_id_to_identifier={1: "demo"},
    )

    with pytest.raises(PermissionDeniedError):
        await service.get(6)


@pytest.mark.asyncio
async def test_get_stamps_hidden_description_and_zeroes_truncation_metadata() -> None:
    """A hidden 'description' must also blank description_truncated/
    description_length on the returned detail -- otherwise the true length of
    hidden content would leak through those sibling fields even though
    'description' itself is dropped (the adapter's normalize_* is not
    hidden-field-aware by design; masking is this Service's job)."""
    detail_with_meta = dataclasses.replace(_detail(6), description_truncated=True, description_length=900)
    record = _record(6, detail=detail_with_meta)
    api = _FakeWorkPackageApi()
    api._records_by_id[6] = record
    settings = dataclasses.replace(make_settings(), hidden_fields={"work_package": ("description",)})
    service, _ = _service(api, settings=settings)

    detail = await service.get(6)

    assert detail.description_truncated is False
    assert detail.description_length is None


@pytest.mark.asyncio
async def test_list_stamps_hidden_description_and_zeroes_summary_metadata() -> None:
    """Same as the detail-level test above, but for WorkPackageSummary's
    has_description field too (a field WorkPackageDetail doesn't carry)."""
    summary_with_meta = _summary(6, description="secret", description_truncated=True, description_length=900)
    payload = _payload(6)
    api = _FakeWorkPackageApi(raw_elements=[payload])
    api._records_by_id[6] = _record(6, summary=summary_with_meta, payload=payload)
    settings = dataclasses.replace(make_settings(), hidden_fields={"work_package": ("description",)})
    service, _ = _service(api, settings=settings)

    result = await service.list()

    summary = result.results[0]
    assert summary.description_truncated is False
    assert summary.description_length is None
    assert summary.has_description is False


@pytest.mark.asyncio
async def test_get_field_hidden_by_work_package_scope_not_a_sibling_scope() -> None:
    """Entity-scope regression: hiding 'description' under a DIFFERENT
    entity name ('project') must not mask work_package's description --
    masking must be keyed to the work_package entity specifically."""
    settings = dataclasses.replace(make_settings(), hidden_fields={"project": ("description",)})
    service, _ = _service(settings=settings)

    detail = await service.get(6)

    assert detail.description == "Some description"


@pytest.mark.asyncio
async def test_get_filters_hierarchy_entries_outside_read_allowlist() -> None:
    children = [{"href": "/api/v3/work_packages/10", "title": "In scope", "display_id": None}]
    ancestors = [{"href": "/api/v3/work_packages/20", "title": "Out of scope", "display_id": None}]
    detail = _detail(6, children=children, ancestors=ancestors)
    record = _record(6, detail=detail)
    api = _FakeWorkPackageApi()
    api._records_by_id[6] = record

    async def allowed(href: str, *, context=None) -> bool:
        return href == "/api/v3/work_packages/10"

    service, _ = _service(
        api,
        settings=dataclasses.replace(make_settings(), read_projects=("demo",)),
        work_package_project_allowed=allowed,
    )

    result = await service.get(6)

    assert result.children == children
    assert result.ancestors is None  # the only ancestor entry was filtered out


@pytest.mark.asyncio
async def test_get_skips_hierarchy_filtering_under_unrestricted_scope() -> None:
    """Under read_projects=('*',), the hierarchy filter must short-circuit
    without calling work_package_project_allowed at all."""
    ancestors = [{"href": "/api/v3/work_packages/20", "title": "Anywhere", "display_id": None}]
    detail = _detail(6, ancestors=ancestors)
    record = _record(6, detail=detail)
    api = _FakeWorkPackageApi()
    api._records_by_id[6] = record

    calls: list[str] = []

    async def tracking_allowed(href: str, *, context=None) -> bool:
        calls.append(href)
        return True

    service, _ = _service(api, work_package_project_allowed=tracking_allowed)

    result = await service.get(6)

    assert result.ancestors == ancestors
    assert calls == []


@pytest.mark.asyncio
async def test_get_batch_partial_failure() -> None:
    api = _FakeWorkPackageApi()
    api._records_by_id[6] = _record(6)
    service, _ = _service(api)

    result = await service.get_batch(ids=[6, 999])

    assert result.total == 2
    assert result.succeeded == 1
    assert result.failed == 1
    ok_item = next(item for item in result.results if item.id == 6)
    assert ok_item.success is True
    failed_item = next(item for item in result.results if item.id == 999)
    assert failed_item.success is False


@pytest.mark.asyncio
async def test_get_batch_rejects_empty_ids() -> None:
    service, _ = _service()

    with pytest.raises(ValueError):
        await service.get_batch(ids=[])


@pytest.mark.asyncio
async def test_get_batch_rejects_too_many_ids() -> None:
    service, _ = _service()

    with pytest.raises(ValueError):
        await service.get_batch(ids=list(range(101)))


@pytest.mark.asyncio
async def test_apply_date_filters_rejects_both_on_and_between() -> None:
    service, _ = _service()

    with pytest.raises(InvalidInputError):
        await service.list(created_on="2026-01-01", created_between=["2026-01-01", "2026-01-31"])


@pytest.mark.asyncio
async def test_list_my_open_uses_current_user_and_open_status_filter() -> None:
    service, api = _service()

    await service.list_my_open()

    filters = api.list_calls[0]["filters"]
    assert {"assigned_to_id": {"operator": "=", "values": ["42"]}} in filters
    assert {"status_id": {"operator": "o", "values": []}} in filters


@pytest.mark.asyncio
async def test_list_collection_defense_in_depth_guard_on_empty_read_scope() -> None:
    """Direct test of the shared `_list_collection` helper's own empty-scope
    guard, independent of its public callers (list/search/list_my_open), so a
    future new caller can't silently bypass it -- re-anchored from
    tests/unit/test_work_package_reads.py's client.py-level equivalent
    (test_list_work_package_collection_defense_in_depth_guard), which called
    the now-deleted private client.py method directly."""

    class _NoRequestApi:
        async def list(self, **kwargs):
            raise AssertionError("no request should ever be issued")

        def to_record(self, payload, *, text_limit):
            raise AssertionError("no record should ever be built")

        async def get(self, work_package_ref, *, text_limit=None):
            raise AssertionError("no request should ever be issued")

    service, _ = _service(_NoRequestApi(), settings=dataclasses.replace(make_settings(), read_projects=()))

    result = await service._list_collection(
        project_id=None, filters=[], offset=1, limit=10, sort_by=None, group_by=None, total_is_scope_safe=False
    )

    assert result.count == 0
    assert result.results == []
    assert result.next_offset is None
    assert result.truncated is False


@pytest.mark.asyncio
async def test_get_stays_masked_under_restricted_scope_even_with_hierarchy_present() -> None:
    """Regression (found by an independent Codex review of this migration,
    not the self-audit): apply_hidden_fields stamps `_hidden_keys` as a
    dynamic (non-dataclass-field) attribute. dataclasses.replace() -- which
    _filter_hierarchy_allowlist calls whenever read_projects is restricted
    (not "*") -- builds a brand-new instance carrying only the declared
    dataclass fields, silently dropping `_hidden_keys`. Stamping BEFORE
    filtering meant every get() call under a restricted scope returned a
    fully UNMASKED detail, leaking any hidden work_package field regardless
    of whether children/ancestors were even present. This test uses a
    RESTRICTED scope (not "*") specifically because the bug only manifests
    when _filter_hierarchy_allowlist actually calls dataclasses.replace()."""
    ancestors = [{"href": "/api/v3/work_packages/20", "title": "Parent", "display_id": None}]
    detail = _detail(6, ancestors=ancestors)
    record = _record(6, detail=detail)
    api = _FakeWorkPackageApi()
    api._records_by_id[6] = record
    settings = dataclasses.replace(
        make_settings(), read_projects=("demo",), hidden_fields={"work_package": ("description",)}
    )
    service, _ = _service(api, settings=settings, work_package_project_allowed=_all_project_allowed)

    result = await service.get(6)

    # Hidden fields are TAGGED, not nulled (see hidden_fields.apply_hidden_fields's
    # own docstring: the value stays on the dataclass; tools._to_payload's
    # serialization seam is what actually drops the key from the response).
    # The bug this test guards is `_hidden_keys` going missing entirely --
    # which would make _to_payload treat the field as NOT hidden at all.
    assert getattr(result, "_hidden_keys", frozenset()) == frozenset({"description"})


@pytest.mark.asyncio
async def test_get_hierarchy_truncated_flag_cleared_when_all_visible_entries_filtered_out() -> None:
    """Regression (independent Codex review): the Adapter computes
    children_truncated/ancestors_truncated from the RAW, pre-allowlist-filter
    element count. If every entry beyond the raw limit is itself
    out-of-scope, leaving *_truncated True after filtering down to zero
    visible entries discloses the mere existence of hierarchy members the
    caller isn't allowed to see. `_filter_hierarchy_allowlist` must clear the
    flag whenever the allowlist filter actually removed something."""
    ancestors = [{"href": "/api/v3/work_packages/20", "title": "Out of scope", "display_id": None}]
    detail = dataclasses.replace(_detail(6, ancestors=ancestors), ancestors_truncated=True)
    record = _record(6, detail=detail)
    api = _FakeWorkPackageApi()
    api._records_by_id[6] = record
    service, _ = _service(
        api,
        settings=dataclasses.replace(make_settings(), read_projects=("demo",)),
        work_package_project_allowed=_no_project_allowed,
    )

    result = await service.get(6)

    assert result.ancestors is None
    assert result.ancestors_truncated is False


@pytest.mark.asyncio
async def test_get_hierarchy_truncated_flag_preserved_when_nothing_filtered_out() -> None:
    """Counterpart to the test above: when the allowlist filter removes
    NOTHING (every raw entry survives), the truncated flag must stay exactly
    as the Adapter computed it -- proving the fix doesn't just always clear
    the flag, only when filtering actually changed the visible count."""
    ancestors = [{"href": "/api/v3/work_packages/20", "title": "In scope", "display_id": None}]
    detail = dataclasses.replace(_detail(6, ancestors=ancestors), ancestors_truncated=True)
    record = _record(6, detail=detail)
    api = _FakeWorkPackageApi()
    api._records_by_id[6] = record
    service, _ = _service(
        api,
        settings=dataclasses.replace(make_settings(), read_projects=("demo",)),
        work_package_project_allowed=_all_project_allowed,
    )

    result = await service.get(6)

    assert result.ancestors == ancestors
    assert result.ancestors_truncated is True
