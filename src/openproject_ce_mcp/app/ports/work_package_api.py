"""Work Packages Domain API port -- covers the full domain.

The Protocol covers both the read path (list, search, get, batch-get,
list-my-open) and the write path (validate_create, validate_update,
parse_form, commit_create, commit_update, delete, post_comment).

The two form-validation endpoints mirror two distinct validation sites:
`validate_create` POSTs `projects/{project_id}/work_packages/form`
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
reference resolution reused across multiple domains. The ONE piece of I/O
this purity depends on -- dereferencing a field's linked-only `allowedValues`
(unbounded candidate sets, e.g. any `User`-typed field, never embed the list)
-- is done by `parse_form(form, resolve_links=True)` in the Adapter, BEFORE
the schema reaches the Service, so `_embedded.allowedValues` is always
populated by the time the Service's matching logic sees it. Same shape as
`ProjectApi.list_available_parent_projects` dereferencing the `parent`
field's link. `resolve_links` defaults to False and most `parse_form` call
sites never pass True -- see that method's own docstring for why only the
dedicated schema probe needs the dereferenced form.

Comment-posting/normalization deliberately reuses the EXISTING
`ActivityApi`/`HttpxActivityApi` (injected separately into `WorkPackageService`)
rather than duplicating activity normalization onto this Port -- `post_comment`
below only posts the raw activity; `ActivityApi` handles turning the response
into a normalized `ActivitySummary` and the `_fill_missing_activity_user`
fallback's raw single-activity fetch.

Separate, parallel port from `app/ports/work_package_lookup_api.py`
(`WorkPackageLookupApi`) -- NOT an extension of it. `WorkPackageLookupApi` is
documented as deliberately minimal (two raw, unnormalized GET methods only),
built for `WorkPackageResolver`'s reference-resolution needs and consumed by
several other app/ domains via the `WorkPackageIdResolver`/
`WorkPackageProjectAllowedCheck` seams in `app/ports/work_package_ref.py`.
Those contracts must not change. `HttpxWorkPackageApi` (the adapter for this
port) does not delegate to `HttpxWorkPackageLookupApi` internally -- both are
independent, thin HTTP translators over the same `work_packages/{id}`
endpoint, deliberately duplicated: neither should wrap the other as an
implementation detail, so a future change to one cannot silently change the
other's contract. `WorkPackageResolver` stays bound to `WorkPackageLookupApi`;
`WorkPackageService` is a separate consumer of the same resolver via the
existing `WorkPackageProjectAllowedCheck` seam for hierarchy-allowlist
filtering, not a reason to merge the two ports.

Unlike `ProjectApi`, `list()` returns RAW HAL element payloads plus a
pre-computed `raw_element_count`, not pre-normalized `WorkPackageRecord`s.
Raw elements are filtered against the read allowlist FIRST, and only the
elements that survive that filter are normalized afterward -- never the
reverse. Normalizing every raw element unconditionally (as `ProjectApi.list()`
does) would (a) do wasted normalization work for items the caller can never
see, and (b) let a malformed/unexpected field on an out-of-scope work package
raise during normalization before the allowlist filter ever gets a chance to
drop it -- a normalization crash on data the caller was never authorized to
see. Allowlist filtering is a Service/Policy concern (the Adapter stays a
dumb HTTP translator with no authorization logic of its own); the Service
normalizes only the elements that pass `work_package_payload_allowed`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from ...models import SortCriterion, WorkPackageDetail, WorkPackageSummary
from .project_resolution import WorkPackageResolutionContext


@dataclass(frozen=True)
class WorkPackagePage:
    raw_elements: list[dict[str, Any]]  # UNFILTERED, UNNORMALIZED raw HAL elements
    server_total: int | None
    raw_groups: list[dict[str, Any]] | None = None  # top-level `groups`, only when include_sums requested
    raw_total_sums: dict[str, Any] | None = None  # top-level `totalSums`, only when include_sums requested


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
        include_sums: bool = False,
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

    async def parse_form(
        self,
        form: dict[str, Any],
        *,
        resolve_links: bool = False,
        allowed_values_cache: WorkPackageResolutionContext | None = None,
    ) -> WorkPackageFormResult:
        """Unwrap of `_embedded.payload`/`.validationErrors`/`.schema` from a
        raw form response returned by `validate_create`/`validate_update`.
        Async because, when `resolve_links=True`, a schema field with an
        unbounded candidate set (e.g. a `User`-typed field) is dereferenced
        from `_links.allowedValues.href` into `_embedded.allowedValues` here
        -- see the module docstring's "Schema-option-resolution" note: this
        I/O is the adapter's job so the Service's matching logic can stay
        pure and always see an embedded list.

        `resolve_links` defaults to False: `update()`'s auto-percentage/
        auto-remaining-time probe and every call site's final parse only
        ever read `.payload`/`.validationErrors`, or `.schema` for `writable`
        flags -- never `allowedValues` -- so dereferencing there would be
        pure waste. Only `_get_write_schema`'s dedicated schema probe (the
        one call site that resolves `responsible`/`priority`/`category`/
        `project_phase`/custom-field options) passes `resolve_links=True`.
        Never mutates the input `form`'s schema in place -- returns a new
        schema dict, so a caller holding a reference to the original `form`
        sees it unchanged.

        `allowed_values_cache`, when given (a bulk_create/bulk_update batch's
        shared `wp_context`), is consulted/populated per dereferenced href
        instead of always dispatching the GET -- see
        `WorkPackageResolutionContext.get_allowed_values`'s docstring for why
        caching by href (not by project/field) is the safe granularity."""
        ...

    async def commit_create(self, payload: dict[str, Any], *, text_limit: int | None) -> WorkPackageRecord:
        """POST `work_packages` (the real create). `text_limit` is caller-supplied
        (the Service passes `FORMATTABLE_LIMIT` for create/update responses --
        NOT the uncapped default `get()` uses for its own single-item path)."""
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
