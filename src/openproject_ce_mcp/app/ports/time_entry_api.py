"""Time Entries Domain API port (ADR 0001).

`fetch_page` returns the raw HAL page dict (not records), matching
`RelationApi`'s precedent -- `fetch_bounded_and_paginate`'s `item_allowed`
callable filters the raw `_links.project` link directly (see
`_time_entry_payload_allowed`/`_link_matches_project_refs` in the
pre-migration client.py), so no `to_record()` call is needed before
filtering here: unlike Relations, the filter-relevant link is already
present on the raw payload, with no lazy-normalization-avoidance rationale
requiring an intermediate record. `to_record()`/`normalize` is only called
for elements that already survived the filter.

`get_raw` returns the raw HAL payload (not a record) for the same reason:
`get_time_entry`/`update_time_entry`/`delete_time_entry` all read
`payload.get("_links", {}).get("project")` directly off the raw fetch,
BEFORE any normalization, to run their allowlist check -- normalizing first
would be wasted work for a time entry the caller isn't allowed to see, and
would require re-deriving the link from an already-normalized summary.

`validate_create`/`validate_update` return OpenProject's raw CreateFormAPI/
UpdateFormAPI response (`_embedded.payload`/`validationErrors`), evaluated
inline by the Service's own preview/commit branching -- NOT by the
`client.py`-private `_finalize_write`, which remains in place for Work
Packages/Attachments (see the migration plan's finalizer discussion). Time
Entries is the first domain-specific Service to inline this 3-way branching
itself rather than sharing a generic wrapper.

`fetch_activities_for_entity` must let transport/permission/not-found
errors propagate normally -- it has two call contexts with different error
handling (`TimeEntryService.list_activities()`'s best-effort per-project
fallback catches `NotFoundError`/`PermissionDeniedError`/
`OpenProjectServerError` and skips to the next project; `_resolve_activity_id`'s
call during create/update does NOT catch these, since a real server/permission
error there must surface, not be silently swallowed into a misleading
"activity not found" error). `fetch_activities` (the global endpoint) is the
only caller for its OWN failure signal and may return `None` on the same
three error types -- this asymmetry is deliberate, not an inconsistency.

Services may not import `app/adapters/` directly (see
`tests/test_architecture_boundaries.py`'s layer-dependency rules), so every
adapter-side normalize function this Service needs is reached only through
this Protocol -- `to_record`/`to_activity_record` for HAL payloads,
`parse_form_result` for a validated create/update form's payload +
validation-errors extraction (mirrors `client.py`'s module-level
`_normalize_validation_errors`, ported verbatim into the adapter, never
imported by the Service directly).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from ...models import TimeEntryActivitySummary, TimeEntrySummary


@dataclass(frozen=True)
class TimeEntryRecord:
    summary: Callable[[], TimeEntrySummary]


@dataclass(frozen=True)
class TimeEntryActivityRecord:
    summary: TimeEntryActivitySummary


@dataclass(frozen=True)
class TimeEntryFormResult:
    payload: dict[str, Any]
    validation_errors: dict[str, str]


class TimeEntryApi(Protocol):
    """Narrow, Time-Entries-only Domain API port. TimeEntryService depends on
    this Protocol, never on HttpxTimeEntryApi concretely (enforced by the
    architecture-boundary test).
    """

    async def fetch_page(self, *, offset: int, page_size: int) -> dict[str, Any]: ...
    def to_record(self, payload: dict[str, Any], *, text_limit: int | None) -> TimeEntryRecord: ...
    def to_activity_record(self, payload: dict[str, Any]) -> TimeEntryActivityRecord: ...
    def parse_form_result(self, form: dict[str, Any]) -> TimeEntryFormResult: ...
    def project_link_title_and_id(self, link: Any) -> tuple[str | None, int | None]: ...
    async def get_raw(self, time_entry_id: int) -> dict[str, Any]: ...
    async def validate_create(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    async def validate_update(self, time_entry_id: int, payload: dict[str, Any]) -> dict[str, Any]: ...
    async def create(self, payload: dict[str, Any]) -> TimeEntryRecord: ...
    async def update(self, time_entry_id: int, payload: dict[str, Any]) -> TimeEntryRecord: ...
    async def delete(self, time_entry_id: int) -> None: ...
    async def fetch_activities(self) -> dict[str, Any] | None: ...
    async def fetch_activities_for_entity(self, *, project_id: int, work_package_id: int | None) -> dict[str, Any]: ...
