"""What names a version in a project result: the decision on its custom field references.

A project payload can carry a version-format custom field whose version is shared into the project from
a project the read scope does not cover. Every service that returns project summaries or details asks
here for the decision (made by `_scoped_references`) and builds the result from the record with it;
the hide-on-read masking of the values is `_custom_field_masking`, applied by the service's stamp.

Functions only, in an underscore-prefixed module: every public class under app/services/ must be
named `*Service`/`*Resolver`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from ...config import Settings
from ...models import ProjectDetail, ProjectSummary
from ..ports.project_api import ProjectRecord
from ..ports.scoped_reference import ScopedReferencesAllowedBulkCheck, VisibleReferences
from . import _scoped_references


def _shown(settings: Settings):
    return lambda field: _scoped_references.custom_field_shown("project", field, settings=settings) is not False


async def visible_references(
    records: Sequence[ProjectRecord], *, settings: Settings, check: ScopedReferencesAllowedBulkCheck
) -> VisibleReferences:
    return await _scoped_references.visible_references(
        records=records, settings=settings, check=check, shown=_shown(settings)
    )


async def hidden_references_replaced(
    record: ProjectRecord, written_links: Iterable[str], *, settings: Settings, check: ScopedReferencesAllowedBulkCheck
) -> int:
    """How many versions a write that sets the custom field links `written_links` would remove from `record`
    although a result may not name them, so the caller cannot know they are there."""
    return await _scoped_references.hidden_references_replaced(
        record, set(written_links), settings=settings, check=check, shown=_shown(settings)
    )


async def present_summaries(
    records: Sequence[ProjectRecord], *, settings: Settings, references_allowed: ScopedReferencesAllowedBulkCheck
) -> list[ProjectSummary]:
    """The records as summaries that name only the versions the read scope covers."""
    visible = await visible_references(records, settings=settings, check=references_allowed)
    return [record.scoped_summary(visible=visible) for record in records]


async def present_detail(
    record: ProjectRecord, *, settings: Settings, references_allowed: ScopedReferencesAllowedBulkCheck
) -> ProjectDetail:
    visible = await visible_references([record], settings=settings, check=references_allowed)
    return record.scoped_detail(visible=visible)
