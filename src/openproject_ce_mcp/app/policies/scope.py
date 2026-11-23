"""Project-scope / allowlist policy. Pure, no I/O.

Contains a small, deliberately duplicated private copy of `_trim_text`
(+ `SUBJECT_LIMIT`) rather than a shared helper, to keep this module free of
dependencies on other, less-stable modules.

`parse_project_href` is the one definition of a project link: what
OpenProject emits for this instance, nothing else. Every check, the project
directory and the services that need a linked project's id use it; a link
under another root path raises ProjectLinkPrefixError where it is checked, so
a base URL that does not match the server fails loudly instead of denying
everything.

`id_from_href` is exported (not underscore-prefixed) because it is shared
across `app/` itself (this module's own copy, `app/services/project_service.py`,
and `app/services/file_link_service.py`) -- `services` is permitted to import
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

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum, auto
from fnmatch import fnmatch
from functools import lru_cache
from typing import Any
from urllib.parse import unquote

from ...config import Settings
from ..errors import PermissionDeniedError, ProjectLinkPrefixError
from ..origin import api_prefix_from_url, strict_origin
from ..resource_href import BIGINT_MAX, instance_path

SUBJECT_LIMIT = 255

URN_UNDISCLOSED = "urn:openproject-org:api:v3:undisclosed"

# OpenProject renders a project link from the project's workspace type
# (`/projects`, and on 17.x `/programs` or `/portfolios`) and reads
# `/workspaces` as a project reference too; all four address one Project id
# space. The id is a PostgreSQL bigint.
_PROJECT_TARGET = re.compile(r"(?:projects|programs|portfolios|workspaces)/(?P<id>[1-9][0-9]{0,18})")
# Only for naming another root path; the instance's own prefix is matched
# first and exactly.
_PROJECT_UNDER_ANY_ROOT = re.compile(r"(?P<root>/(?:[A-Za-z0-9._~!$&'()*+,=:@/-]*/)?)api/v3/" + _PROJECT_TARGET.pattern)


@dataclass(frozen=True, slots=True)
class LinkedProject:
    id: int


@dataclass(frozen=True, slots=True)
class PrefixMismatch:
    """A project link on the instance's origin under another root path than
    OPENPROJECT_BASE_URL implies."""

    emitted_prefix: str


@lru_cache(maxsize=8)
def _instance(base_url: str) -> tuple[tuple[str, str, int] | None, str]:
    return strict_origin(base_url), api_prefix_from_url(base_url)


def parse_project_href(href: Any, *, settings: Settings) -> LinkedProject | PrefixMismatch | None:
    """The project an href links to, or None when it is not a project link of
    this instance. Accepts exactly what OpenProject emits: a relative path, or
    an absolute URL on the instance's origin, without query, fragment,
    parameters, dot segments or percent-encoding."""
    origin, api_prefix = _instance(settings.base_url)
    path = instance_path(href, origin=origin)
    if path is None:
        return None
    target = _PROJECT_TARGET.fullmatch(path[len(api_prefix) :]) if path.startswith(api_prefix) else None
    if target is not None:
        project_id = int(target.group("id"))
        return LinkedProject(project_id) if project_id <= BIGINT_MAX else None
    other = _PROJECT_UNDER_ANY_ROOT.fullmatch(path)
    if other is None or int(other.group("id")) > BIGINT_MAX:
        return None
    return PrefixMismatch(f"{other.group('root')}api/v3/")


def prefix_mismatch_error(mismatch: PrefixMismatch, *, settings: Settings) -> ProjectLinkPrefixError:
    return ProjectLinkPrefixError(
        f"OpenProject links its projects under {mismatch.emitted_prefix}, but OPENPROJECT_BASE_URL "
        f"implies {api_prefix_from_url(settings.base_url)}. Set OPENPROJECT_BASE_URL to the path "
        "OpenProject itself uses."
    )


def project_id_from_href(href: Any, *, settings: Settings) -> int | None:
    """The linked project's id; raises ProjectLinkPrefixError for a prefix mismatch."""
    parsed = parse_project_href(href, settings=settings)
    if isinstance(parsed, PrefixMismatch):
        raise prefix_mismatch_error(parsed, settings=settings)
    return parsed.id if parsed is not None else None


class LinkState(Enum):
    """Classification of a raw HAL project-link value.

    RESOLVED: a project link of this instance ({"href": "/api/v3/projects/7", ...}).
    UNDISCLOSED: OpenProject's own URN placeholder for an existing-but-
      invisible project -- structurally complete, only the identity is
      redacted server-side.
    EXPLICITLY_UNSCOPED: the link key is present but its value is
      documented-empty ({"href": None}) -- e.g. a global Membership/View/Query.
    MISSING: the Python value itself is None (no _links.project key at all).
    MALFORMED: present but not a project link of this instance (not a dict,
      no "href" key, href not a string, or an href `parse_project_href`
      rejects: another origin, another resource, any other shape).
    """

    RESOLVED = auto()
    UNDISCLOSED = auto()
    EXPLICITLY_UNSCOPED = auto()
    MISSING = auto()
    MALFORMED = auto()


def classify_project_link(link: Any, *, settings: Settings) -> LinkState:
    """Raises ProjectLinkPrefixError for a project link under another root
    path, so a misconfigured base URL fails loudly instead of denying all."""
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
    if href == URN_UNDISCLOSED:
        return LinkState.UNDISCLOSED
    if project_id_from_href(href, settings=settings) is None:
        return LinkState.MALFORMED
    return LinkState.RESOLVED


def ensure_embedded_project_consistent(payload: dict[str, Any], *, link: Any, settings: Settings) -> None:
    """An embedded project is trusted by its own id, identifier and name, so
    its self link, and the top-level link sent next to it if any, must be
    project links of this instance naming that same id."""
    links = payload.get("_links")
    self_link = links.get("self") if isinstance(links, dict) else None
    linked_ids = [project_id_from_href(_href(self_link), settings=settings)]
    if link is not None:
        linked_ids.append(project_id_from_href(_href(link), settings=settings))
    if any(linked_id is None or linked_id != payload.get("id") for linked_id in linked_ids):
        raise PermissionDeniedError("OpenProject access to this project is disabled by OPENPROJECT_READ_PROJECTS.")


def _href(link: Any) -> Any:
    return link.get("href") if isinstance(link, dict) else None


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


def project_record_candidates(project_id: int | None, identifier: str | None, name: str | None) -> set[str]:
    """Candidates of a project known by id, identifier and name, as a scope pattern may name it."""
    name_cf = (name or "").casefold()
    return {
        candidate
        for candidate in (
            (identifier or "").casefold(),
            "" if project_id is None else str(project_id),
            name_cf,
            name_cf.replace(" ", "-"),
        )
        if candidate
    }


def project_payload_name(payload: Mapping[str, Any]) -> str | None:
    """The name a project payload carries, as every scope input reads it: trimmed, and absent when the server sent
    none. Never the display label of a nameless project."""
    return _trim_text(payload.get("name"), limit=SUBJECT_LIMIT)


def project_payload_candidates(payload: Mapping[str, Any]) -> set[str]:
    """Candidates of a project payload OpenProject returned.

    Never the reference it was requested by: from 17.3 OpenProject resolves a
    former identifier to the renamed project, which no longer carries it.
    """
    return project_record_candidates(
        payload.get("id"),
        _trim_text(payload.get("identifier"), limit=SUBJECT_LIMIT),
        project_payload_name(payload),
    )


def project_link_candidates(link: Any, *, settings: Settings, project_id_to_identifier: Mapping[int, str]) -> set[str]:
    if not isinstance(link, dict):
        return set()
    candidates: set[str] = set()
    href = link.get("href")
    title = link.get("title")
    if href:
        project_id = project_id_from_href(href, settings=settings)
        if project_id is not None:
            candidates.add(str(project_id))
            known_identifier = project_id_to_identifier.get(project_id)
            if known_identifier:
                candidates.add(known_identifier.casefold())
    if title:
        title_cf = str(title).casefold()
        candidates.add(title_cf)
        # Also add an identifier-style variant (spaces → hyphens) so that a project
        # named "My Project" matches the pattern "my-project" (its likely identifier).
        candidates.add(title_cf.replace(" ", "-"))
    return candidates


def project_named_by_link_allowed(
    link: Mapping[str, Any], *, settings: Settings, ids_by_identifier: Mapping[str, int]
) -> bool:
    """Read-scope verdict for a link that names a project by identifier and name rather than by id
    (the time entry activities' project links do). The id comes from the directory, so a scope
    pattern that is an id matches too."""
    href = link.get("href")
    identifier = unquote(href.rstrip("/").rsplit("/", maxsplit=1)[-1]) if isinstance(href, str) else None
    title = link.get("title")
    project_id = ids_by_identifier.get(identifier) if identifier is not None else None
    candidates = project_record_candidates(project_id, identifier, title if isinstance(title, str) else None)
    return scope_matches_candidates(settings.read_projects, candidates)


def project_known_by_id_allowed(
    project_id: int, name: str | None, *, settings: Settings, project_id_to_identifier: Mapping[int, str]
) -> bool:
    """Read-scope verdict for a project that a result names only by id and name. An identifier
    pattern covers it only when the directory already knows the identifier: fail closed."""
    candidates = project_record_candidates(project_id, project_id_to_identifier.get(project_id), name)
    return scope_matches_candidates(settings.read_projects, candidates)


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
    payload: dict[str, Any], *, link_key: str, settings: Settings, project_id_to_identifier: Mapping[int, str]
) -> bool:
    """Shared body for every `<domain>_payload_allowed(payload, ...)` wrapper and for the services
    that judge a payload's project link directly: each one only differs in which `_links` key
    carries the project reference."""
    return project_link_allowed(
        payload.get("_links", {}).get(link_key), settings=settings, project_id_to_identifier=project_id_to_identifier
    )


_DEFINING_PROJECT_LINK_KEYS = ("definingProject", "definingWorkspace")
_PROJECT_BOUND_TYPES = frozenset({"Version", "Sprint", "BacklogBucket"})


def defining_project_allowed(
    item: Mapping[str, Any], *, settings: Settings, project_id_to_identifier: Mapping[int, str]
) -> bool:
    """False for an embedded resource (version, sprint, backlog bucket) whose defining project the
    read scope does not cover; any other resource passes."""
    links = item.get("_links", {})
    key = next((candidate for candidate in _DEFINING_PROJECT_LINK_KEYS if candidate in links), None)
    if key is None and item.get("_type") not in _PROJECT_BOUND_TYPES:
        return True
    return defining_project_link_allowed(
        links.get(key) if key else None, settings=settings, project_id_to_identifier=project_id_to_identifier
    )


def ensure_defining_project_link_allowed(
    link: Any, *, settings: Settings, project_id_to_identifier: Mapping[int, str]
) -> None:
    """Project link of a version, sprint or backlog bucket. OpenProject leaves the link out (16.x)
    or renders the undisclosed placeholder (17.x) when the defining project is not visible to the
    token, so both mean the same: covered under `*`, not covered under a restricted scope."""
    if classify_project_link(link, settings=settings) is LinkState.MISSING:
        if scope_allows_all(settings.read_projects):
            return
        raise PermissionDeniedError("OpenProject access to this project is disabled by OPENPROJECT_READ_PROJECTS.")
    ensure_project_link_allowed(link, settings=settings, project_id_to_identifier=project_id_to_identifier)


def ensure_defining_project_write_link_allowed(
    link: Any, *, settings: Settings, project_id_to_identifier: Mapping[int, str]
) -> None:
    """Write counterpart of `ensure_defining_project_link_allowed`."""
    if classify_project_link(link, settings=settings) is not LinkState.MISSING:
        ensure_project_write_link_allowed(link, settings=settings, project_id_to_identifier=project_id_to_identifier)
        return
    ensure_defining_project_link_allowed(link, settings=settings, project_id_to_identifier=project_id_to_identifier)
    if not scope_allows_all(settings.write_projects):
        raise PermissionDeniedError("OpenProject writes to this project are disabled by OPENPROJECT_WRITE_PROJECTS.")


def defining_project_link_allowed(
    link: Any, *, settings: Settings, project_id_to_identifier: Mapping[int, str]
) -> bool:
    return payload_allowed(
        lambda: ensure_defining_project_link_allowed(
            link, settings=settings, project_id_to_identifier=project_id_to_identifier
        )
    )


def project_link_allowed(link: Any, *, settings: Settings, project_id_to_identifier: Mapping[int, str]) -> bool:
    """Bool form of `ensure_project_link_allowed` (same REQUIRED-link contract)."""
    return payload_allowed(
        lambda: ensure_project_link_allowed(link, settings=settings, project_id_to_identifier=project_id_to_identifier)
    )


def ensure_project_link_allowed(link: Any, *, settings: Settings, project_id_to_identifier: Mapping[int, str]) -> None:
    """REQUIRED-project-link contract: for resource types whose
    representer always emits a project link (a real one, or OpenProject's own
    URN_UNDISCLOSED placeholder for an invisible-but-existing project).
    MISSING/MALFORMED/an unexpected EXPLICITLY_UNSCOPED are always denied,
    regardless of scope -- none of those are a documented state for a
    required-link resource. Use `ensure_project_link_allowed_if_present`
    instead for the handful of resources (Membership, View, Board, Job
    Status) with a genuinely optional project association.
    """
    state = classify_project_link(link, settings=settings)
    if state in (LinkState.MISSING, LinkState.MALFORMED, LinkState.EXPLICITLY_UNSCOPED):
        raise PermissionDeniedError("OpenProject access to this project is disabled by OPENPROJECT_READ_PROJECTS.")
    if state is LinkState.UNDISCLOSED:
        if scope_allows_all(settings.read_projects):
            return
        raise PermissionDeniedError("OpenProject access to this project is disabled by OPENPROJECT_READ_PROJECTS.")
    if scope_allows_all(settings.read_projects):
        return
    candidates = project_link_candidates(link, settings=settings, project_id_to_identifier=project_id_to_identifier)
    if not scope_matches_candidates(settings.read_projects, candidates):
        raise PermissionDeniedError("OpenProject access to this project is disabled by OPENPROJECT_READ_PROJECTS.")


def ensure_project_write_link_allowed(
    link: Any, *, settings: Settings, project_id_to_identifier: Mapping[int, str]
) -> None:
    ensure_project_link_allowed(link, settings=settings, project_id_to_identifier=project_id_to_identifier)
    state = classify_project_link(link, settings=settings)
    if state is LinkState.UNDISCLOSED:
        if scope_allows_all(settings.write_projects):
            return
        raise PermissionDeniedError("OpenProject writes to this project are disabled by OPENPROJECT_WRITE_PROJECTS.")
    if scope_allows_all(settings.write_projects):
        return
    candidates = project_link_candidates(link, settings=settings, project_id_to_identifier=project_id_to_identifier)
    if not scope_matches_candidates(settings.write_projects, candidates):
        raise PermissionDeniedError("OpenProject writes to this project are disabled by OPENPROJECT_WRITE_PROJECTS.")


def ensure_project_link_allowed_if_present(
    link: Any, *, settings: Settings, project_id_to_identifier: Mapping[int, str]
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
    state = classify_project_link(link, settings=settings)
    if state is LinkState.MALFORMED:
        raise PermissionDeniedError("OpenProject access to this project is disabled by OPENPROJECT_READ_PROJECTS.")
    if state is LinkState.UNDISCLOSED:
        if scope_allows_all(settings.read_projects):
            return
        raise PermissionDeniedError("OpenProject access to this project is disabled by OPENPROJECT_READ_PROJECTS.")
    if scope_allows_all(settings.read_projects):
        return
    candidates = project_link_candidates(link, settings=settings, project_id_to_identifier=project_id_to_identifier)
    if not scope_matches_candidates(settings.read_projects, candidates):
        raise PermissionDeniedError("OpenProject access to this project is disabled by OPENPROJECT_READ_PROJECTS.")


def ensure_project_write_link_allowed_if_present(
    link: Any, *, settings: Settings, project_id_to_identifier: Mapping[int, str]
) -> None:
    ensure_project_link_allowed_if_present(link, settings=settings, project_id_to_identifier=project_id_to_identifier)
    state = classify_project_link(link, settings=settings)
    if state is LinkState.UNDISCLOSED:
        if scope_allows_all(settings.write_projects):
            return
        raise PermissionDeniedError("OpenProject writes to this project are disabled by OPENPROJECT_WRITE_PROJECTS.")
    if scope_allows_all(settings.write_projects):
        return
    candidates = project_link_candidates(link, settings=settings, project_id_to_identifier=project_id_to_identifier)
    if not scope_matches_candidates(settings.write_projects, candidates):
        raise PermissionDeniedError("OpenProject writes to this project are disabled by OPENPROJECT_WRITE_PROJECTS.")
