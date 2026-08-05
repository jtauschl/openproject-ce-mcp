"""Relations Domain API port.

Full surface: fetch_page (raw HAL page, walked by
app.pagination.fetch_bounded_and_paginate for both list_relations and
get_work_package_relations) + to_record (raw payload -> RelationRecord,
called per raw element BEFORE the Service's allowlist filter) + get
(single relation, used by update()/delete()) + create + update + delete.

`fetch_page` returns the raw HAL page dict, not a list of records, because
`fetch_bounded_and_paginate`'s injected `fetch_page` callable needs the raw
`_embedded.elements` shape (including each element's raw `id` for its
seen-ids repeat-page guard) before any normalization happens.

`RelationRecord.summary` is a LAZY callable, matching `ReminderRecord`'s
precedent (see reminder_api.py's module docstring for the full rationale):
raw `_links.from`/`_links.to` links are filtered against the read allowlist
BEFORE ever normalizing a relation -- an eager `summary` field would
normalize (and potentially KeyError on) a relation the Service is about to
discard because one of its two linked work packages sits outside the read
allowlist.

`from_link`/`to_link` are carried as RAW link dicts (not pre-extracted
hrefs), because the Service's allowlist check needs the href off each one
directly -- a missing or malformed link must fail closed, distinguishable
from "link present but href absent."
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from ...models import RelationSummary


@dataclass(frozen=True)
class RelationRecord:
    summary: Callable[[], RelationSummary]
    from_link: dict[str, Any] | None
    to_link: dict[str, Any] | None


class RelationApi(Protocol):
    """Narrow, Relations-only Domain API port. RelationService depends on
    this Protocol, never on HttpxRelationApi concretely (enforced by the
    architecture-boundary test).
    """

    async def fetch_page(self, *, offset: int, page_size: int, filters: str | None) -> dict[str, Any]: ...
    def to_record(self, payload: dict[str, Any]) -> RelationRecord: ...
    async def get(self, relation_id: int) -> RelationRecord: ...
    async def create(self, work_package_ref: str, payload: dict[str, Any]) -> RelationRecord: ...
    async def update(self, relation_id: int, payload: dict[str, Any]) -> RelationRecord: ...
    async def delete(self, relation_id: int) -> None: ...
