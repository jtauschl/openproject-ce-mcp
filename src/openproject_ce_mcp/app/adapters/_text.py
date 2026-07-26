"""Shared HAL-normalization text/link helpers for the httpx_*_api adapters (ADR 0001).

Extracted from six byte-identical per-adapter copies once the sixth domain
(Wiki Pages) migrated -- every adapter's own module docstring had documented
this exact trigger condition ("unify only once every domain has migrated").
`can_update_from_links` was added here once the Boards migration made it the
3rd byte-identical copy (Document, News, Board all had the exact same
`"update" in links or "updateImmediately" in links` body), found during
Boards' step-6 self-audit. `origin_from_url` moved to the package-root
`app/origin.py` (also found during Boards' step-6 audit) since
`BoardService` needed the identical same-origin check but `services` cannot
import from `adapters` -- re-exported here unchanged so every existing
`from ._text import origin_from_url` import keeps working.
Deliberately excludes `_normalize_validation_errors` and `_extract_formattable_text`:
those differ meaningfully between adapters (e.g. httpx_project_api.py's
validation-error path calls a `_with_meta` variant, httpx_membership_api.py's
skips the formattable-text-first branch) and are not safe to unify without
changing behavior -- kept as adapter-local, near-identical-but-not-identical
code, per this project's standing "don't unify what isn't truly the same"
principle.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin, urlparse

from ..origin import origin_from_url

SUBJECT_LIMIT = 255


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
