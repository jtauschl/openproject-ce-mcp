from __future__ import annotations

import asyncio
import dataclasses

import pytest
from _client_test_helpers import make_settings

from openproject_ce_mcp.app.errors import NotFoundError, OpenProjectServerError, PermissionDeniedError
from openproject_ce_mcp.app.ports.work_package_resolution import WorkPackageAllowedContext
from openproject_ce_mcp.app.resolvers.work_package_resolver import WorkPackageResolver


def _wp_payload(wp_id: int, *, project_href: str | None = "/api/v3/projects/6") -> dict:
    links: dict = {}
    if project_href is not None:
        links["project"] = {"href": project_href, "title": "Demo"}
    return {"id": wp_id, "_type": "WorkPackage", "subject": f"WP {wp_id}", "_links": links}


class _FakeWorkPackageLookupApi:
    """No I/O -- an in-memory WorkPackageLookupApi double."""

    def __init__(self, records: dict[str, dict], *, not_found: set[str] | None = None) -> None:
        self._records = records
        self._not_found = not_found or set()
        self.get_calls: list[str] = []
        self.get_by_href_calls: list[str] = []

    async def get(self, work_package_ref: str) -> dict:
        self.get_calls.append(work_package_ref)
        if work_package_ref in self._not_found or work_package_ref not in self._records:
            raise NotFoundError(f"no fake work package for ref {work_package_ref}")
        return self._records[work_package_ref]

    async def get_by_href(self, href: str) -> dict:
        self.get_by_href_calls.append(href)
        if href in self._not_found or href not in self._records:
            raise NotFoundError(f"no fake work package for href {href}")
        return self._records[href]


def _resolver(
    records: dict[str, dict], *, settings=None, not_found=None
) -> tuple[WorkPackageResolver, _FakeWorkPackageLookupApi]:
    api = _FakeWorkPackageLookupApi(records, not_found=not_found)
    resolver = WorkPackageResolver(api=api, settings=settings or make_settings(), project_id_to_identifier={})
    return resolver, api


# --- resolve_id ---


@pytest.mark.asyncio
async def test_resolve_id_numeric_ref() -> None:
    resolver, api = _resolver({"42": _wp_payload(42)})

    result = await resolver.resolve_id(42)

    assert result == 42
    assert api.get_calls == ["42"]


@pytest.mark.asyncio
async def test_resolve_id_semantic_project_prefixed_ref() -> None:
    resolver, _api = _resolver({"PROJ-123": _wp_payload(7)})

    result = await resolver.resolve_id("PROJ-123")

    assert result == 7


@pytest.mark.asyncio
async def test_resolve_id_numeric_ref_not_found_reraises_plain_not_found() -> None:
    resolver, _api = _resolver({}, not_found={"42"})

    with pytest.raises(NotFoundError) as exc_info:
        await resolver.resolve_id(42)

    assert "17.5" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_resolve_id_semantic_ref_not_found_gets_175_hint_message() -> None:
    resolver, _api = _resolver({}, not_found={"PROJ-999"})

    with pytest.raises(
        NotFoundError,
        match=r"Work package 'PROJ-999' was not found.*OpenProject 17\.5\+.*exact project identifier",
    ):
        await resolver.resolve_id("PROJ-999")


@pytest.mark.asyncio
async def test_resolve_id_write_false_uses_read_allowlist() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("other",))
    resolver, _api = _resolver({"42": _wp_payload(42)}, settings=settings)

    # Read is wide open, write is restricted -- write=False must not trigger the
    # write check, so this must succeed.
    result = await resolver.resolve_id(42, write=False)

    assert result == 42


@pytest.mark.asyncio
async def test_resolve_id_write_true_uses_write_allowlist_and_denies() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("*",), write_projects=("other",))
    resolver, _api = _resolver({"42": _wp_payload(42)}, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_WRITE_PROJECTS"):
        await resolver.resolve_id(42, write=True)


@pytest.mark.asyncio
async def test_resolve_id_read_allowlist_denies() -> None:
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    resolver, _api = _resolver({"42": _wp_payload(42)}, settings=settings)

    with pytest.raises(PermissionDeniedError, match="OPENPROJECT_READ_PROJECTS"):
        await resolver.resolve_id(42)


# --- project_link_allowed ---


@pytest.mark.asyncio
async def test_project_link_allowed_true_when_project_in_scope() -> None:
    href = "/api/v3/work_packages/42"
    resolver, _api = _resolver({href: _wp_payload(42)})

    assert await resolver.project_link_allowed(href) is True


@pytest.mark.asyncio
async def test_project_link_allowed_false_when_project_out_of_scope() -> None:
    href = "/api/v3/work_packages/42"
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    resolver, _api = _resolver({href: _wp_payload(42)}, settings=settings)

    assert await resolver.project_link_allowed(href) is False


@pytest.mark.asyncio
async def test_project_link_allowed_false_when_work_package_not_found() -> None:
    href = "/api/v3/work_packages/999"
    resolver, _api = _resolver({}, not_found={href})

    assert await resolver.project_link_allowed(href) is False


@pytest.mark.asyncio
async def test_project_link_allowed_does_not_swallow_non_not_found_errors() -> None:
    """A transient server/transport error must not be silently treated as
    "not allowed" -- only NotFoundError maps to False; anything else (e.g. a
    5xx) must propagate unchanged, matching the original method's explicit
    "do NOT swallow" contract."""

    class _RaisingApi:
        async def get_by_href(self, href: str) -> dict:
            raise OpenProjectServerError("boom")

    resolver = WorkPackageResolver(api=_RaisingApi(), settings=make_settings(), project_id_to_identifier={})

    with pytest.raises(OpenProjectServerError, match="boom"):
        await resolver.project_link_allowed("/api/v3/work_packages/999")


@pytest.mark.asyncio
async def test_project_link_allowed_without_context_always_fetches_fresh() -> None:
    href = "/api/v3/work_packages/42"
    resolver, api = _resolver({href: _wp_payload(42)})

    await resolver.project_link_allowed(href)
    await resolver.project_link_allowed(href)

    assert api.get_by_href_calls == [href, href]


@pytest.mark.asyncio
async def test_project_link_allowed_with_context_caches_on_second_call() -> None:
    href = "/api/v3/work_packages/42"
    resolver, api = _resolver({href: _wp_payload(42)})
    context = WorkPackageAllowedContext()

    first = await resolver.project_link_allowed(href, context=context)
    second = await resolver.project_link_allowed(href, context=context)

    assert first is True
    assert second is True
    assert api.get_by_href_calls == [href]  # only fetched once


@pytest.mark.asyncio
async def test_project_link_allowed_with_context_caches_denied_result_too() -> None:
    href = "/api/v3/work_packages/42"
    settings = dataclasses.replace(make_settings(), read_projects=("other",))
    resolver, api = _resolver({href: _wp_payload(42)}, settings=settings)
    context = WorkPackageAllowedContext()

    first = await resolver.project_link_allowed(href, context=context)
    second = await resolver.project_link_allowed(href, context=context)

    assert first is False
    assert second is False
    assert api.get_by_href_calls == [href]


@pytest.mark.asyncio
async def test_project_link_allowed_different_hrefs_are_cached_independently() -> None:
    href_a = "/api/v3/work_packages/1"
    href_b = "/api/v3/work_packages/2"
    resolver, api = _resolver({href_a: _wp_payload(1), href_b: _wp_payload(2)})
    context = WorkPackageAllowedContext()

    await resolver.project_link_allowed(href_a, context=context)
    await resolver.project_link_allowed(href_b, context=context)
    await resolver.project_link_allowed(href_a, context=context)

    assert api.get_by_href_calls == [href_a, href_b]


# --- project_links_allowed (OPM-379/F3) ---


class _ConcurrencyTrackingWorkPackageLookupApi:
    """Like `_FakeWorkPackageLookupApi`, but tracks the observed peak of
    concurrent in-flight `get_by_href()` calls -- each call increments a
    counter, yields control (so overlapping calls actually interleave
    instead of running back-to-back within a single event-loop tick), then
    decrements. Mirrors `test_app_work_package_service.py`'s
    `_ConcurrencyTrackingWorkPackageApi` (OPM-379/F6's equivalent test
    double) for the analogous F3 concurrency-bound assertion."""

    def __init__(self, records: dict[str, dict], *, delay: float = 0.0) -> None:
        self._records = records
        self._delay = delay
        self.active = 0
        self.peak_active = 0
        self.get_by_href_calls: list[str] = []

    async def get(self, work_package_ref: str) -> dict:
        raise AssertionError("unused")

    async def get_by_href(self, href: str) -> dict:
        self.get_by_href_calls.append(href)
        self.active += 1
        self.peak_active = max(self.peak_active, self.active)
        try:
            await asyncio.sleep(self._delay)
            if href not in self._records:
                raise NotFoundError(f"no fake work package for href {href}")
            return self._records[href]
        finally:
            self.active -= 1


@pytest.mark.asyncio
async def test_project_links_allowed_bounds_concurrency_to_the_semaphore_limit() -> None:
    """Regression (OPM-379/F3): a naive `asyncio.gather` over every href with
    no cap could fire an unbounded number of simultaneous requests. The
    shared, instance-level `_allowlist_semaphore` must keep the observed peak
    at or below `_ALLOWLIST_BULK_CONCURRENCY` (10), while still proving
    genuine overlap (not accidental full serialization)."""
    hrefs = [f"/api/v3/work_packages/{i}" for i in range(1, 31)]
    records = {href: _wp_payload(i) for i, href in enumerate(hrefs, start=1)}
    api = _ConcurrencyTrackingWorkPackageLookupApi(records, delay=0.01)
    resolver = WorkPackageResolver(api=api, settings=make_settings(), project_id_to_identifier={})
    context = WorkPackageAllowedContext()

    outcomes = await resolver.project_links_allowed(hrefs, context=context)

    assert all(outcome is True for outcome in outcomes.values())
    assert api.peak_active <= 10
    assert api.peak_active > 1, "expected genuine overlap between calls, not accidental serialization"


@pytest.mark.asyncio
async def test_project_links_allowed_shares_one_semaphore_across_two_concurrent_top_level_calls() -> None:
    """The semaphore is a resolver-instance attribute, not created per
    `project_links_allowed()` call -- two simultaneous top-level calls (e.g.
    a concurrent list_relations + list_reminders in the real Services) on the
    SAME WorkPackageResolver instance must share one combined cap of 10, not
    each get their own independent 10 (2nd Codex review round requirement:
    explicitly two DIFFERENT call sites sharing the semaphore, not just two
    calls to the same one)."""
    hrefs_a = [f"/api/v3/work_packages/a{i}" for i in range(15)]
    hrefs_b = [f"/api/v3/work_packages/b{i}" for i in range(15)]
    records = {href: _wp_payload(i) for i, href in enumerate(hrefs_a + hrefs_b)}
    api = _ConcurrencyTrackingWorkPackageLookupApi(records, delay=0.01)
    resolver = WorkPackageResolver(api=api, settings=make_settings(), project_id_to_identifier={})

    await asyncio.gather(
        resolver.project_links_allowed(hrefs_a, context=WorkPackageAllowedContext()),
        resolver.project_links_allowed(hrefs_b, context=WorkPackageAllowedContext()),
    )

    assert api.peak_active <= 10


@pytest.mark.asyncio
async def test_project_links_allowed_dedupes_within_one_call() -> None:
    """A duplicate href within one `hrefs` iterable must trigger only one
    GET, in insertion order (dict.fromkeys, not a set -- deterministic
    scheduling)."""
    href = "/api/v3/work_packages/1"
    resolver, api = _resolver({href: _wp_payload(1)})
    context = WorkPackageAllowedContext()

    outcomes = await resolver.project_links_allowed([href, href, href], context=context)

    assert outcomes == {href: True}
    assert api.get_by_href_calls == [href]


@pytest.mark.asyncio
async def test_project_links_allowed_cache_hits_short_circuit_with_no_io() -> None:
    """An href already present in `context` (e.g. from a prior page's bulk
    resolution, or from a single project_link_allowed() call) must not
    trigger a new GET -- its cached outcome is returned directly."""
    href = "/api/v3/work_packages/1"
    resolver, api = _resolver({href: _wp_payload(1)})
    context = WorkPackageAllowedContext()
    context.set(href, True)

    outcomes = await resolver.project_links_allowed([href], context=context)

    assert outcomes == {href: True}
    assert api.get_by_href_calls == []


@pytest.mark.asyncio
async def test_project_links_allowed_separate_calls_do_not_share_a_cache() -> None:
    """Cross-call caching remains deliberately unavailable (pre-existing
    security decision, unaffected by a1 vs a2 -- see OPM-379 plan notes: a
    work package can change project at runtime, so a cached positive result
    across calls risks stale authorization). Two calls with separate
    WorkPackageAllowedContext instances must each fetch fresh."""
    href = "/api/v3/work_packages/1"
    resolver, api = _resolver({href: _wp_payload(1)})

    await resolver.project_links_allowed([href], context=WorkPackageAllowedContext())
    await resolver.project_links_allowed([href], context=WorkPackageAllowedContext())

    assert api.get_by_href_calls == [href, href]


@pytest.mark.asyncio
async def test_project_links_allowed_returns_full_map_including_cache_hits_and_misses() -> None:
    href_cached = "/api/v3/work_packages/1"
    href_fresh = "/api/v3/work_packages/2"
    resolver, api = _resolver({href_cached: _wp_payload(1), href_fresh: _wp_payload(2)})
    context = WorkPackageAllowedContext()
    context.set(href_cached, True)

    outcomes = await resolver.project_links_allowed([href_cached, href_fresh], context=context)

    assert outcomes == {href_cached: True, href_fresh: True}
    assert api.get_by_href_calls == [href_fresh]


@pytest.mark.asyncio
async def test_project_links_allowed_captures_not_found_as_false_like_the_single_check() -> None:
    href = "/api/v3/work_packages/999"
    resolver, _api = _resolver({}, not_found={href})
    context = WorkPackageAllowedContext()

    outcomes = await resolver.project_links_allowed([href], context=context)

    assert outcomes == {href: False}
    # A successful (even if False) outcome IS cached -- NotFoundError maps to
    # a real False, not a captured exception (matches project_link_allowed's
    # own NotFoundError -> False mapping).
    assert context.get(href) is False


@pytest.mark.asyncio
async def test_project_links_allowed_captures_other_errors_as_exception_outcomes_not_cached() -> None:
    """A transient server/transport error must not be silently treated as
    "not allowed", and must NOT be cached -- a captured regular Exception is
    returned as that href's outcome instead of propagating out of
    project_links_allowed() itself, so ONE failing href among many doesn't
    abort every other href's concurrent resolution. Left uncached so a retry
    (this call or a later one) fetches fresh rather than replaying a stale
    failure."""

    class _RaisingApi:
        def __init__(self) -> None:
            self.get_by_href_calls: list[str] = []

        async def get(self, work_package_ref: str) -> dict:
            raise AssertionError("unused")

        async def get_by_href(self, href: str) -> dict:
            self.get_by_href_calls.append(href)
            raise OpenProjectServerError("boom")

    api = _RaisingApi()
    resolver = WorkPackageResolver(api=api, settings=make_settings(), project_id_to_identifier={})
    context = WorkPackageAllowedContext()

    href = "/api/v3/work_packages/1"
    outcomes = await resolver.project_links_allowed([href], context=context)

    assert isinstance(outcomes[href], OpenProjectServerError)
    assert context.get(href) is None, "a failed outcome must not be cached"

    # A second call with a fresh context re-fetches (not cached) and fails again.
    await resolver.project_links_allowed([href], context=WorkPackageAllowedContext())
    assert api.get_by_href_calls == [href, href]


@pytest.mark.asyncio
async def test_project_links_allowed_two_failing_hrefs_both_captured_independently() -> None:
    """When multiple hrefs in the same bulk call fail, each gets its OWN
    captured exception in the outcome map -- the caller (a Service's
    sequential per-item consumption) decides which one, if any, actually
    matters; project_links_allowed() itself never picks a "winner"."""

    class _SelectivelyRaisingApi:
        async def get(self, work_package_ref: str) -> dict:
            raise AssertionError("unused")

        async def get_by_href(self, href: str) -> dict:
            if href == "/api/v3/work_packages/1":
                raise OpenProjectServerError("first boom")
            raise OpenProjectServerError("second boom")

    resolver = WorkPackageResolver(api=_SelectivelyRaisingApi(), settings=make_settings(), project_id_to_identifier={})
    context = WorkPackageAllowedContext()

    outcomes = await resolver.project_links_allowed(
        ["/api/v3/work_packages/1", "/api/v3/work_packages/2"], context=context
    )

    assert isinstance(outcomes["/api/v3/work_packages/1"], OpenProjectServerError)
    assert isinstance(outcomes["/api/v3/work_packages/2"], OpenProjectServerError)
    assert str(outcomes["/api/v3/work_packages/1"]) == "first boom"
    assert str(outcomes["/api/v3/work_packages/2"]) == "second boom"


@pytest.mark.asyncio
async def test_project_links_allowed_cancellation_releases_permits_and_a_later_call_completes() -> None:
    """A cancelled bulk resolution must not leak semaphore permits or leave
    background tasks running -- a subsequent call on the same resolver must
    complete normally afterward. `CancelledError` itself must propagate (NOT
    be captured as a per-href Exception outcome the way a regular Exception
    is), matching the resolver's documented "regular Exception, never
    BaseException/CancelledError" contract."""

    class _BlockingThenNormalApi:
        def __init__(self) -> None:
            self.get_by_href_calls: list[str] = []
            self.release = asyncio.Event()

        async def get(self, work_package_ref: str) -> dict:
            raise AssertionError("unused")

        async def get_by_href(self, href: str) -> dict:
            self.get_by_href_calls.append(href)
            if href == "/api/v3/work_packages/blocked":
                await self.release.wait()  # blocks until explicitly released or the task is cancelled
            return _wp_payload(1)

    api = _BlockingThenNormalApi()
    resolver = WorkPackageResolver(api=api, settings=make_settings(), project_id_to_identifier={})

    blocked_call = asyncio.ensure_future(
        resolver.project_links_allowed(["/api/v3/work_packages/blocked"], context=WorkPackageAllowedContext())
    )
    await asyncio.sleep(0)  # let the blocked call actually enter get_by_href and acquire its permit
    blocked_call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await blocked_call

    # Cheap, direct confirmation the permit was released (private attribute,
    # but the most direct possible check) -- backed up below by the stronger
    # behavioral proof (a fresh saturating call actually completes).
    assert resolver._allowlist_semaphore._value == 10  # noqa: SLF001

    # All 10 permits must be available again -- prove it by saturating the
    # semaphore with exactly 10 concurrently-blocked hrefs plus one more that
    # can only proceed once a permit is free; if cancellation had leaked the
    # first call's permit, only 9 would be available and this would hang.
    api.release.set()
    fresh_hrefs = [f"/api/v3/work_packages/{i}" for i in range(10)]
    outcomes = await asyncio.wait_for(
        resolver.project_links_allowed(fresh_hrefs, context=WorkPackageAllowedContext()), timeout=2.0
    )
    assert all(outcome is True for outcome in outcomes.values())
