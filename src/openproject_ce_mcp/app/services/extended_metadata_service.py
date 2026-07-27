"""Application Service for the Extended Metadata domain (19th migrated domain).

Depends on the ExtendedMetadataApi Protocol, never HttpxExtendedMetadataApi
concretely (enforced by the architecture-boundary test). No Resolver, no
Policy file: all five bundled lookups are purely global, no project link and
no allowlist concept at all -- matching Query Metadata's own bundled-lookups
shape. No `_write_outcome.py` state machine: zero write methods in this
domain (render_text is a POST, but produces no persisted resource and has no
confirm/preview semantics in the original client.py).

render_text deliberately does NOT share the "extended" read-enablement gate
the other four methods use -- it keeps its pre-existing, verbatim-preserved
"work_package" scope (client.py's original self._ensure_read_enabled
("work_package")). This is intra-Service per-method variation, not a reason
to split render_text into its own Service: Query Metadata's own
list_filter_instance_schemas already varies its Resolver usage per-method
within one Service, establishing the same precedent one layer over (there:
which Resolver runs; here: which scope string is checked).

The other four methods (list_help_texts, get_help_text, list_working_days,
list_non_working_days, get_custom_option) activate the "extended" scope
(OPENPROJECT_ENABLE_EXTENDED_READ / legacy OPENPROJECT_ENABLE_METADATA_TOOLS)
at the SERVICE layer for the first time -- config.py and tools.py already
define and register this scope (tools.py's READ_TOOLS_BY_SCOPE["extended"]
already lists all 6 of this domain's tool names), but no Service anywhere
called access.ensure_read_enabled("extended", ...) at runtime before this
migration. This is a deliberate behavior change: these four methods had NO
read-enablement check at all in client.py, and now require
OPENPROJECT_ENABLE_EXTENDED_READ=true.
"""

from __future__ import annotations

from ...config import Settings
from ...models import (
    CustomOptionSummary,
    HelpTextListResult,
    HelpTextSummary,
    NonWorkingDayListResult,
    RenderedText,
    WorkingDayListResult,
)
from ..policies import access, hidden_fields
from ..ports.extended_metadata_api import ExtendedMetadataApi


class ExtendedMetadataService:
    def __init__(self, *, api: ExtendedMetadataApi, settings: Settings) -> None:
        self._api = api
        self._settings = settings

    async def render_text(self, *, text: str, format: str = "markdown") -> RenderedText:
        access.ensure_read_enabled("work_package", settings=self._settings)
        record = await self._api.render_text(text=text, format=format)
        return hidden_fields.apply_hidden_fields("rendered_text", record.summary, settings=self._settings)

    async def list_help_texts(self) -> HelpTextListResult:
        access.ensure_read_enabled("extended", settings=self._settings)
        records = await self._api.list_help_texts()
        results = [
            hidden_fields.apply_hidden_fields("help_text", record.summary, settings=self._settings)
            for record in records
        ]
        return HelpTextListResult(count=len(results), results=results)

    async def get_help_text(self, help_text_id: int) -> HelpTextSummary:
        access.ensure_read_enabled("extended", settings=self._settings)
        record = await self._api.get_help_text(help_text_id)
        return hidden_fields.apply_hidden_fields("help_text", record.summary, settings=self._settings)

    async def list_working_days(self) -> WorkingDayListResult:
        access.ensure_read_enabled("extended", settings=self._settings)
        records = await self._api.list_working_days()
        results = [
            hidden_fields.apply_hidden_fields("working_day", record.summary, settings=self._settings)
            for record in records
        ]
        return WorkingDayListResult(count=len(results), results=results)

    async def list_non_working_days(self, *, year: int | None = None) -> NonWorkingDayListResult:
        access.ensure_read_enabled("extended", settings=self._settings)
        records = await self._api.list_non_working_days(year=year)
        results = [
            hidden_fields.apply_hidden_fields("non_working_day", record.summary, settings=self._settings)
            for record in records
        ]
        return NonWorkingDayListResult(count=len(results), results=results)

    async def get_custom_option(self, custom_option_id: int) -> CustomOptionSummary:
        access.ensure_read_enabled("extended", settings=self._settings)
        record = await self._api.get_custom_option(custom_option_id)
        return hidden_fields.apply_hidden_fields("custom_option", record.summary, settings=self._settings)
