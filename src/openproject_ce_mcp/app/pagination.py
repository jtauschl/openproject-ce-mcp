"""Shared pagination-envelope helpers (ADR 0001).

Package-root shared kernel: pure, dependency-free pagination math used by the
Versions domain (and available to any future migrated domain) without creating a
layering violation.
"""

from __future__ import annotations

from typing import Any


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
