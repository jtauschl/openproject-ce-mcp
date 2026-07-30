"""Project-scope / allowlist policy (ADR 0001). Pure, no I/O.

Contains small, deliberately duplicated private copies of `_trim_text`/
`_slug_from_href` (+ `SUBJECT_LIMIT`) -- duplicated rather than
imported from client.py to avoid `app/` importing from `client.py` (these are still
used ~136/15 times respectively by every other domain's normalize_* methods).
Unify only once every domain has migrated and client.py's copies become truly dead.

`id_from_href` is exported (not underscore-prefixed) because, unlike the two
helpers above, it crossed this project's own "3+ identical copies" threshold
WITHIN `app/` itself (this module's own copy, `app/services/project_service.py`,
and `app/services/file_link_service.py` -- found during the File Links
migration's step-6 self-audit, OPM-296) -- `services` is permitted to import
from `policies` (see `tests/test_architecture_boundaries.py`'s
`_LAYER_DEPENDENCIES`), so this is the natural shared home rather than a new
package-root module.

Every project-link check must classify the link's structure BEFORE deciding
whether a wide-open scope short-circuits the check -- a missing or malformed
link is never automatically "allowed" just because the configured scope is
`*`. OpenProject's own `associated_project` representer macro
(`lib/api/v3/workspaces/linked_resource.rb` in the vendored source) renders
an explicit `urn:openproject-org:api:v3:undisclosed` URN link (never omits
the link itself) when a project exists but is invisible to the caller, and a
handful of resource types (Membership, View, Board/Query, Job Status) have a
genuinely optional project association where the server documents an
explicit empty/absent link as normal, not anomalous.

`classify_project_link` gives every call site a typed answer instead of a
bare `Any`. `ensure_project_link_allowed`/`ensure_project_write_link_allowed`
(the two names every existing call site already uses) are the REQUIRED-
project-link contract: MISSING/MALFORMED always denied, regardless of scope.
`ensure_project_link_allowed_if_present`/`ensure_project_write_link_allowed_if_present`
are the OPTIONAL-project-link contract (Membership/View/Board/Job Status
only): MISSING/EXPLICITLY_UNSCOPED are allowed under a wide-open scope and
denied under a restrictive one (a documented, legitimate server state, not a
defect), while MALFORMED is always denied there too -- a structurally broken
link is never the same thing as "deliberately no link".
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum, auto
from fnmatch import fnmatch
from typing import Any
from urllib.parse import unquote

from ...config import Settings
from ..errors import PermissionDeniedError

SUBJECT_LIMIT = 255

URN_UNDISCLOSED = "urn:openproject-org:api:v3:undisclosed"


class LinkState(Enum):
    """Classification of a raw HAL project-link value.

    RESOLVED: a real project link ({"href": "/api/v3/projects/7", ...}).
    UNDISCLOSED: OpenProject's own URN placeholder for an existing-but-
      invisible project -- structurally complete, only the identity is
      redacted server-side.
    EXPLICITLY_UNSCOPED: the link key is present but its value is
      documented-empty ({"href": None}) -- e.g. a global Membership/View/Query.
    MISSING: the Python value itself is None (no _links.project key at all).
    MALFORMED: present but structurally broken (not a dict, no "href" key,
      href is not a non-blank string and not None, or href is whitespace-only).
    """

    RESOLVED = auto()
    UNDISCLOSED = auto()
    EXPLICITLY_UNSCOPED = auto()
    MISSING = auto()
    MALFORMED = auto()


def classify_project_link(link: Any) -> LinkState:
    if link is None:
        return LinkState.MISSING
    if not isinstance(link, dict):
        return LinkState.MALFORMED
    if "href" not in link:
        # e.g. {} or {"title": "x"} with no "href" key at all -- no known
        # representer ever omits the key itself, only its value.
        return LinkState.MALFORMED
    href = link.get("href")
    if href is None:
        return LinkState.EXPLICITLY_UNSCOPED
    if not isinstance(href, str) or not href.strip():
        return LinkState.MALFORMED
    if href == URN_UNDISCLOSED:
        return LinkState.UNDISCLOSED
    return LinkState.RESOLVED


def _trim_text(value: Any, *, limit: int) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def id_from_href(href: str | None) -> int | None:
    if not href:
        return None
    parts = href.rstrip("/").split("/")
    try:
        return int(parts[-1])
    except (ValueError, IndexError):
        return None


def _slug_from_href(href: str | None) -> str | None:
    if not href:
        return None
    parts = href.rstrip("/").split("/")
    try:
        slug = parts[-1]
        return unquote(slug) or None
    except IndexError:
        return None


def scope_allows_all(values: tuple[str, ...]) -> bool:
    return any(item.strip() == "*" for item in values)


def scope_matches_candidates(scope: tuple[str, ...], candidates: set[str]) -> bool:
    normalized_candidates = {candidate.casefold() for candidate in candidates if candidate}
    if not normalized_candidates:
        return False
    if scope_allows_all(scope):
        return True
    for raw_pattern in scope:
        pattern = raw_pattern.strip().casefold()
        if not pattern:
            continue
        for candidate in normalized_candidates:
            # fnmatch is case-insensitive (not fnmatchcase) since both are casefolded
            if fnmatch(candidate, pattern):
                return True
    return False


def project_candidates(
    *,
    project_id_to_identifier: dict[int, str],
    project_ref: str | None = None,
    payload: dict[str, Any] | None = None,
    link: Any = None,
    identifier: str | None = None,
    name: str | None = None,
) -> set[str]:
    candidates: set[str] = set()
    for value in (project_ref, identifier, name):
        if value:
            candidates.add(str(value).casefold())
    if payload is not None:
        identifier_value = _trim_text(payload.get("identifier"), limit=SUBJECT_LIMIT)
        name_value = _trim_text(payload.get("name"), limit=SUBJECT_LIMIT)
        if identifier_value:
            candidates.add(identifier_value.casefold())
        if name_value:
            candidates.add(name_value.casefold())
        project_id = payload.get("id")
        if project_id is not None:
            candidates.add(str(project_id).casefold())
    if isinstance(link, dict):
        href = link.get("href")
        title = link.get("title")
        if href:
            slug = _slug_from_href(href)
            if slug:
                candidates.add(slug.casefold())
            project_id = id_from_href(href)
            if project_id is not None:
                candidates.add(str(project_id).casefold())
                known_identifier = project_id_to_identifier.get(project_id)
                if known_identifier:
                    candidates.add(known_identifier.casefold())
        if title:
            title_cf = str(title).casefold()
            candidates.add(title_cf)
            # Also add an identifier-style variant (spaces → hyphens) so that a project
            # named "My Project" matches the pattern "my-project" (its likely identifier).
            candidates.add(title_cf.replace(" ", "-"))
    return {candidate for candidate in candidates if candidate}


def payload_allowed(ensure: Callable[[], None]) -> bool:
    """Run an `ensure_*_allowed` check, turning PermissionDeniedError into False.

    Shared by every bool-returning `_X_payload_allowed` wrapper.
    """
    try:
        ensure()
        return True
    except PermissionDeniedError:
        return False


def project_link_payload_allowed(
    payload: dict[str, Any], *, link_key: str, settings: Settings, project_id_to_identifier: dict[int, str]
) -> bool:
    """Shared body for every domain's `<domain>_payload_allowed(payload, ...)`
    wrapper (`document_policy.py`, `news_policy.py`, `version_policy.py`):
    each one only ever differed in which `_links` key carries the project
    reference (`"project"` for Documents/News, `"definingProject"` for
    Versions) -- found to be near-identical, cross-sibling duplication (not
    the documented, sanctioned client.py-transition duplication) during the
    Documents migration's post-implementation review.
    """
    return payload_allowed(
        lambda: ensure_project_link_allowed(
            payload.get("_links", {}).get(link_key),
            settings=settings,
            project_id_to_identifier=project_id_to_identifier,
        )
    )


def ensure_project_link_allowed(link: Any, *, settings: Settings, project_id_to_identifier: dict[int, str]) -> None:
    """REQUIRED-project-link contract: for resource types whose
    representer always emits a project link (a real one, or OpenProject's own
    URN_UNDISCLOSED placeholder for an invisible-but-existing project).
    MISSING/MALFORMED/an unexpected EXPLICITLY_UNSCOPED are always denied,
    regardless of scope -- none of those are a documented state for a
    required-link resource. Use `ensure_project_link_allowed_if_present`
    instead for the handful of resources (Membership, View, Board, Job
    Status) with a genuinely optional project association.
    """
    state = classify_project_link(link)
    if state in (LinkState.MISSING, LinkState.MALFORMED, LinkState.EXPLICITLY_UNSCOPED):
        raise PermissionDeniedError("OpenProject access to this project is disabled by OPENPROJECT_READ_PROJECTS.")
    if state is LinkState.UNDISCLOSED:
        if scope_allows_all(settings.read_projects):
            return
        raise PermissionDeniedError("OpenProject access to this project is disabled by OPENPROJECT_READ_PROJECTS.")
    if scope_allows_all(settings.read_projects):
        return
    candidates = project_candidates(project_id_to_identifier=project_id_to_identifier, link=link)
    if not scope_matches_candidates(settings.read_projects, candidates):
        raise PermissionDeniedError("OpenProject access to this project is disabled by OPENPROJECT_READ_PROJECTS.")


def ensure_project_write_link_allowed(
    link: Any, *, settings: Settings, project_id_to_identifier: dict[int, str]
) -> None:
    ensure_project_link_allowed(link, settings=settings, project_id_to_identifier=project_id_to_identifier)
    state = classify_project_link(link)
    if state is LinkState.UNDISCLOSED:
        if scope_allows_all(settings.write_projects):
            return
        raise PermissionDeniedError("OpenProject writes to this project are disabled by OPENPROJECT_WRITE_PROJECTS.")
    if scope_allows_all(settings.write_projects):
        return
    candidates = project_candidates(project_id_to_identifier=project_id_to_identifier, link=link)
    if not scope_matches_candidates(settings.write_projects, candidates):
        raise PermissionDeniedError("OpenProject writes to this project are disabled by OPENPROJECT_WRITE_PROJECTS.")


def ensure_project_link_allowed_if_present(
    link: Any, *, settings: Settings, project_id_to_identifier: dict[int, str]
) -> None:
    """OPTIONAL-project-link contract: for the few resource types
    (Membership, View, Board/Query, Job Status) whose representer documents
    an explicit empty/absent project link as normal, not anomalous (a global
    membership, an unbound view, a global query, a projectless job).
    MISSING/EXPLICITLY_UNSCOPED are allowed under a wide-open scope and
    denied under a restrictive one; MALFORMED is always denied regardless of
    scope, since a structurally broken link is never the same thing as
    "deliberately none".
    """
    state = classify_project_link(link)
    if state is LinkState.MALFORMED:
        raise PermissionDeniedError("OpenProject access to this project is disabled by OPENPROJECT_READ_PROJECTS.")
    if state is LinkState.UNDISCLOSED:
        if scope_allows_all(settings.read_projects):
            return
        raise PermissionDeniedError("OpenProject access to this project is disabled by OPENPROJECT_READ_PROJECTS.")
    if scope_allows_all(settings.read_projects):
        return
    candidates = project_candidates(project_id_to_identifier=project_id_to_identifier, link=link)
    if not scope_matches_candidates(settings.read_projects, candidates):
        raise PermissionDeniedError("OpenProject access to this project is disabled by OPENPROJECT_READ_PROJECTS.")


def ensure_project_write_link_allowed_if_present(
    link: Any, *, settings: Settings, project_id_to_identifier: dict[int, str]
) -> None:
    ensure_project_link_allowed_if_present(link, settings=settings, project_id_to_identifier=project_id_to_identifier)
    state = classify_project_link(link)
    if state is LinkState.UNDISCLOSED:
        if scope_allows_all(settings.write_projects):
            return
        raise PermissionDeniedError("OpenProject writes to this project are disabled by OPENPROJECT_WRITE_PROJECTS.")
    if scope_allows_all(settings.write_projects):
        return
    candidates = project_candidates(project_id_to_identifier=project_id_to_identifier, link=link)
    if not scope_matches_candidates(settings.write_projects, candidates):
        raise PermissionDeniedError("OpenProject writes to this project are disabled by OPENPROJECT_WRITE_PROJECTS.")
