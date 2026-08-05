"""Shared pagination-envelope helpers.

Package-root shared kernel: pure, dependency-free pagination math used by the
Versions domain (and available to any other app/ domain) without creating a
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
    server_page_size: int,
    offset: int,
    limit: int,
    item_allowed_bulk: Callable[[list[dict[str, Any]]], Awaitable[list[bool | Exception]]] | None = None,
) -> tuple[list[_T], int, int | None, bool]:
    """Scan server pages, normalize + filter the raw elements, and stop as
    soon as `limit + 1` allowed items are confirmed (or the collection is
    genuinely exhausted) -- never walks the full collection first.

    Originally a verbatim extraction of client.py's private
    `_fetch_bounded_and_paginate` (first extracted for the Relations
    migration), which walked EVERY server page to completion before ever
    slicing out the requested `offset`/`limit` window -- `offset`/`limit`
    then reduced neither server load nor response size. Rebuilt here
    (OPM-373 Phase 5) to early-stop instead, same shape as
    `scan_and_paginate`/`scan_records_and_paginate`: collect one extra
    (`limit + 1`) allowed item before deciding `truncated`, so "more
    matches exist" can be distinguished from "this happened to be the
    last one" without a false-positive `next_offset` promise.

    `post_filter` was removed (a Codex CLI review caught that TimeEntryService,
    this helper's other caller besides Relations, was the only user of it,
    and its post-filter predicates ran on already-normalized-but-not-yet-
    paginated results -- incompatible with early-stopping, since a
    normalized-but-later-rejected item must not count toward the `limit + 1`
    lookahead). TimeEntryService.list_all was migrated in the same change to
    fold its four post-filter predicates (work_package_id/user/spent_on_from/
    spent_on_to) into `item_allowed` itself, normalizing each raw item first
    -- the item_allowed callback now decides ALL acceptance criteria, not
    just the ACL check, matching every other `scan_*`-helper caller's shape.

    `item_allowed` is async (rather than plain bool) so ACL checks that need
    their own lookups (e.g. relations checking each linked work package's
    project) can use this helper too -- without it, callers needing an async
    filter had to hand-roll their own fetch+params, which is exactly how a
    prior pageSize-omission bug happened.

    Some project-scoped sub-collection endpoints (verified live: a project's
    versions endpoint) silently ignore both offset and pageSize and always
    return every element -- without the seen-ids check below, the
    short-page/limit-reached break conditions never trigger and this loops
    forever, re-fetching the same full page. Tracked against the RAW element
    ids (before item_allowed/normalize), so a page that's merely fully
    filtered out doesn't get mistaken for a repeat.

    `item_allowed_bulk` (OPM-379/F3) is a page-batching alternative to
    `item_allowed`: given ALL of a fetched page's raw elements at once, it
    resolves whatever concurrent I/O each element's allowlist decision needs
    (e.g. Relations' from/to hrefs) in one batch, before the sequential
    skip/limit+1-lookahead consumption loop below runs -- that loop is
    otherwise UNCHANGED, it just reads a pre-resolved `bool | Exception`
    outcome per element instead of awaiting `item_allowed(item)` one at a
    time. Exactly one of `item_allowed`/`item_allowed_bulk` may be given (or
    neither, for an unfiltered scan) -- callers that don't need concurrent
    per-item resolution keep using the simpler `item_allowed` path
    unchanged. Deliberately still resolves a whole PAGE at a time, never the
    whole call's collection -- resolving speculatively beyond the current
    page would defeat the early-stopping this helper exists for (see the
    module-level OPM-379 plan notes: collecting across the whole call would
    silently reintroduce the full-collection-scan bug OPM-373 Phase 5 fixed).

    An `Exception` outcome is only raised if the sequential consumption logic
    would actually have reached that element under the old one-at-a-time
    `item_allowed` control flow (i.e. skip-counted or considered for the
    limit+1 lookahead) -- an outcome for an element the loop breaks out of
    the page before reaching is silently discarded, matching what the old
    sequential logic would have done (it would never have awaited that
    element's check at all).
    """
    skip_count = (offset - 1) * limit
    skipped = 0
    results: list[_T] = []
    seen_ids: set[Any] = set()
    server_offset = 1
    is_first_page = True

    while len(results) <= limit:
        payload = await fetch_page(server_offset, server_page_size)
        raw_elements = [item for item in payload.get("_embedded", {}).get("elements", []) if isinstance(item, dict)]
        if not raw_elements:
            break
        page_ids = {item.get("id") for item in raw_elements}
        if not is_first_page and page_ids and page_ids <= seen_ids:
            break
        is_first_page = False
        seen_ids.update(page_ids)

        page_outcomes: list[bool | Exception] | None = None
        if item_allowed_bulk is not None:
            page_outcomes = await item_allowed_bulk(raw_elements)

        for index, item in enumerate(raw_elements):
            if page_outcomes is not None:
                outcome = page_outcomes[index]
                if isinstance(outcome, Exception):
                    raise outcome
                allowed = outcome
            elif item_allowed is not None:
                allowed = await item_allowed(item)
            else:
                allowed = True
            if not allowed:
                continue
            if skipped < skip_count:
                skipped += 1
                continue
            results.append(normalize(item))
            if len(results) > limit:
                # The (limit + 1)-th allowed item proves at least one more
                # match exists beyond the requested page -- stop
                # immediately, without checking the rest of this page or
                # server exhaustion. Any outcome for a later element in
                # page_outcomes (already resolved speculatively) is simply
                # never consulted here, so a deferred Exception past this
                # point is correctly never raised.
                break

        if len(results) > limit:
            break
        if len(raw_elements) < server_page_size:
            break
        server_offset += 1

    truncated = len(results) > limit
    if truncated:
        results = results[:limit]
    total = len(results)
    next_offset = offset + 1 if truncated else None
    return results, total, next_offset, truncated


async def scan_and_paginate(
    *,
    fetch_page: Callable[[int, int], Awaitable[dict[str, Any]]],
    item_allowed: Callable[[dict[str, Any]], Awaitable[bool]],
    server_page_size: int,
    offset: int,
    limit: int,
) -> tuple[list[dict[str, Any]], bool]:
    """Sibling of `fetch_bounded_and_paginate`/`scan_records_and_paginate`,
    for callers whose raw HAL page dict has no separate `normalize`/`total`
    concerns of its own (the caller normalizes the returned raw elements
    itself). All three helpers share the same early-stopping shape: scan
    just enough server pages to collect `limit + 1` allowed raw elements
    (one extra, to distinguish "more matches exist" from "this happened to
    be the last one") and stop, skipping the first `(offset - 1) * limit`
    already-seen matches along the way. Some redundant server calls on deep
    pagination (a fresh scan from page 1 on every call, since the two
    offset spaces -- caller units of `limit`, server units of
    `server_page_size` -- can't be conflated into one server-side offset),
    but bounded work per call instead of a full collection walk.

    Returns the raw (unnormalized) allowed elements for the requested page --
    callers normalize/apply any further post-normalize filtering themselves,
    since result and filter shapes differ per caller. Ported from client.py's
    `_scan_and_paginate` (release/0.3.6, OPM-373 Phase 5) -- same shape,
    generalized to accept `fetch_page` as an injected callable like
    `fetch_bounded_and_paginate` already does, instead of a hardwired path.
    """
    skip_count = (offset - 1) * limit
    skipped = 0
    results: list[dict[str, Any]] = []
    seen_ids: set[Any] = set()
    server_offset = 1
    is_first_page = True

    while len(results) <= limit:
        payload = await fetch_page(server_offset, server_page_size)
        raw_elements = [item for item in payload.get("_embedded", {}).get("elements", []) if isinstance(item, dict)]
        if not raw_elements:
            break
        # Same repeat-page guard as fetch_bounded_and_paginate/paginate_all:
        # some project-scoped sub-collection endpoints silently ignore
        # offset/pageSize and always return the same full page, which would
        # otherwise loop forever since `len(raw_elements) < server_page_size`
        # never becomes true.
        page_ids = {item.get("id") for item in raw_elements}
        if not is_first_page and page_ids and page_ids <= seen_ids:
            break
        is_first_page = False
        seen_ids.update(page_ids)

        for item in raw_elements:
            if not await item_allowed(item):
                continue
            if skipped < skip_count:
                skipped += 1
                continue
            results.append(item)
            if len(results) > limit:
                # The (limit + 1)-th allowed item proves at least one more
                # match exists beyond the requested page -- stop immediately,
                # without checking the rest of this page or server exhaustion.
                break

        if len(results) > limit:
            break
        if len(raw_elements) < server_page_size:
            break
        server_offset += 1

    truncated = len(results) > limit
    if truncated:
        results = results[:limit]
    return results, truncated


async def scan_records_and_paginate(
    fetch_page: Callable[[int, int], Awaitable[tuple[list[_T], int]]],
    *,
    item_allowed: Callable[[_T], bool],
    server_page_size: int,
    offset: int,
    limit: int,
    key: Callable[[_T], Any] | None = None,
) -> tuple[list[_T], bool]:
    """Early-stopping counterpart to `paginate_all`, for callers whose
    `fetch_page` already returns normalized records (not raw HAL dicts) --
    e.g. an Adapter's own `list_all(offset, page_size) -> (records, total)`
    method, the same signature `paginate_all` already accepts.

    Same early-stopping shape as `scan_and_paginate`/`fetch_bounded_and_paginate`
    (collects `limit + 1` allowed records before deciding `truncated`, to
    distinguish "more matches exist" from "this happened to be the last
    one"), adapted to `paginate_all`'s already-normalized-record contract
    instead of `fetch_bounded_and_paginate`'s raw-dict-plus-normalize-callback
    contract -- the two input shapes don't share one helper cleanly, hence
    three siblings rather than one.

    `item_allowed` here is SYNCHRONOUS (unlike `scan_and_paginate`'s async
    version) -- every `paginate_all` caller's own per-item filter
    (allowlist/search) already runs on normalized fields with no further
    I/O, so there's no async ACL lookup to support here the way Relations'
    cross-work-package check needs.

    Deliberately does NOT use the server-reported `total` from `fetch_page`'s
    return tuple as an exhaustion signal (an earlier draft did; a Codex CLI
    review caught the bug before commit): several adapters using this
    `(records, total)` contract fall back to `total = len(records)` when the
    server response has no `total` field at all (verified against
    `httpx_sprint_api.py`), which would make `server_offset *
    server_page_size >= total` true on the FIRST full page even when more
    pages genuinely exist -- silently truncating real results. Exhaustion is
    judged the same way `scan_and_paginate`/`_fetch_all_pages` already do:
    purely by `len(page_items) < server_page_size` (a short page) plus the
    repeat-page guard below, never by a reported total.
    """
    skip_count = (offset - 1) * limit
    skipped = 0
    results: list[_T] = []
    seen_keys: set[Any] = set()
    server_offset = 1
    is_first_page = True

    while len(results) <= limit:
        page_items, _total = await fetch_page(server_offset, server_page_size)
        if not page_items:
            break
        if key is not None:
            page_keys = {key(item) for item in page_items}
            if not is_first_page and page_keys and page_keys <= seen_keys:
                break
            seen_keys.update(page_keys)
        is_first_page = False

        for item in page_items:
            if not item_allowed(item):
                continue
            if skipped < skip_count:
                skipped += 1
                continue
            results.append(item)
            if len(results) > limit:
                break

        if len(results) > limit:
            break
        if len(page_items) < server_page_size:
            break
        server_offset += 1

    truncated = len(results) > limit
    if truncated:
        results = results[:limit]
    return results, truncated


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
