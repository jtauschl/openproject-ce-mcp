"""Request-scoped work-package-project-allowed cache (ADR 0001).

Lives in the Ports layer (not Resolvers) because `app/ports/work_package_ref.py`
needs the type for a Protocol signature, and Ports must not import from
Resolvers -- mirrors why `ProjectResolutionContext` lives in
`app/ports/project_resolution.py` rather than under `app/resolvers/`.
"""

from __future__ import annotations


class WorkPackageAllowedContext:
    """Request-scoped cache for `WorkPackageResolver.project_link_allowed` results.

    Lifetime is bounded to a single top-level call (e.g. one
    list_relations/list_notifications/list_reminders/get_work_package_relations
    invocation) -- construct a new instance per call, never store one on self.

    Much simpler than `ProjectResolutionContext`: a work-package href is a
    single, unambiguous cache key (unlike a project ref, which can be a
    numeric id, an identifier, or a display name all naming the same project,
    requiring `ProjectResolutionContext`'s multi-alias `_store` logic). This is
    just a plain `dict[str, bool]` get/set wrapper.
    """

    def __init__(self) -> None:
        self._cache: dict[str, bool] = {}

    def get(self, href: str) -> bool | None:
        return self._cache.get(href)

    def set(self, href: str, allowed: bool) -> None:
        self._cache[href] = allowed
