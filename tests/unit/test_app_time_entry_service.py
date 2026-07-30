from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import InvalidInputError, PermissionDeniedError
from openproject_ce_mcp.app.ports.time_entry_api import TimeEntryActivityRecord, TimeEntryFormResult, TimeEntryRecord
from openproject_ce_mcp.app.ports.user_api import UserRecord
from openproject_ce_mcp.app.services.time_entry_service import TimeEntryService
from openproject_ce_mcp.models import CurrentUser, TimeEntryActivitySummary, TimeEntrySummary, UserSummary

PROJECT_ID_TO_IDENTIFIER = {1: "demo", 20: "other"}


def _summary(
    time_entry_id: int = 7,
    *,
    project: str | None = "Demo",
    entity_type: str | None = "WorkPackage",
    entity_id: int | None = 42,
    user: str | None = "Admin",
    activity: str | None = "Development",
    hours: str | None = "PT1H",
    spent_on: str | None = "2026-03-20",
    comment: str | None = None,
) -> TimeEntrySummary:
    return TimeEntrySummary(
        id=time_entry_id,
        project=project,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_name="Task",
        user=user,
        activity=activity,
        hours=hours,
        spent_on=spent_on,
        start_time=None,
        end_time=None,
        ongoing=False,
        comment=comment,
        created_at=None,
        updated_at=None,
        url="https://op.example.com/time_entries/7",
    )


def _activity_summary(activity_id: int = 1, *, name: str = "Development") -> TimeEntryActivitySummary:
    return TimeEntryActivitySummary(
        id=activity_id,
        name=name,
        position=1,
        is_default=True,
        projects=["Demo"],
        url=f"https://op.example.com/time_entries/activities/{activity_id}",
    )


class _FakeTimeEntryApi:
    def __init__(
        self,
        records: list[TimeEntrySummary] | None = None,
        *,
        time_entry_id: int = 7,
        project_link: dict | None = None,
        activities: list[TimeEntryActivitySummary] | None = None,
        fetch_activities_result: dict | None = None,
        form_payload_overrides: dict | None = None,
    ) -> None:
        self._list_summaries = records if records is not None else [_summary()]
        self._project_link = project_link or {"href": "/api/v3/projects/1", "title": "Demo"}
        self._by_id = {time_entry_id: self._list_summaries[0]} if len(self._list_summaries) == 1 else None
        self._activities = activities if activities is not None else [_activity_summary()]
        self._fetch_activities_result = fetch_activities_result
        self._form_payload_overrides = form_payload_overrides or {}
        self.fetch_page_calls: list[tuple[int, int]] = []
        self.get_raw_calls: list[int] = []
        self.validate_create_calls: list[dict] = []
        self.validate_update_calls: list[tuple[int, dict]] = []
        self.create_calls: list[dict] = []
        self.update_calls: list[tuple[int, dict]] = []
        self.delete_calls: list[int] = []
        self.fetch_activities_for_entity_calls: list[tuple[int, int | None]] = []

    def to_record(self, payload: dict, *, text_limit: int | None) -> TimeEntryRecord:
        return TimeEntryRecord(summary=lambda: payload["__summary__"])

    def to_activity_record(self, payload: dict) -> TimeEntryActivityRecord:
        return TimeEntryActivityRecord(summary=payload["__summary__"])

    def project_link_title_and_id(self, link):
        if not isinstance(link, dict):
            return None, None
        href = link.get("href")
        project_id = int(href.rstrip("/").split("/")[-1]) if href else None
        return link.get("title"), project_id

    def parse_form_result(self, form: dict) -> TimeEntryFormResult:
        embedded = form.get("_embedded", {})
        return TimeEntryFormResult(
            payload=embedded.get("payload", {}), validation_errors=embedded.get("validationErrors", {})
        )

    async def fetch_page(self, *, offset: int, page_size: int) -> dict:
        self.fetch_page_calls.append((offset, page_size))
        elements = [
            {"id": i, "__summary__": s, "_links": {"project": self._project_link}}
            for i, s in enumerate(self._list_summaries)
        ]
        return {"_embedded": {"elements": elements}}

    async def get_raw(self, time_entry_id: int) -> dict:
        self.get_raw_calls.append(time_entry_id)
        assert self._by_id is not None, "get_raw() needs a single-record fake"
        return {"__summary__": self._by_id[time_entry_id], "_links": {"project": self._project_link}}

    async def validate_create(self, payload: dict) -> dict:
        self.validate_create_calls.append(payload)
        canonical = {**payload, **self._form_payload_overrides}
        return {"_embedded": {"payload": canonical, "validationErrors": {}}}

    async def validate_update(self, time_entry_id: int, payload: dict) -> dict:
        self.validate_update_calls.append((time_entry_id, payload))
        canonical = {**payload, **self._form_payload_overrides}
        return {"_embedded": {"payload": canonical, "validationErrors": {}}}

    async def create(self, payload: dict) -> TimeEntryRecord:
        self.create_calls.append(payload)
        return TimeEntryRecord(summary=lambda: _summary(650))

    async def update(self, time_entry_id: int, payload: dict) -> TimeEntryRecord:
        self.update_calls.append((time_entry_id, payload))
        assert self._by_id is not None
        return TimeEntryRecord(summary=lambda: self._by_id[time_entry_id])

    async def delete(self, time_entry_id: int) -> None:
        self.delete_calls.append(time_entry_id)

    async def fetch_activities(self) -> dict | None:
        return self._fetch_activities_result

    async def fetch_activities_for_entity(self, *, project_id: int, work_package_id: int | None) -> dict:
        self.fetch_activities_for_entity_calls.append((project_id, work_package_id))
        allowed = [{"__summary__": a} for a in self._activities]
        return {"_embedded": {"schema": {"activity": {"_embedded": {"allowedValues": allowed}}}}}


class _FakeProjectApi:
    """Only used via fetch_project_page -- fetch_project_page itself calls
    api.list(...), so this fake models THAT contract, not TimeEntryApi's."""

    def __init__(self, projects: list[tuple[int, str]] | None = None, *, list_raises: Exception | None = None) -> None:
        self._projects = projects if projects is not None else [(1, "Demo")]
        self._list_raises = list_raises

    async def list(self, *, server_offset: int, server_page_size: int, search, text_limit=None):
        from openproject_ce_mcp.app.ports.project_api import ProjectPage, ProjectRecord
        from openproject_ce_mcp.models import ProjectSummary

        if self._list_raises is not None:
            raise self._list_raises
        if server_offset > 1:
            return ProjectPage(records=[])
        records = [
            ProjectRecord(
                summary=ProjectSummary(
                    id=pid,
                    name=name,
                    identifier=f"proj-{pid}",
                    active=True,
                    description=None,
                    url=f"https://op.example.com/projects/{pid}",
                ),
                to_detail=lambda: (_ for _ in ()).throw(AssertionError("unused")),
                payload={"id": pid, "name": name, "_links": {"self": {"href": f"/api/v3/projects/{pid}"}}},
            )
            for pid, name in self._projects
        ]
        return ProjectPage(records=records, server_total=len(records), exhausted=True)


class _FakeUserApi:
    def __init__(self, *, user_id: int = 9, name: str = "Numeric User") -> None:
        self.get_user_calls: list[str] = []
        self._user_id = user_id
        self._name = name

    async def get_user(self, user_ref: str) -> UserRecord:
        self.get_user_calls.append(user_ref)
        summary = UserSummary(
            id=self._user_id,
            name=self._name,
            login="numeric",
            email=None,
            status=None,
            admin=False,
            locked=False,
            avatar_url=None,
            created_at=None,
            updated_at=None,
            url=f"https://op.example.com/users/{self._user_id}",
        )
        return UserRecord(summary=summary, to_detail=lambda: (_ for _ in ()).throw(AssertionError("unused")))


class _FakeWorkPackageLookupApi:
    def __init__(self, project_link: dict | None = None) -> None:
        self._project_link = project_link or {"href": "/api/v3/projects/1", "title": "Demo"}
        self.get_calls: list[str] = []

    async def get(self, work_package_ref: str) -> dict:
        self.get_calls.append(work_package_ref)
        return {"id": 42, "_links": {"project": self._project_link}}

    async def get_by_href(self, href: str) -> dict:
        return {"_links": {"project": self._project_link}}


def _resolve_work_package_id_ok(resolved_id: int = 42):
    calls: list[tuple[int | str, bool]] = []

    async def resolve(work_package_ref, *, write: bool = False) -> int:
        calls.append((work_package_ref, write))
        return resolved_id

    resolve.calls = calls  # type: ignore[attr-defined]
    return resolve


def _resolve_project_ref_ok(project_id: int = 1, name: str = "Demo"):
    calls: list[tuple[str, bool]] = []

    async def resolve(project_ref: str, *, write: bool = False) -> dict:
        calls.append((project_ref, write))
        return {"id": project_id, "name": name}

    resolve.calls = calls  # type: ignore[attr-defined]
    return resolve


def _resolve_project_id_ok(project_id: str = "1"):
    async def resolve(project_ref: str, *, write: bool = False) -> str:
        return project_id

    return resolve


def _resolve_principal_id_ok(user_id: str = "9"):
    calls: list[str] = []

    async def resolve(principal_ref: str) -> str:
        calls.append(principal_ref)
        return user_id

    resolve.calls = calls  # type: ignore[attr-defined]
    return resolve


def _get_current_user_ok(name: str = "Current User"):
    async def get() -> CurrentUser:
        return CurrentUser(id=1, name=name, login="me", url="https://op.example.com/users/1")

    return get


def _service(
    *,
    api: _FakeTimeEntryApi | None = None,
    project_api: _FakeProjectApi | None = None,
    user_api: _FakeUserApi | None = None,
    work_package_lookup_api: _FakeWorkPackageLookupApi | None = None,
    settings=None,
    resolve_work_package_id=None,
    resolve_project_ref=None,
    resolve_project_id=None,
    resolve_principal_id=None,
    get_current_user=None,
) -> TimeEntryService:
    return TimeEntryService(
        api=api or _FakeTimeEntryApi(),
        project_api=project_api or _FakeProjectApi(),
        user_api=user_api or _FakeUserApi(),
        work_package_lookup_api=work_package_lookup_api or _FakeWorkPackageLookupApi(),
        settings=settings or make_settings(),
        project_id_to_identifier=PROJECT_ID_TO_IDENTIFIER,
        resolve_work_package_id=resolve_work_package_id or _resolve_work_package_id_ok(),
        resolve_project_ref=resolve_project_ref or _resolve_project_ref_ok(),
        resolve_project_id=resolve_project_id or _resolve_project_id_ok(),
        resolve_principal_id=resolve_principal_id or _resolve_principal_id_ok(),
        get_current_user=get_current_user or _get_current_user_ok(),
        api_prefix="/api/v3/",
    )


# --- list_activities --------------------------------------------------------


@pytest.mark.asyncio
async def test_list_activities_returns_global_endpoint_result_when_non_empty() -> None:
    api = _FakeTimeEntryApi(
        fetch_activities_result={"_embedded": {"elements": [{"__summary__": _activity_summary(1)}]}}
    )
    service = _service(api=api)

    result = await service.list_activities()

    assert result.count == 1
    assert result.results[0].id == 1
    assert api.fetch_activities_for_entity_calls == []


@pytest.mark.asyncio
async def test_list_activities_falls_back_to_project_scan_when_global_endpoint_empty() -> None:
    api = _FakeTimeEntryApi(fetch_activities_result=None, activities=[_activity_summary(2, name="Support")])
    project_api = _FakeProjectApi(projects=[(1, "Demo")])
    service = _service(api=api, project_api=project_api)

    result = await service.list_activities()

    assert result.count == 1
    assert result.results[0].id == 2
    assert api.fetch_activities_for_entity_calls == [(1, None)]


@pytest.mark.asyncio
async def test_list_activities_returns_empty_when_project_scan_itself_fails() -> None:
    """Regression: the pre-migration original wrapped the ENTIRE project-scan
    fallback (including the project-listing call itself, not just each
    per-project form request) in a try/except that returns an empty result
    for NotFoundError/PermissionDeniedError/OpenProjectServerError. A prior
    port only guarded the per-project form call, letting a failure from
    listing projects itself propagate instead of degrading gracefully."""
    api = _FakeTimeEntryApi(fetch_activities_result=None)
    project_api = _FakeProjectApi(list_raises=PermissionDeniedError("no access"))
    service = _service(api=api, project_api=project_api)

    result = await service.list_activities()

    assert result.count == 0
    assert result.results == []


# --- list_all -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_all_returns_time_entries_under_wide_open_allowlist() -> None:
    api = _FakeTimeEntryApi(records=[_summary(7)])
    settings = dataclasses.replace(make_settings(), read_projects=("*",))
    service = _service(api=api, settings=settings)

    result = await service.list_all()

    assert result.count == 1
    assert result.results[0].id == 7


@pytest.mark.asyncio
async def test_list_all_denies_entries_outside_read_allowlist() -> None:
    api = _FakeTimeEntryApi(records=[_summary(7)], project_link={"href": "/api/v3/projects/2", "title": "Other"})
    settings = dataclasses.replace(make_settings(), read_projects=("demo",))
    service = _service(api=api, settings=settings)

    result = await service.list_all()

    assert result.count == 0


@pytest.mark.asyncio
async def test_list_all_resolves_work_package_id_and_filters_by_entity() -> None:
    api = _FakeTimeEntryApi(
        records=[
            _summary(1, entity_type="WorkPackage", entity_id=42),
            _summary(2, entity_type="WorkPackage", entity_id=99),
        ]
    )
    resolve = _resolve_work_package_id_ok(42)
    settings = dataclasses.replace(make_settings(), read_projects=("*",))
    service = _service(api=api, settings=settings, resolve_work_package_id=resolve)

    result = await service.list_all(work_package_id="PROJ-1")

    assert resolve.calls == [("PROJ-1", False)]
    assert [r.id for r in result.results] == [1]


@pytest.mark.asyncio
async def test_list_all_filters_by_user_me() -> None:
    api = _FakeTimeEntryApi(records=[_summary(1, user="Current User"), _summary(2, user="Someone Else")])
    settings = dataclasses.replace(make_settings(), read_projects=("*",))
    service = _service(api=api, settings=settings, get_current_user=_get_current_user_ok("Current User"))

    result = await service.list_all(user="me")

    assert [r.id for r in result.results] == [1]


@pytest.mark.asyncio
async def test_list_all_filters_by_numeric_user_id() -> None:
    api = _FakeTimeEntryApi(records=[_summary(1, user="Numeric User"), _summary(2, user="Someone Else")])
    settings = dataclasses.replace(make_settings(), read_projects=("*",))
    user_api = _FakeUserApi(name="Numeric User")
    service = _service(api=api, settings=settings, user_api=user_api)

    result = await service.list_all(user="9")

    assert user_api.get_user_calls == ["9"]
    assert [r.id for r in result.results] == [1]


@pytest.mark.asyncio
async def test_list_all_filters_by_spent_on_range() -> None:
    api = _FakeTimeEntryApi(
        records=[
            _summary(1, spent_on="2026-03-01"),
            _summary(2, spent_on="2026-03-15"),
            _summary(3, spent_on="2026-04-01"),
        ]
    )
    settings = dataclasses.replace(make_settings(), read_projects=("*",))
    service = _service(api=api, settings=settings)

    result = await service.list_all(spent_on_from="2026-03-10", spent_on_to="2026-03-31")

    assert [r.id for r in result.results] == [2]


# --- get ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_returns_time_entry_under_allowed_project() -> None:
    api = _FakeTimeEntryApi(time_entry_id=7)
    settings = dataclasses.replace(make_settings(), read_projects=("*",))
    service = _service(api=api, settings=settings)

    result = await service.get(7)

    assert result.id == 7
    assert api.get_raw_calls == [7]


@pytest.mark.asyncio
async def test_get_denies_time_entry_outside_read_allowlist() -> None:
    api = _FakeTimeEntryApi(time_entry_id=7, project_link={"href": "/api/v3/projects/2", "title": "Other"})
    settings = dataclasses.replace(make_settings(), read_projects=("demo",))
    service = _service(api=api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get(7)


# --- create -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_previews_without_confirm() -> None:
    api = _FakeTimeEntryApi()
    service = _service(api=api)

    result = await service.create(
        work_package_id=42, activity="Development", hours="PT1H", spent_on="2026-03-20", confirm=False
    )

    assert result.confirmed is False
    assert result.requires_confirmation is True
    assert api.create_calls == []


@pytest.mark.asyncio
async def test_create_commits_when_confirmed() -> None:
    api = _FakeTimeEntryApi()
    service = _service(api=api)

    result = await service.create(
        work_package_id=42, activity="Development", hours="PT1H", spent_on="2026-03-20", confirm=True
    )

    assert result.confirmed is True
    assert result.result is not None
    assert result.result.id == 650
    assert len(api.create_calls) == 1


@pytest.mark.asyncio
async def test_create_commits_the_server_canonicalized_form_payload_not_the_local_one() -> None:
    """Regression: OpenProject's own CreateFormAPI can canonicalize/add
    defaults to the locally-built payload (e.g. normalize hours format). The
    commit must send back the form's own _embedded.payload, not silently
    re-send the pre-validation payload the caller originally built."""
    api = _FakeTimeEntryApi(form_payload_overrides={"hours": "PT2H"})
    service = _service(api=api)

    await service.create(work_package_id=42, activity="Development", hours="PT1H", spent_on="2026-03-20", confirm=True)

    assert len(api.create_calls) == 1
    assert api.create_calls[0]["hours"] == "PT2H"


@pytest.mark.asyncio
async def test_update_commits_the_server_canonicalized_form_payload_not_the_local_one() -> None:
    api = _FakeTimeEntryApi(form_payload_overrides={"hours": "PT3H"})
    service = _service(api=api)

    await service.update(time_entry_id=7, hours="PT1H", confirm=True)

    assert len(api.update_calls) == 1
    assert api.update_calls[0][1]["hours"] == "PT3H"


@pytest.mark.asyncio
async def test_create_trims_project_name_from_direct_project_ref() -> None:
    """Regression: the pre-migration original capped a resolved project's
    display name at SUBJECT_LIMIT, matching every other project-name field --
    a prior port returned the raw, untrimmed name instead."""
    api = _FakeTimeEntryApi()
    long_name = "x" * 300
    resolve_project_ref = _resolve_project_ref_ok(name=long_name)
    service = _service(api=api, resolve_project_ref=resolve_project_ref)

    result = await service.create(
        project="demo", activity="Development", hours="PT1H", spent_on="2026-03-20", confirm=True
    )

    assert result.project is not None
    assert len(result.project) <= 255


@pytest.mark.asyncio
async def test_create_uses_entity_link_not_project_link_when_work_package_known() -> None:
    """GitHub issue #10 regression: resolving an activity by name while a
    work package is already known must query with the entity link, not the
    project link, or a log_own_time-only caller is wrongly denied."""
    api = _FakeTimeEntryApi()
    wp_lookup = _FakeWorkPackageLookupApi(project_link={"href": "/api/v3/projects/1", "title": "Demo"})
    service = _service(api=api, work_package_lookup_api=wp_lookup)

    await service.create(work_package_id=42, activity="Development", hours="PT1H", spent_on="2026-03-20", confirm=True)

    assert api.fetch_activities_for_entity_calls == [(1, 42)]


@pytest.mark.asyncio
async def test_create_denies_write_outside_project_allowlist_even_without_confirm() -> None:
    api = _FakeTimeEntryApi()
    wp_lookup = _FakeWorkPackageLookupApi(project_link={"href": "/api/v3/projects/1", "title": "Demo"})
    settings = dataclasses.replace(make_settings(), write_projects=("other",))
    service = _service(api=api, work_package_lookup_api=wp_lookup, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.create(
            work_package_id=42, activity="Development", hours="PT1H", spent_on="2026-03-20", confirm=False
        )


@pytest.mark.asyncio
async def test_create_reports_validation_errors_as_not_ready() -> None:
    class _RejectingApi(_FakeTimeEntryApi):
        async def validate_create(self, payload: dict) -> dict:
            self.validate_create_calls.append(payload)
            return {"_embedded": {"payload": payload, "validationErrors": {"hours": {"message": "invalid"}}}}

    api = _RejectingApi()
    service = _service(api=api)

    result = await service.create(
        work_package_id=42, activity="Development", hours="PT1H", spent_on="2026-03-20", confirm=True
    )

    assert result.ready is False
    assert result.validation_errors == {"hours": {"message": "invalid"}}
    assert api.create_calls == []


@pytest.mark.asyncio
async def test_create_rejects_hidden_hours_field() -> None:
    api = _FakeTimeEntryApi()
    settings = dataclasses.replace(make_settings(), hidden_fields={"time_entry": ("hours",)})
    service = _service(api=api, settings=settings)

    with pytest.raises(InvalidInputError, match="hidden"):
        await service.create(
            work_package_id=42, activity="Development", hours="PT1H", spent_on="2026-03-20", confirm=True
        )


# --- update -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_previews_without_confirm() -> None:
    api = _FakeTimeEntryApi(time_entry_id=7)
    service = _service(api=api)

    result = await service.update(time_entry_id=7, hours="PT2H", confirm=False)

    assert result.requires_confirmation is True
    assert api.update_calls == []


@pytest.mark.asyncio
async def test_update_commits_when_confirmed() -> None:
    api = _FakeTimeEntryApi(time_entry_id=7)
    service = _service(api=api)

    result = await service.update(time_entry_id=7, hours="PT2H", confirm=True)

    assert result.result is not None
    assert len(api.update_calls) == 1
    assert api.update_calls[0][0] == 7


@pytest.mark.asyncio
async def test_update_denies_write_outside_project_allowlist_even_without_confirm() -> None:
    api = _FakeTimeEntryApi(time_entry_id=7, project_link={"href": "/api/v3/projects/1", "title": "Demo"})
    settings = dataclasses.replace(make_settings(), write_projects=("other",))
    service = _service(api=api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.update(time_entry_id=7, hours="PT2H", confirm=False)


# --- delete -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_previews_without_confirm() -> None:
    api = _FakeTimeEntryApi(time_entry_id=7)
    service = _service(api=api)

    result = await service.delete(time_entry_id=7, confirm=False)

    assert result.requires_confirmation is True
    assert result.result is not None
    assert api.delete_calls == []


@pytest.mark.asyncio
async def test_delete_commits_when_confirmed() -> None:
    api = _FakeTimeEntryApi(time_entry_id=7)
    service = _service(api=api)

    result = await service.delete(time_entry_id=7, confirm=True)

    assert result.confirmed is True
    assert result.result is None
    assert api.delete_calls == [7]


@pytest.mark.asyncio
async def test_delete_denies_write_even_without_confirm() -> None:
    api = _FakeTimeEntryApi(time_entry_id=7, project_link={"href": "/api/v3/projects/1", "title": "Demo"})
    settings = dataclasses.replace(make_settings(), write_projects=("other",))
    service = _service(api=api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.delete(time_entry_id=7, confirm=False)


# --- hidden-field stamping ---------------------------------------------------


@pytest.mark.asyncio
async def test_list_all_hides_comment_and_its_metadata_when_time_entry_comment_hidden() -> None:
    record = _summary(7, comment="secret note")
    api = _FakeTimeEntryApi(records=[record])
    settings = dataclasses.replace(make_settings(), read_projects=("*",), hidden_fields={"time_entry": ("comment",)})
    service = _service(api=api, settings=settings)

    result = await service.list_all()

    entry = result.results[0]
    assert entry.comment is None
    assert entry.comment_truncated is False
    assert entry.comment_length is None
