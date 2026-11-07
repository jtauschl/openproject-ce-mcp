"""Which versions, sprints and backlog buckets a result may name, for every entity whose records carry them.

A record of a covered project can carry a version, sprint or bucket shared into it from a project the read
scope does not cover, in a built-in field or in a custom field. The decision is made here, once per call, and
handed to the adapters as `VisibleReferences`: this is the only module that builds one, so a result cannot be
presented without it. An entity module (`_work_package_references`, `_project_references`) supplies what is
its own: which result fields a hide setting removes, and the references that belong to no record.

Functions only, in an underscore-prefixed module: every public class under app/services/ must be
named `*Service`/`*Resolver`.
"""

from __future__ import annotations

from collections.abc import Callable, Container, Iterable, Sequence
from typing import Any

from ...config import Settings
from ..policies import hidden_fields
from ..policies.scope import scope_allows_all
from ..ports.scoped_reference import (
    ScopedRecord,
    ScopedReference,
    ScopedReferencesAllowedBulkCheck,
    VisibleReferences,
    reference_of_link,
)
from ..resource_href import ResourceLinks


def custom_field_shown(entity: str, field: str, *, settings: Settings) -> bool | None:
    """Whether a `customField<N>` result field of `entity` is shown; None for any other field."""
    if not field.startswith("customField"):
        return None
    return not (
        hidden_fields.field_hidden(entity, "custom_fields", settings=settings)
        or hidden_fields.custom_field_hidden(field, field, settings=settings)
    )


async def visible_references(
    *,
    records: Sequence[ScopedRecord] = (),
    extra: Iterable[ScopedReference] = (),
    settings: Settings,
    check: ScopedReferencesAllowedBulkCheck,
    shown: Callable[[str], bool],
    fields: Container[str] | None = None,
    shown_only: bool = True,
) -> VisibleReferences:
    """The references the results built from `records` may name, plus `extra`. Everything under `*`;
    otherwise one deduplicated check for the references of the fields among `fields` (all when not
    given) and, unless `shown_only` is false, shown, which fails as a whole if any check fails."""
    if scope_allows_all(settings.read_projects):
        return VisibleReferences.everything()
    wanted: dict[ScopedReference, None] = {}
    for record in records:
        for field, references in record.references.items():
            if (fields is None or field in fields) and (not shown_only or shown(field)):
                wanted.update(dict.fromkeys(references))
    wanted.update(dict.fromkeys(extra))
    outcomes = await check(wanted) if wanted else {}
    visible: list[ScopedReference] = []
    for reference in wanted:
        outcome = outcomes[reference]
        if isinstance(outcome, Exception):
            raise outcome
        if outcome:
            visible.append(reference)
    return VisibleReferences.only(visible)


async def hidden_references_replaced(
    record: ScopedRecord,
    written_fields: set[str],
    *,
    settings: Settings,
    check: ScopedReferencesAllowedBulkCheck,
    shown: Callable[[str], bool],
) -> int:
    """How many references a write that sets the result fields `written_fields` would remove from `record`
    although a result may not name them, so the caller cannot know they are there."""
    visible = await visible_references(
        records=[record], settings=settings, check=check, shown=shown, fields=written_fields, shown_only=False
    )
    replaced = {
        reference
        for field, references in record.references.items()
        if field in written_fields
        for reference in references
    }
    return sum(not visible.contains(reference) for reference in replaced)


async def field_with_visible_options(
    field: dict[str, Any], *, links: ResourceLinks, settings: Settings, check: ScopedReferencesAllowedBulkCheck
) -> dict[str, Any]:
    """The schema field without the allowed values that name a version, sprint or bucket the read
    scope does not cover, so a value can be neither assigned by name nor probed for."""
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
        return field
    outcomes = await check(named)
    visible = []
    for option in options:
        reference = reference_of_link(option.get("_links", {}).get("self"), links) if isinstance(option, dict) else None
        if reference is None:
            visible.append(option)
            continue
        outcome = outcomes[reference]
        if isinstance(outcome, Exception):
            raise outcome
        if outcome:
            visible.append(option)
    return {**field, "_embedded": {**field["_embedded"], "allowedValues": visible}}
