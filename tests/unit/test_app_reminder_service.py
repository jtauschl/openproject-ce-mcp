from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import InvalidInputError, PermissionDeniedError
from openproject_ce_mcp.app.ports.reminder_api import ReminderRecord
from openproject_ce_mcp.app.services.reminder_service import ReminderService
from openproject_ce_mcp.models import ReminderSummary

PROJECT_ID_TO_IDENTIFIER = {6: "demo", 7: "secret"}


def _summary(reminder_id: int = 7, *, work_package_id: int | None = 42) -> ReminderSummary:
    return ReminderSummary(
        id=reminder_id,
        remind_at="2026-12-01T09:00:00Z",
        note="n",
        work_package_id=work_package_id,
        creator="Alice",
    )


def _record(reminder_id: int = 7, *, remindable_href: str | None = "/api/v3/work_packages/42") -> ReminderRecord:
    remindable_link = {"href": remindable_href} if remindable_href is not None else None
    summary = _summary(reminder_id)
    return ReminderRecord(summary=lambda: summary, remindable_link=remindable_link)


def _raw(reminder_id: int, *, remindable_href: str | None) -> dict:
    """A raw payload standing in for what fetch_page's `_embedded.elements`
    would contain -- `_FakeReminderApi.to_record` below turns this into a
    ReminderRecord, mirroring the real Adapter's fetch_page/to_record split
    (OPM-379/F5)."""
    links = {"remindable": {"href": remindable_href}} if remindable_href is not None else {}
    return {"id": reminder_id, "_links": links}


def _record_that_crashes_if_normalized(reminder_id: int, *, remindable_href: str | None) -> dict:
    """A raw payload whose to_record().summary() raises -- for proving
    list_all() never normalizes a record it has already decided to filter
    out. Mirrors the real HttpxReminderApi's actual failure mode:
    normalize_reminder crashes with a KeyError on a payload missing "id",
    not a made-up test-only exception type."""
    links = {"remindable": {"href": remindable_href}} if remindable_href is not None else {}
    return {"id": reminder_id, "_links": links, "_crash_if_normalized": True}


class _FakeReminderApi:
    def __init__(
        self, raw_elements: list[dict] | None = None, *, reminder_id: int = 7, record: ReminderRecord | None = None
    ) -> None:
        # Single-record fakes (used by get()/get_remindable_link()/update())
        # pass `reminder_id` (and optionally an explicit `record`, e.g. with a
        # malformed/missing remindable link); multi-record fakes (used by
        # list_all() only) never call get()/update() and don't need `_by_id`
        # populated.
        self._raw_elements = (
            raw_elements
            if raw_elements is not None
            else [_raw(reminder_id, remindable_href="/api/v3/work_packages/42")]
        )
        self._by_id = {reminder_id: record or _record(reminder_id)} if raw_elements is None else None
        self.fetch_page_calls = 0
        self.get_calls: list[int] = []
        self.get_remindable_link_calls: list[int] = []
        self.create_calls: list[tuple[int, dict]] = []
        self.update_calls: list[tuple[int, dict]] = []
        self.delete_calls: list[int] = []

    async def fetch_page(self, *, offset: int, page_size: int) -> dict:
        self.fetch_page_calls += 1
        if offset > 1:
            return {"_embedded": {"elements": []}}
        return {"_embedded": {"elements": self._raw_elements}}

    def to_record(self, payload: dict) -> ReminderRecord:
        remindable_link = payload.get("_links", {}).get("remindable")
        reminder_id = payload["id"]
        if payload.get("_crash_if_normalized"):

            def _boom() -> ReminderSummary:
                raise AssertionError(
                    f"summary() must never be called for reminder {reminder_id} once "
                    "it has been filtered out by the allowlist check"
                )

            return ReminderRecord(summary=_boom, remindable_link=remindable_link)
        summary = _summary(reminder_id)
        return ReminderRecord(summary=lambda: summary, remindable_link=remindable_link)

    async def get(self, reminder_id: int) -> ReminderRecord:
        self.get_calls.append(reminder_id)
        assert self._by_id is not None, "get() needs a single-record fake"
        return self._by_id[reminder_id]

    async def get_remindable_link(self, reminder_id: int) -> dict | None:
        self.get_remindable_link_calls.append(reminder_id)
        assert self._by_id is not None, "get_remindable_link() needs a single-record fake"
        return self._by_id[reminder_id].remindable_link

    async def create(self, work_package_id: int, payload: dict) -> ReminderRecord:
        self.create_calls.append((work_package_id, payload))
        return _record()

    async def update(self, reminder_id: int, payload: dict) -> ReminderRecord:
        self.update_calls.append((reminder_id, payload))
        assert self._by_id is not None, "update() needs a single-record fake constructed with reminder_id="
        return self._by_id[reminder_id]

    async def delete(self, reminder_id: int) -> None:
        self.delete_calls.append(reminder_id)


class _FakeWorkPackageLookupApi:
    def __init__(self, project_link: dict | None = None) -> None:
        self._project_link = project_link or {"href": "/api/v3/projects/6"}
        self.get_by_href_calls: list[str] = []

    async def get(self, work_package_ref: str) -> dict:
        raise AssertionError("get should not be used by ReminderService's update/delete path")

    async def get_by_href(self, href: str) -> dict:
        self.get_by_href_calls.append(href)
        return {"_links": {"project": self._project_link}}


def _resolve_work_package_id_ok(resolved_id: int = 42):
    calls: list[tuple[int | str, bool]] = []

    async def resolve(work_package_ref: int | str, *, write: bool = False) -> int:
        calls.append((work_package_ref, write))
        return resolved_id

    resolve.calls = calls  # type: ignore[attr-defined]
    return resolve


def _resolve_work_package_id_denied():
    async def resolve(work_package_ref: int | str, *, write: bool = False) -> int:
        raise PermissionDeniedError("OpenProject access to this project is disabled.")

    return resolve


def _work_package_project_allowed_from(allowed_hrefs: set[str]):
    calls: list[str] = []

    async def check(href: str, *, context=None) -> bool:
        calls.append(href)
        return href in allowed_hrefs

    check.calls = calls  # type: ignore[attr-defined]
    return check


def _work_package_project_allowed_bulk_from(allowed_hrefs: set[str]):
    """Fake `WorkPackageProjectAllowedBulkCheck` (OPM-379/F3): mirrors
    `WorkPackageResolver.project_links_allowed`'s dedupe/cache/only-bools-
    cached contract closely enough for Service-level tests. `calls` records
    each bulk invocation's deduped href list (in order), for tests that need
    to assert the Service resolved the right set of hrefs -- concurrency
    itself is exercised at the resolver level, not re-proven here."""
    calls: list[list[str]] = []

    async def bulk(hrefs, *, context) -> dict[str, bool | Exception]:
        unique = list(dict.fromkeys(hrefs))
        calls.append(unique)
        outcomes: dict[str, bool | Exception] = {}
        for href in unique:
            cached = context.get(href)
            if cached is not None:
                outcomes[href] = cached
                continue
            allowed = href in allowed_hrefs
            context.set(href, allowed)
            outcomes[href] = allowed
        return outcomes

    bulk.calls = calls  # type: ignore[attr-defined]
    return bulk


def _service(
    *,
    api: _FakeReminderApi | None = None,
    work_package_lookup_api: _FakeWorkPackageLookupApi | None = None,
    settings=None,
    resolve_work_package_id=None,
    work_package_project_allowed=None,
    work_package_project_allowed_bulk=None,
) -> ReminderService:
    return ReminderService(
        api=api or _FakeReminderApi(),
        work_package_lookup_api=work_package_lookup_api or _FakeWorkPackageLookupApi(),
        settings=settings or make_settings(),
        project_id_to_identifier=PROJECT_ID_TO_IDENTIFIER,
        resolve_work_package_id=resolve_work_package_id or _resolve_work_package_id_ok(),
        work_package_project_allowed=work_package_project_allowed
        or _work_package_project_allowed_from({"/api/v3/work_packages/42"}),
        work_package_project_allowed_bulk=work_package_project_allowed_bulk
        or _work_package_project_allowed_bulk_from({"/api/v3/work_packages/42"}),
    )


# --- list_all -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_all_returns_empty_without_a_request_under_empty_read_projects() -> None:
    api = _FakeReminderApi()
    settings = dataclasses.replace(make_settings(), read_projects=())
    service = _service(api=api, settings=settings)

    result = await service.list_all()

    assert result.count == 0
    assert result.results == []
    assert api.fetch_page_calls == 0


@pytest.mark.asyncio
async def test_list_all_filters_by_read_projects_via_work_package() -> None:
    allowed = _raw(1, remindable_href="/api/v3/work_packages/1")
    denied = _raw(2, remindable_href="/api/v3/work_packages/2")
    api = _FakeReminderApi(raw_elements=[allowed, denied])
    settings = dataclasses.replace(make_settings(), read_projects=("demo",))
    check = _work_package_project_allowed_bulk_from({"/api/v3/work_packages/1"})
    service = _service(api=api, settings=settings, work_package_project_allowed_bulk=check)

    result = await service.list_all()

    assert result.count == 1
    assert result.results[0].id == 1
    assert len(check.calls) == 1, "both reminders fit on one server page -- the bulk hook must fire exactly once"
    assert set(check.calls[0]) == {"/api/v3/work_packages/1", "/api/v3/work_packages/2"}  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_list_all_never_normalizes_a_record_filtered_out_by_the_allowlist() -> None:
    """Regression: client.py's
    original filters RAW elements by allowlist first, normalizing only the
    survivors -- an eager `summary` field would normalize every record up
    front (including denied ones), which would also crash on a denied
    record missing an unrelated field like "id" instead of being silently
    excluded. ReminderRecord.summary is a lazy callable specifically so a
    denied record's summary() is never invoked."""
    allowed = _raw(1, remindable_href="/api/v3/work_packages/1")
    denied = _record_that_crashes_if_normalized(2, remindable_href="/api/v3/work_packages/2")
    api = _FakeReminderApi(raw_elements=[allowed, denied])
    settings = dataclasses.replace(make_settings(), read_projects=("demo",))
    check = _work_package_project_allowed_bulk_from({"/api/v3/work_packages/1"})
    service = _service(api=api, settings=settings, work_package_project_allowed_bulk=check)

    result = await service.list_all()

    assert result.count == 1
    assert result.results[0].id == 1


@pytest.mark.asyncio
async def test_list_all_skips_records_with_no_remindable_link() -> None:
    no_link = _raw(1, remindable_href=None)
    api = _FakeReminderApi(raw_elements=[no_link])
    settings = dataclasses.replace(make_settings(), read_projects=("demo",))
    check = _work_package_project_allowed_bulk_from(set())
    service = _service(api=api, settings=settings, work_package_project_allowed_bulk=check)

    result = await service.list_all()

    assert result.count == 0
    # No remindable href to resolve at all -- the bulk hook must not even be
    # called with an empty href list.
    assert check.calls == []  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_list_all_skips_filtering_under_wide_open_scope() -> None:
    api = _FakeReminderApi()
    settings = dataclasses.replace(make_settings(), read_projects=("*",))
    check = _work_package_project_allowed_bulk_from(set())
    service = _service(api=api, settings=settings, work_package_project_allowed_bulk=check)

    result = await service.list_all()

    assert result.count == 1
    assert check.calls == []  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_list_all_masks_hidden_note() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"reminder": ("note",)})
    service = _service(settings=settings)

    result = await service.list_all()

    assert getattr(result.results[0], "_hidden_keys", frozenset()) == {"note"}


# --- create -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_preview_without_confirm_does_not_call_api_create() -> None:
    api = _FakeReminderApi()
    resolver = _resolve_work_package_id_ok(resolved_id=42)
    service = _service(api=api, resolve_work_package_id=resolver)

    result = await service.create(work_package_id=42, remind_at="2026-12-01T09:00:00Z", confirm=False)

    assert result.state == "preview"
    assert result.reminder_id is None
    assert result.result is None
    assert api.create_calls == []
    assert resolver.calls == [(42, True)]  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_create_commit_with_confirm_calls_api_create() -> None:
    api = _FakeReminderApi()
    service = _service(api=api)

    result = await service.create(work_package_id=42, remind_at="2026-12-01T09:00:00Z", note="n", confirm=True)

    assert result.state == "confirmed"
    assert result.reminder_id == 7
    assert result.result is not None
    assert api.create_calls == [(42, {"remindAt": "2026-12-01T09:00:00Z", "note": "n"})]


@pytest.mark.asyncio
async def test_create_denies_write_outside_write_allowlist() -> None:
    api = _FakeReminderApi()
    service = _service(api=api, resolve_work_package_id=_resolve_work_package_id_denied())

    with pytest.raises(PermissionDeniedError):
        await service.create(work_package_id=42, remind_at="2026-12-01T09:00:00Z", confirm=True)

    assert api.create_calls == []


@pytest.mark.asyncio
async def test_create_denies_write_even_without_confirm() -> None:
    api = _FakeReminderApi()
    service = _service(api=api, resolve_work_package_id=_resolve_work_package_id_denied())

    with pytest.raises(PermissionDeniedError):
        await service.create(work_package_id=42, remind_at="2026-12-01T09:00:00Z", confirm=False)

    assert api.create_calls == []


@pytest.mark.asyncio
async def test_create_rejects_hidden_note_field() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"reminder": ("note",)})
    service = _service(settings=settings)

    with pytest.raises(InvalidInputError, match="hidden"):
        await service.create(work_package_id=42, remind_at="2026-12-01T09:00:00Z", note="secret", confirm=False)


# --- update -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_preview_without_confirm_does_not_call_api_update() -> None:
    api = _FakeReminderApi()
    work_package_lookup_api = _FakeWorkPackageLookupApi()
    service = _service(api=api, work_package_lookup_api=work_package_lookup_api)

    result = await service.update(reminder_id=7, note="updated", confirm=False)

    assert result.state == "preview"
    assert api.update_calls == []
    assert api.get_remindable_link_calls == [7]
    # The href passed to get_by_href must be the one derived from THIS
    # reminder's own remindable link, not hardcoded or swapped -- found
    # missing during this migration's step-6 self-audit (every fixture in
    # this file happens to share the same href, so a hardcoded-href or
    # argument-swap bug would otherwise slip through undetected).
    assert work_package_lookup_api.get_by_href_calls == ["/api/v3/work_packages/42"]


@pytest.mark.asyncio
async def test_update_commit_with_confirm_calls_api_update() -> None:
    api = _FakeReminderApi()
    service = _service(api=api)

    result = await service.update(reminder_id=7, note="updated", confirm=True)

    assert result.state == "confirmed"
    assert result.result is not None
    assert api.update_calls == [(7, {"note": "updated"})]


@pytest.mark.asyncio
async def test_update_requires_a_field() -> None:
    api = _FakeReminderApi()
    service = _service(api=api)

    with pytest.raises(InvalidInputError, match="At least one field"):
        await service.update(reminder_id=7, confirm=True)

    assert api.update_calls == []


@pytest.mark.asyncio
async def test_update_denies_malformed_remindable_link_even_under_open_scope() -> None:
    api = _FakeReminderApi(record=_record(7, remindable_href=None))
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("*",))
    service = _service(api=api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await service.update(reminder_id=7, note="updated", confirm=True)

    assert api.update_calls == []


@pytest.mark.asyncio
async def test_delete_denies_malformed_remindable_link_even_under_open_scope() -> None:
    """Mirrors test_update_denies_malformed_remindable_link_even_under_open_scope
    -- delete() shares the identical _ensure_reminder_project_write_allowed
    helper, so this must fail closed the same way, not just update()."""
    api = _FakeReminderApi(record=_record(7, remindable_href=None))
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("*",))
    service = _service(api=api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await service.delete(reminder_id=7, confirm=True)

    assert api.delete_calls == []


@pytest.mark.asyncio
async def test_update_denies_write_outside_write_allowlist() -> None:
    api = _FakeReminderApi()
    work_package_lookup_api = _FakeWorkPackageLookupApi(project_link={"href": "/api/v3/projects/7"})
    settings = dataclasses.replace(make_settings(), write_projects=("demo",))
    service = _service(api=api, work_package_lookup_api=work_package_lookup_api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.update(reminder_id=7, note="updated", confirm=True)

    assert api.update_calls == []


@pytest.mark.asyncio
async def test_update_denies_write_even_without_confirm() -> None:
    api = _FakeReminderApi()
    work_package_lookup_api = _FakeWorkPackageLookupApi(project_link={"href": "/api/v3/projects/7"})
    settings = dataclasses.replace(make_settings(), write_projects=("demo",))
    service = _service(api=api, work_package_lookup_api=work_package_lookup_api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.update(reminder_id=7, note="updated", confirm=False)

    assert api.update_calls == []


# --- delete -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_preview_without_confirm_does_not_call_api_delete() -> None:
    api = _FakeReminderApi()
    service = _service(api=api)

    result = await service.delete(reminder_id=7, confirm=False)

    assert result.state == "preview"
    assert api.delete_calls == []


@pytest.mark.asyncio
async def test_delete_commit_with_confirm_calls_api_delete() -> None:
    api = _FakeReminderApi()
    service = _service(api=api)

    result = await service.delete(reminder_id=7, confirm=True)

    assert result.state == "confirmed"
    assert result.result is None
    assert api.delete_calls == [7]


@pytest.mark.asyncio
async def test_delete_denies_write_outside_write_allowlist() -> None:
    api = _FakeReminderApi()
    work_package_lookup_api = _FakeWorkPackageLookupApi(project_link={"href": "/api/v3/projects/7"})
    settings = dataclasses.replace(make_settings(), write_projects=("demo",))
    service = _service(api=api, work_package_lookup_api=work_package_lookup_api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.delete(reminder_id=7, confirm=True)

    assert api.delete_calls == []


@pytest.mark.asyncio
async def test_delete_denies_write_even_without_confirm() -> None:
    api = _FakeReminderApi()
    work_package_lookup_api = _FakeWorkPackageLookupApi(project_link={"href": "/api/v3/projects/7"})
    settings = dataclasses.replace(make_settings(), write_projects=("demo",))
    service = _service(api=api, work_package_lookup_api=work_package_lookup_api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.delete(reminder_id=7, confirm=False)

    assert api.delete_calls == []


# --- entity-scope regression --------------------------------------------------


@pytest.mark.asyncio
async def test_note_hidden_by_reminder_scope_not_watcher_scope() -> None:
    """Regression test for the entity="reminder" vs a same-shaped neighbor
    hide-field bug class (same bug class as the Priority/Notification
    findings)."""
    settings_watcher_hidden = dataclasses.replace(make_settings(), hidden_fields={"watcher": ("note",)})
    service_watcher_hidden = _service(settings=settings_watcher_hidden)
    result_watcher_hidden = await service_watcher_hidden.list_all()
    assert getattr(result_watcher_hidden.results[0], "_hidden_keys", frozenset()) == frozenset()

    settings_reminder_hidden = dataclasses.replace(make_settings(), hidden_fields={"reminder": ("note",)})
    service_reminder_hidden = _service(settings=settings_reminder_hidden)
    result_reminder_hidden = await service_reminder_hidden.list_all()
    assert getattr(result_reminder_hidden.results[0], "_hidden_keys", frozenset()) == {"note"}
