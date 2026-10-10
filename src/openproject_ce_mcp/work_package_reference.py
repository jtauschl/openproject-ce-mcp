"""The work package references OpenProject can resolve, as one pure rule shared
by the tool layer and `app/`, neither of which may import the other."""

from __future__ import annotations

import re

# `WorkPackage.find` resolves a numeric id or "<project slug>-<sequence>"
# through the identifier column and the alias table, which holds every slug
# the project ever had: semantic ("PROJ", at most 10 characters) and classic
# ("my-proj", at most 100 lowercase letters, digits, hyphens and underscores,
# not digits alone). Sequences start at 1 and are written without leading
# zeros. Any other value is a guaranteed 404, and a stream of those reads as
# probing to a web application firewall in front of the server.
_NUMERIC = re.compile(r"[0-9]+")
_DISPLAY_ID = re.compile(r"(?:[A-Z][A-Z0-9_]{0,9}|(?![0-9]+-[0-9]+\Z)[a-z0-9_-]{1,100})-[1-9][0-9]*")


def canonical_work_package_ref(value: int | str) -> str | None:
    """Return the reference as OpenProject resolves it, or None for a value it
    cannot resolve. A numeric id loses its leading zeros: OpenProject before
    17.4 reads "007" as 7, later versions as a display id that never exists."""
    text = str(value).strip()
    if _NUMERIC.fullmatch(text):
        return text.lstrip("0") or None
    return text if _DISPLAY_ID.fullmatch(text) else None
