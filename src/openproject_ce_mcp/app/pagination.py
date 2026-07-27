"""Shared pagination-envelope helpers (ADR 0001).

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

    Single source of truth for a pair that used to be written as two separately
    worded (but logically identical) expressions per list method -- `truncated`
    is exactly "next_offset is not None", derived here instead of re-derived.
    """
    next_offset = _next_offset(offset, limit, total)
    return next_offset, next_offset is not None


def clamp_limit(limit: int | None, *, default_page_size: int, max_page_size: int, max_results: int) -> int:
    """Resolve a caller-supplied `limit` (or None) to an effective page size,
    capped by both `max_page_size` and `max_results`.

    Byte-identical `effective_limit = min(limit or settings.default_page_size,
    settings.max_page_size, settings.max_results)` was duplicated across 8 call
    sites in 7 Service files (found during the Sprints migration's step-6
    self-audit, which added the last 2 of the 8) -- extracted here once past
    this project's own "3+ identical copies" unification threshold.
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


async def paginate_all(
    fetch_page: Callable[[int, int], Awaitable[tuple[list[_T], int]]], *, page_size: int
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
    """
    items: list[_T] = []
    offset = 1
    while True:
        page_items, total = await fetch_page(offset, page_size)
        items.extend(page_items)
        next_offset, truncated = paginate_server(offset=offset, limit=page_size, total=total)
        if not truncated:
            return items
        offset = next_offset if next_offset is not None else offset + 1
