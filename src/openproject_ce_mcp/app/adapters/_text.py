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

`slug_from_href` was added here once a step-6 self-audit (during the Query
Metadata migration) found it byte-identical across httpx_action_capability_api.py
and httpx_query_metadata_api.py -- past this project's own "3+ identical
copies" threshold once a third, genuinely dead copy in httpx_project_api.py
(defined, but with zero call sites in that file) is counted too; the dead
copy was removed outright there rather than migrated to an unused import.
httpx_board_api.py's own `_slug_from_href` stays LOCAL and deliberately
unmigrated: it uses `rsplit` with no `unquote` call, a genuinely different
(not just differently-written) behavior for a percent-encoded slug --
unifying it here would silently change Board's output for any href whose
final segment needs unquoting, not just remove duplication.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import unquote, urljoin, urlparse

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


def web_url(relative_path: str, *, base_url: str) -> str:
    """Build an absolute web URL from an already-relative path, unconditionally
    (no same-origin check -- unlike `link_to_web_url`, which resolves an
    arbitrary HREF that could point at a foreign origin). Verbatim port of
    client.py's own `_web_url` bound method.

    Extracted here once it crossed this project's "3+ identical copies"
    threshold (found during the Watchers migration's step-6 self-audit,
    OPM-294): `httpx_wiki_page_api.py` and `httpx_watcher_api.py` both had
    this exact function locally; `httpx_group_api.py`/`httpx_user_api.py`
    each had a reducible special case (`_web_url(<id>, ...)` hardcoding a
    resource-type prefix inline) expressible as
    `web_url(f"<resource>/{id}", base_url=...)` using this shape instead.
    """
    return urljoin(f"{base_url.rstrip('/')}/", relative_path.lstrip("/"))
