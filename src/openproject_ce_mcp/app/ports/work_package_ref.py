"""Work-package-reference resolution ports.

Narrow seams onto Work Packages' reference-resolution machinery, analogous
to how `project_ref.py`'s `ProjectRefResolver` is the seam several Services
depend on. Bound to `WorkPackageResolver.resolve_id`/`.project_link_allowed`
(see `app/resolvers/work_package_resolver.py`); consumed by
Attachments/Time Entries/Reminders/Watchers/Emoji Reactions/Relations/
Notifications/File Links/Activities/Work Packages Services.

Also holds `work_package_ref()`, a pure, synchronous helper that validates
a reference for a `work_packages/{id}` path (no I/O, no scope check) against
the shared rule in `work_package_reference.py`. It lives here because the
adapters, `WorkPackageResolver` and `RelationService` need the identical
rule, and `ports` is the one layer all of them may import from (see the
layer-dependency rules in `tests/test_architecture_boundaries.py`).
"""

from __future__ import annotations

from collections.abc import Awaitable, Iterable
from typing import Protocol

from ...work_package_reference import canonical_work_package_ref
from ..errors import InvalidInputError
from .work_package_resolution import WorkPackageAllowedContext


def work_package_ref(ref: int | str) -> str:
    """Return the reference for a ``work_packages/{id}`` path: a numeric id or
    a display id such as ``PROJ-123``. On an instance without semantic
    identifiers a display id simply yields a 404 (``NotFoundError``).

    Raises InvalidInputError for any other value, before a request is made.
    The accepted shapes contain no character that needs URL-encoding and no
    path segment, so the result goes into the path as is.
    """
    canonical = canonical_work_package_ref(ref)
    if canonical is None:
        raise InvalidInputError(
            f"OpenProject work_package_id must be a numeric id or a display id like PROJ-42, not {str(ref).strip()!r}."
        )
    return canonical


class WorkPackageIdResolver(Protocol):
    """Narrow seam onto `WorkPackageResolver.resolve_id`."""

    def __call__(self, work_package_ref: int | str, *, write: bool = False) -> Awaitable[int]: ...


class WorkPackageProjectAllowedCheck(Protocol):
    """Narrow seam onto `WorkPackageResolver.project_link_allowed`."""

    def __call__(self, href: str, *, context: WorkPackageAllowedContext | None = None) -> Awaitable[bool]: ...


class WorkPackageProjectAllowedBulkCheck(Protocol):
    """Narrow seam onto `WorkPackageResolver.project_links_allowed`.

    Resolves a batch of hrefs concurrently, bounded by a shared instance-scoped
    semaphore that is deliberately independent from
    `WorkPackageService._batch_read_semaphore` (see `WorkPackageResolver` --
    sharing one semaphore between the two would deadlock). Returns
    `bool | Exception` per href rather than plain
    `bool`: a caller resolving hrefs it would not all have reached under the
    old sequential control flow (e.g. a relation's `to` side when `from` is
    already denied) must be able to defer judging which speculative failures
    actually matter, instead of an exception from an irrelevant href aborting
    the whole page. Only successful `bool` outcomes are written into `context`
    -- a failed href is never cached, so a retry (this call or a later one)
    fetches fresh rather than replaying a stale error.
    """

    def __call__(
        self, hrefs: Iterable[str], *, context: WorkPackageAllowedContext
    ) -> Awaitable[dict[str, bool | Exception]]: ...
