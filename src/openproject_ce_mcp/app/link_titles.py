"""Link titles of a write preview, and the collections whose titles a shown value may keep.

A preview echoes the form OpenProject returns, whose links carry the title and display id of
what they point to. A link such as `parent`, `version` or a custom field value can point into a
project the read allowlist does not cover and would show its subject or name. Only links to
resources every user of the instance sees alike, or to the project the write targets, keep
their title; every other link keeps its href. A value shown outside a preview (a board filter value)
names its record only for a link into `KEPT_TITLE_COLLECTIONS`.
"""

from __future__ import annotations

import re
from typing import Any

_TITLE_KEYS = ("title", "displayId")

KEPT_LINK_NAMES = frozenset(
    {
        "self",
        "type",
        "status",
        "priority",
        "project",
        "category",
        "projectPhase",
        "projectPhaseDefinition",
        "assignee",
        "responsible",
        "author",
        "user",
        "principal",
        "role",
        "roles",
        "activity",
        "filter",
        "operator",
    }
)


# The collections whose records every user of the instance sees alike, so a link into one of them
# may name its record in a shown value. A link into any other collection (version, project, work
# package ...) can name something in a project outside the read scope.
KEPT_TITLE_COLLECTIONS = frozenset(
    {
        "statuses",
        "types",
        "priorities",
        "roles",
        "users",
        "groups",
        "principals",
        "project_phase_definitions",
    }
)

_COLLECTION_OF_LINK = re.compile(r"(?:(?!/api/v3/)[^?#])*/api/v3/([a-z_]+)/[^/?#]+")


def collection_of(href: str) -> str | None:
    """The collection a link points into (`versions` for `/api/v3/versions/12`), or None when the whole
    href is not exactly `<url root>/api/v3/<collection>/<id>`: a longer path, a query or a fragment
    never counts as a known collection."""
    match = _COLLECTION_OF_LINK.fullmatch(href)
    return match.group(1) if match else None


def without_foreign_capable_titles(value: Any) -> Any:
    """A copy of a preview payload in which every link outside `KEPT_LINK_NAMES` has no title and
    no display id."""
    if isinstance(value, list):
        return [without_foreign_capable_titles(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {
        key: _links(child) if key == "_links" and isinstance(child, dict) else without_foreign_capable_titles(child)
        for key, child in value.items()
    }


def _links(links: dict[str, Any]) -> dict[str, Any]:
    return {name: _link(link, keep_titles=name in KEPT_LINK_NAMES) for name, link in links.items()}


def _link(link: Any, *, keep_titles: bool) -> Any:
    return link if keep_titles else without_titles(link)


def without_titles(link: Any) -> Any:
    """A link (or list of links) with no title and no display id."""
    if isinstance(link, list):
        return [without_titles(item) for item in link]
    if not isinstance(link, dict):
        return link
    return {key: child for key, child in link.items() if key not in _TITLE_KEYS}
