"""Work Packages Domain API port -- covers the full domain (ADR 0001).

Originally read-only (list, search, get, batch-get, list-my-open); this
Protocol was extended additively with the write-path methods (validate_create,
validate_update, parse_form, commit_create, commit_update, delete,
post_comment) once the write-path migration (OPM-286's second sub-step)
landed, per the original module docstring's own stated plan.

The two form-validation endpoints mirror the flat code's two distinct probe
sites exactly: `validate_create` POSTs `projects/{project_id}/work_packages/form`
(used by both `create()` and `create_subtask()` -- both need the
project-scoped form), `validate_update` POSTs `work_packages/{ref}/form` (used
by `update()`, including a possible SECOND call with a mutated payload for the
auto-percentage/auto-remaining-time derivation). Both return the RAW HAL form
response dict, UNPARSED -- unlike Time Entries' `TimeEntryFormResult` (which
separates parsing from validation), Work Packages needs the raw `schema`
sub-object too (for schema-backed field/custom-field option resolution and the
auto-derivation's writable/hidden checks), not just `payload`/`validationErrors`.
`parse_form()` is a separate, pure, synchronous Protocol method that unwraps
`_embedded.payload`/`.validationErrors`/`.schema` into one `WorkPackageFormResult`
so the Service never touches `_embedded` directly -- there can be UP TO THREE
distinct `/form` POSTs in one `update()` call (an embedded schema probe fired
from inside payload-building whenever a schema-backed field is used, the real
full-payload validation call, and a possible second validation call for the
auto-derivation pass), and `parse_form` is called on each of their raw
responses independently.

Schema-option-resolution logic (matching a caller-supplied id-or-name against
`schema[key]._embedded.allowedValues`, resolving custom-field keys) is
deliberately NOT part of this Port -- it is pure, no-I/O matching logic over
an already-fetched schema dict, and lives in `WorkPackageService` instead
(mirrors `TimeEntryService._resolve_activity_id`'s equivalent shape). No
dedicated Resolver class is warranted either: this matching is 100% local to
one domain's write-payload construction, unlike a Resolver's job of serving
reference resolution reused across multiple domains.

Comment-posting/normalization deliberately reuses the EXISTING, already-migrated
`ActivityApi`/`HttpxActivityApi` (injected separately into `WorkPackageService`)
rather than duplicating activity normalization onto this Port -- `post_comment`
below only posts the raw activity; `ActivityApi` handles turning the response
into a normalized `ActivitySummary` and the `_fill_missing_activity_user`
fallback's raw single-activity fetch.

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


@dataclass(frozen=True)
class WorkPackageFormResult:
    payload: dict[str, Any]
    validation_errors: dict[str, str]
    schema: dict[str, Any]  # raw _embedded.schema -- needed by the Service's schema-option
    # resolution AND the auto-percentage/remaining-time schema check


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

    async def validate_create(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST `projects/{project_id}/work_packages/form`. Returns the raw HAL
        form response, unparsed -- callers pass it to `parse_form`."""
        ...

    async def validate_update(self, work_package_ref: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST `work_packages/{work_package_ref}/form`. Returns the raw HAL
        form response, unparsed -- callers pass it to `parse_form`. Called
        once for the real validation pass, and again (with a mutated payload)
        for the auto-percentage/auto-remaining-time re-validation when it
        applies -- side-effect-free, safe to call more than once."""
        ...

    def parse_form(self, form: dict[str, Any]) -> WorkPackageFormResult:
        """Pure, synchronous unwrap of `_embedded.payload`/`.validationErrors`/
        `.schema` from a raw form response returned by `validate_create`/
        `validate_update`."""
        ...

    async def commit_create(self, payload: dict[str, Any], *, text_limit: int | None) -> WorkPackageRecord:
        """POST `work_packages` (the real create). `text_limit` is caller-supplied
        (the Service passes `FORMATTABLE_LIMIT`, matching the flat write
        normalizer's default for create/update responses -- NOT the uncapped
        default `get()` uses for its own single-item path)."""
        ...

    async def commit_update(
        self, work_package_ref: str, payload: dict[str, Any], *, text_limit: int | None
    ) -> WorkPackageRecord:
        """PATCH `work_packages/{work_package_ref}` (the real update)."""
        ...

    async def delete(self, work_package_ref: str) -> None:
        """DELETE `work_packages/{work_package_ref}`."""
        ...

    async def post_comment(
        self, work_package_ref: str, *, comment: str, internal: bool, notify: bool
    ) -> dict[str, Any]:
        """POST `work_packages/{work_package_ref}/activities`. Returns the raw,
        unnormalized activity payload -- the Service normalizes it via the
        separately-injected `ActivityApi`, not this Port."""
        ...
