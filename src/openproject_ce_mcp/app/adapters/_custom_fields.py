"""Entity-neutral normalization of `customField<N>` / `customComment<N>` values.

Work packages and projects carry their custom fields in the same HAL shape (OpenProject's custom field
injector renders both), so one module reads them: the caps, the format detection, the scoped link titles
and the raw-key helpers. An adapter passes the payload, its `_links`, the text limit of the read and the
`ScopedTitles` of the result; hide-on-read masking and the decision which references are visible stay in the
service layer.
"""

from __future__ import annotations

from typing import Any

from ..ports.scoped_reference import ScopedReference, VisibleReferences, reference_of_link
from ..resource_href import ResourceLinks
from ._text import SUBJECT_LIMIT
from ._text import delimit_user_content as _delimit_user_content
from ._text import extract_formattable_text_with_meta as _extract_formattable_text_with_meta
from ._text import trim_text as _trim_text
from ._text import trim_text_with_meta as _trim_text_with_meta

# Caps the NUMBER of distinct customField<N> entries kept in custom_fields
# (and, independently, the number of customComment<N> entries kept in
# custom_comments -- see extract_custom_comments).
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


def link_title_with_meta(link: dict[str, Any]) -> tuple[str | None, bool]:
    """Like `_link_title`, but also reports whether the title was cut.

    `_link_title` (`_text.link_title`) is shared by every other WP link
    field (assignee/status/version/etc.), none of which need a truncation
    signal, so it stays a plain `str | None` return there. Custom fields DO
    need the signal, to correctly fold it into `custom_fields_truncated`
    (see `normalize_custom_field_entry`) -- this local wrapper reuses the
    same `SUBJECT_LIMIT` cap via `trim_text_with_meta` instead of
    duplicating `_link_title`'s own logic.
    """
    title, truncated, _length = _trim_text_with_meta(link.get("title"), limit=SUBJECT_LIMIT)
    return title, truncated


# The namespaces whose resources are not bound to a project: a custom field link into one of them
# keeps its title. Any other link in a custom field loses it.
_UNBOUND_LINK_NAMESPACES = frozenset({"custom_options", "users", "groups", "placeholder_users", "custom_field_items"})


class ScopedTitles:
    """The titles of the links of one resource that a result may show: a version, sprint or
    bucket only when it is visible, a custom field link into a resource without a project, and
    nothing else."""

    def __init__(self, visible: VisibleReferences, links: ResourceLinks) -> None:
        self._visible = visible
        self._links = links

    def with_meta(self, link: Any) -> tuple[str | None, bool]:
        if not isinstance(link, dict):
            return None, False
        reference = reference_of_link(link, self._links)
        if reference is not None:
            return link_title_with_meta(link) if self._visible.contains(reference) else (None, False)
        parsed = self._links.parse(link)
        if parsed is not None and parsed.namespace in _UNBOUND_LINK_NAMESPACES:
            return link_title_with_meta(link)
        return None, False

    def one(self, link: Any) -> str | None:
        return self.with_meta(link)[0]

    def many(self, links: Any) -> list[str]:
        if not isinstance(links, list):
            return []
        return [title for item in links if (title := self.one(item)) is not None]


def links_references(value: Any, links: ResourceLinks) -> frozenset[ScopedReference]:
    items = value if isinstance(value, list) else [value]
    return frozenset(reference for item in items if (reference := reference_of_link(item, links)) is not None)


def is_custom_field_key(key: str) -> bool:
    """True for a raw `customField<N>` key -- and ONLY that shape.

    Deliberately excludes `customField<N>_errors` (a calculated_value-format
    sibling property, out of CE scope) and `customComment<N>` (handled
    separately by `extract_custom_comments`): `key[11:]` is the remainder
    after the 11-character `"customField"` prefix, and `.isdigit()` rejects
    both `_errors` (non-digit suffix) and `Comment<N>` (wrong prefix
    entirely, never reaches this check). Verified against
    custom_field_injector.rb: `inject_property_value`/`inject_link_value` use
    `custom_field.attribute_name` (-> `customField<N>`), while
    `inject_comment_value` uses the distinct `comment_attribute_name` (->
    `customComment<N>`).
    """
    return key.startswith("customField") and key[11:].isdigit()


def custom_field_raw_entries(payload: dict[str, Any], links: dict[str, Any]) -> dict[str, Any]:
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
    entries: dict[str, Any] = {key: value for key, value in payload.items() if is_custom_field_key(key)}
    if isinstance(links, dict):
        for key, value in links.items():
            if is_custom_field_key(key) and key not in entries:
                entries[key] = value
    return entries


def normalize_custom_field_entry(raw: Any, *, text_limit: int | None, scoped: ScopedTitles) -> tuple[Any, bool] | None:
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
        title, title_truncated = scoped.with_meta(raw)
        return title, title_truncated
    if isinstance(raw, list):
        title_results = [scoped.with_meta(item) for item in raw if isinstance(item, dict)]
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


def extract_custom_fields(
    payload: dict[str, Any], links: dict[str, Any], *, text_limit: int | None, scoped: ScopedTitles
) -> tuple[dict[str, Any] | None, bool]:
    """Build the `custom_fields` dict, capped at CUSTOM_FIELD_VALUE_LIMIT entries.

    ``text_limit`` is the caller's description limit, applied to text values too. Keys are visited in
    ascending id order and an entry of an unrecognized shape is skipped without using a slot, so
    malformed entries cannot crowd out valid ones. ``truncated`` is true when keys were left over or any
    kept value was itself cut.
    """
    raw_entries = custom_field_raw_entries(payload, links)
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
        normalized = normalize_custom_field_entry(raw_entries[key], text_limit=text_limit, scoped=scoped)
        if normalized is None:
            continue
        value, entry_truncated = normalized
        kept[key] = value
        any_entry_truncated = any_entry_truncated or entry_truncated

    count_capped = considered < len(raw_entries)
    truncated = count_capped or any_entry_truncated
    return (kept or None), truncated


def extract_custom_comments(payload: dict[str, Any]) -> tuple[dict[str, str] | None, bool]:
    """Build the `custom_comments` dict from raw `customComment<N>` keys.

    `customComment<N>` is a plain top-level string, never under `_links`. Only a model that opts in with
    `acts_as_customizable comments: true` has them: projects from 17.2 on (`app/models/project.rb`),
    never work packages, so a work package payload yields `(None, False)`.
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
            # `custom_comments` is `dict[str, str]`: a null comment has no slot and carries no information.
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


def custom_field_references(
    payload_links: dict[str, Any], links: ResourceLinks
) -> dict[str, frozenset[ScopedReference]]:
    """`customField<N>` key -> the references its link value names, for the fields that name any."""
    found = {key: links_references(value, links) for key, value in payload_links.items() if is_custom_field_key(key)}
    return {key: references for key, references in found.items() if references}
