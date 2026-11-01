"""The references OpenProject can resolve, as pure rules shared by the tool
layer and `app/`, neither of which may import the other."""

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


def is_numeric_ref(value: str) -> bool:
    """Whether a reference is an id: ASCII digits only. `str.isdigit()` also
    accepts superscripts and other scripts' digits, which are names here."""
    return _NUMERIC.fullmatch(value) is not None


def canonical_work_package_ref(value: int | str) -> str | None:
    """Return the reference as OpenProject resolves it, or None for a value it
    cannot resolve. A numeric id loses its leading zeros: OpenProject before
    17.4 reads "007" as 7, later versions as a display id that never exists."""
    text = str(value).strip()
    if is_numeric_ref(text):
        return text.lstrip("0") or None
    return text if _DISPLAY_ID.fullmatch(text) else None


def canonical_display_id(value: str) -> str | None:
    """Return the value as a display id (`PROJ-42`), or None when it is not one.

    A numeric id is not a display id: in classic identifier mode the number is all the
    instance reports as `displayId`, and it cannot tell two tickets apart."""
    canonical = canonical_work_package_ref(value)
    return None if canonical is None or is_numeric_ref(canonical) else canonical


def has_semantic_display_id(display_id: str | None) -> bool:
    """Whether a `displayId` reported by OpenProject names a ticket by project (`PROJ-42`).

    OpenProject reports the numeric id as a string in classic identifier mode and for a
    work package without an identifier in semantic mode; before 17.4 the field is absent."""
    return display_id is not None and display_id != "" and not is_numeric_ref(display_id)
