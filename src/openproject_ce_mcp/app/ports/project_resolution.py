"""Request-scoped project resolution cache.

Lives in the Ports layer (not Resolvers) because `app/ports/project_ref.py` needs the
type for a Protocol signature, and Ports must not import from Resolvers.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


class ProjectResolutionContext:
    """Request-scoped cache for resolved project payloads.

    Lifetime is bounded to a single top-level call (e.g. one
    create_work_package/update_work_package/create_subtask invocation) --
    construct a new instance per call, never store one on self, and never
    reuse one across calls that might touch different projects (a bulk
    operation's items, for instance, each get their own context, not one
    shared across the whole batch).

    Still performs the real resolve-and-allowlist-check on first use of each
    (project_ref, write) pair; this only avoids repeating that same fetch for
    a ref+scope already resolved earlier in the same top-level call -- it
    never skips a check outright.
    """

    def __init__(self, resolve: Callable[..., Awaitable[dict[str, Any]]]) -> None:
        self._resolve = resolve
        self._cache: dict[tuple[str, bool], dict[str, Any]] = {}

    async def resolve(self, project_ref: str, *, write: bool = False) -> dict[str, Any]:
        key = (project_ref, write)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        payload = await self._resolve(project_ref, write=write)
        self._store(payload, write=write, extra_ref=project_ref)
        return payload

    def seed(self, project_ref: str, payload: dict[str, Any], *, write: bool = False) -> None:
        """Pre-populate the cache from a resolution the caller already performed.

        A write=True resolution already implies the read check passed too
        (write allowlist checks always check read first), so a caller that
        resolved with write=True may safely seed both keys with the same
        payload -- callers that only resolved a read should only seed write=False.
        """
        self._store(payload, write=write, extra_ref=project_ref)

    def _store(self, payload: dict[str, Any], *, write: bool, extra_ref: str | None = None) -> None:
        # A resolved payload is cached under every alias it's actually known by
        # (the ref used to look it up, its numeric id, its identifier) -- not
        # "cross-project reuse", since these all name the same already-checked
        # project. This matters because some resolvers translate a numeric ref
        # to the identifier internally (_resolve_version_id) before making a
        # further call; without this, that translated ref would miss the cache
        # and trigger a second, redundant fetch of the same project.
        refs = {extra_ref} if extra_ref else set()
        project_id = payload.get("id")
        if project_id is not None:
            refs.add(str(project_id))
        identifier = payload.get("identifier")
        if identifier:
            refs.add(identifier)
        for ref in refs:
            self._cache[(ref, write)] = payload


class WorkPackageResolutionContext:
    """Adds an id-level cache for resolved type/version/sprint references on top
    of a ProjectResolutionContext (composition, not inheritance -- composition
    keeps this cache layer decoupled from ProjectResolutionContext's own
    implementation).

    Same lifetime rule as ProjectResolutionContext: bounded to a single
    top-level call by default (create_work_package/update_work_package each
    construct their own when the caller doesn't supply one). A bulk operation
    may deliberately share ONE instance across all of its items -- safe to do
    because the id cache is keyed by (project, kind, ref), so items touching
    different projects within the same bulk call never share a resolution
    across projects. Discard the instance once the (bulk) call ends; never
    reuse one across separate top-level calls.

    `_allowed_values` (`get_allowed_values`/`store_allowed_values`) caches a
    schema field's dereferenced `allowedValues` elements, keyed by the
    resolved `href` itself -- NOT by (project, field), because OpenProject's
    own href generation already encodes the right granularity: for a
    not-yet-persisted work package (the bulk_create path) the href is
    project-scoped (`available_assignees_in_workspace(project_id)`), but for
    an existing one (the bulk_update path) it is scoped to that INDIVIDUAL
    work package (`available_assignees_in_work_package(work_package_id)`) --
    two work packages in the same project can have different allowed
    assignees (e.g. workflow-status-dependent visibility). Caching by the
    href itself can never conflate the two, since OpenProject would never
    generate the same href for two different scopes. Same request-scoped
    lifetime as the id cache above -- never reused across separate top-level
    calls, since assignability can change between calls.
    """

    def __init__(self, project_context: ProjectResolutionContext) -> None:
        self.project_context = project_context
        self._ids: dict[tuple[str, str, str], str] = {}
        self._allowed_values: dict[str, list[dict[str, Any]]] = {}

    def get_id(self, kind: str, project: str, ref: str) -> str | None:
        return self._ids.get((project, kind, ref))

    def store_id(self, kind: str, project: str, ref: str, resolved_id: str) -> None:
        self._ids[(project, kind, ref)] = resolved_id

    def get_allowed_values(self, href: str) -> list[dict[str, Any]] | None:
        return self._allowed_values.get(href)

    def store_allowed_values(self, href: str, elements: list[dict[str, Any]]) -> None:
        self._allowed_values[href] = elements
