"""Shared HAL-normalization text/link helpers for the httpx_*_api adapters.

`origin_from_url` is re-exported here unchanged from the package-root
`app/origin.py` so existing `from ._text import origin_from_url` imports
keep working; it lives at the package root because `services` needs the same
same-origin check but cannot import from `adapters`.

This module deliberately excludes most `_normalize_validation_errors`/
`_extract_formattable_text` variants: several adapters' versions differ
meaningfully (e.g. `httpx_project_api.py`'s validation-error path calls a
`_with_meta` variant, `httpx_membership_api.py`'s skips the
formattable-text-first branch) and are not safe to unify without changing
behavior -- they stay adapter-local, near-identical-but-not-identical code,
per this project's standing "don't unify what isn't truly the same"
principle. `normalize_form_validation_errors` below is the one exception
that is shared: a three-branch shape (formattable-text extraction, then
`entry.get("message")`, then a raw trim fallback) used identically by
`httpx_grid_api.py` and `httpx_time_entry_api.py`.

`httpx_board_api.py`'s own `_slug_from_href` stays LOCAL and is not shared
with `slug_from_href` below: it uses `rsplit` with no `unquote` call, a
genuinely different (not just differently-written) behavior for a
percent-encoded slug -- sharing it here would silently change Board's output
for any href whose final segment needs unquoting.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import unquote, urljoin, urlparse

from ..errors import InvalidInputError
from ..origin import origin_from_url

SUBJECT_LIMIT = 255


def reject_path_traversal_segments(value: str, *, field_name: str) -> str:
    """Reject a raw id/slug containing a `.`/`..` path segment.

    `urllib.parse.quote()` never escapes `.` (an "unreserved" RFC 3986
    character even with `safe=""`), so an id like
    `"../users/7"` passes through quoting completely unchanged. httpx then
    normalizes that segment away when building the request URL (confirmed:
    `httpx.Request("GET", ".../job_statuses/../projects/42").url` resolves to
    `.../projects/42`), letting a caller reach an entirely different
    endpoint -- bypassing whatever project-link allowlist check the intended
    endpoint would have applied. Any raw id/slug interpolated directly into
    a URL path (not a numeric id or a project/work-package resolver) must be
    checked with this before being used in an f-string/quote() call.
    """
    text = str(value)
    segments = text.split("/")
    if any(segment in (".", "..") for segment in segments):
        raise InvalidInputError(f"OpenProject {field_name} must not contain a '.' or '..' path segment.")
    return text


def trim_text(value: Any, *, limit: int) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def id_from_href(href: str | None) -> int | None:
    if not href:
        return None
    parts = href.rstrip("/").split("/")
    try:
        return int(parts[-1])
    except (ValueError, IndexError):
        return None


def slug_from_href(href: str | None) -> str | None:
    if not href:
        return None
    parts = href.rstrip("/").split("/")
    try:
        slug = parts[-1]
        return unquote(slug) or None
    except IndexError:
        return None


def link_title(link: Any) -> str | None:
    if not isinstance(link, dict):
        return None
    title = link.get("title")
    return trim_text(title, limit=SUBJECT_LIMIT)


def delimit_user_content(text: str | None) -> str | None:
    if text is None or not text.strip():
        return text
    return f"<user-content>{text}</user-content>"


def can_update_from_links(links: dict[str, Any]) -> bool:
    return "update" in links or "updateImmediately" in links


def _extract_formattable_text(value: Any, *, limit: int) -> str | None:
    if isinstance(value, dict):
        return trim_text(value.get("raw") or value.get("html"), limit=limit)
    return trim_text(value, limit=limit)


def normalize_form_validation_errors(value: Any, *, limit: int = SUBJECT_LIMIT) -> dict[str, str]:
    """Try formattable-text extraction, then `entry.get("message")`, then a
    raw trim fallback. Used by Grids' and Time Entries' `create`/`update`
    form-validation responses, both of which share this exact three-branch
    shape.
    """
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, str] = {}
    for key, entry in value.items():
        message = _extract_formattable_text(entry, limit=limit)
        if message is None and isinstance(entry, dict):
            message = trim_text(entry.get("message"), limit=limit)
        if message is None:
            message = trim_text(entry, limit=limit)
        if message:
            normalized[str(key)] = message
    return normalized


def link_to_web_url(href: str | None, *, base_url: str, origin: str) -> str | None:
    """Same-origin-checked href -> absolute web URL, or None for a foreign origin.

    A foreign-origin absolute href silently yields None rather than raising.
    """
    if not href:
        return None
    parsed = urlparse(href)
    if parsed.scheme:
        if origin_from_url(href) != origin:
            return None
        return href
    if href.startswith("/"):
        return urljoin(f"{origin.rstrip('/')}/", href.lstrip("/"))
    return urljoin(f"{base_url.rstrip('/')}/", href)
