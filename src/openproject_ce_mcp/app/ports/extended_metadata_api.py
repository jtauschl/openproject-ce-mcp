"""Extended Metadata Domain API port.

Bundles 5 unrelated-but-adjacent, purely-global, read-only lookups under one
ticket/Service, following the same rationale as Actions & Capabilities and
Query Metadata: render_text, Help Texts, Working Days, Non-Working Days,
Custom Options. Every method shares no project link and no list/detail
divergence (no `to_detail` split on any Record -- none of these five
domains has a list endpoint whose row shape differs from its single-item GET
shape). render_text does not share the "extended" read-enablement gate the
other four use -- it keeps its pre-existing "work_package" scope, a
deliberate, verbatim-preserved exception (see ExtendedMetadataService's own
docstring), not a reason to split it into its own Service.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ...models import (
    CustomOptionSummary,
    HelpTextSummary,
    NonWorkingDay,
    RenderedText,
    WorkingDay,
)


@dataclass(frozen=True)
class RenderedTextRecord:
    summary: RenderedText


@dataclass(frozen=True)
class HelpTextRecord:
    summary: HelpTextSummary


@dataclass(frozen=True)
class WorkingDayRecord:
    summary: WorkingDay


@dataclass(frozen=True)
class NonWorkingDayRecord:
    summary: NonWorkingDay


@dataclass(frozen=True)
class CustomOptionRecord:
    summary: CustomOptionSummary


class ExtendedMetadataApi(Protocol):
    """Narrow, Extended-Metadata-only Domain API port. ExtendedMetadataService
    depends on this Protocol, never on HttpxExtendedMetadataApi concretely
    (enforced by the architecture-boundary test).
    """

    async def render_text(self, *, text: str, format: str) -> RenderedTextRecord: ...

    async def list_help_texts(self) -> list[HelpTextRecord]: ...

    async def get_help_text(self, help_text_id: int) -> HelpTextRecord: ...

    async def list_working_days(self) -> list[WorkingDayRecord]: ...

    async def list_non_working_days(self, *, year: int | None) -> list[NonWorkingDayRecord]: ...

    async def get_custom_option(self, custom_option_id: int) -> CustomOptionRecord: ...
