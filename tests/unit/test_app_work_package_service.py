from __future__ import annotations

import asyncio
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
from openproject_ce_mcp.app.resolvers.work_package_resolver import WorkPackageResolver
from openproject_ce_mcp.app.services.work_package_service import WorkPackageService
from openproject_ce_mcp.models import (
    ActivitySummary,
    CurrentUser,
    StatusSummary,
    WorkPackageDetail,
    WorkPackageGroupSums,
    WorkPackageSummary,
)

PROJECT_ID_TO_IDENTIFIER = {1: "demo", 20: "other"}


def _summary(
    wp_id: int = 6,
    *,
    subject: str = "Demo WP",
    project: str | None = "Demo",
    description: str | None = "Some description",
    description_truncated: bool = False,
    description_length: int | None = None,
    version: str | None = None,
    target_versions: list[str] | None = None,
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
        version=version,
        target_versions=target_versions if target_versions is not None else [],
        sprint=None,
        start_date=None,
        due_date=None,
        description=description,
        has_description=description is not None,
        description_truncated=description_truncated,
        description_length=description_length,
    )


def _detail(
    wp_id: int = 6,
    *,
    children=None,
    ancestors=None,
    version: str | None = None,
    target_versions: list[str] | None = None,
) -> WorkPackageDetail:
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
        version=version,
        target_versions=target_versions if target_versions is not None else [],
        sprint=None,
        parent_id=None,
        parent_display_id=None,
        start_date=None,
        due_date=None,
        lock_version=1,
        description="Some description",
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
    def __init__(
        self,
        *,
        raw_elements: list[dict] | None = None,
        server_total: int | None = None,
        raw_groups: list[dict] | None = None,
        raw_total_sums: dict | None = None,
    ) -> None:
        self._raw_elements = raw_elements if raw_elements is not None else [_payload()]
        self._server_total = server_total if server_total is not None else len(self._raw_elements)
        self._raw_groups = raw_groups
        self._raw_total_sums = raw_total_sums
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
        self.parse_form_resolve_links_calls: list[bool] = []
        self.parse_form_allowed_values_cache_calls: list[object] = []

    async def list(self, *, filters, offset, limit, sort_by, group_by, include_sums: bool = False) -> WorkPackagePage:
        self.list_calls.append(
            {"filters": filters, "offset": offset, "limit": limit, "group_by": group_by, "include_sums": include_sums}
        )
        return WorkPackagePage(
            raw_elements=self._raw_elements,
            server_total=self._server_total,
            raw_groups=self._raw_groups if include_sums else None,
            raw_total_sums=self._raw_total_sums if include_sums else None,
        )

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

    async def parse_form(
        self, form: dict, *, resolve_links: bool = False, allowed_values_cache=None
    ) -> WorkPackageFormResult:
        self.parse_form_resolve_links_calls.append(resolve_links)
        self.parse_form_allowed_values_cache_calls.append(allowed_values_cache)
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


class _TargetVersionsEchoingWorkPackageApi(_FakeWorkPackageApi):
    async def validate_create(self, project_id: str, payload: dict) -> dict:
        form = await super().validate_create(project_id, payload)
        form["_embedded"]["payload"] = {
            **form["_embedded"]["payload"],
            "_links": {**form["_embedded"]["payload"].get("_links", {}), "targetVersions": []},
        }
        return form

    async def validate_update(self, work_package_ref: str, payload: dict) -> dict:
        form = await super().validate_update(work_package_ref, payload)
        form["_embedded"]["payload"] = {
            **form["_embedded"]["payload"],
            "_links": {**form["_embedded"]["payload"].get("_links", {}), "targetVersions": []},
        }
        return form


class _FakeStatusApi:
    def __init__(self, *, is_closed: bool = False) -> None:
        self.is_closed = is_closed
        self.get_status_calls: list[int] = []

    async def get_status(self, status_id: int) -> StatusRecord:
        self.get_status_calls.append(status_id)
        name = "Closed" if self.is_closed else "New"
        return StatusRecord(
            summary=StatusSummary(
                id=status_id,
                name=name,
                is_default=False,
                is_closed=self.is_closed,
                color=None,
                position=1,
            ),
            lookup_name=name,
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


def _bulk_from_single(single):
    """Builds a `WorkPackageProjectAllowedBulkCheck` fake from an existing
    single-href `WorkPackageProjectAllowedCheck` fake: since
    `_filter_hierarchy_allowlist` now resolves children+ancestors through the
    bulk seam exclusively, every single-href fake in this file needs a bulk
    equivalent too -- this derives one generically instead of hand-writing a
    bulk version of each (`_all_project_allowed`, `_no_project_allowed`,
    per-test custom predicates)."""

    async def bulk(hrefs, *, context) -> dict[str, bool | Exception]:
        outcomes: dict[str, bool | Exception] = {}
        for href in dict.fromkeys(hrefs):
            cached = context.get(href)
            if cached is not None:
                outcomes[href] = cached
                continue
            allowed = await single(href, context=None)
            context.set(href, allowed)
            outcomes[href] = allowed
        return outcomes

    return bulk


def _service(
    api: _FakeWorkPackageApi | None = None,
    *,
    settings=None,
    project_id_to_identifier: dict[int, str] | None = None,
    work_package_project_allowed=None,
    work_package_project_allowed_bulk=None,
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
        try:
            return int(ref)
        except ValueError:
            raise NotFoundError(f"OpenProject work package '{ref}' was not found.") from None

    async def current_user():
        return CurrentUser(id=42, name="Admin", login="admin")

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
        work_package_project_allowed_bulk=work_package_project_allowed_bulk
        or _bulk_from_single(work_package_project_allowed or _all_project_allowed),
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
async def test_list_my_open_exposes_custom_fields_via_same_normalize_path() -> None:
    """Smoke-level regression guard: list_my_open_work_packages
    reuses the same normalize_work_package_summary/WorkPackageService._stamp
    path as list()/search() -- custom_fields must appear automatically, with
    no list_my_open-specific production code required."""
    summary_with_cf = dataclasses.replace(_summary(6), custom_fields={"customField1": "Acme Corp"})
    payload = _payload(6)
    api = _FakeWorkPackageApi(raw_elements=[payload])
    api._records_by_id[6] = _record(6, summary=summary_with_cf, payload=payload)
    service, _ = _service(api)

    result = await service.list_my_open()

    assert result.results[0].custom_fields == {"customField1": "Acme Corp"}


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
async def test_list_include_sums_populates_groups_and_total_sums_under_open_scope() -> None:
    raw_groups = [{"value": "New", "count": 3, "sums": {"estimatedTime": "P1D"}}]
    raw_total_sums = {"estimatedTime": "P2D"}
    api = _FakeWorkPackageApi(raw_groups=raw_groups, raw_total_sums=raw_total_sums)
    service, _ = _service(api, settings=dataclasses.replace(make_settings(), read_projects=("*",)))

    result = await service.list(group_by="status", include_sums=True)

    assert result.groups == [WorkPackageGroupSums(value="New", count=3, sums={"estimatedTime": "P1D"})]
    assert result.total_sums == {"estimatedTime": "P2D"}
    assert api.list_calls[0]["include_sums"] is True


@pytest.mark.asyncio
async def test_list_include_sums_without_group_by_still_populates_total_sums() -> None:
    """OpenProject computes totalSums over the whole filtered result set even
    without groupBy -- confirmed live against a real instance. Only `groups`
    depends on group_by being set; `total_sums` does not."""
    api = _FakeWorkPackageApi(raw_groups=None, raw_total_sums={"estimatedTime": "P2D"})
    service, _ = _service(api, settings=dataclasses.replace(make_settings(), read_projects=("*",)))

    result = await service.list(include_sums=True)

    assert result.groups is None
    assert result.total_sums == {"estimatedTime": "P2D"}


@pytest.mark.asyncio
async def test_list_include_sums_defaults_to_none_when_not_requested() -> None:
    service, api = _service()

    result = await service.list(group_by="status")

    assert result.groups is None
    assert result.total_sums is None
    assert api.list_calls[0]["include_sums"] is False


@pytest.mark.asyncio
async def test_search_include_sums_short_circuits_under_restricted_scope_without_project() -> None:
    """Regression guard for the scope-leak this feature could otherwise
    introduce: search() with no explicit project and a restricted
    OPENPROJECT_READ_PROJECTS never achieves total_is_scope_safe, so
    include_sums must never reach the adapter -- OpenProject's own groups/
    totalSums would otherwise be computed over every project the search
    matched, not just the caller's allowed set."""
    raw_groups = [{"value": "New", "count": 3, "sums": {}}]
    api = _FakeWorkPackageApi(raw_groups=raw_groups, raw_total_sums={"estimatedTime": "P1D"})
    service, _ = _service(api, settings=dataclasses.replace(make_settings(), read_projects=("demo",)))

    result = await service.search(search="foo", group_by="status", include_sums=True)

    assert result.groups is None
    assert result.total_sums is None
    assert api.list_calls[0]["include_sums"] is False


@pytest.mark.asyncio
async def test_search_include_sums_populates_when_explicit_project_given() -> None:
    raw_groups = [{"value": "New", "count": 1, "sums": {}}]
    api = _FakeWorkPackageApi(raw_groups=raw_groups, raw_total_sums={"estimatedTime": "PT1H"})
    service, _ = _service(api, settings=dataclasses.replace(make_settings(), read_projects=("demo",)))

    result = await service.search(search="foo", project="demo", group_by="status", include_sums=True)

    assert result.groups == [WorkPackageGroupSums(value="New", count=1, sums={})]
    assert result.total_sums == {"estimatedTime": "PT1H"}
    assert api.list_calls[0]["include_sums"] is True


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
async def test_list_does_not_report_truncated_when_limit_lands_exactly_on_last_allowed_item() -> None:
    """Regression: under a restricted, non-wildcard OPENPROJECT_READ_PROJECTS,
    exactly `limit` allowed items exist and nothing else does. list() always
    adds a server-side project_id filter scoped to the allowed projects (see
    list()'s total_is_scope_safe derivation), so it goes through
    _list_collection_fast_path, not the scanned path -- but that fast path
    still applies the client-side allowlist as a second line of defense, and
    still trims to `limit` rather than trusting the server to have honored
    the requested page size exactly."""
    allowed = [_payload(1, project_href="/api/v3/projects/1"), _payload(2, project_href="/api/v3/projects/1")]
    api = _FakeWorkPackageApi(raw_elements=allowed, server_total=2)
    service, _ = _service(
        api,
        settings=dataclasses.replace(make_settings(), read_projects=("demo",)),
        project_id_to_identifier={1: "demo"},
    )

    result = await service.list(limit=2)

    assert [r.id for r in result.results] == [1, 2]
    assert result.truncated is False
    assert result.next_offset is None
    # The fast path requests exactly `limit` from the server (project_id
    # filter already narrows the query server-side).
    assert api.list_calls[0]["limit"] == 2


@pytest.mark.asyncio
async def test_list_reports_truncated_when_a_further_allowed_item_exists_beyond_limit() -> None:
    """Sibling of the above: a genuine (limit + 1)-th allowed item IS present
    -- truncated must still correctly report True in that case."""
    allowed = [
        _payload(1, project_href="/api/v3/projects/1"),
        _payload(2, project_href="/api/v3/projects/1"),
        _payload(3, project_href="/api/v3/projects/1"),
    ]
    api = _FakeWorkPackageApi(raw_elements=allowed, server_total=3)
    service, _ = _service(
        api,
        settings=dataclasses.replace(make_settings(), read_projects=("demo",)),
        project_id_to_identifier={1: "demo"},
    )

    result = await service.list(limit=2)

    assert [r.id for r in result.results] == [1, 2]
    assert result.truncated is True
    assert result.next_offset == 2


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


# ---------------------------------------------------------------------------
# custom_fields/custom_comments hide-on-read (key-only match)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_hides_custom_field_matched_by_raw_key() -> None:
    detail_with_cf = dataclasses.replace(
        _detail(6),
        custom_fields={"customField1": "Acme Corp", "customField2": 42},
        custom_comments={"customComment1": "a note", "customComment2": "kept"},
    )
    api = _FakeWorkPackageApi()
    api._records_by_id[6] = _record(6, detail=detail_with_cf)
    settings = dataclasses.replace(make_settings(), hide_custom_fields=("customField1",))
    service, _ = _service(api, settings=settings)

    detail = await service.get(6)

    assert detail.custom_fields == {"customField2": 42}
    # Hiding customField1 also hides its matching customComment1 counterpart
    # (derived from the removed customField<N> id, not matched directly --
    # customComment<N> keys never match a customField<N> hide pattern).
    assert detail.custom_comments == {"customComment2": "kept"}


@pytest.mark.asyncio
async def test_get_does_not_hide_custom_field_matched_only_by_friendly_name() -> None:
    """Read-side hide-on-read is KEY-ONLY (per the approved strategy) --
    a pattern written as the custom field's friendly name (e.g. "Story
    points") has no effect on custom_fields, unlike the write path's
    ensure_custom_field_writable, which matches both the schema name and the
    key. This is the read/write asymmetry documented in field-hiding.md."""
    detail_with_cf = dataclasses.replace(_detail(6), custom_fields={"customField1": 8})
    api = _FakeWorkPackageApi()
    api._records_by_id[6] = _record(6, detail=detail_with_cf)
    settings = dataclasses.replace(make_settings(), hide_custom_fields=("Story points",))
    service, _ = _service(api, settings=settings)

    detail = await service.get(6)

    assert detail.custom_fields == {"customField1": 8}


@pytest.mark.asyncio
async def test_get_hide_custom_fields_wildcard_matches_raw_key() -> None:
    detail_with_cf = dataclasses.replace(
        _detail(6), custom_fields={"customField1": "a", "customField2": "b", "customField30": "c"}
    )
    api = _FakeWorkPackageApi()
    api._records_by_id[6] = _record(6, detail=detail_with_cf)
    settings = dataclasses.replace(make_settings(), hide_custom_fields=("customField*",))
    service, _ = _service(api, settings=settings)

    detail = await service.get(6)

    assert detail.custom_fields is None


@pytest.mark.asyncio
async def test_list_hides_custom_field_matched_by_raw_key_on_summary() -> None:
    summary_with_cf = _summary(6)
    summary_with_cf = dataclasses.replace(summary_with_cf, custom_fields={"customField1": "a", "customField2": "b"})
    payload = _payload(6)
    api = _FakeWorkPackageApi(raw_elements=[payload])
    api._records_by_id[6] = _record(6, summary=summary_with_cf, payload=payload)
    settings = dataclasses.replace(make_settings(), hide_custom_fields=("customField2",))
    service, _ = _service(api, settings=settings)

    result = await service.list()

    assert result.results[0].custom_fields == {"customField1": "a"}


@pytest.mark.asyncio
async def test_get_all_custom_fields_hidden_via_whole_field_hide_resets_truncated_flag() -> None:
    """Hiding the WHOLE custom_fields field (OPENPROJECT_HIDE_WORK_PACKAGE_FIELDS
    =custom_fields) must also reset custom_fields_truncated to False --
    otherwise a truncation flag would leak metadata about hidden data, even
    though custom_fields itself is dropped by apply_hidden_fields. Mirrors
    the existing description_truncated/description_length reset above."""
    detail_with_cf = dataclasses.replace(_detail(6), custom_fields={"customField1": "a"}, custom_fields_truncated=True)
    api = _FakeWorkPackageApi()
    api._records_by_id[6] = _record(6, detail=detail_with_cf)
    settings = dataclasses.replace(make_settings(), hidden_fields={"work_package": ("custom_fields",)})
    service, _ = _service(api, settings=settings)

    detail = await service.get(6)

    assert "custom_fields" in detail._hidden_keys  # type: ignore[attr-defined]
    assert detail.custom_fields_truncated is False


@pytest.mark.asyncio
async def test_get_all_custom_comments_hidden_via_whole_field_hide_resets_truncated_flag() -> None:
    detail_with_cc = dataclasses.replace(
        _detail(6), custom_comments={"customComment1": "note"}, custom_comments_truncated=True
    )
    api = _FakeWorkPackageApi()
    api._records_by_id[6] = _record(6, detail=detail_with_cc)
    settings = dataclasses.replace(make_settings(), hidden_fields={"work_package": ("custom_comments",)})
    service, _ = _service(api, settings=settings)

    detail = await service.get(6)

    assert "custom_comments" in detail._hidden_keys  # type: ignore[attr-defined]
    assert detail.custom_comments_truncated is False


@pytest.mark.asyncio
async def test_get_hiding_version_also_masks_target_versions() -> None:
    # version/target_versions are a coupled alias pair -- hiding just one of
    # them via OPENPROJECT_HIDE_WORK_PACKAGE_FIELDS must hide both, or the
    # other trivially leaks the "hidden" one back out.
    detail_with_versions = dataclasses.replace(_detail(6), version="1.0", target_versions=["1.0"])
    api = _FakeWorkPackageApi()
    api._records_by_id[6] = _record(6, detail=detail_with_versions)
    settings = dataclasses.replace(make_settings(), hidden_fields={"work_package": ("version",)})
    service, _ = _service(api, settings=settings)

    detail = await service.get(6)

    assert detail.version is None
    assert detail.target_versions == []
    assert detail._hidden_keys >= {"version", "target_versions"}  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_get_hiding_target_versions_also_masks_version() -> None:
    detail_with_versions = dataclasses.replace(_detail(6), version="1.0", target_versions=["1.0"])
    api = _FakeWorkPackageApi()
    api._records_by_id[6] = _record(6, detail=detail_with_versions)
    settings = dataclasses.replace(make_settings(), hidden_fields={"work_package": ("target_versions",)})
    service, _ = _service(api, settings=settings)

    detail = await service.get(6)

    assert detail.version is None
    assert detail.target_versions == []
    assert detail._hidden_keys >= {"version", "target_versions"}  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_get_partial_key_only_hide_leaves_truncated_flag_as_originally_computed() -> None:
    """When only SOME keys are masked via the key-only custom-field hide
    (not the whole field), custom_fields_truncated is left as originally
    computed (the raw-payload pre-mask truncation signal) -- a documented
    choice, distinct from _filter_hierarchy_allowlist's scope-allowlist
    re-derivation (a different class of leak; see _mask_custom_field_values'
    docstring)."""
    detail_with_cf = dataclasses.replace(
        _detail(6), custom_fields={"customField1": "a", "customField2": "b"}, custom_fields_truncated=True
    )
    api = _FakeWorkPackageApi()
    api._records_by_id[6] = _record(6, detail=detail_with_cf)
    settings = dataclasses.replace(make_settings(), hide_custom_fields=("customField1",))
    service, _ = _service(api, settings=settings)

    detail = await service.get(6)

    assert detail.custom_fields == {"customField2": "b"}
    assert detail.custom_fields_truncated is True


@pytest.mark.asyncio
async def test_get_no_hide_custom_fields_configured_leaves_dict_identity_unchanged() -> None:
    """No OPENPROJECT_HIDE_CUSTOM_FIELDS configured -> _mask_custom_field_keys
    returns the original dict object unchanged (no rebuild), per the
    documented no-op-avoidance in _mask_custom_field_keys."""
    original = {"customField1": "a"}
    detail_with_cf = dataclasses.replace(_detail(6), custom_fields=original)
    api = _FakeWorkPackageApi()
    api._records_by_id[6] = _record(6, detail=detail_with_cf)
    service, _ = _service(api, settings=make_settings())

    detail = await service.get(6)

    assert detail.custom_fields is original


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
async def test_get_filters_hierarchy_deduplicates_an_href_shared_by_children_and_ancestors() -> None:
    """Children and ancestors are combined into ONE
    deduplicated bulk resolution, not resolved separately -- a shared href
    appearing in both arrays (e.g. the same work package genuinely is both a
    sibling reference AND an ancestor in some malformed/edge-case server
    response) must only trigger one resolution, not two."""
    shared_href = "/api/v3/work_packages/10"
    children = [{"href": shared_href, "title": "Shared", "display_id": None}]
    ancestors = [{"href": shared_href, "title": "Shared", "display_id": None}]
    detail = _detail(6, children=children, ancestors=ancestors)
    record = _record(6, detail=detail)
    api = _FakeWorkPackageApi()
    api._records_by_id[6] = record

    calls: list[list[str]] = []

    async def tracking_bulk(hrefs, *, context) -> dict[str, bool | Exception]:
        unique = list(dict.fromkeys(hrefs))
        calls.append(unique)
        outcomes: dict[str, bool | Exception] = {}
        for href in unique:
            outcomes[href] = True
            context.set(href, True)
        return outcomes

    service, _ = _service(
        api,
        settings=dataclasses.replace(make_settings(), read_projects=("demo",)),
        work_package_project_allowed_bulk=tracking_bulk,
    )

    result = await service.get(6)

    assert result.children == children
    assert result.ancestors == ancestors
    # ONE bulk call, for the whole combined+deduplicated href set -- not one
    # call for children and a separate one for ancestors, and the shared
    # href appears only once.
    assert calls == [[shared_href]]


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
async def test_get_batch_exposes_custom_fields_via_same_normalize_path() -> None:
    """Smoke-level regression guard: get_work_packages (batch)
    reuses the same normalize_work_package_detail/WorkPackageService._stamp
    path as get() -- custom_fields/custom_comments must appear automatically,
    with no batch-specific production code required."""
    detail_with_cf = dataclasses.replace(_detail(6), custom_fields={"customField1": "Acme Corp"})
    api = _FakeWorkPackageApi()
    api._records_by_id[6] = _record(6, detail=detail_with_cf)
    service, _ = _service(api)

    result = await service.get_batch(ids=[6])

    item = result.results[0]
    assert item.success is True
    assert item.work_package is not None
    assert item.work_package.custom_fields == {"customField1": "Acme Corp"}


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


class _ConcurrencyTrackingWorkPackageApi(_FakeWorkPackageApi):
    """Records the observed peak of concurrent in-flight `get()` calls.

    Each call increments a counter, yields control (so overlapping calls
    actually interleave instead of running back-to-back under a single
    event-loop tick), then decrements -- the same shape a real HTTP call's
    await point would produce.
    """

    def __init__(self, *, ids: list[int]) -> None:
        super().__init__()
        self._records_by_id = {i: _record(i) for i in ids}
        self.active = 0
        self.peak_active = 0

    async def get(self, work_package_ref: str, *, text_limit: int | None = None) -> WorkPackageRecord:
        self.active += 1
        self.peak_active = max(self.peak_active, self.active)
        try:
            await asyncio.sleep(0)
            return await super().get(work_package_ref, text_limit=text_limit)
        finally:
            self.active -= 1


@pytest.mark.asyncio
async def test_get_batch_bounds_concurrent_requests_to_the_semaphore_limit() -> None:
    """Regression: get_batch used to fan out asyncio.gather with
    no concurrency cap at all -- up to BATCH_READ_MAX_IDS (100) requests
    could fire simultaneously. The shared, Service-level semaphore must keep
    the observed peak at or below its configured limit."""
    ids = list(range(1, 51))
    api = _ConcurrencyTrackingWorkPackageApi(ids=ids)
    service, _ = _service(api)

    await service.get_batch(ids=ids)

    assert api.peak_active <= 10
    assert api.peak_active > 1, "expected genuine overlap between calls, not accidental serialization"


@pytest.mark.asyncio
async def test_get_batch_hierarchy_filtering_completes_under_a_timeout_while_f6_semaphore_is_saturated() -> None:
    """Structural independence of the batch-read and allowlist semaphores,
    behaviorally proven (not just
    the object-identity assertion in test_architecture_boundaries.py): each
    of get_batch()'s 10 concurrently in-flight get() calls holds a
    `_batch_read_semaphore` permit for its ENTIRE duration, INCLUDING its own
    nested `_filter_hierarchy_allowlist()` call, which needs the SEPARATE
    allowlist semaphore to resolve each work package's ancestor href. If the
    two semaphores were shared, this would deadlock: all 10 permits held by
    the 10 in-flight get() calls, every one of them then blocked waiting for
    an allowlist permit that can only free up once a get() call finishes -- which
    can't happen while it's still waiting. Proven by requiring the whole
    get_batch() (more ids than the semaphore limit, so genuine saturation is
    guaranteed) to complete within a generous timeout."""
    ids = list(range(1, 21))  # double the semaphore limit -- guarantees saturation, not just possible overlap
    ancestor_href = "/api/v3/work_packages/999"

    class _HierarchyApi(_ConcurrencyTrackingWorkPackageApi):
        def __init__(self, *, ids: list[int]) -> None:
            super().__init__(ids=ids)
            self._records_by_id = {
                i: _record(i, detail=_detail(i, ancestors=[{"href": ancestor_href, "title": "Ancestor"}])) for i in ids
            }

    api = _HierarchyApi(ids=ids)
    settings = dataclasses.replace(make_settings(), read_projects=("demo",))

    class _AncestorLookupApi:
        """Minimal real WorkPackageLookupApi fake, used ONLY so this test
        routes through the REAL `WorkPackageResolver.project_links_allowed`
        (and its real, separate `_allowlist_semaphore`) instead of a fake
        bulk callback that never touches the actual F3 semaphore -- a fake
        callback would only prove F6 doesn't deadlock on ITSELF, not that F6
        and the real F3 semaphore are safe together (2nd Codex review round
        finding: the original version of this test used a fake bulk hook and
        so never actually exercised the real semaphore it claims to prove
        independence from)."""

        async def get(self, work_package_ref: str) -> dict:
            raise AssertionError("unused")

        async def get_by_href(self, href: str) -> dict:
            await asyncio.sleep(0)  # yields control, same as a real leaf HTTP lookup would
            return {"id": 999, "_links": {"project": {"href": "/api/v3/projects/1", "title": "Demo"}}}

    resolver = WorkPackageResolver(
        api=_AncestorLookupApi(), settings=settings, project_id_to_identifier=PROJECT_ID_TO_IDENTIFIER
    )
    service, _ = _service(
        api,
        settings=settings,
        work_package_project_allowed=resolver.project_link_allowed,
        work_package_project_allowed_bulk=resolver.project_links_allowed,
    )

    result = await asyncio.wait_for(service.get_batch(ids=ids), timeout=5.0)

    assert result.succeeded == len(ids)
    assert api.peak_active <= 10


@pytest.mark.asyncio
async def test_get_batch_semaphore_is_shared_across_concurrent_calls() -> None:
    """The semaphore is a Service-level attribute, not created per get_batch()
    call -- two simultaneous get_batch() calls on the SAME Service instance
    must share one combined cap, not each get their own independent 10."""
    api = _ConcurrencyTrackingWorkPackageApi(ids=list(range(1, 51)))
    service, _ = _service(api)

    await asyncio.gather(
        service.get_batch(ids=list(range(1, 26))),
        service.get_batch(ids=list(range(26, 51))),
    )

    assert api.peak_active <= 10


@pytest.mark.asyncio
async def test_get_batch_releases_permit_after_expected_error() -> None:
    """A permit consumed by a work package that fails with an expected,
    item-local error (OpenProjectError/InvalidInputError) must still be
    released -- otherwise the semaphore would leak capacity on every failed
    item and eventually deadlock the whole batch."""
    api = _FakeWorkPackageApi()
    api._records_by_id = {6: _record(6)}
    service, _ = _service(api)

    # All of these ids are unknown to the fake API and will fail -- if a
    # single permit leaked per failure, batches larger than the semaphore
    # size (10) would hang instead of completing.
    result = await service.get_batch(ids=list(range(100, 115)))

    assert result.failed == 15
    assert result.succeeded == 0


@pytest.mark.asyncio
async def test_get_batch_unexpected_exception_still_propagates_and_aborts_batch() -> None:
    """Pre-existing behavior, unchanged by the new semaphore: fetch_one only
    catches (OpenProjectError, InvalidInputError) -- any OTHER exception
    propagates out of asyncio.gather() and aborts the whole batch rather
    than becoming an item-local failure."""

    class _BoomApi(_FakeWorkPackageApi):
        async def get(self, work_package_ref: str, *, text_limit: int | None = None) -> WorkPackageRecord:
            if work_package_ref == "7":
                raise RuntimeError("boom")
            return await super().get(work_package_ref, text_limit=text_limit)

    api = _BoomApi()
    api._records_by_id = {6: _record(6), 7: _record(7)}
    service, _ = _service(api)

    with pytest.raises(RuntimeError, match="boom"):
        await service.get_batch(ids=[6, 7])


@pytest.mark.asyncio
async def test_get_batch_preserves_input_order_in_results() -> None:
    api = _FakeWorkPackageApi()
    api._records_by_id = {i: _record(i) for i in (3, 1, 2)}
    service, _ = _service(api)

    result = await service.get_batch(ids=[3, 1, 2])

    assert [item.id for item in result.results] == [3, 1, 2]


@pytest.mark.asyncio
async def test_apply_date_filters_rejects_both_on_and_between() -> None:
    service, _ = _service()

    with pytest.raises(InvalidInputError):
        await service.list(created_on="2026-01-01", created_between=["2026-01-01", "2026-01-31"])


@pytest.mark.asyncio
async def test_overdue_only_filters_by_due_date_before_today_and_open_status() -> None:
    service, api = _service()

    await service.list(overdue_only=True)

    filters = api.list_calls[0]["filters"]
    assert {"due_date": {"operator": "<t-", "values": ["1"]}} in filters
    assert {"status_id": {"operator": "o", "values": []}} in filters


@pytest.mark.asyncio
async def test_due_within_days_filters_by_relative_date_range() -> None:
    service, api = _service()

    await service.list(due_within_days=7)

    filters = api.list_calls[0]["filters"]
    assert {"due_date": {"operator": "<t+", "values": ["7"]}} in filters


@pytest.mark.asyncio
async def test_due_within_days_zero_is_a_legal_boundary_value() -> None:
    """due_within_days=0 (due today only) is a legal, non-negative boundary --
    distinct from None (the "no filter" default), which must not raise."""
    service, api = _service()

    await service.list(due_within_days=0)

    filters = api.list_calls[0]["filters"]
    assert {"due_date": {"operator": "<t+", "values": ["0"]}} in filters


@pytest.mark.asyncio
async def test_overdue_only_rejects_combination_with_due_on() -> None:
    service, _ = _service()

    with pytest.raises(InvalidInputError):
        await service.list(overdue_only=True, due_on="2026-01-01")


@pytest.mark.asyncio
async def test_overdue_only_rejects_combination_with_due_within_days() -> None:
    service, _ = _service()

    with pytest.raises(InvalidInputError):
        await service.list(overdue_only=True, due_within_days=3)


@pytest.mark.asyncio
async def test_due_within_days_rejects_combination_with_due_between() -> None:
    service, _ = _service()

    with pytest.raises(InvalidInputError):
        await service.list(due_within_days=3, due_between=["2026-01-01", "2026-01-31"])


@pytest.mark.asyncio
async def test_due_within_days_rejects_negative_value() -> None:
    service, _ = _service()

    with pytest.raises(InvalidInputError):
        await service.list(due_within_days=-1)


@pytest.mark.asyncio
async def test_search_overdue_only_filters_by_due_date_before_today_and_open_status() -> None:
    service, api = _service()

    await service.search(search="foo", overdue_only=True)

    filters = api.list_calls[0]["filters"]
    assert {"due_date": {"operator": "<t-", "values": ["1"]}} in filters
    assert {"status_id": {"operator": "o", "values": []}} in filters


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
    """Regression: apply_hidden_fields stamps `_hidden_keys` as a
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
    # own docstring: the value stays on the dataclass; presentation._to_payload's
    # serialization seam is what actually drops the key from the response).
    # The bug this test guards is `_hidden_keys` going missing entirely --
    # which would make _to_payload treat the field as NOT hidden at all.
    assert getattr(result, "_hidden_keys", frozenset()) == frozenset({"description"})


@pytest.mark.asyncio
async def test_get_hierarchy_truncated_flag_cleared_when_all_visible_entries_filtered_out() -> None:
    """Regression: the Adapter computes
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

    assert result.state == "preview"
    assert result.ready is True
    assert api.commit_create_calls == []
    assert len(api.validate_create_calls) == 1


@pytest.mark.asyncio
async def test_create_commit_calls_commit_create_and_masks_result() -> None:
    api = _FakeWorkPackageApi()
    settings = dataclasses.replace(make_settings(), hidden_fields={"work_package": ("description",)})
    service, _ = _service(api, settings=settings)

    result = await service.create(project="demo", type="Task", subject="New WP", confirm=True)

    assert result.state == "confirmed"
    assert result.ready is True
    assert len(api.commit_create_calls) == 1
    assert result.result is not None
    # apply_hidden_fields stamps a _hidden_keys marker; it does not blank the
    # field itself -- presentation._to_payload's serialization layer drops the
    # key entirely at the MCP response boundary.
    assert result.result._hidden_keys == frozenset({"description"})


@pytest.mark.asyncio
async def test_create_strips_unrequested_target_versions_on_commit() -> None:
    # Regression: OpenProject's form response echoes an unrequested
    # _links.targetVersions, which the server rejects on commit as a
    # version/targetVersions conflict.
    api = _TargetVersionsEchoingWorkPackageApi()
    service, _ = _service(api)

    preview = await service.create(project="demo", type="Task", subject="New WP", version="1.0", confirm=False)
    assert "targetVersions" in preview.payload["_links"]

    result = await service.create(project="demo", type="Task", subject="New WP", version="1.0", confirm=True)

    assert result.state == "confirmed"
    assert len(api.commit_create_calls) == 1
    committed_payload = api.commit_create_calls[0]
    assert "targetVersions" not in committed_payload["_links"]


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
async def test_create_legacy_version_write_rejected_when_only_target_versions_hidden() -> None:
    # version/target_versions write the same underlying data -- hiding just
    # target_versions must also block a legacy version=... write, not only a
    # target_versions=[...] write, or the coupled-alias write-side gate would
    # be trivially bypassable via the other field's name.
    api = _FakeWorkPackageApi()
    settings = dataclasses.replace(make_settings(), hidden_fields={"work_package": ("target_versions",)})
    service, _ = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden"):
        await service.create(project="demo", type="Task", subject="New WP", version="1.0", confirm=False)


@pytest.mark.asyncio
async def test_create_legacy_version_clear_rejected_when_only_target_versions_hidden() -> None:
    from openproject_ce_mcp.app.services.work_package_service import CLEAR_VERSION

    api = _FakeWorkPackageApi()
    settings = dataclasses.replace(make_settings(), hidden_fields={"work_package": ("target_versions",)})
    service, _ = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden"):
        await service.create(project="demo", type="Task", subject="New WP", version=CLEAR_VERSION, confirm=False)


@pytest.mark.asyncio
async def test_create_target_versions_write_rejected_when_only_version_hidden() -> None:
    # The reverse direction: hiding just version must also block a
    # target_versions=[...] write (already covered implicitly by the
    # existing ensure_field_writable("version", ...) call in the
    # target_versions branch, but asserted explicitly here for symmetry).
    api = _FakeWorkPackageApi()
    settings = dataclasses.replace(make_settings(), hidden_fields={"work_package": ("version",)})
    service, _ = _service(api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden"):
        await service.create(project="demo", type="Task", subject="New WP", target_versions=["1.0"], confirm=False)


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
    # Regression guard (N+1 fix): custom_fields triggers _get_write_schema's
    # dedicated schema probe, which is the ONE call site that needs linked
    # allowedValues resolved. create()'s own final parse_form (after the real
    # validate_create) never needs .schema, so it must stay resolve_links=False.
    assert api.parse_form_resolve_links_calls == [True, False]


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


@pytest.mark.asyncio
async def test_create_target_versions_resolves_each_ref_once() -> None:
    api = _FakeWorkPackageApi()
    service, _ = _service(api)
    resolved_refs: list[str] = []

    async def resolve_version_id(version_ref, *, project=None, context=None):
        resolved_refs.append(version_ref)
        return {"1.0": "10", "2.0": "20"}[version_ref]

    service._resolve_version_id = resolve_version_id  # type: ignore[method-assign]

    result = await service.create(
        project="demo", type="Task", subject="New WP", target_versions=["1.0", "2.0"], confirm=False
    )

    assert resolved_refs == ["1.0", "2.0"]
    assert result.payload["_links"]["targetVersions"] == [
        {"href": "/api/v3/versions/10"},
        {"href": "/api/v3/versions/20"},
    ]


@pytest.mark.asyncio
async def test_create_target_versions_dedupes_repeated_refs() -> None:
    api = _FakeWorkPackageApi()
    service, _ = _service(api)

    result = await service.create(
        project="demo", type="Task", subject="New WP", target_versions=["1.0", "1.0"], confirm=False
    )

    assert result.payload["_links"]["targetVersions"] == [{"href": "/api/v3/versions/4"}]


@pytest.mark.asyncio
async def test_create_target_versions_empty_list_sets_empty_links() -> None:
    api = _FakeWorkPackageApi()
    service, _ = _service(api)

    result = await service.create(project="demo", type="Task", subject="New WP", target_versions=[], confirm=False)

    assert result.payload["_links"]["targetVersions"] == []


@pytest.mark.asyncio
async def test_create_version_and_target_versions_together_rejected() -> None:
    api = _FakeWorkPackageApi()
    service, _ = _service(api)

    with pytest.raises(InvalidInputError, match="cannot both be"):
        await service.create(
            project="demo", type="Task", subject="New WP", version="1.0", target_versions=["2.0"], confirm=False
        )


@pytest.mark.asyncio
async def test_create_target_versions_not_stripped_by_echo_workaround() -> None:
    # The single most important new test: the strip-workaround (triggered by
    # version is not None) exists for a genuinely different bug (an
    # unrequested targetVersions echoed back on a legacy version= write) and
    # must never strip a real target_versions=[...] write. Uses the plain
    # fake (echoes the payload actually sent) rather than
    # _TargetVersionsEchoingWorkPackageApi, which always overwrites
    # targetVersions with [] regardless of what was sent -- that fixture
    # simulates the echo bug itself, not a genuine write's round-trip, so it
    # cannot distinguish "stripped" from "server always returns []" here.
    api = _FakeWorkPackageApi()
    service, _ = _service(api)

    result = await service.create(project="demo", type="Task", subject="New WP", target_versions=["1.0"], confirm=True)

    assert result.state == "confirmed"
    committed_payload = api.commit_create_calls[0]
    assert committed_payload["_links"]["targetVersions"] == [{"href": "/api/v3/versions/4"}]


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
async def test_create_subtask_strips_unrequested_target_versions_on_commit() -> None:
    api = _TargetVersionsEchoingWorkPackageApi()
    api._records_by_id[6] = _record(6, payload=_payload(6, project_href="/api/v3/projects/1", project_title="Demo"))
    service, _ = _service(api)

    result = await service.create_subtask(
        parent_work_package_id=6, type="Task", subject="Child task", version="1.0", confirm=True
    )

    assert result.state == "confirmed"
    committed_payload = api.commit_create_calls[0]
    assert "targetVersions" not in committed_payload["_links"]


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
async def test_bulk_create_sanitizes_error_message_for_unexpected_exception(monkeypatch) -> None:
    """Regression: bulk_create's per-item except Exception is deliberately
    broad (isolating one item's failure must not abort the rest, unlike
    get_batch's asyncio.gather-based fetch_one) -- but an exception outside
    the typed OpenProjectError hierarchy is a real internal bug, and its raw
    str() must not reach the caller verbatim (it could carry an internal
    detail an OpenProjectError's own sanitized message never would)."""
    api = _FakeWorkPackageApi()
    service, _ = _service(api)

    async def _raise_unexpected(*args, **kwargs):
        raise KeyError("some/internal/path/detail")

    monkeypatch.setattr(service, "create", _raise_unexpected)

    result = await service.bulk_create(
        items=[{"project": "demo", "type": "Task", "subject": "Anything"}],
        confirm=False,
    )

    assert result.items[0].success is False
    assert "some/internal/path/detail" not in result.items[0].error
    assert result.items[0].error == "Internal error creating this item."


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


@pytest.mark.asyncio
async def test_bulk_create_passes_the_same_allowed_values_cache_to_every_item() -> None:
    """Every item in one bulk_create batch must share the SAME
    WorkPackageResolutionContext instance as parse_form's allowed_values_cache
    -- this is what lets the adapter reuse a resolved allowedValues href
    across items instead of re-fetching it per item."""
    api = _FakeWorkPackageApi()
    api.next_schema = {"customField10": {"name": "Story points", "location": "payload"}}
    service, _ = _service(api)

    await service.bulk_create(
        items=[
            {"project": "demo", "type": "Task", "subject": "One", "custom_fields": {"customField10": 1}},
            {"project": "demo", "type": "Task", "subject": "Two", "custom_fields": {"customField10": 2}},
        ],
        confirm=False,
    )

    # Two items, each with custom_fields -> two schema-probe parse_form calls
    # (resolve_links=True) plus each item's final resolve_links=False parse.
    schema_probe_caches = [
        cache
        for resolve_links, cache in zip(
            api.parse_form_resolve_links_calls, api.parse_form_allowed_values_cache_calls, strict=True
        )
        if resolve_links
    ]
    assert len(schema_probe_caches) == 2
    assert schema_probe_caches[0] is not None
    assert schema_probe_caches[0] is schema_probe_caches[1]


# ----------------------------------------------------------------------
# update()
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_preview_without_commit_does_not_call_commit_update() -> None:
    api = _FakeWorkPackageApi()
    service, _ = _service(api)

    result = await service.update(work_package_id=6, subject="Renamed", confirm=False)

    assert result.state == "preview"
    assert api.commit_update_calls == []
    assert len(api.validate_update_calls) == 1


@pytest.mark.asyncio
async def test_update_commit_calls_commit_update() -> None:
    api = _FakeWorkPackageApi()
    service, _ = _service(api)

    result = await service.update(work_package_id=6, subject="Renamed", confirm=True)

    assert result.state == "confirmed"
    assert len(api.commit_update_calls) == 1
    ref, payload = api.commit_update_calls[0]
    assert ref == "6"
    assert payload["subject"] == "Renamed"


@pytest.mark.asyncio
async def test_update_strips_unrequested_target_versions_on_commit() -> None:
    # Regression: OpenProject's form response echoes an unrequested
    # _links.targetVersions, which the server rejects on commit as a
    # version/targetVersions conflict.
    api = _TargetVersionsEchoingWorkPackageApi()
    service, _ = _service(api)

    preview = await service.update(work_package_id=6, version="1.0", confirm=False)
    assert "targetVersions" in preview.payload["_links"]

    result = await service.update(work_package_id=6, version="1.0", confirm=True)

    assert result.state == "confirmed"
    assert len(api.commit_update_calls) == 1
    _, committed_payload = api.commit_update_calls[0]
    assert "targetVersions" not in committed_payload["_links"]


@pytest.mark.asyncio
async def test_update_clear_version_strips_unrequested_target_versions_on_commit() -> None:
    from openproject_ce_mcp.app.services.work_package_service import CLEAR_VERSION

    api = _TargetVersionsEchoingWorkPackageApi()
    service, _ = _service(api)

    result = await service.update(work_package_id=6, version=CLEAR_VERSION, confirm=True)

    assert result.state == "confirmed"
    _, committed_payload = api.commit_update_calls[0]
    assert committed_payload["_links"]["version"]["href"] is None
    assert "targetVersions" not in committed_payload["_links"]


@pytest.mark.asyncio
async def test_update_without_version_intent_leaves_target_versions_untouched() -> None:
    api = _TargetVersionsEchoingWorkPackageApi()
    service, _ = _service(api)

    result = await service.update(work_package_id=6, subject="Renamed", confirm=True)

    assert result.state == "confirmed"
    _, committed_payload = api.commit_update_calls[0]
    assert committed_payload["_links"]["targetVersions"] == []


@pytest.mark.asyncio
async def test_update_rejected_target_versions_conflict_reports_validation_errors() -> None:
    api = _TargetVersionsEchoingWorkPackageApi()
    api.validation_errors_queue.append({"version": "Version is not assignable."})
    service, _ = _service(api)

    result = await service.update(work_package_id=6, version="1.0", confirm=True)

    assert result.state == "invalid"
    assert result.ready is False
    assert result.validation_errors == {"version": "Version is not assignable."}
    assert "targetVersions" in result.payload["_links"]
    assert api.commit_update_calls == []


@pytest.mark.asyncio
async def test_update_target_versions_clear_via_empty_list() -> None:
    api = _FakeWorkPackageApi()
    service, _ = _service(api)

    result = await service.update(work_package_id=6, target_versions=[], confirm=True)

    assert result.state == "confirmed"
    _, committed_payload = api.commit_update_calls[0]
    assert committed_payload["_links"]["targetVersions"] == []


@pytest.mark.asyncio
async def test_update_target_versions_not_stripped_by_echo_workaround() -> None:
    # See test_create_target_versions_not_stripped_by_echo_workaround for why
    # the plain fake is used here rather than _TargetVersionsEchoingWorkPackageApi.
    api = _FakeWorkPackageApi()
    service, _ = _service(api)

    result = await service.update(work_package_id=6, target_versions=["1.0"], confirm=True)

    assert result.state == "confirmed"
    _, committed_payload = api.commit_update_calls[0]
    assert committed_payload["_links"]["targetVersions"] == [{"href": "/api/v3/versions/4"}]


@pytest.mark.asyncio
async def test_update_version_and_target_versions_together_rejected() -> None:
    api = _FakeWorkPackageApi()
    service, _ = _service(api)

    with pytest.raises(InvalidInputError, match="cannot both be"):
        await service.update(work_package_id=6, version="1.0", target_versions=["2.0"], confirm=False)


@pytest.mark.asyncio
async def test_update_version_rejected_against_multi_target_version_work_package() -> None:
    # The data-loss guard: a legacy version= write against a work package
    # that already has more than one target version must be rejected, not
    # silently collapsed down to one.
    api = _FakeWorkPackageApi()
    api._records_by_id[6] = _record(
        6,
        payload={
            **_payload(6),
            "_links": {
                **_payload(6)["_links"],
                "targetVersions": [
                    {"href": "/api/v3/versions/10", "title": "1.0"},
                    {"href": "/api/v3/versions/20", "title": "2.0"},
                ],
            },
        },
    )
    service, _ = _service(api)

    with pytest.raises(InvalidInputError, match="multiple target versions"):
        await service.update(work_package_id=6, version="1.0", confirm=False)


@pytest.mark.asyncio
async def test_update_version_clear_rejected_against_multi_target_version_work_package() -> None:
    # Correction from Codex's review: CLEAR_VERSION must NOT be excluded from
    # the guard -- clearing to zero via the legacy field is exactly as
    # destructive as collapsing to one.
    from openproject_ce_mcp.app.services.work_package_service import CLEAR_VERSION

    api = _FakeWorkPackageApi()
    api._records_by_id[6] = _record(
        6,
        payload={
            **_payload(6),
            "_links": {
                **_payload(6)["_links"],
                "targetVersions": [
                    {"href": "/api/v3/versions/10", "title": "1.0"},
                    {"href": "/api/v3/versions/20", "title": "2.0"},
                ],
            },
        },
    )
    service, _ = _service(api)

    with pytest.raises(InvalidInputError, match="multiple target versions"):
        await service.update(work_package_id=6, version=CLEAR_VERSION, confirm=False)


@pytest.mark.asyncio
async def test_update_version_allowed_against_single_target_version_work_package() -> None:
    # Guards against the check being too broad: 0 or 1 existing target
    # versions must not trigger the guard.
    api = _FakeWorkPackageApi()
    api._records_by_id[6] = _record(
        6,
        payload={
            **_payload(6),
            "_links": {
                **_payload(6)["_links"],
                "targetVersions": [{"href": "/api/v3/versions/10", "title": "1.0"}],
            },
        },
    )
    service, _ = _service(api)

    result = await service.update(work_package_id=6, version="2.0", confirm=False)

    assert result.ready is True


@pytest.mark.asyncio
async def test_update_version_allowed_against_no_target_version_work_package() -> None:
    api = _FakeWorkPackageApi()
    service, _ = _service(api)

    result = await service.update(work_package_id=6, version="2.0", confirm=False)

    assert result.ready is True


@pytest.mark.asyncio
async def test_update_target_versions_itself_not_blocked_by_data_loss_guard() -> None:
    # The guard only fires for the legacy version= parameter -- a caller
    # using target_versions explicitly against a multi-version work package
    # must succeed normally.
    api = _FakeWorkPackageApi()
    api._records_by_id[6] = _record(
        6,
        payload={
            **_payload(6),
            "_links": {
                **_payload(6)["_links"],
                "targetVersions": [
                    {"href": "/api/v3/versions/10", "title": "1.0"},
                    {"href": "/api/v3/versions/20", "title": "2.0"},
                ],
            },
        },
    )
    service, _ = _service(api)

    result = await service.update(work_package_id=6, target_versions=["1.0"], confirm=False)

    assert result.ready is True


def test_strip_unrequested_target_versions_does_not_mutate_input() -> None:
    from openproject_ce_mcp.app.services.work_package_service import _strip_unrequested_target_versions

    original_links = {"version": {"href": "/api/v3/versions/11"}, "targetVersions": []}
    payload = {"subject": "WP", "_links": original_links}
    original_payload = {"subject": "WP", "_links": {"version": {"href": "/api/v3/versions/11"}, "targetVersions": []}}

    stripped = _strip_unrequested_target_versions(payload)

    assert "targetVersions" not in stripped["_links"]
    assert stripped is not payload
    assert stripped["_links"] is not original_links
    assert payload == original_payload
    assert payload["_links"] is original_links


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
    # Regression guard (N+1 fix): the auto-derive probe and the final parse
    # only ever read .schema for plain writable flags (or don't read .schema
    # at all) -- never allowedValues -- so parse_form must never be asked to
    # resolve links on this path. A status-close update with no
    # responsible/priority/category/project_phase/custom_fields in the
    # payload means _get_write_schema's resolve_links=True probe is skipped
    # entirely too.
    assert api.parse_form_resolve_links_calls == [False, False]


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
async def test_bulk_update_item_with_target_versions_reaches_write_payload() -> None:
    api = _FakeWorkPackageApi()
    service, _ = _service(api)

    result = await service.bulk_update(
        items=[{"work_package_id": 6, "target_versions": ["1.0"]}],
        confirm=True,
    )

    assert result.succeeded == 1
    _, committed_payload = api.commit_update_calls[0]
    assert committed_payload["_links"]["targetVersions"] == [{"href": "/api/v3/versions/4"}]


@pytest.mark.asyncio
async def test_bulk_create_item_with_target_versions_reaches_write_payload() -> None:
    api = _FakeWorkPackageApi()
    service, _ = _service(api)

    result = await service.bulk_create(
        items=[{"project": "demo", "type": "Task", "subject": "New WP", "target_versions": ["1.0", "2.0"]}],
        confirm=False,
    )

    assert result.succeeded == 1
    _, payload = api.validate_create_calls[0]
    assert payload["_links"]["targetVersions"] == [{"href": "/api/v3/versions/4"}]


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
async def test_bulk_update_passes_the_same_cache_but_each_item_gets_its_own_form_probe() -> None:
    """Unlike bulk_create's project-scoped href reuse, bulk_update's
    schema probe is per-work-package (validate_update targets that WP's own
    ref) -- the shared cache object must still be passed to every item's
    parse_form call so a REPEATED field on the SAME work package would hit
    the cache, but two different work packages naturally get two separate
    validate_update/parse_form round trips (this is expected, not a caching
    failure -- see the href-keyed design rationale)."""
    api = _FakeWorkPackageApi()
    api._records_by_id = {6: _record(6), 7: _record(7)}
    api.next_schema = {"customField10": {"name": "Story points", "location": "payload"}}
    service, _ = _service(api)

    await service.bulk_update(
        items=[
            {"work_package_id": 6, "custom_fields": {"customField10": 1}},
            {"work_package_id": 7, "custom_fields": {"customField10": 2}},
        ],
        confirm=False,
    )

    schema_probe_caches = [
        cache
        for resolve_links, cache in zip(
            api.parse_form_resolve_links_calls, api.parse_form_allowed_values_cache_calls, strict=True
        )
        if resolve_links
    ]
    assert len(schema_probe_caches) == 2
    assert schema_probe_caches[0] is not None
    # Same cache OBJECT shared across items (so a repeated href within one
    # item, or across items resolving the identical href, would hit it) --
    # even though this test's two work packages happen to each trigger their
    # own validate_update call (a validate_update-per-work-package is
    # unavoidable; only the allowedValues dereference itself is cacheable).
    assert schema_probe_caches[0] is schema_probe_caches[1]


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


@pytest.mark.asyncio
async def test_bulk_update_sanitizes_error_message_for_unexpected_exception(monkeypatch) -> None:
    """Regression: see test_bulk_create_sanitizes_error_message_for_unexpected_exception
    -- same fix, same rationale, applied to bulk_update's own item loop."""
    api = _FakeWorkPackageApi()
    service, _ = _service(api)

    async def _raise_unexpected(*args, **kwargs):
        raise KeyError("some/internal/path/detail")

    monkeypatch.setattr(service, "update", _raise_unexpected)

    result = await service.bulk_update(
        items=[{"work_package_id": 6, "subject": "Anything"}],
        confirm=False,
    )

    assert result.items[0].success is False
    assert "some/internal/path/detail" not in result.items[0].error
    assert result.items[0].error == "Internal error updating this item."


# ----------------------------------------------------------------------
# delete()
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_preview_without_commit_does_not_call_delete() -> None:
    api = _FakeWorkPackageApi()
    service, _ = _service(api)

    result = await service.delete(work_package_id=6, confirm=False)

    assert result.state == "preview"
    assert result.result is not None
    assert api.delete_calls == []


@pytest.mark.asyncio
async def test_delete_commit_calls_delete_and_returns_no_result() -> None:
    api = _FakeWorkPackageApi()
    service, _ = _service(api)

    result = await service.delete(work_package_id=6, confirm=True)

    assert result.state == "confirmed"
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

    assert result.state == "preview"
    assert api.post_comment_calls == []


@pytest.mark.asyncio
async def test_add_comment_commit_posts_and_returns_normalized_result() -> None:
    activity_api = _FakeActivityApi()
    api = _FakeWorkPackageApi()
    service, _ = _service(api, activity_api=activity_api)

    result = await service.add_comment(work_package_id=6, comment="Hello", internal=True, notify=True, confirm=True)

    assert result.state == "confirmed"
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
    assert result.state == "preview"


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
# guard, found during the write-path wiring pass: none of the 5 flat write
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

    assert result.state == "preview"


@pytest.mark.asyncio
async def test_add_comment_works_with_read_disabled() -> None:
    api = _FakeWorkPackageApi()
    settings = dataclasses.replace(make_settings(), enable_work_package_read=False)
    service, _ = _service(api, settings=settings)

    result = await service.add_comment(work_package_id=6, comment="Hello", confirm=False)

    assert result.state == "preview"


# --- custom_field_filters -----------------------------------------
#
# Per-format representative coverage: one entry per CE-realistic custom-field
# format (string, text, link, int, float, date, bool, list, user, version --
# ten total, see docs/filters.md's "Custom-Field Filters" section), verifying
# only that the filter fragment this Service builds is correctly shaped and
# reaches the fake API's `filters` list unchanged -- per-field operator/format
# legality is intentionally NOT locally validated (see
# CUSTOM_FIELD_FILTER_OPERATORS's module docstring in work_package_service.py)
# so these tests do not (and cannot) exercise format-specific rejection; they
# only confirm the key-normalization/filter-append plumbing is correct for
# each format's real operator vocabulary.


@pytest.mark.asyncio
async def test_list_custom_field_filters_plain_value_int_format() -> None:
    # "Plain-value" representative per the ticket's acceptance criterion.
    service, api = _service()

    await service.list(custom_field_filters={"cf_12": {"operator": "=", "values": ["42"]}})

    assert {"cf_12": {"operator": "=", "values": ["42"]}} in api.list_calls[0]["filters"]


@pytest.mark.asyncio
async def test_list_custom_field_filters_link_based_user_format_with_me() -> None:
    # "Link-based" representative per the ticket's acceptance criterion --
    # user-format CFs accept the literal "me" value, resolved server-side.
    service, api = _service()

    await service.list(project="demo", custom_field_filters={"cf_3": {"operator": "=", "values": ["me"]}})

    assert {"cf_3": {"operator": "=", "values": ["me"]}} in api.list_calls[0]["filters"]


@pytest.mark.asyncio
async def test_list_custom_field_filters_string_format() -> None:
    service, api = _service()
    await service.list(custom_field_filters={"cf_1": {"operator": "~", "values": ["Acme"]}})
    assert {"cf_1": {"operator": "~", "values": ["Acme"]}} in api.list_calls[0]["filters"]


@pytest.mark.asyncio
async def test_list_custom_field_filters_text_format() -> None:
    service, api = _service()
    await service.list(custom_field_filters={"cf_2": {"operator": "!~", "values": ["draft"]}})
    assert {"cf_2": {"operator": "!~", "values": ["draft"]}} in api.list_calls[0]["filters"]


@pytest.mark.asyncio
async def test_list_custom_field_filters_link_format() -> None:
    # link-format CFs have no dedicated filter strategy server-side and fall
    # through to plain :string (verified against custom_field_filter.rb /
    # custom_fields/base.rb's `type` case, both lacking a "link" branch).
    service, api = _service()
    await service.list(custom_field_filters={"cf_4": {"operator": "=", "values": ["https://example.com"]}})
    assert {"cf_4": {"operator": "=", "values": ["https://example.com"]}} in api.list_calls[0]["filters"]


@pytest.mark.asyncio
async def test_list_custom_field_filters_float_format() -> None:
    service, api = _service()
    await service.list(custom_field_filters={"cf_5": {"operator": ">=", "values": ["3.14"]}})
    assert {"cf_5": {"operator": ">=", "values": ["3.14"]}} in api.list_calls[0]["filters"]


@pytest.mark.asyncio
async def test_list_custom_field_filters_date_format() -> None:
    service, api = _service()
    await service.list(custom_field_filters={"cf_6": {"operator": "=d", "values": ["2026-01-01"]}})
    assert {"cf_6": {"operator": "=d", "values": ["2026-01-01"]}} in api.list_calls[0]["filters"]


@pytest.mark.asyncio
async def test_list_custom_field_filters_bool_format() -> None:
    # Bool CF values are the literal wire strings "t"/"f", not JSON true/false.
    service, api = _service()
    await service.list(custom_field_filters={"cf_7": {"operator": "=", "values": ["t"]}})
    assert {"cf_7": {"operator": "=", "values": ["t"]}} in api.list_calls[0]["filters"]


@pytest.mark.asyncio
async def test_list_custom_field_filters_list_format_contains_all() -> None:
    # "&=" (EqualsAll / contains-all) is a CF-only operator with no built-in
    # :list_optional equivalent -- confirming it passes through untouched.
    service, api = _service()
    await service.list(project="demo", custom_field_filters={"cf_8": {"operator": "&=", "values": ["1", "2"]}})
    assert {"cf_8": {"operator": "&=", "values": ["1", "2"]}} in api.list_calls[0]["filters"]


@pytest.mark.asyncio
async def test_list_custom_field_filters_version_format() -> None:
    service, api = _service()
    await service.list(project="demo", custom_field_filters={"cf_9": {"operator": "=", "values": ["10"]}})
    assert {"cf_9": {"operator": "=", "values": ["10"]}} in api.list_calls[0]["filters"]


@pytest.mark.asyncio
async def test_list_custom_field_filters_normalizes_customfield_key() -> None:
    service, api = _service()
    await service.list(custom_field_filters={"customField12": {"operator": "=", "values": ["42"]}})
    assert {"cf_12": {"operator": "=", "values": ["42"]}} in api.list_calls[0]["filters"]


@pytest.mark.asyncio
async def test_search_custom_field_filters_plain_value_representative() -> None:
    service, api = _service()

    await service.search(search="foo", custom_field_filters={"cf_12": {"operator": "=", "values": ["42"]}})

    assert {"cf_12": {"operator": "=", "values": ["42"]}} in api.list_calls[0]["filters"]


@pytest.mark.asyncio
async def test_list_custom_field_filters_none_or_empty_appends_nothing() -> None:
    service, api = _service()

    await service.list(custom_field_filters=None)
    filters_a = api.list_calls[0]["filters"]

    await service.list(custom_field_filters={})
    filters_b = api.list_calls[1]["filters"]

    assert not any(key.startswith("cf_") for f in filters_a for key in f)
    assert not any(key.startswith("cf_") for f in filters_b for key in f)


@pytest.mark.asyncio
async def test_list_custom_field_filters_rejects_hidden_field_by_cf_key() -> None:
    settings = dataclasses.replace(make_settings(), hide_custom_fields=("cf_12",))
    service, api = _service(settings=settings)

    with pytest.raises(InvalidInputError, match="hidden"):
        await service.list(custom_field_filters={"cf_12": {"operator": "=", "values": ["42"]}})

    # Rejected before any request reaches the fake API.
    assert api.list_calls == []


@pytest.mark.asyncio
async def test_list_custom_field_filters_rejects_hidden_field_by_customfield_key() -> None:
    # A hide pattern configured using the customField<N> spelling must also
    # reject a cf_<N>-keyed filter for the same field -- both canonical
    # spellings of the field's own key are checked explicitly (see
    # _apply_custom_field_filters's docstring), since normalize_hide_token
    # does not itself translate between the two forms.
    settings = dataclasses.replace(make_settings(), hide_custom_fields=("customField12",))
    service, api = _service(settings=settings)

    with pytest.raises(InvalidInputError, match="hidden"):
        await service.list(custom_field_filters={"cf_12": {"operator": "=", "values": ["42"]}})

    assert api.list_calls == []


@pytest.mark.asyncio
async def test_search_custom_field_filters_rejects_hidden_field() -> None:
    settings = dataclasses.replace(make_settings(), hide_custom_fields=("cf_12",))
    service, api = _service(settings=settings)

    with pytest.raises(InvalidInputError, match="hidden"):
        await service.search(search="foo", custom_field_filters={"cf_12": {"operator": "=", "values": ["42"]}})

    assert api.list_calls == []


@pytest.mark.asyncio
async def test_list_custom_field_filters_wildcard_hide_pattern_matches() -> None:
    settings = dataclasses.replace(make_settings(), hide_custom_fields=("cf_1*",))
    service, api = _service(settings=settings)

    with pytest.raises(InvalidInputError, match="hidden"):
        await service.list(custom_field_filters={"cf_12": {"operator": "=", "values": ["42"]}})

    assert api.list_calls == []


@pytest.mark.asyncio
async def test_list_custom_field_filters_rejects_invalid_key_shape_at_service_layer() -> None:
    # Defense-in-depth: a direct OpenProjectClient/Service caller bypassing
    # tools_validation.py's _validate_custom_field_filters must still get a
    # clean InvalidInputError, not a malformed filter silently sent upstream.
    service, api = _service()

    with pytest.raises(InvalidInputError, match="must be of the form"):
        await service.list(custom_field_filters={"story_points": {"operator": "=", "values": ["1"]}})

    assert api.list_calls == []


@pytest.mark.asyncio
async def test_list_custom_field_filters_rejects_non_dict_spec_at_service_layer() -> None:
    # Regression guard: a direct caller passing a malformed (non-dict) spec
    # must get a clean InvalidInputError, not an unhandled AttributeError
    # from spec.get(...) on a None/non-dict value.
    service, api = _service()

    with pytest.raises(InvalidInputError, match="must be an object"):
        await service.list(custom_field_filters={"cf_1": None})  # type: ignore[dict-item]

    assert api.list_calls == []


@pytest.mark.asyncio
async def test_list_no_regression_to_built_in_filters_alongside_custom_field_filters() -> None:
    service, api = _service()

    await service.list(
        status="Open status ref",
        custom_field_filters={"cf_12": {"operator": "=", "values": ["42"]}},
    )

    filters = api.list_calls[0]["filters"]
    assert {"status_id": {"operator": "=", "values": ["5"]}} in filters
    assert {"cf_12": {"operator": "=", "values": ["42"]}} in filters
