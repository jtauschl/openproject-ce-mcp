"""The closest allowed argument name for an argument a tool does not have.

Every rule yields only a name contained in `allowed`, so a hint never names an argument the tool lacks and
never accepts the wrong name: the call is still rejected. A rule stays silent where more than one name could
be meant, because a wrong suggestion on a write tool points at the wrong resource.
"""

from __future__ import annotations

import difflib
from collections.abc import Collection

_SYNONYMS = {"query": "search", "text": "search"}
_CUTOFF = 0.85


def _the_one(candidates: list[str]) -> str | None:
    return candidates[0] if len(candidates) == 1 else None


def _close(name: str, candidates: Collection[str]) -> str | None:
    matches = difflib.get_close_matches(name, sorted(candidates), n=1, cutoff=_CUTOFF)
    return matches[0] if matches else None


def suggest_argument(name: str, allowed: Collection[str], required: Collection[str]) -> str | None:
    """The allowed name `name` most likely stands for, or None when nothing qualifies."""
    if name.endswith("_id") and name[: -len("_id")] in allowed:
        return name[: -len("_id")]
    if name == "id":
        return _the_one([a for a in required if a.endswith("_id")])
    if name == "ids":
        return _the_one([a for a in allowed if a.endswith("_ids")])
    synonym = _SYNONYMS.get(name)
    if synonym in allowed:
        return synonym
    for suffix in ("_ids", "_id"):
        if name.endswith(suffix):
            stems = {a[: -len(suffix)]: a for a in allowed if a.endswith(suffix)}
            stem = _close(name[: -len(suffix)], stems)
            return stems[stem] if stem is not None else None
    return _close(name, allowed)
