"""Shared pagination-envelope helpers.

Package-root shared kernel: pure, dependency-free pagination math used by the
Versions domain (and available to any future migrated domain) without creating a
layering violation.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar


def _next_offset(offset: int, limit: int, total: int) -> int | None:
    if offset * limit >= total:
        return None
    return offset + 1


def paginate_server(*, offset: int, limit: int, total: int) -> tuple[int | None, bool]:
    """next_offset/truncated for a page the server already sliced (offset/pageSize sent
    as request params, `total` trusted as reported).

    Single source of truth for this pair: `truncated` is exactly
    "next_offset is not None", derived here rather than re-derived per call site.
    """
    next_offset = _next_offset(offset, limit, total)
    return next_offset, next_offset is not None


def clamp_limit(limit: int | None, *, default_page_size: int, max_page_size: int, max_results: int) -> int:
    """Resolve a caller-supplied `limit` (or None) to an effective page size,
    capped by both `max_page_size` and `max_results`.

    Single source of truth for `effective_limit = min(limit or
    settings.default_page_size, settings.max_page_size, settings.max_results)`,
    shared across every Service that needs it rather than duplicated per call site.
    """
    return min(limit or default_page_size, max_page_size, max_results)


def effective_limit(limit: int | None, *, settings: Any) -> int:
    """`clamp_limit`, but reading `default_page_size`/`max_page_size`/`max_results`
    directly off a `Settings` instance instead of three separate keyword args.

    A byte-identical `_effective_limit(self, limit)` method (each just this one
    `clamp_limit(...)` call wrapping `self._settings`'s three fields) was
    duplicated across RoleService, ActionCapabilityService, GroupService, and
    UserService -- found during the Statuses/Priorities/Types migration's
    (16th domain) step-6 self-audit, past this project's own "3+ identical
    copies" unification threshold. `settings` is typed `Any` here, not
    `config.Settings`, only to avoid this dependency-free package-root module
    importing from the parent package -- every call site passes a real
    `Settings` instance.
    """
    return clamp_limit(
        limit,
        default_page_size=settings.default_page_size,
        max_page_size=settings.max_page_size,
        max_results=settings.max_results,
    )


def paginate_client(*, offset: int, limit: int, results: list[Any]) -> tuple[list[Any], int, int | None, bool]:
    """Slice an already-fetched, already-filtered in-memory list into one page.

    Returns (page, total, next_offset, truncated). `total` is len(results) --
    the filtered candidate set already held locally, not a server-reported
    total. Same next_offset/truncated relationship as paginate_server.
    """
    total = len(results)
    start = (offset - 1) * limit
    end = start + limit
    page = results[start:end]
    next_offset, truncated = paginate_server(offset=offset, limit=limit, total=total)
    return page, total, next_offset, truncated


_T = TypeVar("_T")


async def fetch_bounded_and_paginate(
    *,
    fetch_page: Callable[[int, int], Awaitable[dict[str, Any]]],
    normalize: Callable[[dict[str, Any]], _T],
    item_allowed: Callable[[dict[str, Any]], Awaitable[bool]] | None,
    post_filter: Callable[[list[_T]], list[_T]] | None,
    server_page_size: int,
    offset: int,
    limit: int,
) -> tuple[list[_T], int, int | None, bool]:
    """Walk every server page, normalize + filter the raw elements, apply an
    optional post-normalize filter (e.g. project/search predicates), then
    paginate the survivors in memory via paginate_client.

    Verbatim extraction of client.py's private `_fetch_bounded_and_paginate`
    (first extracted for the Relations migration) -- the shape is
    unchanged, only the raw-payload-fetching part is now injected via
    `fetch_page(server_offset, server_page_size) -> raw HAL page dict` instead
    of being hardwired to `self._get(path, params=...)`, so this is reusable
    by any Service, not just OpenProjectClient. client.py's own
    `_fetch_bounded_and_paginate` (kept for list_time_entries, its one
    remaining still-flat caller) now delegates here instead of duplicating
    the loop.

    item_allowed is async (rather than plain bool) so ACL checks that need
    their own lookups (e.g. relations checking each linked work package's
    project) can use this helper too -- without it, callers needing an async
    filter had to hand-roll their own fetch+params, which is exactly how a
    prior pageSize-omission bug happened.

    Some project-scoped sub-collection endpoints (verified live: a project's
    versions endpoint) silently ignore both offset and pageSize and always
    return every element -- without the seen-ids check below,
    `page_count < server_page_size` never becomes true and this loops
    forever, re-fetching the same full page. Tracked against the RAW element
    ids (before item_allowed/normalize), so a page that's merely fully
    filtered out doesn't get mistaken for a repeat.
    """
    results: list[_T] = []
    seen_ids: set[Any] = set()
    server_offset = 1
    is_first_page = True
    while True:
        payload = await fetch_page(server_offset, server_page_size)
        raw_elements = payload.get("_embedded", {}).get("elements", [])
        page_ids = {item.get("id") for item in raw_elements if isinstance(item, dict)}
        if not is_first_page and page_ids and page_ids <= seen_ids:
            break
        is_first_page = False
        seen_ids.update(page_ids)
        page_count = 0
        for item in raw_elements:
            if isinstance(item, dict):
                page_count += 1
                if item_allowed is None or await item_allowed(item):
                    results.append(normalize(item))
        if page_count < server_page_size:
            break
        server_offset += 1
    if post_filter is not None:
        results = post_filter(results)
    return paginate_client(offset=offset, limit=limit, results=results)


async def paginate_all(
    fetch_page: Callable[[int, int], Awaitable[tuple[list[_T], int]]],
    *,
    page_size: int,
    key: Callable[[_T], Any] | None = None,
) -> list[_T]:
    """Walk a server-paginated fetcher (offset, page_size) -> (items, total) to
    completion, returning every item across all pages.

    For an internal consumer that needs the complete dataset to scan (e.g.
    resolving a name reference by value), not a single page for display.
    `VersionResolver`/`ProjectResolver` each hand-roll an equivalent
    `while True` loop already (see version_resolver.py, project_resolver.py),
    but those are tied to project-scoped fetch signatures with per-page
    allowlist checks -- not extracted here to avoid forcing an unrelated
    refactor of that project-scoped machinery onto this purely-global helper.

    Some sub-collection endpoints (verified live: a project's versions
    endpoint) silently ignore both offset and page size and always return
    every element -- without the seen-keys check below, `truncated` never
    becomes False and this loops forever, re-fetching the same full page.
    `key` extracts a per-item identity (e.g. `lambda r: r.summary.id`) so a
    repeated page is detected and dropped rather than merely capped; when
    omitted, an accumulated-count check against `total` still prevents the
    infinite loop, but a repeated page's items would be duplicated in the
    result.
    """
    items: list[_T] = []
    seen_keys: set[Any] = set()
    offset = 1
    is_first_page = True
    while True:
        page_items, total = await fetch_page(offset, page_size)
        if key is not None:
            page_keys = {key(item) for item in page_items}
            if not is_first_page and page_keys and page_keys <= seen_keys:
                return items
            seen_keys.update(page_keys)
        is_first_page = False
        items.extend(page_items)
        if len(items) >= total:
            return items
        next_offset, truncated = paginate_server(offset=offset, limit=page_size, total=total)
        if not truncated:
            return items
        offset = next_offset if next_offset is not None else offset + 1
