"""Work-package-reference resolver (ADR 0001).

Mirrors `ProjectResolver`'s shape (`app/resolvers/project_resolver.py`):
constructor takes `api` + `settings`, depends only on the `WorkPackageLookupApi`
Port (never raw HTTP), exposes `resolve_id`-style methods. Extracted so the 7
still-flat client.py domains that depend on work-package-reference resolution
(Attachments, Time Entries, Reminders, Watchers, Emoji Reactions, Relations,
Notifications, File Links) can each migrate independently later without
waiting for the full Work Packages CRUD migration (~1170 lines, the last big
blocker, not attempted here).

`resolve_id()` is a verbatim behavioral port of client.py's
`_resolve_work_package_id` body; `project_link_allowed()` is a verbatim
behavioral port of `_work_package_project_allowed`, plus an optional
`WorkPackageAllowedContext` cache parameter so the 5 client.py call sites
can thread a shared `WorkPackageAllowedContext` through instead of each
building their own bare `dict[str, bool] = {}`
(see client.py's call sites for `_work_package_project_allowed`).
"""

from __future__ import annotations

from ...config import Settings
from ..errors import NotFoundError
from ..policies import scope as scope_policy
from ..ports.work_package_lookup_api import WorkPackageLookupApi
from ..ports.work_package_resolution import WorkPackageAllowedContext


class WorkPackageResolver:
    def __init__(
        self, *, api: WorkPackageLookupApi, settings: Settings, project_id_to_identifier: dict[int, str]
    ) -> None:
        self._api = api
        self._settings = settings
        self._project_id_to_identifier = project_id_to_identifier

    async def resolve_id(self, work_package_ref: int | str, *, write: bool = False) -> int:
        """Resolve a work-package reference to its canonical numeric id.

        Needed where the numeric id itself is required (e.g. a relation filter or a
        client-side equality check) rather than a request path. A numeric reference
        does not short-circuit: it always triggers a fetch of the work
        package too, so its project can be validated against the allowlist before
        its ``id`` is read back. A project-prefixed identifier is resolved the same
        way, but additionally only works on OpenProject 17.5+ (and requires the
        exact, case-sensitive project identifier).

        ``write=True`` checks the WRITE allowlist instead of the read one --
        needed wherever the resolved work package is a REPARENT/relation
        TARGET being written into, not just read (e.g. a caller with write
        access to work package A must not be able to attach it under a work
        package B they can only read).
        """
        reference = str(work_package_ref).strip()
        try:
            payload = await self._api.get(reference)
        except NotFoundError as exc:
            if reference.isdigit():
                raise
            # A project-prefixed reference only resolves on OpenProject 17.5+ (and
            # requires the exact, case-sensitive project identifier). Give a hint
            # instead of a bare "not found" so a too-old instance or a case/prefix
            # mismatch is distinguishable from a genuinely missing work package.
            raise NotFoundError(
                f"Work package '{reference}' was not found. Semantic references like 'PROJ-123' "
                "require OpenProject 17.5+ and the exact project identifier (case-sensitive); "
                "on older instances use the numeric work-package id."
            ) from exc
        project_link = payload.get("_links", {}).get("project")
        if write:
            scope_policy.ensure_project_write_link_allowed(
                project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
            )
        else:
            scope_policy.ensure_project_link_allowed(
                project_link, settings=self._settings, project_id_to_identifier=self._project_id_to_identifier
            )
        return int(payload["id"])

    async def project_link_allowed(self, href: str, *, context: WorkPackageAllowedContext | None = None) -> bool:
        """True if the work package at ``href`` sits in a project the caller may read.

        When ``context`` is given, a cache hit short-circuits the fetch; a
        cache miss fetches and stores the result before returning it. When
        ``context is None``, behaves exactly like the original uncached
        method -- always fetches fresh.
        """
        if context is not None:
            cached = context.get(href)
            if cached is not None:
                return cached
            allowed = await self._project_link_allowed_uncached(href)
            context.set(href, allowed)
            return allowed
        return await self._project_link_allowed_uncached(href)

    async def _project_link_allowed_uncached(self, href: str) -> bool:
        try:
            work_package = await self._api.get_by_href(href)
        except NotFoundError:
            return False
        # Do NOT swallow server/transport errors as "not allowed" — a transient
        # 5xx must not silently drop a relation the caller is entitled to see.
        return scope_policy.payload_allowed(
            lambda: scope_policy.ensure_project_link_allowed(
                work_package.get("_links", {}).get("project"),
                settings=self._settings,
                project_id_to_identifier=self._project_id_to_identifier,
            )
        )
