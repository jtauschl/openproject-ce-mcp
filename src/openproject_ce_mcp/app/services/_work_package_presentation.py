"""What every work package result goes through before it leaves the server: the parent check and
the hidden-field masking.

One module for both services that return work package summaries (`WorkPackageService`,
`QueryExecutionService`), so a masking rule cannot exist in one of them and be missing in the other.

Functions only, in an underscore-prefixed module: every public class under app/services/ must be
named `*Service`/`*Resolver`.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from typing import Any, TypeVar

from ...config import Settings
from ...models import ResolvedWorkPackage, WorkPackageDetail, WorkPackageSummary
from ..policies import hidden_fields
from ..ports.scoped_reference import ScopedReferencesAllowedBulkCheck, VisibleReferences
from ..ports.work_package_api import WorkPackageRecord
from ..ports.work_package_ref import WorkPackageProjectAllowedBulkCheck
from ._work_package_parents import without_uncovered_parents
from ._work_package_references import visible_references
from .project_scoped_list import SUBJECT_LIMIT, trim_text

WorkPackageT = TypeVar("WorkPackageT", WorkPackageSummary, WorkPackageDetail)

# version and target_versions read and write the same underlying data: hiding one must hide both.
_VERSION_ALIASES: dict[str, Any] = {"version": None, "target_versions": []}


def _mask_custom_field_keys(values: dict[str, Any] | None, *, settings: Settings) -> dict[str, Any] | None:
    """Hide-on-read for a `custom_fields` dict, matched against the raw `customField<N>` key only,
    never the friendly name. The write path matches both, so a pattern that names only the field
    has no effect on reads (docs/field-hiding.md).

    Returns the original object when nothing was removed."""
    if not values:
        return values
    if not settings.hide_custom_fields:
        return values
    filtered = {
        key: value
        for key, value in values.items()
        if not hidden_fields.custom_field_hidden(key, key, settings=settings)
    }
    if len(filtered) == len(values):
        return values
    return filtered or None


def _mask_custom_comments_by_hidden_field_ids(
    comments: dict[str, str] | None,
    *,
    custom_fields: dict[str, Any] | None,
    masked_custom_fields: dict[str, Any] | None,
) -> dict[str, str] | None:
    """Drop the `customComment<N>` entry of every `customField<N>` that masking removed. The hide
    patterns are written against the `customField<N>` form, so a comment key cannot be matched
    against them directly."""
    if not comments:
        return comments
    if custom_fields is masked_custom_fields:
        return comments
    before_ids = {key[len("customField") :] for key in (custom_fields or {})}
    after_ids = {key[len("customField") :] for key in (masked_custom_fields or {})}
    removed_ids = before_ids - after_ids
    if not removed_ids:
        return comments
    filtered = {key: value for key, value in comments.items() if key[len("customComment") :] not in removed_ids}
    if len(filtered) == len(comments):
        return comments
    return filtered or None


def _mask_custom_field_values(value: WorkPackageT, *, settings: Settings) -> WorkPackageT:
    """Mask `custom_fields` and `custom_comments` by key, and reset their truncation flags when the
    whole field is hidden, so the flag does not describe hidden data. A flag left unchanged after a
    key-only mask describes data the caller configured the hide for, so it discloses nothing new."""
    custom_fields = _mask_custom_field_keys(value.custom_fields, settings=settings)
    custom_comments = _mask_custom_comments_by_hidden_field_ids(
        value.custom_comments, custom_fields=value.custom_fields, masked_custom_fields=custom_fields
    )
    custom_fields_truncated = value.custom_fields_truncated
    custom_comments_truncated = value.custom_comments_truncated
    if hidden_fields.field_hidden("work_package", "custom_fields", settings=settings):
        custom_fields_truncated = False
    if hidden_fields.field_hidden("work_package", "custom_comments", settings=settings):
        custom_comments_truncated = False
    if (
        custom_fields is value.custom_fields
        and custom_comments is value.custom_comments
        and custom_fields_truncated == value.custom_fields_truncated
        and custom_comments_truncated == value.custom_comments_truncated
    ):
        return value
    return dataclasses.replace(
        value,
        custom_fields=custom_fields,
        custom_comments=custom_comments,
        custom_fields_truncated=custom_fields_truncated,
        custom_comments_truncated=custom_comments_truncated,
    )


def stamp_summary(summary: WorkPackageSummary, *, settings: Settings) -> WorkPackageSummary:
    """The last step before a summary leaves the server: `dataclasses.replace` drops the dynamic
    `_hidden_keys` the hidden-field stamp sets, so nothing may rebuild the summary afterwards."""
    if hidden_fields.field_hidden("work_package", "description", settings=settings):
        summary = dataclasses.replace(
            summary, description_truncated=False, description_length=None, has_description=False
        )
    summary = _mask_custom_field_values(summary, settings=settings)
    return hidden_fields.apply_hidden_fields_with_aliases(
        "work_package", summary, settings=settings, aliases=_VERSION_ALIASES
    )


def stamp_detail(detail: WorkPackageDetail, *, settings: Settings) -> WorkPackageDetail:
    """The detail counterpart of `stamp_summary`."""
    if hidden_fields.field_hidden("work_package", "description", settings=settings):
        detail = dataclasses.replace(detail, description_truncated=False, description_length=None)
    detail = _mask_custom_field_values(detail, settings=settings)
    return hidden_fields.apply_hidden_fields_with_aliases(
        "work_package", detail, settings=settings, aliases=_VERSION_ALIASES
    )


def present_target(payload: Mapping[str, Any], *, settings: Settings) -> ResolvedWorkPackage:
    """The work package a write reference resolved to, as a result may show it.

    Every caller has passed the project write gate, which also requires the read scope, so nothing
    here re-checks scope. The subject is trimmed, not delimited, exactly as `WorkPackageDetail`'s.
    """
    links = payload.get("_links", {})
    return hidden_fields.apply_hidden_fields(
        "work_package",
        ResolvedWorkPackage(
            id=int(payload["id"]),
            display_id=payload.get("displayId"),
            project=_link_title(links.get("project")),
            subject=trim_text(payload.get("subject"), limit=SUBJECT_LIMIT),
            status=_link_title(links.get("status")),
        ),
        settings=settings,
    )


def _link_title(link: Any) -> str | None:
    return trim_text(link.get("title"), limit=SUBJECT_LIMIT) if isinstance(link, dict) else None


async def present_summaries(
    records: Sequence[WorkPackageRecord],
    *,
    visible: VisibleReferences | None = None,
    settings: Settings,
    api_prefix: str,
    project_allowed_bulk: WorkPackageProjectAllowedBulkCheck,
    references_allowed: ScopedReferencesAllowedBulkCheck,
) -> list[WorkPackageSummary]:
    """The records as summaries a result may show: naming only the versions and sprints the read
    scope covers, each without a parent it does not cover, then stamped. A caller that needs the
    decision for more than the summaries passes it in."""
    if visible is None:
        visible = await visible_references(records=records, settings=settings, check=references_allowed)
    covered = await without_uncovered_parents(
        [record.scoped_summary(visible=visible) for record in records],
        settings=settings,
        api_prefix=api_prefix,
        project_allowed_bulk=project_allowed_bulk,
    )
    return [stamp_summary(summary, settings=settings) for summary in covered]


async def present_detail(
    record: WorkPackageRecord, *, settings: Settings, references_allowed: ScopedReferencesAllowedBulkCheck
) -> WorkPackageDetail:
    """The record as a detail that names only the versions and sprints the read scope covers. The
    caller applies the hierarchy filter and then `stamp_detail`."""
    visible = await visible_references(records=[record], settings=settings, check=references_allowed)
    return record.scoped_detail(visible=visible)
