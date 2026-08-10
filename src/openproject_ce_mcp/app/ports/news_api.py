"""News Domain API port -- narrow, no universal gateway."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from ...models import NewsDetail, NewsSummary


@dataclass(frozen=True)
class NewsRecord:
    """One news entry as read from the API: the list-row-truncated `summary`,
    a LAZY `to_detail` thunk for the larger single-item shape, plus the raw
    `project` HAL link (carried separately because the allowlist Policy
    check needs the raw link (href/id), which neither normalized model
    carries).

    `to_detail` is a callable, not a precomputed `NewsDetail` field, because
    normalize_news/normalize_news_detail apply DIFFERENT truncation limits to
    the same raw description -- detail cannot be derived from summary by a
    simple copy (unlike VersionRecord.to_detail(), whose VersionSummary/
    VersionDetail share identical truncation and where the copy is genuinely
    free). Computing it eagerly for every row would re-run a second,
    independent text-extraction pass over every record's description on
    every list call, for a value `NewsService.list()` never reads (only
    `get()`/`update()`/`delete()` -- single-item paths -- call `to_detail()`).
    """

    summary: NewsSummary
    to_detail: Callable[[], NewsDetail]
    project_link: dict[str, Any] | None


class NewsApi(Protocol):
    """Narrow, News-only Domain API port. NewsService depends on this
    Protocol, never on HttpxNewsApi concretely (enforced by the
    architecture-boundary test).

    `list_page` follows the same `(offset, page_size) -> (records, total)`
    shape `SprintApi`/`DocumentApi`/`ViewApi` use, letting `NewsService.list()`
    scan only as many server pages as needed via `scan_records_and_paginate`
    rather than walking the entire server collection before slicing out the
    requested `offset`/`limit` window.
    """

    async def list_page(
        self, *, offset: int, page_size: int, text_limit: int | None = None
    ) -> tuple[list[NewsRecord], int]: ...
    async def get(self, news_id: int, *, text_limit: int | None = None) -> NewsRecord: ...
    async def commit_create(self, payload: dict[str, Any]) -> NewsDetail: ...
    async def commit_update(self, news_id: int, payload: dict[str, Any]) -> NewsDetail: ...
    async def delete(self, news_id: int) -> None: ...
