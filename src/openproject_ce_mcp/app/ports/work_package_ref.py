"""Work-package-reference resolution ports (ADR 0001).

Two narrow seams onto Work Packages' reference-resolution machinery, analogous
to how `project_ref.py`'s `ProjectRefResolver` is the seam ~10 existing
Services depend on today. The concrete values `OpenProjectClient` hands in are
the bound methods `self._work_package_resolver.resolve_id` /
`.project_link_allowed` (structural typing, no wrapper class needed) -- see
`app/resolvers/work_package_resolver.py`. No Service consumes these seams yet
(this is infrastructure-only, preparing for future migrations of
Attachments/Time Entries/Reminders/Watchers/Emoji Reactions/Relations/
Notifications/File Links, which currently depend on client.py's private
`_resolve_work_package_id`/`_work_package_project_allowed` instead); they are
declared here ready for those future migrations to wire in.

Also holds `work_package_ref()`, the pure, synchronous URL-encoding helper
extracted from client.py's `_work_package_ref` (no I/O, no scope check). It
lives here rather than in `app/adapters/_text.py` (its adapters-only home
would be unreachable from `app/resolvers/`) or inline in
`work_package_resolver.py` (unreachable from `app/adapters/`) because both
`HttpxWorkPackageLookupApi` (adapters layer) and `WorkPackageResolver`
(resolvers layer) need the identical encoding rule, and `ports` is the only
layer both may import from (see the layer-dependency rules in
`tests/test_architecture_boundaries.py`).
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Protocol
from urllib.parse import quote

from ..errors import InvalidInputError
from .work_package_resolution import WorkPackageAllowedContext


def work_package_ref(ref: int | str) -> str:
    """Return a path-safe work-package reference for a ``work_packages/{id}`` path.

    Both a numeric id and a project-prefixed identifier (e.g. ``PROJ-123``,
    exposed as ``displayId`` in OpenProject 17.5+) are accepted directly by the
    ``GET/PATCH/DELETE /api/v3/work_packages/{id}`` endpoints: in semantic mode
    OpenProject resolves the project-based form on the server. The reference is
    passed through verbatim (URL-encoded) so the behaviour degrades cleanly — on
    instances without semantic identifiers a project-prefixed reference simply
    yields a 404 (mapped to ``NotFoundError``), while numeric ids keep working on
    every supported version.

    A literal ``.``/``..`` path segment is rejected first (ported from
    release/0.3.4's generalized path-traversal guard, `app/adapters/_text.py`'s
    ``reject_path_traversal_segments`` there is the adapters-layer twin of this
    check) -- `quote()` never escapes ``.``, so such a value would otherwise pass
    through unchanged and httpx would silently normalize it away when building
    the request, redirecting to an unrelated endpoint. Duplicated here rather
    than imported from `_text.py` because `ports/` may import nothing from
    `adapters/` (see `tests/test_architecture_boundaries.py`'s layer-dependency
    rules); `app/errors.py` is shared-kernel and safe to import directly.
    """
    text = str(ref).strip()
    segments = text.split("/")
    if any(segment in (".", "..") for segment in segments):
        raise InvalidInputError("OpenProject work_package_id must not contain a '.' or '..' path segment.")
    return quote(text, safe="")


class WorkPackageIdResolver(Protocol):
    """Narrow seam onto `WorkPackageResolver.resolve_id`."""

    def __call__(self, work_package_ref: int | str, *, write: bool = False) -> Awaitable[int]: ...


class WorkPackageProjectAllowedCheck(Protocol):
    """Narrow seam onto `WorkPackageResolver.project_link_allowed`."""

    def __call__(self, href: str, *, context: WorkPackageAllowedContext | None = None) -> Awaitable[bool]: ...
