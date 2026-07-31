"""Work Packages Domain API port -- READ-only slice (ADR 0001).

Covers only the read paths of the Work Packages domain migration (list,
search, get, batch-get, list-my-open) -- write methods (commit_create,
commit_update, delete, form endpoints) are deliberately NOT declared here yet;
they belong to a later, separate write-path migration step and will extend
this same Protocol additively when that step lands.

Separate, parallel port from `app/ports/work_package_lookup_api.py`
(`WorkPackageLookupApi`) -- NOT an extension of it. `WorkPackageLookupApi` is
documented as deliberately minimal (two raw, unnormalized GET methods only),
built for `WorkPackageResolver`'s reference-resolution needs and consumed by
eight already-migrated domains via the `WorkPackageIdResolver`/
`WorkPackageProjectAllowedCheck` seams in `app/ports/work_package_ref.py`.
Those contracts must not change. `HttpxWorkPackageApi` (the adapter for this
port) does not delegate to `HttpxWorkPackageLookupApi` internally -- both are
independent, thin HTTP translators over the same `work_packages/{id}`
endpoint, deliberately duplicated per ADR 0001's "a small amount of
deliberate duplication... rather than an import from the new layer back"
principle (here applied between two same-domain adapters rather than between
an adapter and client.py, but for the identical reason: neither should wrap
the other as an implementation detail). `WorkPackageResolver` itself stays
unchanged, bound to `WorkPackageLookupApi` as it always has been --
`WorkPackageService` becomes a ninth consumer of the SAME resolver via the
existing `WorkPackageProjectAllowedCheck` seam for hierarchy-allowlist
filtering, not a reason to touch the resolver.

Unlike `ProjectApi`, `list()` returns RAW HAL element payloads plus a
pre-computed `raw_element_count`, not pre-normalized `WorkPackageRecord`s.
This is a deliberate divergence from the `ProjectApi`/`HttpxProjectApi`
shape: `client.py`'s original `_build_work_package_list_result` filters raw
elements against the read allowlist FIRST, and only normalizes the elements
that survive that filter -- normalizing every raw element unconditionally
(as `ProjectApi.list()` does) would (a) do wasted normalization work for
items the caller can never see, and (b) let a malformed/unexpected field on
an out-of-scope work package raise during normalization before the allowlist
filter ever gets a chance to drop it. Allowlist filtering is a Service/Policy
concern (per ADR 0001, the Adapter stays a dumb HTTP translator with no
authorization logic of its own); the Service normalizes only the elements
that pass `work_package_payload_allowed`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from ...models import SortCriterion, WorkPackageDetail, WorkPackageSummary


@dataclass(frozen=True)
class WorkPackagePage:
    raw_elements: list[dict[str, Any]]  # UNFILTERED, UNNORMALIZED raw HAL elements
    server_total: int | None


@dataclass(frozen=True)
class WorkPackageRecord:
    summary: WorkPackageSummary
    to_detail: Callable[[], WorkPackageDetail]  # LAZY -- list()/search() never read this
    payload: dict[str, Any]  # raw HAL payload, _links included (allowlist checks,
    # hierarchy-allowlist filtering need the raw children/ancestors links)


class WorkPackageApi(Protocol):
    async def list(
        self,
        *,
        filters: list[dict[str, Any]],
        offset: int,
        limit: int,
        sort_by: list[SortCriterion] | None,
        group_by: str | None,
    ) -> WorkPackagePage: ...

    def to_record(self, payload: dict[str, Any], *, text_limit: int | None) -> WorkPackageRecord:
        """Normalize one already-allowlist-checked raw element (from a
        `WorkPackagePage.raw_elements` entry, or a single `get()` payload)
        into a `WorkPackageRecord`. Pure, synchronous, no I/O -- exists as a
        Protocol method (not a module-level function) so the Service depends
        only on the `WorkPackageApi` Protocol, never importing the concrete
        adapter's `normalize_work_package_summary`/`_detail` functions
        directly (would violate the Service->Port-only dependency rule).
        """
        ...

    async def get(self, work_package_ref: str, *, text_limit: int | None = None) -> WorkPackageRecord: ...
