from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import (
    InvalidInputError,
    NotFoundError,
    OpenProjectError,
    OpenProjectServerError,
    PermissionDeniedError,
)
from openproject_ce_mcp.app.ports.activity_api import ActivityRecord
from openproject_ce_mcp.app.ports.status_priority_type_api import StatusRecord
from openproject_ce_mcp.app.ports.work_package_api import WorkPackageFormResult, WorkPackagePage, WorkPackageRecord
from openproject_ce_mcp.app.ports.work_package_resolution import WorkPackageAllowedContext
from openproject_ce_mcp.app.services.work_package_service import WorkPackageService
from openproject_ce_mcp.models import ActivitySummary, CurrentUser, StatusSummary, WorkPackageDetail, WorkPackageSummary

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
        self.validate_create_calls: list[tuple[str, dict]] = []
        self.validate_update_calls: list[tuple[str, dict]] = []
        self.commit_create_calls: list[dict] = []
        self.commit_update_calls: list[tuple[str, dict]] = []
        self.delete_calls: list[str] = []
        self.post_comment_calls: list[dict] = []
        # Each entry in validation_errors_queue is consumed once per
        # validate_create/validate_update call, in order -- lets a test force
        # a rejection on a specific call without affecting others.
        self.validation_errors_queue: list[dict[str, str]] = []
        self.next_schema: dict = {}

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

    def _next_validation_errors(self) -> dict[str, str]:
        return self.validation_errors_queue.pop(0) if self.validation_errors_queue else {}

    async def validate_create(self, project_id: str, payload: dict) -> dict:
        self.validate_create_calls.append((project_id, payload))
        return {
            "_embedded": {
                "payload": payload,
                "validationErrors": self._next_validation_errors(),
                "schema": self.next_schema,
            }
        }

    async def validate_update(self, work_package_ref: str, payload: dict) -> dict:
        self.validate_update_calls.append((work_package_ref, payload))
        return {
            "_embedded": {
                "payload": payload,
                "validationErrors": self._next_validation_errors(),
                "schema": self.next_schema,
            }
        }

    def parse_form(self, form: dict) -> WorkPackageFormResult:
        embedded = form.get("_embedded", {})
        return WorkPackageFormResult(
            payload=embedded.get("payload", {}),
            validation_errors=embedded.get("validationErrors", {}),
            schema=embedded.get("schema", {}),
        )

    async def commit_create(self, payload: dict, *, text_limit: int | None) -> WorkPackageRecord:
        self.commit_create_calls.append(payload)
        return _record(99, summary=_summary(99), payload=_payload(99))

    async def commit_update(self, work_package_ref: str, payload: dict, *, text_limit: int | None) -> WorkPackageRecord:
        self.commit_update_calls.append((work_package_ref, payload))
        wp_id = int(work_package_ref)
        return self._records_by_id.get(wp_id, _record(wp_id, payload=payload))

    async def delete(self, work_package_ref: str) -> None:
        self.delete_calls.append(work_package_ref)

    async def post_comment(self, work_package_ref: str, *, comment: str, internal: bool, notify: bool) -> dict:
        self.post_comment_calls.append(
            {"work_package_ref": work_package_ref, "comment": comment, "internal": internal, "notify": notify}
        )
        return {"id": 55, "_type": "Activity", "comment": {"raw": comment}, "_links": {}}


class _FakeStatusApi:
    def __init__(self, *, is_closed: bool = False) -> None:
        self.is_closed = is_closed
        self.get_status_calls: list[int] = []

    async def get_status(self, status_id: int) -> StatusRecord:
        self.get_status_calls.append(status_id)
        return StatusRecord(
            summary=StatusSummary(
                id=status_id,
                name="Closed" if self.is_closed else "New",
                is_default=False,
                is_closed=self.is_closed,
                color=None,
                position=1,
                url="https://op.example.com/statuses/1",
            )
        )

    async def list_statuses(self):
        raise NotImplementedError

    async def list_priorities(self):
        raise NotImplementedError

    async def get_priority(self, priority_id: int):
        raise NotImplementedError

    async def list_types(self, *, project_id):
        raise NotImplementedError

    async def get_type(self, type_id: int):
        raise NotImplementedError


class _FakeActivityApi:
    def __init__(self) -> None:
        self.get_raw_calls: list[int] = []
        self.next_get_raw: dict | None = None

    async def list_for_work_package(self, work_package_id: int):
        return []

    def to_record(self, payload: dict) -> ActivityRecord:
        def to_summary(text_limit):
            return ActivitySummary(
                id=payload["id"],
                type=payload.get("_type"),
                version=None,
                user=payload.get("_links", {}).get("user", {}).get("title"),
                comment=(payload.get("comment") or {}).get("raw"),
                created_at=payload.get("createdAt"),
            )

        return ActivityRecord(to_summary=to_summary)

    async def get_raw(self, activity_id: int) -> dict:
        self.get_raw_calls.append(activity_id)
        if self.next_get_raw is not None:
            return self.next_get_raw
        return {"id": activity_id, "_type": "Activity", "_links": {}}


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
    status_api: _FakeStatusApi | None = None,
    activity_api: _FakeActivityApi | None = None,
    resolve_work_package_id=None,
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

    async def resolve_assignee_id(assignee_ref):
        if assignee_ref.casefold() == "me":
            return "42"
        if assignee_ref.isdigit():
            return assignee_ref
        raise InvalidInputError("assignee must be a positive integer user id or 'me'.")

    async def resolve_sprint_id(sprint_ref, *, project, context=None):
        return "9"

    async def default_resolve_work_package_id(ref, *, write=False):
        return int(ref)

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
        resolve_assignee_id=resolve_assignee_id,
        resolve_sprint_id=resolve_sprint_id,
        resolve_work_package_id=resolve_work_package_id or default_resolve_work_package_id,
        status_api=status_api or _FakeStatusApi(),
        activity_api=activity_api or _FakeActivityApi(),
        current_user=current_user,
        work_package_project_allowed=work_package_project_allowed or _all_project_allowed,
        api_prefix="/api/v3/",
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


# ----------------------------------------------------------------------
# create()
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_preview_without_commit_does_not_call_commit_create() -> None:
    api = _FakeWorkPackageApi()
    service, _ = _service(api)

    result = await service.create(project="demo", type="Task", subject="New WP", confirm=False)

    assert result.requires_confirmation is True
    assert result.confirmed is False
    assert result.ready is True
    assert api.commit_create_calls == []
    assert len(api.validate_create_calls) == 1


@pytest.mark.asyncio
async def test_create_commit_calls_commit_create_and_masks_result() -> None:
    api = _FakeWorkPackageApi()
    settings = dataclasses.replace(make_settings(), hidden_fields={"work_package": ("description",)})
    service, _ = _service(api, settings=settings)

    result = await service.create(project="demo", type="Task", subject="New WP", confirm=True)

    assert result.confirmed is True
    assert result.ready is True
    assert len(api.commit_create_calls) == 1
    assert result.result is not None
    # apply_hidden_fields stamps a _hidden_keys marker; it does not blank the
    # field itself -- tools._to_payload's serialization layer drops the key
    # entirely at the MCP response boundary.
    assert result.result._hidden_keys == frozenset({"description"})


@pytest.mark.asyncio
async def test_create_rejects_when_write_scope_denies_project() -> None:
    api = _FakeWorkPackageApi()

    async def resolve_project_ref_denied(project_ref, *, write=False, context=None):
        raise PermissionDeniedError("OpenProject writes to this project are disabled by OPENPROJECT_WRITE_PROJECTS.")

    service, _ = _service(api)
    service._resolve_project_ref = resolve_project_ref_denied  # type: ignore[method-assign]

    with pytest.raises(PermissionDeniedError):
        await service.create(project="demo", type="Task", subject="New WP", confirm=False)


@pytest.mark.asyncio
async def test_create_rejects_write_to_hidden_field() -> None:
    api = _FakeWorkPackageApi()
    settings = dataclasses.replace(make_settings(), hidden_fields={"work_package": ("subject",)})
    service, _ = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden"):
        await service.create(project="demo", type="Task", subject="New WP", confirm=False)


@pytest.mark.asyncio
async def test_create_reports_validation_errors_as_not_ready() -> None:
    api = _FakeWorkPackageApi()
    api.validation_errors_queue.append({"subject": "can't be blank"})
    service, _ = _service(api)

    result = await service.create(project="demo", type="Task", subject="New WP", confirm=False)

    assert result.ready is False
    assert result.validation_errors == {"subject": "can't be blank"}
    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_create_custom_field_input_rejected_by_raw_key() -> None:
    api = _FakeWorkPackageApi()
    settings = dataclasses.replace(make_settings(), hide_custom_fields=("Story points",))
    service, _ = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="OPENPROJECT_HIDE_CUSTOM_FIELDS"):
        await service.create(
            project="demo", type="Task", subject="New WP", custom_fields={"Story points": 8}, confirm=False
        )


@pytest.mark.asyncio
async def test_create_custom_field_resolved_via_schema() -> None:
    api = _FakeWorkPackageApi()
    api.next_schema = {
        "customField10": {"name": "Story points", "location": "payload"},
    }
    service, _ = _service(api)

    result = await service.create(
        project="demo", type="Task", subject="New WP", custom_fields={"customField10": 8}, confirm=False
    )

    assert result.ready is True
    assert result.payload["customField10"] == 8


@pytest.mark.asyncio
async def test_create_custom_field_rejected_after_schema_resolution_by_resolved_name() -> None:
    api = _FakeWorkPackageApi()
    api.next_schema = {
        "customField10": {"name": "Story points", "location": "payload"},
    }
    settings = dataclasses.replace(make_settings(), hide_custom_fields=("Story points",))
    service, _ = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="OPENPROJECT_HIDE_CUSTOM_FIELDS"):
        await service.create(
            project="demo", type="Task", subject="New WP", custom_fields={"customField10": 8}, confirm=False
        )


@pytest.mark.asyncio
async def test_create_assignee_rejects_name_search() -> None:
    api = _FakeWorkPackageApi()
    service, _ = _service(api)

    with pytest.raises(InvalidInputError, match="assignee must be a positive integer user id or 'me'"):
        await service.create(project="demo", type="Task", subject="New WP", assignee="Jane Doe", confirm=False)


@pytest.mark.asyncio
async def test_create_resolves_parent_with_write_true() -> None:
    api = _FakeWorkPackageApi()
    seen_write: list[bool] = []

    async def resolve_work_package_id(ref, *, write=False):
        seen_write.append(write)
        return int(ref)

    service, _ = _service(api, resolve_work_package_id=resolve_work_package_id)

    await service.create(project="demo", type="Task", subject="Child", parent_work_package_id=6, confirm=False)

    assert seen_write == [True]


# ----------------------------------------------------------------------
# create_subtask()
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_subtask_derives_project_from_parent_link() -> None:
    api = _FakeWorkPackageApi()
    api._records_by_id[6] = _record(6, payload=_payload(6, project_href="/api/v3/projects/1", project_title="Demo"))
    service, _ = _service(api)

    result = await service.create_subtask(parent_work_package_id=6, type="Task", subject="Child task", confirm=False)

    assert result.ready is True
    project_id, payload = api.validate_create_calls[0]
    assert project_id == "1"
    assert payload["_links"]["parent"]["href"] == "/api/v3/work_packages/6"


@pytest.mark.asyncio
async def test_create_subtask_denies_write_when_parent_project_not_write_allowed() -> None:
    api = _FakeWorkPackageApi()
    api._records_by_id[6] = _record(6, payload=_payload(6, project_href="/api/v3/projects/20", project_title="Other"))
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("demo",))
    service, _ = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.create_subtask(parent_work_package_id=6, type="Task", subject="Child task", confirm=False)


@pytest.mark.asyncio
async def test_create_subtask_missing_project_link_raises() -> None:
    api = _FakeWorkPackageApi()
    api._records_by_id[6] = _record(6, payload={"id": 6, "subject": "Parent", "_links": {}})
    service, _ = _service(api)

    with pytest.raises(OpenProjectServerError, match="missing a project link"):
        await service.create_subtask(parent_work_package_id=6, type="Task", subject="Child task", confirm=False)


# ----------------------------------------------------------------------
# bulk_create()
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_create_preview_reports_success_without_committing() -> None:
    api = _FakeWorkPackageApi()
    service, _ = _service(api)

    result = await service.bulk_create(
        items=[
            {"project": "demo", "type": "Task", "subject": "One"},
            {"project": "demo", "type": "Task", "subject": "Two"},
        ],
        confirm=False,
    )

    assert result.total == 2
    assert result.succeeded == 2
    assert result.failed == 0
    assert result.confirmed is False
    assert api.commit_create_calls == []


@pytest.mark.asyncio
async def test_bulk_create_commit_creates_every_item() -> None:
    api = _FakeWorkPackageApi()
    service, _ = _service(api)

    result = await service.bulk_create(
        items=[
            {"project": "demo", "type": "Task", "subject": "One"},
            {"project": "demo", "type": "Task", "subject": "Two"},
        ],
        confirm=True,
    )

    assert result.succeeded == 2
    assert len(api.commit_create_calls) == 2


@pytest.mark.asyncio
async def test_bulk_create_partial_failure_is_isolated_per_item() -> None:
    api = _FakeWorkPackageApi()
    service, _ = _service(api)

    result = await service.bulk_create(
        items=[
            {"project": "demo", "type": "Task", "subject": "Good"},
            {"project": "demo", "type": "Task", "subject": "Bad", "assignee": "Jane Doe"},
        ],
        confirm=False,
    )

    assert result.total == 2
    assert result.succeeded == 1
    assert result.failed == 1
    assert result.items[1].success is False
    assert "assignee" in result.items[1].error


@pytest.mark.asyncio
async def test_bulk_create_shares_resolution_context_across_items_in_same_project() -> None:
    api = _FakeWorkPackageApi()
    project_resolve_calls = 0

    def make_resolve_project_ref():
        async def resolve_project_ref(project_ref, *, write=False, context=None):
            nonlocal project_resolve_calls
            if context is not None:
                cached = context._cache.get((project_ref, write))
                if cached is not None:
                    return cached
            project_resolve_calls += 1
            payload = {"id": 1, "identifier": "demo", "name": "Demo"}
            if context is not None:
                context.seed(project_ref, payload, write=write)
            return payload

        return resolve_project_ref

    service, _ = _service(api)
    service._resolve_project_ref = make_resolve_project_ref()  # type: ignore[method-assign]

    await service.bulk_create(
        items=[
            {"project": "demo", "type": "Task", "subject": "One"},
            {"project": "demo", "type": "Task", "subject": "Two"},
            {"project": "demo", "type": "Task", "subject": "Three"},
        ],
        confirm=False,
    )

    # Only the FIRST item's create() should trigger a real project resolve --
    # the rest hit the shared WorkPackageResolutionContext's cache.
    assert project_resolve_calls == 1


# ----------------------------------------------------------------------
# update()
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_preview_without_commit_does_not_call_commit_update() -> None:
    api = _FakeWorkPackageApi()
    service, _ = _service(api)

    result = await service.update(work_package_id=6, subject="Renamed", confirm=False)

    assert result.requires_confirmation is True
    assert result.confirmed is False
    assert api.commit_update_calls == []
    assert len(api.validate_update_calls) == 1


@pytest.mark.asyncio
async def test_update_commit_calls_commit_update() -> None:
    api = _FakeWorkPackageApi()
    service, _ = _service(api)

    result = await service.update(work_package_id=6, subject="Renamed", confirm=True)

    assert result.confirmed is True
    assert len(api.commit_update_calls) == 1
    ref, payload = api.commit_update_calls[0]
    assert ref == "6"
    assert payload["subject"] == "Renamed"


@pytest.mark.asyncio
async def test_update_denies_write_when_current_project_not_write_allowed() -> None:
    api = _FakeWorkPackageApi()
    api._records_by_id[6] = _record(6, payload=_payload(6, project_href="/api/v3/projects/20", project_title="Other"))
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("demo",))
    service, _ = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.update(work_package_id=6, subject="Renamed", confirm=False)


@pytest.mark.asyncio
async def test_update_rejects_write_to_hidden_field() -> None:
    api = _FakeWorkPackageApi()
    settings = dataclasses.replace(make_settings(), hidden_fields={"work_package": ("subject",)})
    service, _ = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden"):
        await service.update(work_package_id=6, subject="Renamed", confirm=False)


@pytest.mark.asyncio
async def test_update_reports_validation_errors_as_not_ready() -> None:
    api = _FakeWorkPackageApi()
    api.validation_errors_queue.append({"subject": "is too long"})
    service, _ = _service(api)

    result = await service.update(work_package_id=6, subject="Renamed", confirm=False)

    assert result.ready is False
    assert result.validation_errors == {"subject": "is too long"}


@pytest.mark.asyncio
async def test_update_resolves_parent_with_write_true_and_clear_parent_passes_through() -> None:
    from openproject_ce_mcp.app.services.work_package_service import CLEAR_PARENT

    api = _FakeWorkPackageApi()
    seen_write: list[bool] = []

    async def resolve_work_package_id(ref, *, write=False):
        seen_write.append(write)
        return int(ref)

    service, _ = _service(api, resolve_work_package_id=resolve_work_package_id)

    await service.update(work_package_id=6, parent_work_package_id=7, confirm=False)
    assert seen_write == [True]

    # CLEAR_PARENT must pass through unresolved -- no resolver call at all.
    seen_write.clear()
    await service.update(work_package_id=6, parent_work_package_id=CLEAR_PARENT, confirm=False)
    assert seen_write == []
    _, payload = api.validate_update_calls[-1]
    assert payload["_links"]["parent"]["href"] is None


@pytest.mark.asyncio
async def test_update_missing_project_link_raises() -> None:
    api = _FakeWorkPackageApi()
    api._records_by_id[6] = _record(6, payload={"id": 6, "subject": "WP", "_links": {}})
    service, _ = _service(api)

    with pytest.raises(OpenProjectServerError, match="missing a project link"):
        await service.update(work_package_id=6, subject="Renamed", confirm=False)


# ----------------------------------------------------------------------
# update() auto-percentage/auto-remaining-time derivation
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_autofills_percentage_and_remaining_when_closing_without_estimate() -> None:
    api = _FakeWorkPackageApi()
    api.next_schema = {
        "percentageDone": {"writable": True},
        "remainingTime": {"writable": True},
    }
    status_api = _FakeStatusApi(is_closed=True)
    service, _ = _service(api, status_api=status_api)

    result = await service.update(work_package_id=6, status="Closed", confirm=False)

    assert result.ready is True
    assert len(api.validate_update_calls) == 2  # first probe + re-validate after auto-fill
    _, second_payload = api.validate_update_calls[-1]
    assert second_payload["percentageDone"] == 100
    assert second_payload["remainingTime"] is None  # CLEAR-derived: no existing estimate


@pytest.mark.asyncio
async def test_update_autofills_remaining_as_pt0h_when_estimate_exists() -> None:
    api = _FakeWorkPackageApi()
    api._records_by_id[6] = _record(6, payload={**_payload(6), "estimatedTime": "PT8H"})
    api.next_schema = {
        "percentageDone": {"writable": True},
        "remainingTime": {"writable": True},
    }
    status_api = _FakeStatusApi(is_closed=True)
    service, _ = _service(api, status_api=status_api)

    await service.update(work_package_id=6, status="Closed", confirm=False)

    _, second_payload = api.validate_update_calls[-1]
    assert second_payload["remainingTime"] == "PT0H"


@pytest.mark.asyncio
async def test_update_skips_autofill_when_schema_not_writable() -> None:
    api = _FakeWorkPackageApi()
    api.next_schema = {
        "percentageDone": {"writable": False},
        "remainingTime": {"writable": False},
    }
    status_api = _FakeStatusApi(is_closed=True)
    service, _ = _service(api, status_api=status_api)

    await service.update(work_package_id=6, status="Closed", confirm=False)

    # No second validate_update call -- nothing actually changed.
    assert len(api.validate_update_calls) == 1


@pytest.mark.asyncio
async def test_update_preserves_explicit_values_on_close() -> None:
    api = _FakeWorkPackageApi()
    status_api = _FakeStatusApi(is_closed=True)
    service, _ = _service(api, status_api=status_api)

    result = await service.update(
        work_package_id=6, status="Closed", percentage_done=42, remaining_time="PT3H", confirm=False
    )

    assert result.ready is True
    # Caller explicitly supplied both -- no auto-derivation lookup needed.
    assert status_api.get_status_calls == []
    assert len(api.validate_update_calls) == 1
    _, payload = api.validate_update_calls[-1]
    assert payload["percentageDone"] == 42
    assert payload["remainingTime"] == "PT3H"


@pytest.mark.asyncio
async def test_update_no_autofill_when_status_not_changing() -> None:
    api = _FakeWorkPackageApi()
    status_api = _FakeStatusApi(is_closed=True)
    service, _ = _service(api, status_api=status_api)

    await service.update(work_package_id=6, subject="Renamed", confirm=False)

    assert status_api.get_status_calls == []
    assert len(api.validate_update_calls) == 1


@pytest.mark.asyncio
async def test_update_read_disabled_but_write_enabled_still_autofills() -> None:
    # update() deliberately has NO access.ensure_read_enabled gate at all
    # (verified against client.py's flat update_work_package, which never
    # called it either) -- an instance can have work-package writes enabled
    # with reads entirely disabled, and this must keep working, INCLUDING the
    # internal auto-derivation status lookup (which also must not go through
    # StatusPriorityTypeService, since that WOULD gate on read-enablement).
    api = _FakeWorkPackageApi()
    api.next_schema = {
        "percentageDone": {"writable": True},
        "remainingTime": {"writable": True},
    }
    status_api = _FakeStatusApi(is_closed=True)
    settings = dataclasses.replace(make_settings(), enable_work_package_read=False)
    service, _ = _service(api, settings=settings, status_api=status_api)

    result = await service.update(work_package_id=6, status="Closed", confirm=False)

    assert result.ready is True
    assert status_api.get_status_calls == [5]


# ----------------------------------------------------------------------
# bulk_update()
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_update_commit_updates_every_item() -> None:
    api = _FakeWorkPackageApi()
    service, _ = _service(api)

    result = await service.bulk_update(
        items=[{"work_package_id": 6, "subject": "Renamed"}],
        confirm=True,
    )

    assert result.succeeded == 1
    assert len(api.commit_update_calls) == 1


@pytest.mark.asyncio
async def test_bulk_update_partial_failure_is_isolated_per_item() -> None:
    api = _FakeWorkPackageApi()
    service, _ = _service(api)

    result = await service.bulk_update(
        items=[
            {"work_package_id": 6, "subject": "Good"},
            {"work_package_id": 999, "subject": "Missing"},
        ],
        confirm=False,
    )

    assert result.total == 2
    assert result.succeeded == 1
    assert result.failed == 1


# ----------------------------------------------------------------------
# delete()
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_preview_without_commit_does_not_call_delete() -> None:
    api = _FakeWorkPackageApi()
    service, _ = _service(api)

    result = await service.delete(work_package_id=6, confirm=False)

    assert result.requires_confirmation is True
    assert result.confirmed is False
    assert result.result is not None
    assert api.delete_calls == []


@pytest.mark.asyncio
async def test_delete_commit_calls_delete_and_returns_no_result() -> None:
    api = _FakeWorkPackageApi()
    service, _ = _service(api)

    result = await service.delete(work_package_id=6, confirm=True)

    assert result.confirmed is True
    assert result.result is None
    assert api.delete_calls == ["6"]


@pytest.mark.asyncio
async def test_delete_denies_write_when_project_not_write_allowed() -> None:
    api = _FakeWorkPackageApi()
    api._records_by_id[6] = _record(6, payload=_payload(6, project_href="/api/v3/projects/20", project_title="Other"))
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("demo",))
    service, _ = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.delete(work_package_id=6, confirm=False)


# ----------------------------------------------------------------------
# add_comment()
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_comment_preview_without_commit_does_not_post() -> None:
    api = _FakeWorkPackageApi()
    service, _ = _service(api)

    result = await service.add_comment(work_package_id=6, comment="Hello", confirm=False)

    assert result.requires_confirmation is True
    assert result.confirmed is False
    assert api.post_comment_calls == []


@pytest.mark.asyncio
async def test_add_comment_commit_posts_and_returns_normalized_result() -> None:
    activity_api = _FakeActivityApi()
    api = _FakeWorkPackageApi()
    service, _ = _service(api, activity_api=activity_api)

    result = await service.add_comment(work_package_id=6, comment="Hello", internal=True, notify=True, confirm=True)

    assert result.confirmed is True
    assert len(api.post_comment_calls) == 1
    call = api.post_comment_calls[0]
    assert call == {"work_package_ref": "6", "comment": "Hello", "internal": True, "notify": True}
    assert result.result is not None
    assert result.result.comment == "Hello"
    # Aggregated-journal suppression: details/details_truncated/created_at
    # always cleared on the echoed result.
    assert result.result.details is None
    assert result.result.details_truncated is False
    assert result.result.created_at is None


@pytest.mark.asyncio
async def test_add_comment_rejects_write_to_hidden_comment_field() -> None:
    api = _FakeWorkPackageApi()
    settings = dataclasses.replace(make_settings(), hidden_fields={"activity": ("comment",)})
    service, _ = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden"):
        await service.add_comment(work_package_id=6, comment="Hello", confirm=False)

    # The hidden-field check must run BEFORE any network call -- not just
    # before the write itself.
    assert api.get_calls == []
    assert api.post_comment_calls == []


@pytest.mark.asyncio
async def test_add_comment_masking_is_activity_scoped_not_work_package_scoped() -> None:
    # Entity-scope regression guard: hiding a "work_package"-scope field must
    # NOT affect add_comment()'s "activity"-scope masking, and vice versa --
    # each hidden_fields call passes an explicit entity string, this proves
    # there's no accidental cross-entity leakage.
    activity_api = _FakeActivityApi()
    api = _FakeWorkPackageApi()
    settings = dataclasses.replace(make_settings(), hidden_fields={"work_package": ("description",)})
    service, _ = _service(api, activity_api=activity_api, settings=settings)

    # Hiding "work_package.description" must not block writing the comment
    # itself (a different entity/field).
    result = await service.add_comment(work_package_id=6, comment="Hello", confirm=False)
    assert result.requires_confirmation is True


@pytest.mark.asyncio
async def test_add_comment_denies_write_when_project_not_write_allowed() -> None:
    api = _FakeWorkPackageApi()
    api._records_by_id[6] = _record(6, payload=_payload(6, project_href="/api/v3/projects/20", project_title="Other"))
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("demo",))
    service, _ = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.add_comment(work_package_id=6, comment="Hello", confirm=False)


@pytest.mark.asyncio
async def test_add_comment_result_masked_when_comment_hidden_in_output() -> None:
    activity_api = _FakeActivityApi()
    api = _FakeWorkPackageApi()
    settings = dataclasses.replace(make_settings(), hidden_fields={"activity": ("user",)})
    service, _ = _service(api, activity_api=activity_api, settings=settings)

    result = await service.add_comment(work_package_id=6, comment="Hello", confirm=True)

    assert result.result is not None
    assert result.result._hidden_keys == frozenset({"user"})


# ----------------------------------------------------------------------
# _fill_missing_activity_user
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fill_missing_activity_user_success_merges_fetched_user_link() -> None:
    activity_api = _FakeActivityApi()
    activity_api.next_get_raw = {"id": 55, "_links": {"user": {"title": "Jane"}}}
    api = _FakeWorkPackageApi()
    service, _ = _service(api, activity_api=activity_api)

    result = await service._fill_missing_activity_user({"id": 55, "_links": {}})

    assert result["_links"]["user"]["title"] == "Jane"
    assert activity_api.get_raw_calls == [55]


@pytest.mark.asyncio
async def test_fill_missing_activity_user_skipped_when_already_present() -> None:
    activity_api = _FakeActivityApi()
    api = _FakeWorkPackageApi()
    service, _ = _service(api, activity_api=activity_api)

    activity = {"id": 55, "_links": {"user": {"title": "Existing"}}}
    result = await service._fill_missing_activity_user(activity)

    assert result is activity
    assert activity_api.get_raw_calls == []


@pytest.mark.asyncio
async def test_fill_missing_activity_user_skipped_when_hidden() -> None:
    activity_api = _FakeActivityApi()
    settings = dataclasses.replace(make_settings(), hidden_fields={"activity": ("user",)})
    api = _FakeWorkPackageApi()
    service, _ = _service(api, activity_api=activity_api, settings=settings)

    activity = {"id": 55, "_links": {}}
    result = await service._fill_missing_activity_user(activity)

    assert result is activity
    assert activity_api.get_raw_calls == []


@pytest.mark.asyncio
async def test_fill_missing_activity_user_skipped_when_no_usable_id() -> None:
    activity_api = _FakeActivityApi()
    api = _FakeWorkPackageApi()
    service, _ = _service(api, activity_api=activity_api)

    activity = {"id": None, "_links": {}}
    result = await service._fill_missing_activity_user(activity)

    assert result is activity
    assert activity_api.get_raw_calls == []


@pytest.mark.asyncio
async def test_fill_missing_activity_user_swallows_fetch_failure() -> None:
    class _FailingActivityApi(_FakeActivityApi):
        async def get_raw(self, activity_id: int) -> dict:
            self.get_raw_calls.append(activity_id)
            raise OpenProjectError("boom")

    activity_api = _FailingActivityApi()
    api = _FakeWorkPackageApi()
    service, _ = _service(api, activity_api=activity_api)

    activity = {"id": 55, "_links": {}}
    result = await service._fill_missing_activity_user(activity)

    assert result is activity
    assert activity_api.get_raw_calls == [55]


# ----------------------------------------------------------------------
# No read-enablement gate on any write method (cross-cutting regression
# guard, found during the OPM-286 wiring pass: none of the 5 flat write
# methods (create/create_subtask/update/delete/add_comment) ever called
# _ensure_read_enabled, verified against client.py's originals -- a Service
# method that added one would be a real behavioral regression, since an
# instance can have work-package writes enabled with reads entirely
# disabled).
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_works_with_read_disabled() -> None:
    api = _FakeWorkPackageApi()
    settings = dataclasses.replace(make_settings(), enable_work_package_read=False)
    service, _ = _service(api, settings=settings)

    result = await service.create(project="demo", type="Task", subject="New WP", confirm=False)

    assert result.ready is True


@pytest.mark.asyncio
async def test_create_subtask_works_with_read_disabled() -> None:
    api = _FakeWorkPackageApi()
    settings = dataclasses.replace(make_settings(), enable_work_package_read=False)
    service, _ = _service(api, settings=settings)

    result = await service.create_subtask(parent_work_package_id=6, type="Task", subject="Child", confirm=False)

    assert result.ready is True


@pytest.mark.asyncio
async def test_delete_works_with_read_disabled() -> None:
    api = _FakeWorkPackageApi()
    settings = dataclasses.replace(make_settings(), enable_work_package_read=False)
    service, _ = _service(api, settings=settings)

    result = await service.delete(work_package_id=6, confirm=False)

    assert result.requires_confirmation is True


@pytest.mark.asyncio
async def test_add_comment_works_with_read_disabled() -> None:
    api = _FakeWorkPackageApi()
    settings = dataclasses.replace(make_settings(), enable_work_package_read=False)
    service, _ = _service(api, settings=settings)

    result = await service.add_comment(work_package_id=6, comment="Hello", confirm=False)

    assert result.requires_confirmation is True
