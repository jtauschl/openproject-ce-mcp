from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import InvalidInputError, PermissionDeniedError
from openproject_ce_mcp.app.ports.attachment_api import AttachmentRecord
from openproject_ce_mcp.app.services.attachment_service import AttachmentService
from openproject_ce_mcp.models import AttachmentSummary

PROJECT_ID_TO_IDENTIFIER = {6: "demo", 7: "secret"}


def _summary(
    attachment_id: int = 5, *, container_type: str = "WorkPackage", container_id: int = 9
) -> AttachmentSummary:
    return AttachmentSummary(
        id=attachment_id,
        title="report.pdf",
        file_name="report.pdf",
        file_size=1024,
        description=None,
        content_type="application/pdf",
        status="uploaded",
        author="Alice",
        container_type=container_type,
        container_id=container_id,
        created_at="2026-01-01T00:00:00Z",
        download_url="/api/v3/attachments/5/content",
        url="/api/v3/attachments/5",
    )


def _record(attachment_id: int = 5, *, has_container_link: bool = True, container_id: int = 9) -> AttachmentRecord:
    container_link = {"href": f"/api/v3/work_packages/{container_id}"} if has_container_link else None
    summary_container_id = container_id if has_container_link else None
    return AttachmentRecord(
        summary=_summary(attachment_id, container_id=summary_container_id), container_link=container_link
    )


class _FakeAttachmentApi:
    def __init__(
        self, records: list[AttachmentRecord] | None = None, *, max_attachment_size: int | None = 10_000_000
    ) -> None:
        self._records = {r.summary.id: r for r in (records or [_record()])}
        self._max_attachment_size = max_attachment_size
        self.list_for_work_package_calls: list[tuple[int, int]] = []
        self.get_calls: list[int] = []
        self.create_calls: list[tuple[int, dict, str, bytes, str]] = []
        self.delete_calls: list[int] = []

    async def list_for_work_package(self, work_package_id: int, *, page_size: int) -> list[AttachmentRecord]:
        self.list_for_work_package_calls.append((work_package_id, page_size))
        return list(self._records.values())

    async def get(self, attachment_id: int) -> AttachmentRecord:
        self.get_calls.append(attachment_id)
        if attachment_id not in self._records:
            raise AssertionError(f"no fake record for attachment_id {attachment_id}")
        return self._records[attachment_id]

    async def create(
        self, work_package_id: int, *, metadata: dict, file_name: str, file_bytes: bytes, content_type: str
    ) -> AttachmentRecord:
        self.create_calls.append((work_package_id, metadata, file_name, file_bytes, content_type))
        return _record(99, container_id=work_package_id)

    async def delete(self, attachment_id: int) -> None:
        self.delete_calls.append(attachment_id)

    async def get_max_attachment_size(self) -> int | None:
        return self._max_attachment_size


_DEFAULT_PROJECT_LINK = {"href": "/api/v3/projects/6"}


class _FakeWorkPackageLookupApi:
    def __init__(self, project_link: dict | None = _DEFAULT_PROJECT_LINK) -> None:
        self._project_link = project_link
        self.get_calls: list[str] = []

    async def get(self, work_package_ref: str) -> dict:
        self.get_calls.append(work_package_ref)
        return {"id": int(work_package_ref), "_links": {"project": self._project_link}}

    async def get_by_href(self, href: str) -> dict:
        raise AssertionError("get_by_href should not be used by AttachmentService")


def _resolve_work_package_id_ok(resolved_id: int = 9):
    calls: list[tuple[int | str, bool]] = []

    async def resolve(work_package_ref: int | str, *, write: bool = False) -> int:
        calls.append((work_package_ref, write))
        return resolved_id

    resolve.calls = calls  # type: ignore[attr-defined]
    return resolve


def _resolve_work_package_id_denied():
    async def resolve(work_package_ref: int | str, *, write: bool = False) -> int:
        raise PermissionDeniedError("OpenProject access to this project is disabled by OPENPROJECT_READ_PROJECTS.")

    return resolve


def _service(
    *,
    api: _FakeAttachmentApi | None = None,
    work_package_lookup_api: _FakeWorkPackageLookupApi | None = None,
    settings=None,
    resolve_work_package_id=None,
) -> AttachmentService:
    return AttachmentService(
        api=api or _FakeAttachmentApi(),
        work_package_lookup_api=work_package_lookup_api or _FakeWorkPackageLookupApi(),
        settings=settings or make_settings(),
        project_id_to_identifier=PROJECT_ID_TO_IDENTIFIER,
        resolve_work_package_id=resolve_work_package_id or _resolve_work_package_id_ok(),
    )


# --- list_for_work_package ---------------------------------------------------


@pytest.mark.asyncio
async def test_list_for_work_package_returns_stamped_summaries() -> None:
    api = _FakeAttachmentApi()
    resolver = _resolve_work_package_id_ok(resolved_id=9)
    service = _service(api=api, resolve_work_package_id=resolver)

    result = await service.list_for_work_package(9)

    assert result.count == 1
    assert result.results[0].id == 5
    assert resolver.calls == [(9, False)]  # type: ignore[attr-defined]
    assert api.list_for_work_package_calls == [(9, 50)]


@pytest.mark.asyncio
async def test_list_for_work_package_denies_anchor_outside_read_allowlist() -> None:
    api = _FakeAttachmentApi()
    service = _service(api=api, resolve_work_package_id=_resolve_work_package_id_denied())

    with pytest.raises(PermissionDeniedError):
        await service.list_for_work_package(9)

    assert api.list_for_work_package_calls == []


@pytest.mark.asyncio
async def test_list_for_work_package_filters_out_records_from_a_different_container() -> None:
    """A record whose container_type/id doesn't match the resolved anchor
    (e.g. the server returning an attachment belonging to a different
    container than requested) must be dropped -- verbatim of client.py's
    original post-normalization filter."""
    api = _FakeAttachmentApi(
        records=[_record(1, container_id=9), _record(2, container_id=999), _record(3, has_container_link=False)]
    )
    service = _service(api=api, resolve_work_package_id=_resolve_work_package_id_ok(resolved_id=9))

    result = await service.list_for_work_package(9)

    assert result.count == 1
    assert result.results[0].id == 1


@pytest.mark.asyncio
async def test_list_for_work_package_masks_hidden_description() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"attachment": ("description",)})
    service = _service(settings=settings)

    result = await service.list_for_work_package(9)

    assert getattr(result.results[0], "_hidden_keys", frozenset()) == {"description"}


# --- get ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_returns_stamped_summary_and_checks_read_allowlist() -> None:
    work_package_lookup_api = _FakeWorkPackageLookupApi(project_link={"href": "/api/v3/projects/6"})
    settings = dataclasses.replace(make_settings(), read_projects=("demo",))
    service = _service(work_package_lookup_api=work_package_lookup_api, settings=settings)

    attachment = await service.get(5)

    assert attachment.id == 5
    assert work_package_lookup_api.get_calls == ["9"]


@pytest.mark.asyncio
async def test_get_denies_read_outside_read_allowlist() -> None:
    work_package_lookup_api = _FakeWorkPackageLookupApi(project_link={"href": "/api/v3/projects/7"})
    settings = dataclasses.replace(make_settings(), read_projects=("demo",))
    service = _service(work_package_lookup_api=work_package_lookup_api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get(5)


@pytest.mark.asyncio
async def test_get_rejects_a_container_that_is_not_a_work_package() -> None:
    api = _FakeAttachmentApi(records=[_record(5, has_container_link=False)])
    service = _service(api=api)

    with pytest.raises(InvalidInputError, match="Only work package attachments are supported"):
        await service.get(5)


@pytest.mark.asyncio
async def test_get_rejects_a_container_href_only_substring_matching_work_packages() -> None:
    """Codex-found: the original `"work_packages/" in href` substring check
    would wrongly accept a foreign resource whose path merely CONTAINS that
    substring, e.g. `/api/v3/not_work_packages/9` -- authorizing against an
    unrelated work package's project rather than failing closed. The fixed
    check requires an exact `work_packages/<id>` path-segment pair."""
    record = AttachmentRecord(
        summary=_summary(5, container_id=9), container_link={"href": "/api/v3/not_work_packages/9"}
    )
    api = _FakeAttachmentApi(records=[record])
    work_package_lookup_api = _FakeWorkPackageLookupApi()
    service = _service(api=api, work_package_lookup_api=work_package_lookup_api)

    with pytest.raises(InvalidInputError, match="Only work package attachments are supported"):
        await service.get(5)

    assert work_package_lookup_api.get_calls == []


# --- create ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_preview_without_confirm_does_not_call_api_create(tmp_path) -> None:
    report = tmp_path / "report.pdf"
    report.write_bytes(b"hello")
    api = _FakeAttachmentApi()
    settings = dataclasses.replace(make_settings(), enable_work_package_write=True, attachment_root=str(tmp_path))
    service = _service(api=api, settings=settings)

    result = await service.create(work_package_id=9, file_path=str(report), confirm=False)

    assert result.confirmed is False
    assert result.requires_confirmation is True
    assert result.result is None
    assert api.create_calls == []


@pytest.mark.asyncio
async def test_create_resolves_work_package_with_write_true(tmp_path) -> None:
    """create()'s caller-supplied work_package_id is a write TARGET, unlike
    list_for_work_package()'s/get()'s read-only anchor -- must resolve
    with write=True, pinned the same way ActivityService's own list()
    resolver call is pinned to write=False."""
    report = tmp_path / "report.pdf"
    report.write_bytes(b"hello")
    resolver = _resolve_work_package_id_ok(resolved_id=9)
    settings = dataclasses.replace(make_settings(), enable_work_package_write=True, attachment_root=str(tmp_path))
    service = _service(settings=settings, resolve_work_package_id=resolver)

    await service.create(work_package_id=9, file_path=str(report), confirm=False)

    assert resolver.calls == [(9, True)]  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_create_denies_write_even_without_confirm() -> None:
    """The write-allowlist check must run before confirm, not only as part of
    the confirm path -- matching the Watchers/Emoji Reactions test-contract
    lesson (confirm=True alone can't distinguish 'checked before confirm'
    from 'checked only inside the confirm branch')."""
    api = _FakeAttachmentApi()
    service = _service(api=api, resolve_work_package_id=_resolve_work_package_id_denied())

    with pytest.raises(PermissionDeniedError):
        await service.create(work_package_id=9, file_path="report.pdf", confirm=False)

    assert api.create_calls == []


@pytest.mark.asyncio
async def test_create_denies_write_with_confirm() -> None:
    api = _FakeAttachmentApi()
    service = _service(api=api, resolve_work_package_id=_resolve_work_package_id_denied())

    with pytest.raises(PermissionDeniedError):
        await service.create(work_package_id=9, file_path="report.pdf", confirm=True)

    assert api.create_calls == []


@pytest.mark.asyncio
async def test_create_rejects_hidden_file_name_field() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"attachment": ("file_name",)})
    service = _service(settings=settings)

    with pytest.raises(InvalidInputError, match="file_name"):
        await service.create(work_package_id=9, file_path="report.pdf", confirm=False)


@pytest.mark.asyncio
async def test_create_rejects_hidden_description_field_only_when_description_given(tmp_path) -> None:
    report = tmp_path / "report.pdf"
    report.write_bytes(b"hello")
    settings = dataclasses.replace(
        make_settings(), hidden_fields={"attachment": ("description",)}, attachment_root=str(tmp_path)
    )
    service = _service(settings=settings)

    # No description passed: the hidden-description guard must not fire.
    result = await service.create(work_package_id=9, file_path=str(report), confirm=False)
    assert result.requires_confirmation is True

    with pytest.raises(InvalidInputError, match="description"):
        await service.create(work_package_id=9, file_path=str(report), description="notes", confirm=False)


@pytest.mark.asyncio
async def test_create_rejects_oversized_file_before_reading_bytes(tmp_path) -> None:
    """Codex-found, real pre-existing risk: the size check must run BEFORE
    file bytes are read into memory, not after -- an oversized file must
    never be fully buffered just to then be rejected."""
    report = tmp_path / "report.pdf"
    report.write_bytes(b"x" * 100)
    api = _FakeAttachmentApi(max_attachment_size=10)
    settings = dataclasses.replace(make_settings(), attachment_root=str(tmp_path))
    service = _service(api=api, settings=settings)

    with pytest.raises(InvalidInputError, match="exceeds the configured OpenProject maximum"):
        await service.create(work_package_id=9, file_path=str(report), confirm=True)

    assert api.create_calls == []


@pytest.mark.asyncio
async def test_create_rejects_a_file_that_grows_between_the_stat_and_the_read(tmp_path) -> None:
    """Codex-found TOCTOU: the size is checked once against a stat (no
    bytes read), then the file is read a second time for the actual
    upload -- a file that grows in that window must still be rejected,
    not silently uploaded past the configured maximum on the strength of
    the now-stale first check."""
    report = tmp_path / "report.pdf"
    report.write_bytes(b"x" * 5)
    api = _FakeAttachmentApi(max_attachment_size=10)
    settings = dataclasses.replace(make_settings(), enable_work_package_write=True, attachment_root=str(tmp_path))
    service = _service(api=api, settings=settings)

    # Grow the file only after the confirm=True call has already passed the
    # first (stat-only) size check -- simulated by having the fake API's
    # get_max_attachment_size grow the file as a side effect of the first
    # call the Service makes after that check (its own create() call chain
    # calls _validate_attachment_size twice; growing the file here mid-flow
    # is the simplest way to land squarely inside the real TOCTOU window).
    original_validate = service._validate_attachment_size
    calls = {"count": 0}

    async def grow_then_validate(file_size: int) -> None:
        calls["count"] += 1
        if calls["count"] == 1:
            await original_validate(file_size)
            report.write_bytes(b"x" * 20)
        else:
            await original_validate(file_size)

    service._validate_attachment_size = grow_then_validate  # type: ignore[method-assign]

    with pytest.raises(InvalidInputError, match="exceeds the configured OpenProject maximum"):
        await service.create(work_package_id=9, file_path=str(report), confirm=True)

    assert api.create_calls == []


# --- delete -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_preview_without_confirm_does_not_call_api_delete() -> None:
    api = _FakeAttachmentApi()
    service = _service(api=api)

    result = await service.delete(5, confirm=False)

    assert result.confirmed is False
    assert result.requires_confirmation is True
    assert result.work_package_id == 9
    assert result.result is not None
    assert result.result.id == 5
    assert api.delete_calls == []


@pytest.mark.asyncio
async def test_delete_commit_with_confirm_calls_api_delete() -> None:
    api = _FakeAttachmentApi()
    work_package_lookup_api = _FakeWorkPackageLookupApi()
    service = _service(api=api, work_package_lookup_api=work_package_lookup_api)

    result = await service.delete(5, confirm=True)

    assert result.confirmed is True
    assert result.requires_confirmation is False
    assert result.work_package_id == 9
    assert result.result is None
    assert api.delete_calls == [5]
    assert work_package_lookup_api.get_calls == ["9"]


@pytest.mark.asyncio
async def test_delete_preview_masks_hidden_description() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"attachment": ("description",)})
    service = _service(settings=settings)

    result = await service.delete(5, confirm=False)

    assert getattr(result.result, "_hidden_keys", frozenset()) == {"description"}


@pytest.mark.asyncio
async def test_delete_denies_write_outside_write_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), write_projects=("other",))
    api = _FakeAttachmentApi()
    work_package_lookup_api = _FakeWorkPackageLookupApi(project_link={"href": "/api/v3/projects/6"})
    service = _service(api=api, work_package_lookup_api=work_package_lookup_api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.delete(5, confirm=True)

    assert api.delete_calls == []


@pytest.mark.asyncio
async def test_delete_denies_write_even_without_confirm() -> None:
    """The write-allowlist check (_ensure_container_allowed(..., write=True))
    runs unconditionally, before the confirm branch -- matching Reminders'
    own confirm=True/False pair for the identical property (this project's
    established sibling precedent). A confirm=True-only test can't
    distinguish 'checked before confirm' from 'checked only inside the
    confirm branch', since both are reached either way."""
    settings = dataclasses.replace(make_settings(), write_projects=("other",))
    api = _FakeAttachmentApi()
    work_package_lookup_api = _FakeWorkPackageLookupApi(project_link={"href": "/api/v3/projects/6"})
    service = _service(api=api, work_package_lookup_api=work_package_lookup_api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.delete(5, confirm=False)

    assert api.delete_calls == []


@pytest.mark.asyncio
async def test_delete_denies_when_container_unresolvable_even_under_wide_open_write_scope() -> None:
    """Verbatim behavior of client.py's original
    `_ensure_attachment_container_allowed`: a missing/non-work-package
    container link fails closed with InvalidInputError (not
    PermissionDeniedError, unlike File Links' analogous check) -- even under
    write_projects=("*",)."""
    api = _FakeAttachmentApi(records=[_record(5, has_container_link=False)])
    work_package_lookup_api = _FakeWorkPackageLookupApi()
    settings = dataclasses.replace(make_settings(), write_projects=("*",))
    service = _service(api=api, work_package_lookup_api=work_package_lookup_api, settings=settings)

    with pytest.raises(InvalidInputError, match="Only work package attachments are supported"):
        await service.delete(5, confirm=True)

    assert work_package_lookup_api.get_calls == []
    assert api.delete_calls == []


# --- entity-scope regression --------------------------------------------------


@pytest.mark.asyncio
async def test_description_hidden_by_attachment_scope_not_grid_scope() -> None:
    settings_grid_hidden = dataclasses.replace(make_settings(), hidden_fields={"grid": ("description",)})
    service_grid_hidden = _service(settings=settings_grid_hidden)
    result_grid_hidden = await service_grid_hidden.list_for_work_package(9)
    assert getattr(result_grid_hidden.results[0], "_hidden_keys", frozenset()) == frozenset()

    settings_attachment_hidden = dataclasses.replace(make_settings(), hidden_fields={"attachment": ("description",)})
    service_attachment_hidden = _service(settings=settings_attachment_hidden)
    result_attachment_hidden = await service_attachment_hidden.list_for_work_package(9)
    assert getattr(result_attachment_hidden.results[0], "_hidden_keys", frozenset()) == {"description"}
