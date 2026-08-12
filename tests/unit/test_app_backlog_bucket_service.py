from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import NotFoundError, PermissionDeniedError
from openproject_ce_mcp.app.ports.backlog_bucket_api import BacklogBucketRecord
from openproject_ce_mcp.app.services.backlog_bucket_service import BacklogBucketService
from openproject_ce_mcp.models import BacklogBucketDetail, BacklogBucketSummary

BASE_URL = "https://op.example.com"


def _summary(
    bucket_id: int = 1,
    *,
    defining_workspace_id: int | None = 6,
    defining_workspace: str | None = "Demo Project",
    name: str = "Backlog Bucket 1",
) -> BacklogBucketSummary:
    return BacklogBucketSummary(
        id=bucket_id,
        name=name,
        defining_workspace_id=defining_workspace_id,
        defining_workspace=defining_workspace,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-02T00:00:00Z",
    )


def _detail(**kwargs: object) -> BacklogBucketDetail:
    summary = _summary(**kwargs)  # type: ignore[arg-type]
    return BacklogBucketDetail(
        id=summary.id,
        name=summary.name,
        defining_workspace_id=summary.defining_workspace_id,
        defining_workspace=summary.defining_workspace,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
    )


def _record(
    *,
    defining_workspace_link: dict | None = None,
    defining_workspace_payload: dict | None = None,
    **kwargs: object,
) -> BacklogBucketRecord:
    summary = _summary(**kwargs)  # type: ignore[arg-type]
    detail = _detail(**kwargs)  # type: ignore[arg-type]
    if (
        defining_workspace_link is None
        and defining_workspace_payload is None
        and summary.defining_workspace_id is not None
    ):
        defining_workspace_link = {
            "href": f"/api/v3/projects/{summary.defining_workspace_id}",
            "title": summary.defining_workspace,
        }
    return BacklogBucketRecord(
        summary=summary,
        detail=detail,
        defining_workspace_link=defining_workspace_link,
        defining_workspace_payload=defining_workspace_payload,
        lookup_name=summary.name,
    )


class _FakeBacklogBucketApi:
    def __init__(self, records: list[BacklogBucketRecord] | None = None, *, not_found: bool = False) -> None:
        self._records = {r.summary.id: r for r in (records or [_record()])}
        self._not_found = not_found
        self.list_all_calls: list[int] = []
        self.list_for_project_calls: list[tuple[int, int]] = []
        self.get_calls: list[int] = []

    async def list_all(self, *, offset: int, page_size: int) -> tuple[list[BacklogBucketRecord], int]:
        self.list_all_calls.append(page_size)
        if self._not_found:
            raise NotFoundError("OpenProject resource not found.")
        records = list(self._records.values())
        return records, len(records)

    async def list_for_project(
        self, project_id: int, *, offset: int, page_size: int
    ) -> tuple[list[BacklogBucketRecord], int]:
        self.list_for_project_calls.append((project_id, page_size))
        if self._not_found:
            raise NotFoundError("OpenProject resource not found.")
        records = list(self._records.values())
        return records, len(records)

    async def get(self, backlog_bucket_id: int) -> BacklogBucketRecord:
        self.get_calls.append(backlog_bucket_id)
        if self._not_found:
            raise NotFoundError("OpenProject resource not found.")
        if backlog_bucket_id not in self._records:
            raise AssertionError(f"no fake record for backlog_bucket_id {backlog_bucket_id}")
        return self._records[backlog_bucket_id]


async def _resolve_project_ref(project_ref: str, *, write: bool = False, context=None) -> dict:
    return {"id": 6, "identifier": project_ref, "name": "Demo Project", "_links": {}}


def _service(
    api: _FakeBacklogBucketApi | None = None, *, settings=None, resolve_project_ref=_resolve_project_ref
) -> BacklogBucketService:
    api = api or _FakeBacklogBucketApi()
    return BacklogBucketService(
        api=api,
        settings=settings or make_settings(),
        project_id_to_identifier={},
        resolve_project_ref=resolve_project_ref,
    )


@pytest.mark.asyncio
async def test_list_returns_stamped_summaries() -> None:
    api = _FakeBacklogBucketApi()
    service = _service(api)

    result = await service.list()

    assert result.count == 1
    assert result.results[0].id == 1
    assert len(api.list_all_calls) == 1


@pytest.mark.asyncio
async def test_list_filters_by_search_term_in_name() -> None:
    api = _FakeBacklogBucketApi(
        records=[_record(bucket_id=1, name="Sprint Backlog"), _record(bucket_id=2, name="Unrelated")]
    )
    service = _service(api)

    result = await service.list(search="backlog")

    assert [item.id for item in result.results] == [1]


@pytest.mark.asyncio
async def test_list_excludes_backlog_buckets_outside_read_allowlist_via_link_branch() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    api = _FakeBacklogBucketApi()
    service = _service(api, settings=settings)

    result = await service.list()

    assert result.results == []


@pytest.mark.asyncio
async def test_list_excludes_backlog_buckets_outside_read_allowlist_via_embedded_branch() -> None:
    """The embedded-object branch has no Views equivalent: a backlog bucket
    can carry a full `_embedded.definingWorkspace` payload (with an
    `identifier` the synthesized link never has) instead of just a link."""
    settings = dataclasses.replace(make_settings(), read_projects=("demo",))
    disallowed_embedded = {"id": 99, "identifier": "secret-project", "name": "Secret Project"}
    api = _FakeBacklogBucketApi(
        records=[_record(bucket_id=1, defining_workspace_link=None, defining_workspace_payload=disallowed_embedded)]
    )
    service = _service(api, settings=settings)

    result = await service.list()

    assert result.results == []


@pytest.mark.asyncio
async def test_list_includes_backlog_bucket_allowed_via_embedded_branch() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("demo",))
    allowed_embedded = {"id": 7, "identifier": "demo", "name": "Demo"}
    api = _FakeBacklogBucketApi(
        records=[_record(bucket_id=1, defining_workspace_link=None, defining_workspace_payload=allowed_embedded)]
    )
    service = _service(api, settings=settings)

    result = await service.list()

    assert [item.id for item in result.results] == [1]


@pytest.mark.asyncio
async def test_list_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_project_read=False)
    api = _FakeBacklogBucketApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.list()

    assert api.list_all_calls == []


@pytest.mark.asyncio
async def test_list_rewraps_not_found_with_backlogs_message() -> None:
    api = _FakeBacklogBucketApi(not_found=True)
    service = _service(api)

    with pytest.raises(NotFoundError, match="Backlogs module"):
        await service.list()


@pytest.mark.asyncio
async def test_list_for_project_resolves_project_and_lists() -> None:
    api = _FakeBacklogBucketApi()
    service = _service(api)

    result = await service.list_for_project("demo")

    assert result.count == 1
    assert api.list_for_project_calls == [(6, service._settings.max_page_size)]


@pytest.mark.asyncio
async def test_list_for_project_passes_write_false_to_resolve_project_ref() -> None:
    """New call site introduced by this migration -- assert it explicitly,
    same gap class Sprints/Views/Documents each had for their own list()
    methods.
    """
    calls: list[bool] = []

    async def resolve_project_ref_tracking_write(project_ref: str, *, write: bool = False, context=None) -> dict:
        calls.append(write)
        return await _resolve_project_ref(project_ref, write=write, context=context)

    api = _FakeBacklogBucketApi()
    service = _service(api, resolve_project_ref=resolve_project_ref_tracking_write)

    await service.list_for_project("demo")

    assert calls == [False]


@pytest.mark.asyncio
async def test_list_for_project_filters_by_search_term_in_name() -> None:
    api = _FakeBacklogBucketApi(
        records=[_record(bucket_id=1, name="Backlog"), _record(bucket_id=2, name="Sprint")],
    )
    service = _service(api)

    result = await service.list_for_project("demo", search="backlog")

    assert [item.id for item in result.results] == [1]


@pytest.mark.asyncio
async def test_list_for_project_still_filters_by_allowlist_despite_project_scoped_request() -> None:
    """A backlog bucket shared into an allowed project can still be *defined*
    by a different, disallowed project -- list_for_project must filter those
    out the same way list() already does."""
    settings = dataclasses.replace(make_settings(), read_projects=("demo",))
    allowed_embedded = {"id": 6, "identifier": "demo", "name": "Demo Project"}
    disallowed_embedded = {"id": 99, "identifier": "secret-project", "name": "Secret Project"}
    api = _FakeBacklogBucketApi(
        records=[
            _record(bucket_id=1, defining_workspace_link=None, defining_workspace_payload=allowed_embedded),
            _record(bucket_id=2, defining_workspace_link=None, defining_workspace_payload=disallowed_embedded),
        ]
    )
    service = _service(api, settings=settings)

    result = await service.list_for_project("demo")

    assert [item.id for item in result.results] == [1]


@pytest.mark.asyncio
async def test_list_for_project_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_project_read=False)
    api = _FakeBacklogBucketApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.list_for_project("demo")

    assert api.list_for_project_calls == []


@pytest.mark.asyncio
async def test_list_for_project_rewraps_not_found_with_backlogs_message() -> None:
    api = _FakeBacklogBucketApi(not_found=True)
    service = _service(api)

    with pytest.raises(NotFoundError, match="Backlogs module"):
        await service.list_for_project("demo")


@pytest.mark.asyncio
async def test_get_applies_hidden_field_masking() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"backlog_bucket": ("defining_workspace",)})
    api = _FakeBacklogBucketApi()
    service = _service(api, settings=settings)

    result = await service.get(1)

    assert getattr(result, "_hidden_keys", frozenset()) == {"defining_workspace"}
    assert api.get_calls == [1]


@pytest.mark.asyncio
async def test_get_defining_workspace_hidden_by_backlog_bucket_scope_not_project_scope() -> None:
    """Regression test for the entity="backlog_bucket" vs "project"
    hide-field bug class (same bug class found in prior domains, e.g.
    Sprints)."""
    settings_project_hidden = dataclasses.replace(make_settings(), hide_project_fields=("defining_workspace",))
    service_project_hidden = _service(settings=settings_project_hidden)
    result_project_hidden = await service_project_hidden.get(1)
    assert getattr(result_project_hidden, "_hidden_keys", frozenset()) == frozenset()

    settings_bucket_hidden = dataclasses.replace(
        make_settings(), hidden_fields={"backlog_bucket": ("defining_workspace",)}
    )
    service_bucket_hidden = _service(settings=settings_bucket_hidden)
    result_bucket_hidden = await service_bucket_hidden.get(1)
    assert getattr(result_bucket_hidden, "_hidden_keys", frozenset()) == {"defining_workspace"}


@pytest.mark.asyncio
async def test_get_checks_allowlist_for_a_linked_backlog_bucket() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    api = _FakeBacklogBucketApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await service.get(1)


@pytest.mark.asyncio
async def test_get_checks_allowlist_via_embedded_branch() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("demo",))
    disallowed_embedded = {"id": 99, "identifier": "secret-project", "name": "Secret Project"}
    api = _FakeBacklogBucketApi(
        records=[_record(bucket_id=1, defining_workspace_link=None, defining_workspace_payload=disallowed_embedded)]
    )
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await service.get(1)


@pytest.mark.asyncio
async def test_get_checks_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_project_read=False)
    api = _FakeBacklogBucketApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get(1)

    assert api.get_calls == []


@pytest.mark.asyncio
async def test_get_rewraps_not_found_with_backlog_bucket_message() -> None:
    api = _FakeBacklogBucketApi(not_found=True)
    service = _service(api)

    with pytest.raises(NotFoundError, match="Backlogs module"):
        await service.get(1)
