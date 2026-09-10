from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import InvalidInputError, PermissionDeniedError
from openproject_ce_mcp.app.ports.attachment_api import AttachmentContent, AttachmentRecord
from openproject_ce_mcp.app.services.attachment_service import AttachmentService
from openproject_ce_mcp.models import AttachmentSummary
from openproject_ce_mcp.presentation import _to_payload

PROJECT_ID_TO_IDENTIFIER = {6: "demo", 7: "secret"}


def _summary(
    attachment_id: int = 5,
    *,
    container_type: str = "WorkPackage",
    container_id: int = 9,
    file_size_bytes: int | None = 1024,
    content_type: str | None = "application/pdf",
) -> AttachmentSummary:
    return AttachmentSummary(
        id=attachment_id,
        title="report.pdf",
        file_name="report.pdf",
        file_size_bytes=file_size_bytes,
        description=None,
        content_type=content_type,
        status="uploaded",
        author="Alice",
        container_type=container_type,
        container_id=container_id,
        created_at="2026-01-01T00:00:00Z",
        download_url="/api/v3/attachments/5/content",
    )


def _record(
    attachment_id: int = 5,
    *,
    has_container_link: bool = True,
    container_id: int = 9,
    file_size_bytes: int | None = 1024,
    content_type: str | None = "application/pdf",
) -> AttachmentRecord:
    container_link = {"href": f"/api/v3/work_packages/{container_id}"} if has_container_link else None
    summary_container_id = container_id if has_container_link else None
    return AttachmentRecord(
        summary=_summary(
            attachment_id,
            container_id=summary_container_id,
            file_size_bytes=file_size_bytes,
            content_type=content_type,
        ),
        container_link=container_link,
    )


class _FakeAttachmentApi:
    def __init__(
        self,
        records: list[AttachmentRecord] | None = None,
        *,
        max_attachment_size: int | None = 10_000_000,
        contents: dict[int, AttachmentContent] | None = None,
    ) -> None:
        self._records = {r.summary.id: r for r in (records or [_record()])}
        self._max_attachment_size = max_attachment_size
        self._contents = contents or {}
        self.list_for_work_package_calls: list[tuple[int, int]] = []
        self.get_calls: list[int] = []
        self.get_content_calls: list[tuple[int, int]] = []
        self.create_calls: list[tuple[int, dict, str, bytes, str]] = []
        self.delete_calls: list[int] = []

    async def get_content(self, attachment_id: int, *, max_bytes: int) -> AttachmentContent:
        # Honours max_bytes the way the real Transport does: hands back at most
        # max_bytes bytes and flags truncation, so budget arithmetic in the
        # Service is exercised against a faithful contract.
        self.get_content_calls.append((attachment_id, max_bytes))
        content = self._contents[attachment_id]
        return AttachmentContent(
            data=content.data[:max_bytes],
            served_content_type=content.served_content_type,
            truncated=content.truncated or len(content.data) > max_bytes,
        )

    async def list_for_work_package(
        self, work_package_id: int, *, offset: int, page_size: int
    ) -> tuple[list[AttachmentRecord], int]:
        self.list_for_work_package_calls.append((work_package_id, page_size))
        records = list(self._records.values())
        return records, len(records)

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

    async def get_max_attachment_size_bytes(self) -> int | None:
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


@pytest.mark.asyncio
async def test_list_for_work_package_omits_total_size_by_default() -> None:
    api = _FakeAttachmentApi(records=[_record(1, file_size_bytes=1024)])
    service = _service(api=api)

    result = await service.list_for_work_package(9)

    assert result.total_size_bytes is None


@pytest.mark.asyncio
async def test_list_for_work_package_sums_file_sizes_when_requested() -> None:
    api = _FakeAttachmentApi(
        records=[_record(1, file_size_bytes=1024), _record(2, file_size_bytes=2048), _record(3, file_size_bytes=512)]
    )
    service = _service(api=api)

    result = await service.list_for_work_package(9, include_total_size=True)

    assert result.total_size_bytes == 3584


@pytest.mark.asyncio
async def test_list_for_work_package_total_size_is_none_when_a_size_is_unknown() -> None:
    api = _FakeAttachmentApi(records=[_record(1, file_size_bytes=1024), _record(2, file_size_bytes=None)])
    service = _service(api=api)

    result = await service.list_for_work_package(9, include_total_size=True)

    assert result.total_size_bytes is None


@pytest.mark.asyncio
async def test_list_for_work_package_total_size_is_none_when_file_size_hidden() -> None:
    api = _FakeAttachmentApi(records=[_record(1, file_size_bytes=1024)])
    settings = dataclasses.replace(make_settings(), hidden_fields={"attachment": ("file_size_bytes",)})
    service = _service(api=api, settings=settings)

    result = await service.list_for_work_package(9, include_total_size=True)

    assert result.total_size_bytes is None


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
    """Regression: the original `"work_packages/" in href` substring check
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

    assert result.state == "preview"
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
    assert result.state == "preview"

    with pytest.raises(InvalidInputError, match="description"):
        await service.create(work_package_id=9, file_path=str(report), description="notes", confirm=False)


@pytest.mark.asyncio
async def test_create_rejects_oversized_file_before_reading_bytes(tmp_path) -> None:
    """Regression, real pre-existing risk: the size check must run BEFORE
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
    """Regression, a TOCTOU risk: the size is checked once against a stat (no
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
    # get_max_attachment_size_bytes grow the file as a side effect of the first
    # call the Service makes after that check (its own create() call chain
    # calls _validate_attachment_size twice; growing the file here mid-flow
    # is the simplest way to land squarely inside the real TOCTOU window).
    original_validate = service._validate_attachment_size
    calls = {"count": 0}

    async def grow_then_validate(file_size_bytes: int) -> None:
        calls["count"] += 1
        if calls["count"] == 1:
            await original_validate(file_size_bytes)
            report.write_bytes(b"x" * 20)
        else:
            await original_validate(file_size_bytes)

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

    assert result.state == "preview"
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

    assert result.state == "confirmed"
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


# --- get_content ---------------------------------------------------------------


def _png_record(attachment_id: int = 5, *, container_id: int = 9) -> AttachmentRecord:
    return _record(attachment_id, container_id=container_id, content_type="image/png")


@pytest.mark.asyncio
async def test_get_content_checks_container_scope_before_downloading_anything() -> None:
    """Authorization runs to completion first: a denied container must not
    cause a single byte to be fetched."""
    api = _FakeAttachmentApi([_png_record()], contents={5: AttachmentContent(b"PNG", "image/png", False)})
    lookup = _FakeWorkPackageLookupApi(project_link={"href": "/api/v3/projects/7"})
    settings = dataclasses.replace(make_settings(), read_projects=("demo",))
    service = _service(api=api, work_package_lookup_api=lookup, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get_content(5)

    assert api.get_calls == [5]
    assert api.get_content_calls == []


@pytest.mark.asyncio
async def test_get_content_inlineable_image_returns_bytes() -> None:
    api = _FakeAttachmentApi([_png_record()], contents={5: AttachmentContent(b"PNG", "image/png", False)})
    service = _service(api=api)

    outcome = await service.get_content(5)

    assert outcome.metadata.outcome == "image"
    assert outcome.metadata.content_type == "image/png"
    assert outcome.metadata.size_bytes == 3
    assert outcome.metadata.truncated is False
    assert outcome.metadata.reason is None
    assert outcome.image_bytes == b"PNG"
    assert outcome.text is None


@pytest.mark.asyncio
async def test_get_content_oversized_image_is_too_large_and_never_partial() -> None:
    settings = dataclasses.replace(make_settings(), attachment_content_max_bytes=2)
    api = _FakeAttachmentApi([_png_record()], contents={5: AttachmentContent(b"PNG", "image/png", False)})
    service = _service(api=api, settings=settings)

    outcome = await service.get_content(5)

    assert outcome.metadata.outcome == "too_large"
    assert outcome.metadata.size_bytes is None
    assert "2-byte inline limit" in (outcome.metadata.reason or "")
    assert outcome.image_bytes is None
    assert outcome.text is None


@pytest.mark.asyncio
async def test_get_content_text_is_decoded_and_truncation_is_reported_not_refused() -> None:
    settings = dataclasses.replace(make_settings(), attachment_content_max_bytes=5)
    api = _FakeAttachmentApi(
        [_record(content_type="text/plain")],
        contents={5: AttachmentContent(b"hello world", "text/plain; charset=utf-8", False)},
    )
    service = _service(api=api, settings=settings)

    outcome = await service.get_content(5)

    assert outcome.metadata.outcome == "text"
    assert outcome.metadata.content_type == "text/plain"
    assert outcome.metadata.truncated is True
    assert outcome.metadata.size_bytes == 5
    assert "Cut at the 5-byte inline limit" in (outcome.metadata.reason or "")
    assert outcome.text == "hello"
    assert outcome.image_bytes is None


@pytest.mark.asyncio
async def test_get_content_json_served_as_octet_stream_uses_stored_type() -> None:
    """OpenProject serves JSON as application/octet-stream; without the
    stored-type fallback every JSON attachment would come back as an unusable
    binary blob."""
    api = _FakeAttachmentApi(
        [_record(content_type="application/json")],
        contents={5: AttachmentContent(b'{"a": 1}', "application/octet-stream", False)},
    )
    outcome = await _service(api=api).get_content(5)

    assert outcome.metadata.outcome == "text"
    assert outcome.metadata.content_type == "application/json"
    assert outcome.text == '{"a": 1}'


@pytest.mark.asyncio
@pytest.mark.parametrize("served", [None, "application/octet-stream"])
async def test_get_content_image_served_generically_is_not_inlined(served: str | None) -> None:
    """The stored-type fallback is for the text allowlist only: an image is
    classified off the served header alone, so a PNG the server labels as
    octet-stream (or not at all) is reported, never guessed. The reported type
    is the stored one either way -- what the file is, not what the download
    endpoint called it."""
    api = _FakeAttachmentApi([_png_record()], contents={5: AttachmentContent(b"PNG", served, False)})
    outcome = await _service(api=api).get_content(5)

    assert outcome.metadata.outcome == "not_inline_supported"
    assert outcome.metadata.content_type == "image/png"
    assert outcome.image_bytes is None
    assert api.get_content_calls == [(5, make_settings().attachment_content_max_bytes)]


@pytest.mark.asyncio
async def test_get_content_served_type_wins_over_a_disagreeing_stored_type() -> None:
    api = _FakeAttachmentApi(
        [_record(content_type="application/pdf")],
        contents={5: AttachmentContent(b"PNG", "image/png", False)},
    )
    outcome = await _service(api=api).get_content(5)

    assert outcome.metadata.outcome == "image"
    assert outcome.metadata.content_type == "image/png"


@pytest.mark.asyncio
async def test_get_content_svg_is_text_never_an_image() -> None:
    """image/svg+xml is deliberately outside the image allowlist; as +xml it
    is still readable as text (its source), which is all a client can do
    with it."""
    api = _FakeAttachmentApi(
        [_record(content_type="image/svg+xml")],
        contents={5: AttachmentContent(b"<svg/>", "image/svg+xml", False)},
    )
    outcome = await _service(api=api).get_content(5)

    assert outcome.metadata.outcome == "text"
    assert outcome.text == "<svg/>"
    assert outcome.image_bytes is None


@pytest.mark.asyncio
async def test_get_content_unusable_binary_returns_metadata_only() -> None:
    api = _FakeAttachmentApi(
        [_record(content_type="application/pdf")],
        contents={5: AttachmentContent(b"%PDF-1.7", "application/pdf", False)},
    )
    outcome = await _service(api=api).get_content(5)

    assert outcome.metadata.outcome == "not_inline_supported"
    assert outcome.metadata.content_type == "application/pdf"
    assert outcome.metadata.size_bytes is None
    assert "application/pdf" in (outcome.metadata.reason or "")
    assert outcome.image_bytes is None
    assert outcome.text is None


@pytest.mark.asyncio
async def test_get_content_unusable_blob_reports_the_stored_type_not_the_generic_served_one() -> None:
    """OpenProject serves anything it will not inline as
    application/octet-stream, so the served header on this outcome says only
    "not inlineable" -- the stored type is the one that names the file."""
    api = _FakeAttachmentApi(
        [_record(content_type="application/zip")],
        contents={5: AttachmentContent(b"PK\x03\x04", "application/octet-stream", False)},
    )
    outcome = await _service(api=api).get_content(5)

    assert outcome.metadata.outcome == "not_inline_supported"
    assert outcome.metadata.content_type == "application/zip"
    assert "application/zip" in (outcome.metadata.reason or "")
    assert outcome.image_bytes is None
    assert outcome.text is None


@pytest.mark.asyncio
async def test_get_content_unusable_blob_reports_no_type_when_content_type_is_hidden() -> None:
    """`reason` is prose: with content_type hidden, the key is dropped from the
    payload and the sentence must not spell the same value back out."""
    settings = dataclasses.replace(make_settings(), hidden_fields={"attachment": ("content_type",)})
    api = _FakeAttachmentApi(
        [_record(content_type="application/zip")],
        contents={5: AttachmentContent(b"PK\x03\x04", "application/octet-stream", False)},
    )
    outcome = await _service(api=api, settings=settings).get_content(5)

    assert outcome.metadata.outcome == "not_inline_supported"
    assert outcome.metadata.content_type is None
    assert "application/zip" not in (outcome.metadata.reason or "")
    assert "Content type unknown" in (outcome.metadata.reason or "")


@pytest.mark.asyncio
async def test_get_content_max_bytes_may_only_lower_the_configured_cap() -> None:
    settings = dataclasses.replace(make_settings(), attachment_content_max_bytes=100)
    api = _FakeAttachmentApi([_png_record()], contents={5: AttachmentContent(b"PNG", "image/png", False)})
    service = _service(api=api, settings=settings)

    await service.get_content(5, max_bytes=10)
    await service.get_content(5, max_bytes=1000)
    await service.get_content(5)

    assert api.get_content_calls == [(5, 10), (5, 100), (5, 100)]


@pytest.mark.asyncio
async def test_get_content_rejects_non_positive_max_bytes() -> None:
    api = _FakeAttachmentApi([_png_record()], contents={5: AttachmentContent(b"PNG", "image/png", False)})
    with pytest.raises(InvalidInputError, match="max_bytes"):
        await _service(api=api).get_content(5, max_bytes=0)
    assert api.get_content_calls == []


@pytest.mark.asyncio
async def test_get_content_metadata_honours_hidden_attachment_fields() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"attachment": ("content_type", "file_name")})
    api = _FakeAttachmentApi([_png_record()], contents={5: AttachmentContent(b"PNG", "image/png", False)})
    outcome = await _service(api=api, settings=settings).get_content(5)

    payload = _to_payload(outcome.metadata, elide_none=False)
    assert "content_type" not in payload
    assert "file_name" not in payload
    assert payload["outcome"] == "image"
    # The image itself is still inlined: hiding is exposure control on the
    # metadata, not a second authorization layer on the content.
    assert outcome.image_bytes == b"PNG"


@pytest.mark.asyncio
async def test_get_content_size_bytes_is_none_when_file_size_hidden() -> None:
    """`size_bytes` is the returned block's size, but for content returned
    whole it is exactly the hidden `file_size_bytes` -- so it gets the same
    treatment `total_size_bytes` does, rather than leaking the number back
    under another field name. The content itself is still returned."""
    settings = dataclasses.replace(make_settings(), hidden_fields={"attachment": ("file_size_bytes",)})
    api = _FakeAttachmentApi([_png_record()], contents={5: AttachmentContent(b"PNG", "image/png", False)})
    outcome = await _service(api=api, settings=settings).get_content(5)

    assert outcome.metadata.outcome == "image"
    assert outcome.metadata.size_bytes is None
    assert outcome.image_bytes == b"PNG"
    assert _to_payload(outcome.metadata, elide_none=False)["size_bytes"] is None


@pytest.mark.asyncio
async def test_get_content_truncated_text_size_bytes_is_none_when_file_size_hidden() -> None:
    """Even a truncated block's size is withheld: it is the byte cap here, but
    a caller cannot tell that from a size that happens to equal the cap."""
    settings = dataclasses.replace(
        make_settings(), attachment_content_max_bytes=5, hidden_fields={"attachment": ("file_size_bytes",)}
    )
    api = _FakeAttachmentApi(
        [_record(content_type="text/plain")],
        contents={5: AttachmentContent(b"hello world", "text/plain", False)},
    )
    outcome = await _service(api=api, settings=settings).get_content(5)

    assert outcome.metadata.outcome == "text"
    assert outcome.metadata.truncated is True
    assert outcome.metadata.size_bytes is None
    assert outcome.text == "hello"


@pytest.mark.asyncio
async def test_list_with_images_size_bytes_is_none_when_file_size_hidden() -> None:
    """The include_images entries go through the same metadata funnel."""
    settings = dataclasses.replace(make_settings(), hidden_fields={"attachment": ("file_size_bytes",)})
    api = _FakeAttachmentApi([_png_record()], contents={5: AttachmentContent(b"PNG", "image/png", False)})
    result = await _service(api=api, settings=settings).list_for_work_package_with_images(9)

    assert result.list_result.images is not None
    assert [entry.outcome for entry in result.list_result.images] == ["image"]
    assert result.list_result.images[0].size_bytes is None
    assert [outcome.image_bytes for outcome in result.included] == [b"PNG"]


# --- list_for_work_package_with_images ------------------------------------------


@pytest.mark.asyncio
async def test_list_with_images_inlines_in_order_under_one_aggregate_budget() -> None:
    records = [
        _png_record(1),
        _record(2, content_type="application/pdf"),
        _png_record(3),
    ]
    contents = {
        1: AttachmentContent(b"AAA", "image/png", False),
        2: AttachmentContent(b"%PDF", "application/pdf", False),
        3: AttachmentContent(b"BBBB", "image/png", False),
    }
    settings = dataclasses.replace(make_settings(), attachment_content_max_bytes=4)
    api = _FakeAttachmentApi(records, contents=contents)
    service = _service(api=api, settings=settings)

    listing = await service.list_for_work_package_with_images(9)

    assert [s.id for s in listing.list_result.results] == [1, 2, 3]
    assert listing.list_result.images is not None
    outcomes = [(e.attachment_id, e.outcome) for e in listing.list_result.images]
    assert outcomes == [(1, "image"), (2, "not_inline_supported"), (3, "too_large")]
    assert "include_images inlines images only" in (listing.list_result.images[1].reason or "")
    assert "1-byte budget left" in (listing.list_result.images[2].reason or "")
    # Only the PNGs were fetched, the second one with whatever budget was left.
    assert api.get_content_calls == [(1, 4), (3, 1)]
    assert [o.metadata.attachment_id for o in listing.included] == [1]
    assert listing.included[0].image_bytes == b"AAA"


@pytest.mark.asyncio
async def test_list_with_images_exhausted_budget_skips_without_downloading() -> None:
    records = [_png_record(1), _png_record(3)]
    contents = {1: AttachmentContent(b"AAA", "image/png", False), 3: AttachmentContent(b"B", "image/png", False)}
    settings = dataclasses.replace(make_settings(), attachment_content_max_bytes=3)
    api = _FakeAttachmentApi(records, contents=contents)

    listing = await _service(api=api, settings=settings).list_for_work_package_with_images(9)

    assert api.get_content_calls == [(1, 3)]
    assert listing.list_result.images is not None
    assert listing.list_result.images[1].outcome == "too_large"
    assert "3-byte budget for this call was already used" in (listing.list_result.images[1].reason or "")
    assert len(listing.included) == 1


@pytest.mark.asyncio
async def test_list_without_images_leaves_images_field_unset() -> None:
    api = _FakeAttachmentApi([_png_record(1)])
    result = await _service(api=api).list_for_work_package(9)
    assert result.images is None
    assert api.get_content_calls == []
