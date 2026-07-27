"""No write-allowlist-denial test exists here: all five bundled lookups are
purely global with no project link and no allowlist concept at all -- there
is nothing for an allowlist to check. This absence is deliberate, not an
oversight."""

from __future__ import annotations

import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import PermissionDeniedError
from openproject_ce_mcp.app.ports.extended_metadata_api import (
    CustomOptionRecord,
    HelpTextRecord,
    NonWorkingDayRecord,
    RenderedTextRecord,
    WorkingDayRecord,
)
from openproject_ce_mcp.app.services.extended_metadata_service import ExtendedMetadataService
from openproject_ce_mcp.models import CustomOptionSummary, HelpTextSummary, NonWorkingDay, RenderedText, WorkingDay


def _rendered_text_record() -> RenderedTextRecord:
    return RenderedTextRecord(summary=RenderedText(format="markdown", raw="**Hello**", html="<p><b>Hello</b></p>"))


def _help_text_record(help_text_id: int = 5) -> HelpTextRecord:
    return HelpTextRecord(
        summary=HelpTextSummary(
            id=help_text_id, attribute_name="description", attribute_caption="Description", help_text="Describe it."
        )
    )


def _working_day_record() -> WorkingDayRecord:
    return WorkingDayRecord(summary=WorkingDay(name="Monday", day_of_week=1, working=True))


def _non_working_day_record() -> NonWorkingDayRecord:
    return NonWorkingDayRecord(summary=NonWorkingDay(date="2026-12-25", name="Christmas Day"))


def _custom_option_record(custom_option_id: int = 42) -> CustomOptionRecord:
    return CustomOptionRecord(summary=CustomOptionSummary(id=custom_option_id, value="High Priority"))


class _FakeExtendedMetadataApi:
    def __init__(self) -> None:
        self.render_text_calls: list[tuple[str, str]] = []
        self.list_help_texts_calls = 0
        self.get_help_text_calls: list[int] = []
        self.list_working_days_calls = 0
        self.list_non_working_days_calls: list[int | None] = []
        self.get_custom_option_calls: list[int] = []

    async def render_text(self, *, text: str, format: str) -> RenderedTextRecord:
        self.render_text_calls.append((text, format))
        return _rendered_text_record()

    async def list_help_texts(self) -> list[HelpTextRecord]:
        self.list_help_texts_calls += 1
        return [_help_text_record()]

    async def get_help_text(self, help_text_id: int) -> HelpTextRecord:
        self.get_help_text_calls.append(help_text_id)
        return _help_text_record(help_text_id)

    async def list_working_days(self) -> list[WorkingDayRecord]:
        self.list_working_days_calls += 1
        return [_working_day_record()]

    async def list_non_working_days(self, *, year: int | None) -> list[NonWorkingDayRecord]:
        self.list_non_working_days_calls.append(year)
        return [_non_working_day_record()]

    async def get_custom_option(self, custom_option_id: int) -> CustomOptionRecord:
        self.get_custom_option_calls.append(custom_option_id)
        return _custom_option_record(custom_option_id)


def _service(api: _FakeExtendedMetadataApi | None = None, *, settings=None) -> ExtendedMetadataService:
    return ExtendedMetadataService(api=api or _FakeExtendedMetadataApi(), settings=settings or make_settings())


# --- render_text: keeps the pre-existing "work_package" scope ---------------


@pytest.mark.asyncio
async def test_render_text_returns_stamped_result() -> None:
    api = _FakeExtendedMetadataApi()
    service = _service(api)

    result = await service.render_text(text="**Hello**", format="markdown")

    assert result.html == "<p><b>Hello</b></p>"
    assert api.render_text_calls == [("**Hello**", "markdown")]


@pytest.mark.asyncio
async def test_render_text_checks_work_package_read_enabled_not_extended() -> None:
    """Regression test: render_text's read gate is a verbatim-preserved
    exception from the other four methods' newly-activated "extended" gate --
    it must keep checking "work_package", matching client.py's original
    self._ensure_read_enabled("work_package") call exactly.
    """
    settings = dataclasses.replace(make_settings(), enable_work_package_read=False, enable_metadata_tools=True)
    api = _FakeExtendedMetadataApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.render_text(text="Hello", format="markdown")

    assert api.render_text_calls == []


@pytest.mark.asyncio
async def test_render_text_succeeds_without_extended_enabled() -> None:
    """render_text must NOT require the "extended" scope -- only
    "work_package", even though it's registered under the "extended" tool
    group in tools.py."""
    settings = dataclasses.replace(make_settings(), enable_metadata_tools=False)
    api = _FakeExtendedMetadataApi()
    service = _service(api, settings=settings)

    result = await service.render_text(text="Hello", format="markdown")

    assert result.html == "<p><b>Hello</b></p>"


# --- the other four methods: newly-activated "extended" gate ----------------


@pytest.mark.asyncio
async def test_list_help_texts_checks_extended_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_metadata_tools=False)
    api = _FakeExtendedMetadataApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.list_help_texts()

    assert api.list_help_texts_calls == 0


@pytest.mark.asyncio
async def test_list_help_texts_returns_stamped_summaries_when_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_metadata_tools=True)
    api = _FakeExtendedMetadataApi()
    service = _service(api, settings=settings)

    result = await service.list_help_texts()

    assert result.count == 1
    assert result.results[0].id == 5
    assert api.list_help_texts_calls == 1


@pytest.mark.asyncio
async def test_get_help_text_checks_extended_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_metadata_tools=False)
    api = _FakeExtendedMetadataApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get_help_text(5)

    assert api.get_help_text_calls == []


@pytest.mark.asyncio
async def test_list_working_days_checks_extended_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_metadata_tools=False)
    api = _FakeExtendedMetadataApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.list_working_days()

    assert api.list_working_days_calls == 0


@pytest.mark.asyncio
async def test_list_non_working_days_checks_extended_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_metadata_tools=False)
    api = _FakeExtendedMetadataApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.list_non_working_days(year=2026)

    assert api.list_non_working_days_calls == []


@pytest.mark.asyncio
async def test_list_non_working_days_passes_year_through_when_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_metadata_tools=True)
    api = _FakeExtendedMetadataApi()
    service = _service(api, settings=settings)

    result = await service.list_non_working_days(year=2026)

    assert result.count == 1
    assert api.list_non_working_days_calls == [2026]


@pytest.mark.asyncio
async def test_get_custom_option_checks_extended_read_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_metadata_tools=False)
    api = _FakeExtendedMetadataApi()
    service = _service(api, settings=settings)

    with pytest.raises(PermissionDeniedError):
        await service.get_custom_option(42)

    assert api.get_custom_option_calls == []


@pytest.mark.asyncio
async def test_get_custom_option_returns_stamped_summary_when_enabled() -> None:
    settings = dataclasses.replace(make_settings(), enable_metadata_tools=True)
    api = _FakeExtendedMetadataApi()
    service = _service(api, settings=settings)

    result = await service.get_custom_option(42)

    assert result.id == 42
    assert result.value == "High Priority"


# --- hidden-field masking + entity-scope regression --------------------------


@pytest.mark.asyncio
async def test_get_help_text_applies_hidden_field_masking() -> None:
    settings = dataclasses.replace(
        make_settings(), enable_metadata_tools=True, hidden_fields={"help_text": ("help_text",)}
    )
    api = _FakeExtendedMetadataApi()
    service = _service(api, settings=settings)

    result = await service.get_help_text(5)

    assert getattr(result, "_hidden_keys", frozenset()) == {"help_text"}


@pytest.mark.asyncio
async def test_help_text_hidden_by_help_text_scope_not_working_day_or_custom_option_scope() -> None:
    """Regression test for the entity="help_text" vs a same-named-bundle
    neighbor hide-field mixup -- all five lookups in this bundle share one
    Service, so a copy-paste bug swapping entity strings between sibling
    methods is a real risk this bundled shape specifically invites.
    """
    settings_working_day_hidden = dataclasses.replace(
        make_settings(), enable_metadata_tools=True, hidden_fields={"working_day": ("attribute_name",)}
    )
    result_working_day_hidden = await _service(settings=settings_working_day_hidden).get_help_text(5)
    assert getattr(result_working_day_hidden, "_hidden_keys", frozenset()) == frozenset()

    settings_custom_option_hidden = dataclasses.replace(
        make_settings(), enable_metadata_tools=True, hidden_fields={"custom_option": ("attribute_name",)}
    )
    result_custom_option_hidden = await _service(settings=settings_custom_option_hidden).get_help_text(5)
    assert getattr(result_custom_option_hidden, "_hidden_keys", frozenset()) == frozenset()

    settings_help_text_hidden = dataclasses.replace(
        make_settings(), enable_metadata_tools=True, hidden_fields={"help_text": ("attribute_name",)}
    )
    result_help_text_hidden = await _service(settings=settings_help_text_hidden).get_help_text(5)
    assert getattr(result_help_text_hidden, "_hidden_keys", frozenset()) == {"attribute_name"}


@pytest.mark.asyncio
async def test_render_text_applies_hidden_field_masking_under_rendered_text_entity() -> None:
    settings = dataclasses.replace(make_settings(), hidden_fields={"rendered_text": ("html",)})
    api = _FakeExtendedMetadataApi()
    service = _service(api, settings=settings)

    result = await service.render_text(text="Hello", format="markdown")

    assert getattr(result, "_hidden_keys", frozenset()) == {"html"}
