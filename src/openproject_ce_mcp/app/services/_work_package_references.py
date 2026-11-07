"""What is specific to work packages when a result names versions, sprints and backlog buckets.

The decision itself is made by `_scoped_references`, for every entity. Here: which work package result
fields a hide setting removes, the group labels of a grouped query, and the links a write sets.

Functions only, in an underscore-prefixed module: every public class under app/services/ must be
named `*Service`/`*Resolver`.
"""

from __future__ import annotations

from collections.abc import Container, Iterable, Sequence

from ...config import Settings
from ...models import WorkPackageGroupSums
from ..policies import hidden_fields
from ..ports.scoped_reference import ScopedReferencesAllowedBulkCheck, VisibleReferences
from ..ports.work_package_api import WorkPackageGroupRecord, WorkPackageRecord
from . import _scoped_references

# The columns whose group label is the name of a version, sprint or backlog bucket.
_REFERENCE_COLUMNS = frozenset({"version", "target_versions", "observed_in_versions", "sprint", "backlog_bucket"})
HIDDEN_GROUP_LABEL = "[outside read scope]"
# version and target_versions read and write the same data: hiding one hides both.
_VERSION_FIELDS = ("version", "target_versions")


def _field_shown(field: str, *, settings: Settings) -> bool:
    custom = _scoped_references.custom_field_shown("work_package", field, settings=settings)
    if custom is not None:
        return custom
    names = _VERSION_FIELDS if field in _VERSION_FIELDS else (field,)
    return not any(hidden_fields.field_hidden("work_package", name, settings=settings) for name in names)


async def visible_references(
    *,
    records: Sequence[WorkPackageRecord] = (),
    groups: Sequence[WorkPackageGroupRecord] = (),
    settings: Settings,
    check: ScopedReferencesAllowedBulkCheck,
    fields: Container[str] | None = None,
    shown_only: bool = True,
) -> VisibleReferences:
    """The references the results built from `records` and `groups` may name."""
    return await _scoped_references.visible_references(
        records=records,
        extra=[reference for group in groups for reference in group.references],
        settings=settings,
        check=check,
        shown=lambda field: _field_shown(field, settings=settings),
        fields=fields,
        shown_only=shown_only,
    )


def groups_for_result(
    groups: Iterable[WorkPackageGroupRecord], *, group_by: str | None, visible: VisibleReferences
) -> list[WorkPackageGroupSums]:
    """The groups, each named after a reference the result may name. A group that names one it may
    not, or whose label is a reference name without a link to check, keeps its count and sums under
    a neutral label: the totals still add up and the name stays out. Existence is not secret, the
    name is."""
    result: list[WorkPackageGroupSums] = []
    for group in groups:
        unchecked = group.value is not None and not group.references and group_by in _REFERENCE_COLUMNS
        hidden = unchecked or not all(visible.contains(reference) for reference in group.references)
        result.append(
            WorkPackageGroupSums(
                value=HIDDEN_GROUP_LABEL if hidden else group.value, count=group.count, sums=group.sums
            )
        )
    return result


# The link a write sets -> the result fields that show what it replaces.
_WRITTEN_LINK_FIELDS = {
    "version": ("version", "target_versions"),
    "targetVersions": ("version", "target_versions"),
    "observedInVersions": ("observed_in_versions",),
    "sprint": ("sprint",),
}


async def hidden_references_replaced(
    record: WorkPackageRecord,
    written_links: Iterable[str],
    *,
    settings: Settings,
    check: ScopedReferencesAllowedBulkCheck,
) -> int:
    """How many versions, sprints and buckets a write that sets `written_links` would remove from `record`
    although a result may not name them, so the caller cannot know they are there. A custom field
    link is its own result field."""
    written = {field for link in written_links for field in _WRITTEN_LINK_FIELDS.get(link, (link,))}
    return await _scoped_references.hidden_references_replaced(
        record,
        written,
        settings=settings,
        check=check,
        shown=lambda field: _field_shown(field, settings=settings),
    )
