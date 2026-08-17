"""HTTP-backed WorkPackageApi adapter -- covers the full domain.

Write-path methods (`validate_create`/`validate_update`/`parse_form`/
`commit_create`/`commit_update`/`delete`/`post_comment`) are thin HTTP
translations -- straightforward `Transport.{post_json,patch_json,delete}`
calls, no domain logic (schema-option resolution, custom-field matching, the
auto-percentage/auto-remaining-time derivation) lives here; all of that is a
`WorkPackageService` concern (see `app/ports/work_package_api.py`'s module
docstring).

`parse_form` is the one exception with actual I/O, and only when called with
`resolve_links=True`: fields whose candidate set is unbounded (any
`User`-typed field, e.g. `responsible`, or a user/version reference custom
field) never embed `allowedValues` -- OpenProject links a pre-filtered
collection instead (`schema[field]._links.allowedValues.href`). With
`resolve_links=True`, `parse_form` dereferences that link into
`_embedded.allowedValues` (via `_resolve_linked_allowed_values`, which
returns a new schema dict rather than mutating the input) before handing the
schema to the Service, so `WorkPackageService`'s option-matching stays
pure/no-I/O as documented, always seeing an embedded list. Mirrors
`HttpxProjectApi.list_available_parent_projects`'s identical link-dereference
shape for the `parent` field. Defaults to `resolve_links=False` (no I/O,
matching every call site except the dedicated schema probe) -- see
`app/ports/work_package_api.py`'s `parse_form` docstring for which call
sites need which.

No `httpx` import (depends on the `Transport` Protocol only). Owns the pure
normalize_* HAL->model translation functions, matching the Projects/Versions
domains' convention: normalize_* live in the adapter, not the port, and are
NOT hidden-field-aware (masking is a Service concern, applied after these
return -- see `app/services/work_package_service.py`'s `_stamp`).

`list()` deliberately returns raw, unnormalized elements (`WorkPackagePage`)
rather than pre-built `WorkPackageRecord`s -- see `app/ports/work_package_api.py`'s
module docstring for why: allowlist filtering must happen BEFORE
normalization for this domain, unlike Projects. `to_record()` is exposed as a
separate Protocol method so the Service can normalize only the elements that
survive its own allowlist filter, then call it again for `get()`'s single
payload.

`_trim_text`/`_link_title`/`_id_from_href`/`_delimit_user_content`/
`_origin_from_url`/`_reject_path_traversal_segments`/`SUBJECT_LIMIT`/
`_normalize_text`/`_trim_text_with_meta`/`_extract_formattable_text_with_meta`/
`FORMATTABLE_LIMIT` are shared via `app/adapters/_text.py`.
`work_package_ref()` (path-safe reference encoding) is imported from
`app/ports/work_package_ref.py` rather than re-implemented here: adapters may
import from ports (see `tests/test_architecture_boundaries.py`'s layer rules),
and it is already the exact, path-traversal-safe encoding
`HttpxWorkPackageLookupApi`/`WorkPackageResolver` use today -- a third local
copy would be needless duplication where reuse is clean.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from ...models import SortCriterion, WorkPackageDetail, WorkPackageSummary
from ..errors import OpenProjectServerError
from ..ports.work_package_api import WorkPackageFormResult, WorkPackagePage, WorkPackageRecord
from ..ports.work_package_ref import work_package_ref as _work_package_ref_encode
from ..transport.protocol import Transport
from ._text import FORMATTABLE_LIMIT, SUBJECT_LIMIT
from ._text import delimit_user_content as _delimit_user_content
from ._text import extract_formattable_text_with_meta as _extract_formattable_text_with_meta
from ._text import id_from_href as _id_from_href
from ._text import link_title as _link_title
from ._text import normalize_form_validation_errors as _normalize_form_validation_errors
from ._text import origin_from_url as _origin_from_url
from ._text import trim_text as _trim_text
from ._text import trim_text_with_meta as _trim_text_with_meta

WORK_PACKAGE_CHILDREN_LIMIT = 50
WORK_PACKAGE_ANCESTORS_LIMIT = 20

# Caps the NUMBER of distinct customField<N> entries kept in custom_fields
# (and, independently, the number of customComment<N> entries kept in
# custom_comments -- see _extract_custom_comments). Per OPM-94.
CUSTOM_FIELD_VALUE_LIMIT = 50

# Scalar-string length cap for string/link/date-format CF values and for
# custom_comments' plain string values. Mirrors SUBJECT_LIMIT (255, the
# established cap for a single-line/short-scalar OpenProject field in this
# codebase -- see _text.py) rather than FORMATTABLE_LIMIT (1200), which is
# for the multi-paragraph "text" format specifically, not a short scalar.
CUSTOM_FIELD_SCALAR_LIMIT = SUBJECT_LIMIT

# Per-entry item cap for a multi-value list/user/version-format CF (these
# formats can have unboundedly many linked titles). Deliberately smaller
# than CUSTOM_FIELD_VALUE_LIMIT (which caps the number of CF *entries*, not
# titles within one entry) and the same order of magnitude as
# WORK_PACKAGE_ANCESTORS_LIMIT above -- a single multi-value custom field
# with more than 20 titles is already an edge case not worth budgeting
# further context for.
CUSTOM_FIELD_LIST_ITEM_LIMIT = 20

# Combined worst-case bound on custom_fields' contribution to a response,
# given the caps above: at most CUSTOM_FIELD_VALUE_LIMIT (50) entries, each
# either a scalar capped at CUSTOM_FIELD_SCALAR_LIMIT (255) chars, a
# Formattable text capped at the caller's text_limit (FORMATTABLE_LIMIT=1200
# by default), or a list of at most CUSTOM_FIELD_LIST_ITEM_LIMIT (20) titles
# each capped at SUBJECT_LIMIT (255) chars -- so worst case is roughly
# 50 * max(1200, 20 * 255) = 50 * 5100 =~ 255,000 chars (~250 KB) for
# custom_fields, plus a separate, independently-capped custom_comments dict
# of at most 50 entries * 255 chars =~ 12,750 chars (~12 KB). Both dicts are
# finite and bounded regardless of what the server returns.


def _link_title_with_meta(link: dict[str, Any]) -> tuple[str | None, bool]:
    """Like `_link_title`, but also reports whether the title was cut.

    `_link_title` (`_text.link_title`) is shared by every other WP link
    field (assignee/status/version/etc.), none of which need a truncation
    signal, so it stays a plain `str | None` return there. Custom fields DO
    need the signal, to correctly fold it into `custom_fields_truncated`
    (see `_normalize_custom_field_entry`) -- this local wrapper reuses the
    same `SUBJECT_LIMIT` cap via `trim_text_with_meta` instead of
    duplicating `_link_title`'s own logic.
    """
    title, truncated, _length = _trim_text_with_meta(link.get("title"), limit=SUBJECT_LIMIT)
    return title, truncated


def _is_custom_field_key(key: str) -> bool:
    """True for a raw `customField<N>` key -- and ONLY that shape.

    Deliberately excludes `customField<N>_errors` (a calculated_value-format
    sibling property, out of CE scope) and `customComment<N>` (handled
    separately by `_extract_custom_comments`): `key[11:]` is the remainder
    after the 11-character `"customField"` prefix, and `.isdigit()` rejects
    both `_errors` (non-digit suffix) and `Comment<N>` (wrong prefix
    entirely, never reaches this check). Verified against
    custom_field_injector.rb: `inject_property_value`/`inject_link_value` use
    `custom_field.attribute_name` (-> `customField<N>`), while
    `inject_comment_value` uses the distinct `comment_attribute_name` (->
    `customComment<N>`).
    """
    return key.startswith("customField") and key[11:].isdigit()


def _custom_field_raw_entries(payload: dict[str, Any], links: dict[str, Any]) -> dict[str, Any]:
    """Collect every raw `customField<N>` entry, top-level AND `_links`.

    Custom field values are split across TWO locations depending on format
    (verified against custom_field_injector.rb, both the `LINK_FORMATS`
    constant and the `inject_property_value`/`inject_link_value` methods):
    the 7 CE-realistic PLAIN-VALUE formats (string, text, link, int, float,
    date, bool) are injected as plain top-level `@class.property` entries;
    the 3 CE-realistic HAL-LINK formats (list, user, version -- `hierarchy`/
    `weighted_item_list` are Enterprise-gated and out of CE scope) are
    injected via `@class.resource`/`@class.resources`, which the
    `LinkedResource` DSL always renders under `_links`, never at the top
    level. Scanning only the top level would silently drop every
    list/user/version-format CF with no error. The two key-spaces do not
    overlap (each CF id has exactly one format), so a plain dict update is a
    safe merge.
    """
    entries: dict[str, Any] = {key: value for key, value in payload.items() if _is_custom_field_key(key)}
    if isinstance(links, dict):
        for key, value in links.items():
            if _is_custom_field_key(key) and key not in entries:
                entries[key] = value
    return entries


def _normalize_custom_field_entry(raw: Any, *, text_limit: int | None) -> tuple[Any, bool] | None:
    """Shape-detect and normalize one raw customField<N> value.

    Returns `(normalized_value, truncated)`, or `None` to omit the key
    entirely (malformed/unusable shape). Detection is schema-free, by
    payload shape (the adapter has no custom-field-definition/schema access
    at read time):
    - Formattable dict (has a `raw` or `html` key) -> text extraction via the
      existing `_extract_formattable_text_with_meta` machinery, using the
      SAME `text_limit` the caller applies to `description` in that same
      normalization context (`settings.text_limit` in
      `normalize_work_package_summary`; the caller's own `text_limit`
      parameter, default FORMATTABLE_LIMIT, in `normalize_work_package_detail`)
      -- not a hardcoded FORMATTABLE_LIMIT, so a CF text value is exactly as
      capped/uncapped as `description` is for that same read.
    - other dict -> single-value link title via `_link_title` (list/user/
      version, single-value; also covers an empty `{href: null, title:
      null}` link, which normalizes to `_link_title`'s own None).
    - list -> multi-value link titles (list/user/version, multi-value),
      capped at CUSTOM_FIELD_LIST_ITEM_LIMIT titles; a list whose title
      extraction yields zero usable titles still normalizes to `[]` and is
      KEPT (not omitted) -- an empty multi-value link is a real, meaningful
      value ("no titles resolved"), not a malformed entry; only a raw shape
      that cannot be interpreted at all (see below) is omitted.
    - bare scalar (str/int/float/bool) -> passthrough, with the scalar
      string cap applied to `str` values only (int/float/bool are not
      length-capped -- they cannot carry unbounded text). This cap is
      INDEPENDENT of `text_limit`: even when the caller passes
      `text_limit=None` (get_work_package's documented "single work
      packages are not truncated" default), a scalar string-format CF is
      still capped at CUSTOM_FIELD_SCALAR_LIMIT -- `text_limit=None` only
      removes the Formattable/text-format branch's cap above, not this one.
    - None -> passthrough (a legitimate "field has no value" signal, per
      `render_nil: true` on the property injector).
    - anything else (unrecognized shape) -> omitted (returns None).

    A `str` scalar (string/link/date-format CF, indistinguishable from one
    another at the shape level -- link is a plain string URL, not a HAL
    link, per custom_field_injector.rb's `inject_property_value`) and a
    Formattable text-format value are both exactly as user-controlled as
    `description`, so both get `_delimit_user_content()` wrapping (matching
    `description`'s existing untrusted-content handling) -- link-title
    values (from `_link_title`, single or multi-value) are NOT delimited,
    matching every other WP link field in this codebase (type/status/
    assignee/etc.), none of which delimit their titles either.
    """
    if raw is None:
        return None, False
    if isinstance(raw, dict):
        if "raw" in raw or "html" in raw:
            text, truncated, _length = _extract_formattable_text_with_meta(raw, limit=text_limit)
            return _delimit_user_content(text), truncated
        title, title_truncated = _link_title_with_meta(raw)
        return title, title_truncated
    if isinstance(raw, list):
        title_results = [_link_title_with_meta(item) for item in raw if isinstance(item, dict)]
        kept_results = [(title, t) for title, t in title_results if title is not None]
        titles = [title for title, _truncated in kept_results]
        any_kept_title_truncated = any(t for _title, t in kept_results[:CUSTOM_FIELD_LIST_ITEM_LIMIT])
        truncated = len(titles) > CUSTOM_FIELD_LIST_ITEM_LIMIT or any_kept_title_truncated
        return titles[:CUSTOM_FIELD_LIST_ITEM_LIMIT], truncated
    if isinstance(raw, str):
        text = _trim_text(raw, limit=CUSTOM_FIELD_SCALAR_LIMIT)
        return _delimit_user_content(text), len(raw) > CUSTOM_FIELD_SCALAR_LIMIT
    if isinstance(raw, int | float | bool):
        return raw, False
    return None


def _extract_custom_fields(
    payload: dict[str, Any], links: dict[str, Any], *, text_limit: int | None
) -> tuple[dict[str, Any] | None, bool]:
    """Build the `custom_fields` dict, applying every cap from OPM-94 §4/§5.

    ``text_limit`` is threaded through to the Formattable/text-format branch
    of `_normalize_custom_field_entry` -- the SAME value the caller applies
    to `description` in this normalization context, per OPM-94 §1.

    Normalize-first, THEN cap (fixes a blocking bug from an earlier draft):
    up to CUSTOM_FIELD_VALUE_LIMIT raw keys are normalized in ascending
    numeric-id order; a raw key whose value normalizes to `None` above (i.e.
    "omit this entry" -- an unrecognized/malformed shape, not a legitimate
    None value, since a legitimate None is returned as `(None, False)`, not
    bare `None`) is skipped WITHOUT consuming one of the 50 slots, so
    malformed entries can never crowd out later valid ones. `truncated` is
    True if either (a) more raw customField<N> keys existed than could be
    normalized+kept, or (b) any KEPT entry was itself internally truncated
    (Formattable text over the effective text_limit, a scalar string over
    CUSTOM_FIELD_SCALAR_LIMIT, or a multi-value list over
    CUSTOM_FIELD_LIST_ITEM_LIMIT) -- aggregating both signals into one flag
    (also fixing a second earlier bug, where a per-entry truncation flag was
    computed but silently discarded).
    """
    raw_entries = _custom_field_raw_entries(payload, links)
    if not raw_entries:
        return None, False

    def _numeric_key(key: str) -> int:
        return int(key[11:])

    kept: dict[str, Any] = {}
    any_entry_truncated = False
    considered = 0
    for key in sorted(raw_entries, key=_numeric_key):
        if len(kept) >= CUSTOM_FIELD_VALUE_LIMIT:
            break
        considered += 1
        normalized = _normalize_custom_field_entry(raw_entries[key], text_limit=text_limit)
        if normalized is None:
            continue
        value, entry_truncated = normalized
        kept[key] = value
        any_entry_truncated = any_entry_truncated or entry_truncated

    # truncated: True if any raw key beyond what was considered still
    # remains (count-capped), OR any kept entry's own value was internally
    # truncated.
    count_capped = considered < len(raw_entries)
    truncated = count_capped or any_entry_truncated
    return (kept or None), truncated


def _extract_custom_comments(payload: dict[str, Any]) -> tuple[dict[str, str] | None, bool]:
    """Build the `custom_comments` dict from raw `customComment<N>` keys.

    `customComment<N>` is a plain top-level string-or-null property (never
    under `_links`; verified against `inject_comment_value`'s
    `@class.property ... render_nil: true`), gated on the customized model's
    OWN `acts_as_customizable comments:` option (`CustomField#can_have_comment?`
    delegates to `customized_class.can_have_custom_comments?`).

    IMPORTANT, verified live against a real 17.7.1 instance (not merely read
    from source): `app/models/work_package.rb`'s `acts_as_customizable
    validate_on: :saving_custom_fields` call never passes `comments: true` --
    only `app/models/project.rb` does (`comments: true, admin_only_allowed:
    true`). Attempting to set `has_comment: true` on a WorkPackageCustomField
    raises `ActiveRecord::RecordInvalid: "Add a comment text field must be
    blank"`. So `customComment<N>` is structurally IMPOSSIBLE on a
    WorkPackage on this codebase, on every OpenProject version -- this is
    NOT merely gated to 17.2+ as originally assumed from
    `inject_comment_schema`/`inject_comment_value`'s mere presence in the
    17.7 injector alone (that generic machinery never fires for WorkPackage
    because `custom_field.has_comment?` can never be true there). This scan
    is kept anyway (harmless, forward-compatible should a future OpenProject
    version ever add `comments: true` to WorkPackage) but will return
    `(None, False)` for every real WorkPackage payload today -- see
    docker/test/seed.rb's OPM-94 custom-field seed block and this project's
    OPM-94 implementation report for the full finding.
    """
    raw_entries = {
        key: value for key, value in payload.items() if key.startswith("customComment") and key[13:].isdigit()
    }
    if not raw_entries:
        return None, False

    def _numeric_key(key: str) -> int:
        return int(key[13:])

    kept: dict[str, str] = {}
    any_entry_truncated = False
    considered = 0
    for key in sorted(raw_entries, key=_numeric_key):
        if len(kept) >= CUSTOM_FIELD_VALUE_LIMIT:
            break
        considered += 1
        raw_value = raw_entries[key]
        if raw_value is None:
            # A null customComment<N> is omitted, not kept as an explicit
            # None value -- unlike _normalize_custom_field_entry's
            # custom_fields handling (None -> passthrough, since a missing
            # CF value is itself meaningful information). This is a
            # deliberate asymmetry: custom_comments' model type is
            # `dict[str, str]` (models.py), not `dict[str, str | None]`, so
            # there is no None-safe slot to put this value in without
            # widening that type -- a change not worth making for a shape
            # that is currently unreachable on a real WorkPackage (see this
            # function's own docstring). If OpenProject ever does emit a
            # null customComment<N> here, it is dropped, matching how any
            # other unusable/empty value in this dict is dropped rather than
            # widening the type for a still-theoretical case.
            continue
        text = _trim_text(raw_value, limit=CUSTOM_FIELD_SCALAR_LIMIT)
        if text is None:
            continue
        delimited = _delimit_user_content(text)
        assert delimited is not None  # _trim_text returned non-None above, so this cannot be None
        kept[key] = delimited
        any_entry_truncated = any_entry_truncated or len(str(raw_value)) > CUSTOM_FIELD_SCALAR_LIMIT

    count_capped = considered < len(raw_entries)
    truncated = count_capped or any_entry_truncated
    return (kept or None), truncated


def _work_package_dates(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    """(start_date, due_date) for a work package, accounting for milestones.

    OpenProject's work_package_representer.rb (`date_property :date`, `getter:
    default_date_getter(:due_date)`, `skip_render: !milestone?`) omits
    `startDate`/`dueDate` entirely for milestone-type work packages and
    instead reports the single day under a separate `date` key, itself
    reading the underlying `due_date` value -- verified against
    lib/api/v3/work_packages/work_package_representer.rb. Without this, every
    milestone work package normalizes to start_date=None, due_date=None even
    when it has a real date set.
    """
    start_date = payload.get("startDate")
    due_date = payload.get("dueDate")
    if start_date is None and due_date is None and payload.get("date") is not None:
        milestone_date = payload["date"]
        return milestone_date, milestone_date
    return start_date, due_date


def normalize_work_package_summary(payload: dict[str, Any], *, text_limit: int | None) -> WorkPackageSummary:
    """Pure HAL->model translation. Excludes hidden-field-aware text
    extraction -- hidden-field masking (including zeroing
    description_truncated/description_length/has_description when the
    description field itself is hidden) is a Service concern, applied after
    this returns (see WorkPackageService._stamp).

    ``text_limit`` is an explicit parameter since the adapter has no Settings
    access -- the Service passes `settings.text_limit` through, matching
    `normalize_project`'s equivalent parameter.
    """
    links = payload.get("_links", {})
    description, truncated, length = _extract_formattable_text_with_meta(payload.get("description"), limit=text_limit)
    start_date, due_date = _work_package_dates(payload)
    custom_fields, custom_fields_truncated = _extract_custom_fields(payload, links, text_limit=text_limit)
    custom_comments, custom_comments_truncated = _extract_custom_comments(payload)
    return WorkPackageSummary(
        id=int(payload["id"]),
        display_id=payload.get("displayId"),
        subject=_trim_text(payload.get("subject"), limit=SUBJECT_LIMIT) or f"Work package {payload['id']}",
        type=_link_title(links.get("type")),
        status=_link_title(links.get("status")),
        priority=_link_title(links.get("priority")),
        project_phase=_link_title(links.get("projectPhase")),
        assignee=_link_title(links.get("assignee")),
        responsible=_link_title(links.get("responsible")),
        project=_link_title(links.get("project")),
        version=_link_title(links.get("version")),
        sprint=_link_title(links.get("sprint")),
        start_date=start_date,
        due_date=due_date,
        description=_delimit_user_content(description),
        has_description=description is not None,
        description_truncated=truncated,
        description_length=length,
        estimated_time=payload.get("estimatedTime"),
        derived_estimated_time=payload.get("derivedEstimatedTime"),
        spent_time=payload.get("spentTime"),
        remaining_time=payload.get("remainingTime"),
        derived_remaining_time=payload.get("derivedRemainingTime"),
        duration=payload.get("duration"),
        parent_id=_id_from_href(links.get("parent", {}).get("href")),
        # Hierarchy links carry displayId from 17.5 (semantic mode); absent on
        # older/classic instances (verified against the 17.2 representer,
        # which has no displayId on the parent link), where this stays None.
        parent_display_id=links.get("parent", {}).get("displayId"),
        created_at=payload.get("createdAt"),
        updated_at=payload.get("updatedAt"),
        author=_link_title(links.get("author")),
        category=_link_title(links.get("category")),
        schedule_manually=payload.get("scheduleManually"),
        ignore_non_working_days=payload.get("ignoreNonWorkingDays"),
        derived_start_date=payload.get("derivedStartDate"),
        derived_due_date=payload.get("derivedDueDate"),
        percentage_done=payload.get("percentageDone"),
        derived_percentage_done=payload.get("derivedPercentageDone"),
        readonly=payload.get("readonly"),
        custom_fields=custom_fields,
        custom_fields_truncated=custom_fields_truncated,
        custom_comments=custom_comments,
        custom_comments_truncated=custom_comments_truncated,
    )


def normalize_work_package_detail(
    payload: dict[str, Any],
    *,
    text_limit: int | None = FORMATTABLE_LIMIT,
    summary: WorkPackageSummary | None = None,
) -> WorkPackageDetail:
    """Single-work-package read. ``text_limit=None`` (used by get()) returns the
    full description uncapped; the FORMATTABLE_LIMIT default keeps
    write-preview-style callers capped. Excludes hidden-field masking
    (Service concern).

    `summary` lets a caller that already built a `WorkPackageSummary` for the
    same payload pass it in to avoid a second full normalization -- callers
    with only the raw payload omit it and get the summary computed here.
    `description` is still independently re-extracted regardless
    (`preserve_newlines=True`, a genuinely different extraction than the
    summary's, not just a different truncation limit).

    `custom_fields`/`custom_fields_truncated`/`custom_comments`/
    `custom_comments_truncated` are NOT independently re-extracted here --
    unlike `description`, they are read straight off `summary` (computed
    with the SAME `text_limit` this function received, whether `summary`
    was passed in or computed above). Deliberate choice, not an oversight:
    CF text-format values do not get `preserve_newlines=True` in the Detail
    context (they stay single-line-collapsed like the Summary's own
    treatment) -- structured custom-field text is typically short/single-
    purpose data, not multi-paragraph prose like `description`, and
    re-scanning every customField<N>/customComment<N> key a second time per
    Detail call for a rarely-relevant newline distinction was judged not
    worth the doubled shape-detection cost.
    """
    if summary is None:
        summary = normalize_work_package_summary(payload, text_limit=text_limit)
    links = payload.get("_links", {})
    description, truncated, length = _extract_formattable_text_with_meta(
        payload.get("description"), limit=text_limit, preserve_newlines=True
    )

    children_raw = links.get("children", [])
    children = None
    children_truncated = False
    if children_raw:
        children = [
            {"href": c.get("href"), "title": c.get("title"), "display_id": c.get("displayId")}
            for c in children_raw[:WORK_PACKAGE_CHILDREN_LIMIT]
        ]
        children_truncated = len(children_raw) > WORK_PACKAGE_CHILDREN_LIMIT

    ancestors_raw = links.get("ancestors", [])
    ancestors = None
    ancestors_truncated = False
    if ancestors_raw:
        ancestors = [
            {"href": a.get("href"), "title": a.get("title"), "display_id": a.get("displayId")}
            for a in ancestors_raw[:WORK_PACKAGE_ANCESTORS_LIMIT]
        ]
        ancestors_truncated = len(ancestors_raw) > WORK_PACKAGE_ANCESTORS_LIMIT

    start_date, due_date = _work_package_dates(payload)
    return WorkPackageDetail(
        id=summary.id,
        display_id=summary.display_id,
        subject=summary.subject,
        type=summary.type,
        status=summary.status,
        priority=summary.priority,
        project_phase=summary.project_phase,
        assignee=summary.assignee,
        responsible=summary.responsible,
        project=summary.project,
        version=summary.version,
        sprint=summary.sprint,
        parent_id=summary.parent_id,
        parent_display_id=summary.parent_display_id,
        start_date=start_date,
        due_date=due_date,
        lock_version=payload.get("lockVersion"),
        description=_delimit_user_content(description),
        description_truncated=truncated,
        description_length=length,
        estimated_time=summary.estimated_time,
        derived_estimated_time=summary.derived_estimated_time,
        spent_time=summary.spent_time,
        remaining_time=summary.remaining_time,
        derived_remaining_time=summary.derived_remaining_time,
        duration=summary.duration,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
        author=summary.author,
        category=summary.category,
        children=children,
        children_truncated=children_truncated,
        ancestors=ancestors,
        ancestors_truncated=ancestors_truncated,
        schedule_manually=summary.schedule_manually,
        ignore_non_working_days=summary.ignore_non_working_days,
        derived_start_date=summary.derived_start_date,
        derived_due_date=summary.derived_due_date,
        percentage_done=summary.percentage_done,
        derived_percentage_done=summary.derived_percentage_done,
        readonly=summary.readonly,
        custom_fields=summary.custom_fields,
        custom_fields_truncated=summary.custom_fields_truncated,
        custom_comments=summary.custom_comments,
        custom_comments_truncated=summary.custom_comments_truncated,
    )


class HttpxWorkPackageApi:
    def __init__(self, transport: Transport, *, base_url: str, api_prefix: str = "/api/v3/") -> None:
        self._transport = transport
        self._origin = _origin_from_url(base_url)
        self._api_prefix = api_prefix

    def _link_to_api_path(self, href: str) -> str:
        """Same-origin-checked href -> API-relative path. Mirrored by
        `HttpxProjectApi._link_to_api_path`/`HttpxWorkPackageLookupApi._link_to_api_path`
        -- deliberately duplicated per adapter rather than shared, so a future
        change to one cannot silently change another's contract."""
        parsed = urlparse(href)
        if not parsed.scheme:
            path = parsed.path or href
        else:
            if _origin_from_url(href) != self._origin:
                raise OpenProjectServerError("OpenProject returned an unexpected link host.")
            path = parsed.path
        if path.startswith(self._api_prefix):
            relative_path = path[len(self._api_prefix) :]
        else:
            relative_path = path.lstrip("/")
        if parsed.query:
            return f"{relative_path}?{parsed.query}"
        return relative_path

    def to_record(self, payload: dict[str, Any], *, text_limit: int | None) -> WorkPackageRecord:
        summary = normalize_work_package_summary(payload, text_limit=text_limit)
        return WorkPackageRecord(
            summary=summary,
            # Lazy: list()/search() callers never read this -- only get()'s
            # single-item path needs the full detail normalization.
            to_detail=lambda: normalize_work_package_detail(payload, text_limit=text_limit, summary=summary),
            payload=payload,
        )

    async def list(
        self,
        *,
        filters: list[dict[str, Any]],
        offset: int,
        limit: int,
        sort_by: list[SortCriterion] | None,
        group_by: str | None,
        include_sums: bool = False,
    ) -> WorkPackagePage:
        params: dict[str, str] = {
            "offset": str(offset),
            "pageSize": str(limit),
            "filters": json.dumps(filters, separators=(",", ":")),
        }
        if sort_by:
            sort_criteria = [[criterion.field, criterion.direction] for criterion in sort_by]
            params["sortBy"] = json.dumps(sort_criteria, separators=(",", ":"))
        if group_by:
            params["groupBy"] = group_by
        if include_sums:
            params["showSums"] = "true"
        payload = await self._transport.get_json("work_packages", params=params)
        raw_elements = [item for item in payload.get("_embedded", {}).get("elements", []) if isinstance(item, dict)]
        server_total = int(payload.get("total", len(raw_elements)))
        # `groups`/`totalSums` are TOP-LEVEL response keys, not under
        # `_embedded` -- verified live against a real 17.x instance. Gated on
        # the request flag (not response presence) so a caller who didn't
        # ask for sums never sees populated fields.
        raw_groups = payload.get("groups") if include_sums else None
        raw_total_sums = payload.get("totalSums") if include_sums else None
        return WorkPackagePage(
            raw_elements=raw_elements,
            server_total=server_total,
            raw_groups=raw_groups,
            raw_total_sums=raw_total_sums,
        )

    async def get(self, work_package_ref: str, *, text_limit: int | None = None) -> WorkPackageRecord:
        safe_ref = _work_package_ref_encode(work_package_ref)
        payload = await self._transport.get_json(f"work_packages/{safe_ref}")
        return self.to_record(payload, text_limit=text_limit)

    async def validate_create(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._transport.post_json(f"projects/{project_id}/work_packages/form", json_body=payload)

    async def validate_update(self, work_package_ref: str, payload: dict[str, Any]) -> dict[str, Any]:
        safe_ref = _work_package_ref_encode(work_package_ref)
        return await self._transport.post_json(f"work_packages/{safe_ref}/form", json_body=payload)

    async def parse_form(self, form: dict[str, Any], *, resolve_links: bool = False) -> WorkPackageFormResult:
        embedded = form.get("_embedded") or {}
        schema = embedded.get("schema") or {}
        if resolve_links:
            schema = await self._resolve_linked_allowed_values(schema)
        return WorkPackageFormResult(
            payload=embedded.get("payload", {}),
            validation_errors=_normalize_form_validation_errors(embedded.get("validationErrors")),
            schema=schema,
        )

    async def _resolve_linked_allowed_values(self, schema: dict[str, Any]) -> dict[str, Any]:
        """Dereference every schema field's `_links.allowedValues.href` that
        isn't already embedded, returning a new schema dict -- the input is
        never mutated in place, so a caller holding a reference to the
        original `form`/schema sees it unchanged."""
        resolved: dict[str, Any] = dict(schema)
        for key, field in schema.items():
            if not isinstance(field, dict) or (field.get("_embedded") or {}).get("allowedValues") is not None:
                # Either not a field dict, or already carries an embedded
                # allowedValues list -- both cases resolve locally, no I/O.
                continue
            link = (field.get("_links") or {}).get("allowedValues")
            if not isinstance(link, dict):
                continue
            href = link.get("href")
            if not isinstance(href, str) or not href:
                continue
            payload = await self._transport.get_json(self._link_to_api_path(href))
            elements = (payload.get("_embedded") or {}).get("elements", [])
            resolved[key] = {**field, "_embedded": {**(field.get("_embedded") or {}), "allowedValues": elements}}
        return resolved

    async def commit_create(self, payload: dict[str, Any], *, text_limit: int | None) -> WorkPackageRecord:
        response = await self._transport.post_json("work_packages", json_body=payload)
        return self.to_record(response, text_limit=text_limit)

    async def commit_update(
        self, work_package_ref: str, payload: dict[str, Any], *, text_limit: int | None
    ) -> WorkPackageRecord:
        safe_ref = _work_package_ref_encode(work_package_ref)
        response = await self._transport.patch_json(f"work_packages/{safe_ref}", json_body=payload)
        return self.to_record(response, text_limit=text_limit)

    async def delete(self, work_package_ref: str) -> None:
        safe_ref = _work_package_ref_encode(work_package_ref)
        await self._transport.delete(f"work_packages/{safe_ref}")

    async def post_comment(
        self, work_package_ref: str, *, comment: str, internal: bool, notify: bool
    ) -> dict[str, Any]:
        safe_ref = _work_package_ref_encode(work_package_ref)
        return await self._transport.post_json(
            f"work_packages/{safe_ref}/activities",
            params={"notify": str(notify).lower()},
            json_body={"comment": {"raw": comment}, "internal": internal},
        )
