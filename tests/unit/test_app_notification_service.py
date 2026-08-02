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
        url=f"https://op.example.com/api/v3/notifications/{notification_id}",
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


def _service(
    *,
    api: _FakeNotificationApi | None = None,
    settings=None,
    work_package_project_allowed=None,
) -> NotificationService:
    return NotificationService(
        api=api or _FakeNotificationApi(),
        settings=settings or dataclasses.replace(make_settings(), enable_personal_read=True),
        project_id_to_identifier=PROJECT_ID_TO_IDENTIFIER,
        work_package_project_allowed=work_package_project_allowed or _work_package_project_allowed_from(set()),
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
    check = _work_package_project_allowed_from(set())  # denied
    service = _service(api=api, settings=settings, work_package_project_allowed=check)

    result = await service.list_all()

    assert result.count == 0
    assert check.calls == ["/api/v3/work_packages/9"]  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_list_all_resolves_multiple_distinct_work_packages_in_order() -> None:
    """Mirrors ReminderService's equivalent fan-out test: proves the seam is
    called once per distinct href, in record order, not just for a single
    resource-linked record."""
    allowed = _record(1, resource_link={"href": "/api/v3/work_packages/1"})
    denied = _record(2, resource_link={"href": "/api/v3/work_packages/2"})
    api = _FakeNotificationApi(records=[allowed, denied])
    settings = dataclasses.replace(make_settings(), enable_personal_read=True, read_projects=("demo",))
    check = _work_package_project_allowed_from({"/api/v3/work_packages/1"})
    service = _service(api=api, settings=settings, work_package_project_allowed=check)

    result = await service.list_all()

    assert [n.id for n in result.results] == [1]
    assert check.calls == ["/api/v3/work_packages/1", "/api/v3/work_packages/2"]  # type: ignore[attr-defined]


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
    check = _work_package_project_allowed_from(set())
    service = _service(api=api, settings=settings, work_package_project_allowed=check)

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

    assert result.confirmed is False
    assert result.requires_confirmation is True
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

    assert result.confirmed is True
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

    assert result.confirmed is False
    assert result.notification_id is None
    assert api.mark_all_read_calls == 0


@pytest.mark.asyncio
async def test_mark_all_read_calls_api_after_confirmation() -> None:
    api = _FakeNotificationApi()
    settings = dataclasses.replace(make_settings(), enable_personal_write=True)
    service = _service(api=api, settings=settings)

    result = await service.mark_all_read(confirm=True)

    assert result.confirmed is True
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
