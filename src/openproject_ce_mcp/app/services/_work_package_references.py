"""Which versions, sprints and backlog buckets a work package result may name.

A work package of a covered project can carry a version, sprint or bucket shared into it from a project the
read scope does not cover. The decision is made here, once per call, and handed to the adapters as
`VisibleReferences`: this is the only module that builds one, so a result cannot be presented
without it.

Functions only, in an underscore-prefixed module: every public class under app/services/ must be
named `*Service`/`*Resolver`.
"""

from __future__ import annotations

from collections.abc import Container, Iterable, Sequence
from typing import Any

from ...config import Settings
from ...models import WorkPackageGroupSums
from ..policies import hidden_fields
from ..policies.scope import scope_allows_all
from ..ports.scoped_reference import (
    ScopedReference,
    ScopedReferencesAllowedBulkCheck,
    VisibleReferences,
    reference_of_link,
)
from ..ports.work_package_api import WorkPackageGroupRecord, WorkPackageRecord
from ..resource_href import ResourceLinks

# The columns whose group label is the name of a version, sprint or backlog bucket.
_REFERENCE_COLUMNS = frozenset({"version", "target_versions", "observed_in_versions", "sprint", "backlog_bucket"})
HIDDEN_GROUP_LABEL = "[outside read scope]"
# version and target_versions read and write the same data: hiding one hides both.
_VERSION_FIELDS = ("version", "target_versions")


def _field_shown(field: str, *, settings: Settings) -> bool:
    if field.startswith("customField"):
        return not (
            hidden_fields.field_hidden("work_package", "custom_fields", settings=settings)
            or hidden_fields.custom_field_hidden(field, field, settings=settings)
        )
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
    """The references the results built from `records` and `groups` may name. Everything under `*`;
    otherwise one deduplicated check for the references of the fields among `fields` (all when not
    given) and, unless `shown_only` is false, shown, which fails as a whole if any check fails."""
    if scope_allows_all(settings.read_projects):
        return VisibleReferences.everything()
    wanted: dict[ScopedReference, None] = {}
    for record in records:
        for field, references in record.references.items():
            if (fields is None or field in fields) and (not shown_only or _field_shown(field, settings=settings)):
                wanted.update(dict.fromkeys(references))
    for group in groups:
        wanted.update(dict.fromkeys(group.references))
    outcomes = await check(wanted) if wanted else {}
    visible: list[ScopedReference] = []
    for reference in wanted:
        outcome = outcomes[reference]
        if isinstance(outcome, Exception):
            raise outcome
        if outcome:
            visible.append(reference)
    return VisibleReferences.only(visible)


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
    visible = await visible_references(
        records=[record], settings=settings, check=check, fields=written, shown_only=False
    )
    replaced = {
        reference for field, references in record.references.items() if field in written for reference in references
    }
    return sum(not visible.contains(reference) for reference in replaced)


async def field_with_visible_options(
    field: dict[str, Any],
    *,
    links: ResourceLinks,
    settings: Settings,
    check: ScopedReferencesAllowedBulkCheck,
    keep_unnamed: bool = True,
) -> dict[str, Any]:
    """The schema field without the allowed values that name a version, sprint or bucket the read
    scope does not cover, so a value can be neither assigned by name nor probed for. A value that names
    none of them is kept unless `keep_unnamed` is false, for a field whose every value must be one."""
    options = field.get("_embedded", {}).get("allowedValues")
    if not isinstance(options, list) or scope_allows_all(settings.read_projects):
        return field
    named = {
        reference: option
        for option in options
        if isinstance(option, dict)
        and (reference := reference_of_link(option.get("_links", {}).get("self"), links)) is not None
    }
    if not named:
        return field if keep_unnamed else {**field, "_embedded": {**field["_embedded"], "allowedValues": []}}
    outcomes = await check(named)
    visible = []
    for option in options:
        reference = reference_of_link(option.get("_links", {}).get("self"), links) if isinstance(option, dict) else None
        if reference is None:
            if keep_unnamed:
                visible.append(option)
            continue
        outcome = outcomes[reference]
        if isinstance(outcome, Exception):
            raise outcome
        if outcome:
            visible.append(option)
    return {**field, "_embedded": {**field["_embedded"], "allowedValues": visible}}
