from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import PermissionDeniedError
from openproject_ce_mcp.app.ports.notification_api import NotificationPage, NotificationRecord
from openproject_ce_mcp.app.services.notification_service import NotificationService
from openproject_ce_mcp.models import NotificationSummary

PROJECT_ID_TO_IDENTIFIER = {1: "demo", 2: "other"}


def _summary(notification_id: int = 1) -> NotificationSummary:
    return NotificationSummary(
        id=notification_id,
        subject="Something happened",
        reason=None,
        read=False,
        project_id=None,
        project_name=None,
        work_package_id=None,
        work_package_subject=None,
        created_at="2026-01-01T00:00:00Z",
    )


def _record(
    notification_id: int = 1,
    *,
    project_link: dict | None = None,
    resource_link: dict | None = None,
) -> NotificationRecord:
    summary = _summary(notification_id)
    return NotificationRecord(summary=lambda: summary, project_link=project_link, resource_link=resource_link)


def _record_that_crashes_if_normalized(
    notification_id: int, *, project_link: dict | None = None, resource_link: dict | None = None
) -> NotificationRecord:
    def _boom() -> NotificationSummary:
        raise AssertionError(
            f"summary() must never be called for notification {notification_id} once "
            "it has been filtered out by the allowlist check"
        )

    return NotificationRecord(summary=_boom, project_link=project_link, resource_link=resource_link)


class _FakeNotificationApi:
    def __init__(self, records: list[NotificationRecord] | None = None, *, total: int | None = None) -> None:
        self._records = records if records is not None else [_record()]
        self._total = total if total is not None else len(self._records)
        self.list_all_calls: list[tuple[bool, int, int]] = []
        self.mark_read_calls: list[int] = []
        self.mark_all_read_calls = 0

    async def list_all(self, *, unread_only: bool, offset: int, limit: int) -> NotificationPage:
        self.list_all_calls.append((unread_only, offset, limit))
        return NotificationPage(records=list(self._records), total=self._total, exhausted=True)

    async def mark_read(self, notification_id: int) -> None:
        self.mark_read_calls.append(notification_id)

    async def mark_all_read(self) -> None:
        self.mark_all_read_calls += 1


def _work_package_project_allowed_from(allowed_hrefs: set[str]):
    calls: list[str] = []

    async def check(href: str, *, context=None) -> bool:
        calls.append(href)
        return href in allowed_hrefs

    check.calls = calls  # type: ignore[attr-defined]
    return check


def _work_package_project_allowed_bulk_from(allowed_hrefs: set[str], *, errors: dict[str, Exception] | None = None):
    """Fake `WorkPackageProjectAllowedBulkCheck`: mirrors
    `WorkPackageResolver.project_links_allowed`'s dedupe/cache/only-bools-
    cached contract closely enough for Service-level tests. `calls` records
    each bulk invocation's deduped href list (in order) -- concurrency itself
    is exercised at the resolver level, not re-proven here. `errors` lets a
    test force a specific href's outcome to be a captured Exception instead
    of a bool, exactly like the real resolver would produce for a failed
    lookup -- a failed href is deliberately never cached, same as the real
    resolver."""
    calls: list[list[str]] = []
    error_map = errors or {}

    async def bulk(hrefs, *, context) -> dict[str, bool | Exception]:
        unique = list(dict.fromkeys(hrefs))
        calls.append(unique)
        outcomes: dict[str, bool | Exception] = {}
        for href in unique:
            cached = context.get(href)
            if cached is not None:
                outcomes[href] = cached
                continue
            if href in error_map:
                outcomes[href] = error_map[href]
                continue
            allowed = href in allowed_hrefs
            context.set(href, allowed)
            outcomes[href] = allowed
        return outcomes

    bulk.calls = calls  # type: ignore[attr-defined]
    return bulk


def _service(
    *,
    api: _FakeNotificationApi | None = None,
    settings=None,
    work_package_project_allowed=None,
    work_package_project_allowed_bulk=None,
) -> NotificationService:
    return NotificationService(
        api=api or _FakeNotificationApi(),
        settings=settings or dataclasses.replace(make_settings(), enable_personal_read=True),
        project_id_to_identifier=PROJECT_ID_TO_IDENTIFIER,
        work_package_project_allowed=work_package_project_allowed or _work_package_project_allowed_from(set()),
        work_package_project_allowed_bulk=work_package_project_allowed_bulk
        or _work_package_project_allowed_bulk_from(set()),
    )


# --- list_all -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_all_denied_without_personal_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_personal_read=False, enable_work_package_read=True)
    service = _service(settings=settings)

    with pytest.raises(PermissionDeniedError, match="personal"):
        await service.list_all()


@pytest.mark.asyncio
async def test_list_all_allows_project_less_notification_under_restrictive_scope() -> None:
    record = _record(1, project_link=None, resource_link=None)
    api = _FakeNotificationApi(records=[record])
    settings = dataclasses.replace(make_settings(), enable_personal_read=True, read_projects=("demo",))
    service = _service(api=api, settings=settings)

    result = await service.list_all()

    assert result.count == 1
    assert result.results[0].id == 1


@pytest.mark.asyncio
async def test_list_all_still_issues_a_request_under_empty_read_projects() -> None:
    """Unlike Reminders, Notifications must NOT short-circuit on an empty
    read_projects scope -- a project-less/personal notification is still
    visible regardless of the project allowlist, so the request always goes
    out (verbatim behavior of client.py's original)."""
    record = _record(1, project_link=None, resource_link=None)
    api = _FakeNotificationApi(records=[record])
    settings = dataclasses.replace(make_settings(), enable_personal_read=True, read_projects=())
    service = _service(api=api, settings=settings)

    result = await service.list_all()

    # The re-scan loop fetches server pages at max_page_size (50 in
    # make_settings()), not the caller's own requested limit (20) -- it
    # doesn't know in advance how many raw records it'll need to scan
    # through to collect `limit` allowed ones.
    assert api.list_all_calls == [(False, 1, 50)]
    assert result.count == 1


@pytest.mark.asyncio
async def test_list_all_filters_by_project_link() -> None:
    allowed = _record(1, project_link={"href": "/api/v3/projects/1", "title": "Demo"})
    denied = _record(2, project_link={"href": "/api/v3/projects/2", "title": "Other"})
    api = _FakeNotificationApi(records=[allowed, denied])
    settings = dataclasses.replace(make_settings(), enable_personal_read=True, read_projects=("demo",))
    service = _service(api=api, settings=settings)

    result = await service.list_all()

    assert [n.id for n in result.results] == [1]
    assert result.total == 1


@pytest.mark.asyncio
async def test_list_all_resolves_work_package_resource_link_without_project_link() -> None:
    record = _record(1, resource_link={"href": "/api/v3/work_packages/9"})
    api = _FakeNotificationApi(records=[record])
    settings = dataclasses.replace(make_settings(), enable_personal_read=True, read_projects=("demo",))
    check = _work_package_project_allowed_bulk_from(set())  # denied
    service = _service(api=api, settings=settings, work_package_project_allowed_bulk=check)

    result = await service.list_all()

    assert result.count == 0
    assert check.calls == [["/api/v3/work_packages/9"]]  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_list_all_resolves_multiple_distinct_work_packages_in_order() -> None:
    """Mirrors ReminderService's equivalent fan-out test: proves the seam is
    called once per distinct href, in record order, not just for a single
    resource-linked record."""
    allowed = _record(1, resource_link={"href": "/api/v3/work_packages/1"})
    denied = _record(2, resource_link={"href": "/api/v3/work_packages/2"})
    api = _FakeNotificationApi(records=[allowed, denied])
    settings = dataclasses.replace(make_settings(), enable_personal_read=True, read_projects=("demo",))
    check = _work_package_project_allowed_bulk_from({"/api/v3/work_packages/1"})
    service = _service(api=api, settings=settings, work_package_project_allowed_bulk=check)

    result = await service.list_all()

    assert [n.id for n in result.results] == [1]
    # Both notifications fit on one server page -- the bulk hook fires once
    # with both hrefs.
    assert check.calls == [["/api/v3/work_packages/1", "/api/v3/work_packages/2"]]  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_list_all_never_normalizes_a_record_filtered_out_by_the_allowlist() -> None:
    allowed = _record(1, project_link={"href": "/api/v3/projects/1", "title": "Demo"})
    denied = _record_that_crashes_if_normalized(2, project_link={"href": "/api/v3/projects/2", "title": "Other"})
    api = _FakeNotificationApi(records=[allowed, denied])
    settings = dataclasses.replace(make_settings(), enable_personal_read=True, read_projects=("demo",))
    service = _service(api=api, settings=settings)

    result = await service.list_all()

    assert result.count == 1
    assert result.results[0].id == 1


@pytest.mark.asyncio
async def test_list_all_skips_filtering_under_wide_open_scope() -> None:
    api = _FakeNotificationApi(records=[_record(1), _record(2)])
    settings = dataclasses.replace(make_settings(), enable_personal_read=True, read_projects=("*",))
    check = _work_package_project_allowed_bulk_from(set())
    service = _service(api=api, settings=settings, work_package_project_allowed_bulk=check)

    result = await service.list_all()

    assert result.count == 2
    assert check.calls == []  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_list_all_uses_server_reported_total_under_wide_open_scope() -> None:
    api = _FakeNotificationApi(records=[_record(1)], total=50)
    settings = dataclasses.replace(make_settings(), enable_personal_read=True, read_projects=("*",))
    service = _service(api=api, settings=settings)

    result = await service.list_all()

    assert result.total == 50


@pytest.mark.asyncio
async def test_list_all_reports_truncated_and_next_offset_under_wide_open_scope() -> None:
    """Regression: NotificationListResult only ever had count/total -- total was
    always just len(results) (never a real "there are more" signal), so a
    caller had no way to detect if more notifications existed beyond the
    returned page. total=50 with a single-record, limit=1 page must report
    truncated=True/next_offset=2."""
    api = _FakeNotificationApi(records=[_record(1)], total=50)
    settings = dataclasses.replace(make_settings(), enable_personal_read=True, read_projects=("*",))
    service = _service(api=api, settings=settings)

    result = await service.list_all(limit=1, offset=1)

    assert result.truncated is True
    assert result.next_offset == 2

    exhausted_api = _FakeNotificationApi(records=[_record(1)], total=1)
    exhausted_service = _service(api=exhausted_api, settings=settings)
    exhausted_result = await exhausted_service.list_all(limit=1, offset=1)

    assert exhausted_result.truncated is False
    assert exhausted_result.next_offset is None


@pytest.mark.asyncio
async def test_list_all_reports_truncated_under_restrictive_scope_when_limit_hit_mid_page() -> None:
    """Same regression as above, for the restrictive-scope re-scan branch:
    hitting the caller's limit mid-page means at least one more allowed
    notification is waiting on a later server page, so truncated must be
    True."""
    allowed_1 = _record(1, project_link={"href": "/api/v3/projects/1", "title": "Demo"})
    allowed_2 = _record(2, project_link={"href": "/api/v3/projects/1", "title": "Demo"})
    api = _FakePaginatedNotificationApi(pages=[[allowed_1, allowed_2]])
    settings = dataclasses.replace(make_settings(), enable_personal_read=True, read_projects=("demo",))
    service = _service(api=api, settings=settings)

    result = await service.list_all(limit=1)

    assert result.count == 1
    assert result.truncated is True
    assert result.next_offset == 2


@pytest.mark.asyncio
async def test_list_all_reports_not_truncated_under_restrictive_scope_when_genuinely_exhausted() -> None:
    """Counterpart to the above: when the server collection runs out entirely
    (a short/empty final page) before `limit` allowed matches are found,
    truncated must be False and next_offset None."""
    allowed_1 = _record(1, project_link={"href": "/api/v3/projects/1", "title": "Demo"})
    api = _FakePaginatedNotificationApi(pages=[[allowed_1], []])
    settings = dataclasses.replace(make_settings(), enable_personal_read=True, read_projects=("demo",))
    service = _service(api=api, settings=settings)

    result = await service.list_all(limit=5)

    assert result.count == 1
    assert result.truncated is False
    assert result.next_offset is None


@pytest.mark.asyncio
async def test_list_all_not_truncated_when_exactly_limit_allowed_matches_exist_under_restrictive_scope() -> None:
    """Regression test: `_rescan_and_skip`
    previously set `truncated=True` as soon as `len(results) >= limit` was
    reached MID-PAGE, WITHOUT the `limit + 1` lookahead every sibling scan
    helper (`fetch_bounded_and_paginate`/`scan_and_paginate`/
    `scan_records_and_paginate`) already uses to confirm a genuine next match
    exists beyond the requested window -- a false positive whenever a page
    happened to end exactly at the limit-th allowed record, WITHOUT ever
    checking whether a further server page had more. Here the first page has
    exactly `limit`(=2) allowed records, and a second (now-required lookahead)
    page is empty/exhausted -- the pre-fix code would have set
    truncated=True right after page 1 and NEVER issued the page-2 request at
    all; the fixed code must fetch page 2 to confirm exhaustion, mirroring
    the sibling `..._not_truncated_when_exactly_limit_allowed_matches_exist`
    tests elsewhere in this test suite (e.g. test_bounded_fetch_collector.py,
    test_app_document_service.py, test_app_news_service.py)."""
    allowed_1 = _record(1, project_link={"href": "/api/v3/projects/1", "title": "Demo"})
    allowed_2 = _record(2, project_link={"href": "/api/v3/projects/1", "title": "Demo"})
    api = _FakePaginatedNotificationApi(pages=[[allowed_1, allowed_2], []])
    settings = dataclasses.replace(make_settings(), enable_personal_read=True, read_projects=("demo",))
    service = _service(api=api, settings=settings)

    result = await service.list_all(limit=2)

    assert result.count == 2
    assert [n.id for n in result.results] == [1, 2]
    assert result.truncated is False
    assert result.next_offset is None
    # The lookahead page MUST have been fetched -- the pre-fix code stopped
    # (and set truncated=True) right after page 1, without ever issuing this
    # second request.
    assert len(api.list_all_calls) == 2


@pytest.mark.asyncio
async def test_list_all_raises_exception_for_a_record_inside_the_skip_window() -> None:
    """Regression test: a record whose allowlist check fails MUST still
    raise even when it falls inside the (offset-1)*limit skip window -- the
    skip counter only skips already-confirmed ALLOWED records, it does not
    skip performing the check itself, so the old one-at-a-time control flow
    would have awaited (and propagated a failure for) every record up to and
    including the (limit+1)-th allowed one, not just the ones actually kept
    in the returned page. A 2nd-round Codex review caught this: an earlier
    draft of the fix wrongly treated any failure inside the skip window as
    "not a match" and silently continued instead of raising."""
    failing = _record(1, resource_link={"href": "/api/v3/work_packages/1"})
    kept = _record(2, resource_link={"href": "/api/v3/work_packages/2"})
    api = _FakeNotificationApi(records=[failing, kept])
    settings = dataclasses.replace(make_settings(), enable_personal_read=True, read_projects=("demo",))
    check = _work_package_project_allowed_bulk_from(
        {"/api/v3/work_packages/2"},
        errors={"/api/v3/work_packages/1": RuntimeError("transient failure inside the skip window")},
    )
    service = _service(api=api, settings=settings, work_package_project_allowed_bulk=check)

    # offset=2, limit=1 -> skip_count = (2-1)*1 = 1, so the first allowed
    # record found would be skipped, not the first record in raw order --
    # `failing` is the record actually inside that skip window here.
    with pytest.raises(RuntimeError, match="transient failure inside the skip window"):
        await service.list_all(offset=2, limit=1)


@pytest.mark.asyncio
async def test_list_all_raises_exception_still_within_the_limit_plus_one_lookahead() -> None:
    """Regression test: a record whose allowlist check fails while
    `len(results) == limit` (i.e. the loop is still searching for the
    (limit+1)-th confirmed match, per `while len(results) <= limit`) MUST
    still raise -- only records the loop never reaches AFTER the (limit+1)-th
    allowed record is actually found and appended (the `break` further down)
    are exempt. An earlier draft of the fix wrongly swallowed any failure
    once `len(results) >= limit`, which is one record too early."""
    kept = _record(1, resource_link={"href": "/api/v3/work_packages/1"})
    failing = _record(2, resource_link={"href": "/api/v3/work_packages/2"})
    api = _FakeNotificationApi(records=[kept, failing])
    settings = dataclasses.replace(make_settings(), enable_personal_read=True, read_projects=("demo",))
    check = _work_package_project_allowed_bulk_from(
        {"/api/v3/work_packages/1"},
        errors={"/api/v3/work_packages/2": RuntimeError("failure still inside the lookahead search")},
    )
    service = _service(api=api, settings=settings, work_package_project_allowed_bulk=check)

    # limit=1: after `kept` is appended, len(results) == 1 == limit -- the
    # loop is still searching for the (limit+1)-th match, so `failing`'s
    # outcome must still be consulted (and raised), not silently discarded.
    with pytest.raises(RuntimeError, match="failure still inside the lookahead search"):
        await service.list_all(limit=1)


class _FakePaginatedNotificationApi:
    """Simulates real server-side pagination across multiple pages, unlike
    _FakeNotificationApi (which always returns everything in one page and
    exhausted=True) -- needed to prove the re-scan-and-skip loop actually
    continues past a page whose allowed subset runs dry before the caller's
    requested limit does."""

    def __init__(self, pages: list[list[NotificationRecord]]) -> None:
        self._pages = pages
        self.list_all_calls: list[tuple[bool, int, int]] = []

    async def list_all(self, *, unread_only: bool, offset: int, limit: int) -> NotificationPage:
        self.list_all_calls.append((unread_only, offset, limit))
        page_index = offset - 1
        if page_index >= len(self._pages):
            return NotificationPage(records=[], total=0, exhausted=True)
        records = self._pages[page_index]
        total = sum(len(p) for p in self._pages)
        exhausted = offset >= len(self._pages)
        return NotificationPage(records=records, total=total, exhausted=exhausted)


@pytest.mark.asyncio
async def test_list_all_rescans_past_a_page_whose_allowed_subset_runs_dry() -> None:
    """Regression test: a filtered-empty server page
    does not prove no further allowed notifications exist on later pages --
    the Service must keep fetching subsequent server pages under a
    restrictive scope, not stop at the first page's filtered result."""
    allowed = _record(1, project_link={"href": "/api/v3/projects/1", "title": "Demo"})
    denied = _record(2, project_link={"href": "/api/v3/projects/2", "title": "Other"})
    api = _FakePaginatedNotificationApi(pages=[[denied], [denied], [allowed]])
    settings = dataclasses.replace(make_settings(), enable_personal_read=True, read_projects=("demo",))
    service = _service(api=api, settings=settings)

    result = await service.list_all(limit=1)

    assert result.count == 1
    assert result.results[0].id == 1
    # Confirms it actually walked all 3 server pages, not just the first.
    assert len(api.list_all_calls) == 3


# --- mark_read / mark_all_read -------------------------------------------------


@pytest.mark.asyncio
async def test_mark_read_previews_without_confirm() -> None:
    api = _FakeNotificationApi()
    settings = dataclasses.replace(make_settings(), enable_personal_write=True)
    service = _service(api=api, settings=settings)

    result = await service.mark_read(10)

    assert result.state == "preview"
    assert result.notification_id == 10
    assert api.mark_read_calls == []


@pytest.mark.asyncio
async def test_mark_read_denied_without_personal_write_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_personal_write=False)
    service = _service(settings=settings)

    with pytest.raises(PermissionDeniedError, match="personal"):
        await service.mark_read(10)


@pytest.mark.asyncio
async def test_mark_read_calls_api_after_confirmation() -> None:
    api = _FakeNotificationApi()
    settings = dataclasses.replace(make_settings(), enable_personal_write=True)
    service = _service(api=api, settings=settings)

    result = await service.mark_read(10, confirm=True)

    assert result.state == "confirmed"
    assert result.notification_id == 10
    assert api.mark_read_calls == [10]


@pytest.mark.asyncio
async def test_mark_all_read_denied_without_personal_write_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_personal_write=False)
    service = _service(settings=settings)

    with pytest.raises(PermissionDeniedError, match="personal"):
        await service.mark_all_read()


@pytest.mark.asyncio
async def test_mark_all_read_previews_without_confirm() -> None:
    api = _FakeNotificationApi()
    settings = dataclasses.replace(make_settings(), enable_personal_write=True)
    service = _service(api=api, settings=settings)

    result = await service.mark_all_read()

    assert result.state == "preview"
    assert result.notification_id is None
    assert api.mark_all_read_calls == 0


@pytest.mark.asyncio
async def test_mark_all_read_calls_api_after_confirmation() -> None:
    api = _FakeNotificationApi()
    settings = dataclasses.replace(make_settings(), enable_personal_write=True)
    service = _service(api=api, settings=settings)

    result = await service.mark_all_read(confirm=True)

    assert result.state == "confirmed"
    assert result.notification_id is None
    assert api.mark_all_read_calls == 1


# --- entity-scope regression --------------------------------------------------


@pytest.mark.asyncio
async def test_project_name_hidden_by_notification_scope_not_project_scope() -> None:
    """Regression test for the entity="notification" vs a same-shaped
    neighbor hide-field bug class (same bug class as the
    Priority/Notification findings, and the file_link/grid finding)."""
    record = _record(1, project_link={"href": "/api/v3/projects/6", "title": "Demo Project"})
    api = _FakeNotificationApi(records=[record])

    settings_project_hidden = dataclasses.replace(
        make_settings(), enable_personal_read=True, hidden_fields={"project": ("project_name",)}
    )
    service_project_hidden = _service(api=api, settings=settings_project_hidden)
    result_project_hidden = await service_project_hidden.list_all()
    assert getattr(result_project_hidden.results[0], "_hidden_keys", frozenset()) == frozenset()

    settings_notification_hidden = dataclasses.replace(
        make_settings(), enable_personal_read=True, hidden_fields={"notification": ("project_name",)}
    )
    service_notification_hidden = _service(api=api, settings=settings_notification_hidden)
    result_notification_hidden = await service_notification_hidden.list_all()
    assert getattr(result_notification_hidden.results[0], "_hidden_keys", frozenset()) == {"project_name"}
