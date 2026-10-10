"""Grids-only policy. Pure, no I/O.

A grid's `_links.scope` is not an API link but the web path the grid belongs
to: `<root>my/page` (the caller's own dashboard, always allowed),
`<root>projects/<identifier>` or `<root>projects/<identifier>/boards`. The
project behind a scope is resolved by the Service (OpenProject itself maps an
identifier, a former identifier or an id to the project) and handed in as a
`ResolvedProject`; this module only decides. From 17.1 a grid also carries
`_links.project`, an API link that is checked on its own; neither reference
can stand in for the other.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ... import policy_observation
from ...config import Settings
from ..errors import ProjectScopeDeniedError
from ..origin import root_path_from_url
from .scope import (
    PrefixMismatch,
    ensure_project_link_allowed,
    ensure_project_write_link_allowed,
    prefix_mismatch_error,
    project_id_from_href,
    project_record_candidates,
    scope_allows_all,
    scope_matches_candidates,
)

_SCOPE_TARGET = re.compile(r"(?:(?P<my_page>my/page)|projects/(?P<ref>[A-Za-z0-9_-]{1,100})(?:/boards)?)")
# Only for naming another root path: a project may itself be called
# "projects", so the instance's own root is matched first and exactly.
_SCOPE_UNDER_ANY_ROOT = re.compile(r"(?P<root>/(?:[A-Za-z0-9._~!$&'()*+,=:@/-]*/)?)" + _SCOPE_TARGET.pattern)
_PRINTABLE_ASCII = re.compile(r"[!-~]+")

_READ_DENIED = "OpenProject access to this grid is disabled by OPENPROJECT_READ_PROJECTS."
_WRITE_DENIED = "OpenProject writes to this grid are disabled by OPENPROJECT_WRITE_PROJECTS."


@dataclass(frozen=True, slots=True)
class MyPageScope:
    pass


@dataclass(frozen=True, slots=True)
class ProjectScope:
    ref: str


@dataclass(frozen=True, slots=True)
class ResolvedProject:
    id: int
    identifier: str
    name: str | None


def parse_grid_scope(href: Any, *, settings: Settings) -> MyPageScope | ProjectScope | PrefixMismatch | None:
    """The scope's target, or None for any shape OpenProject does not use."""
    if not isinstance(href, str) or not _PRINTABLE_ASCII.fullmatch(href):
        return None
    if not href.startswith("/") or href.startswith("//") or any(char in href for char in "?#;%"):
        return None
    if any(segment in (".", "..") for segment in href.split("/")):
        return None
    root = root_path_from_url(settings.base_url)
    target = _SCOPE_TARGET.fullmatch(href[len(root) :]) if href.startswith(root) else None
    if target is not None:
        return MyPageScope() if target.group("my_page") else ProjectScope(target.group("ref"))
    other = _SCOPE_UNDER_ANY_ROOT.fullmatch(href)
    return PrefixMismatch(f"{other.group('root')}api/v3/") if other else None


def emitted_grid_scope(href: Any, *, write: bool, settings: Settings) -> MyPageScope | ProjectScope:
    """The scope of a grid OpenProject returned. The server chose its shape, so
    another root path is a configuration error and any other shape a denial."""
    scope = parse_grid_scope(href, settings=settings)
    if isinstance(scope, PrefixMismatch):
        raise prefix_mismatch_error(scope, settings=settings)
    if scope is None:
        policy_observation.record_project_scope(None)
        policy_observation.record_policy_decision(f"project_scope_{'write' if write else 'read'}_denied")
        raise ProjectScopeDeniedError("OpenProject grid has a scope that is not a project, its boards or /my/page.")
    return scope


def needs_resolution(*, write: bool, settings: Settings) -> bool:
    """Whether a project scope must be resolved: only a restrictive scope
    looks at which project it is."""
    return not scope_allows_all(settings.read_projects) or (write and not scope_allows_all(settings.write_projects))


def ensure_grid_allowed(
    scope: MyPageScope | ProjectScope,
    *,
    project_link: Any,
    resolved: ResolvedProject | None,
    write: bool,
    settings: Settings,
    project_id_to_identifier: Mapping[int, str],
) -> None:
    """`resolved` is the project behind a ProjectScope, or None when it was
    not resolved (wide-open scope) or OpenProject did not find it for us."""
    decision = "write" if write else "read"
    try:
        _ensure_grid_allowed(
            scope,
            project_link=project_link,
            resolved=resolved,
            write=write,
            settings=settings,
            project_id_to_identifier=project_id_to_identifier,
        )
    except ProjectScopeDeniedError:
        policy_observation.record_policy_decision(f"project_scope_{decision}_denied")
        raise
    # A nested project-link check records its own scope and decision; the
    # grid's own outcome is the one that decided this call.
    policy_observation.record_project_scope(_scope_display(scope, resolved))
    policy_observation.record_policy_decision(f"project_scope_{decision}_allowed")


def _scope_display(scope: MyPageScope | ProjectScope, resolved: ResolvedProject | None) -> str | None:
    if isinstance(scope, MyPageScope):
        return None
    return resolved.identifier if resolved is not None else scope.ref


def _ensure_grid_allowed(
    scope: MyPageScope | ProjectScope,
    *,
    project_link: Any,
    resolved: ResolvedProject | None,
    write: bool,
    settings: Settings,
    project_id_to_identifier: Mapping[int, str],
) -> None:
    policy_observation.record_project_scope(_scope_display(scope, resolved))
    if project_link is not None:
        ensure_link = ensure_project_write_link_allowed if write else ensure_project_link_allowed
        ensure_link(project_link, settings=settings, project_id_to_identifier=project_id_to_identifier)
    if isinstance(scope, MyPageScope) or not needs_resolution(write=write, settings=settings):
        return
    if resolved is None:
        raise ProjectScopeDeniedError(_WRITE_DENIED if write else _READ_DENIED)
    if project_link is not None and project_id_from_href(project_link.get("href"), settings=settings) != resolved.id:
        raise ProjectScopeDeniedError(_WRITE_DENIED if write else _READ_DENIED)
    candidates = project_record_candidates(resolved.id, resolved.identifier, resolved.name)
    if not scope_allows_all(settings.read_projects) and not scope_matches_candidates(
        settings.read_projects, candidates
    ):
        raise ProjectScopeDeniedError(_READ_DENIED)
    if (
        write
        and not scope_allows_all(settings.write_projects)
        and not scope_matches_candidates(settings.write_projects, candidates)
    ):
        raise ProjectScopeDeniedError(_WRITE_DENIED)
