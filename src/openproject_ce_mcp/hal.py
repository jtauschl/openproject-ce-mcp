"""Transport-neutral HAL+JSON normalization (OPM-190).

Package-root module deliberately independent of both `client.py` and `app/`
(no imports from either, no `httpx`) -- `normalize_links` is used by both
sides of the still-incomplete OPM-153 migration (client.py's legacy facade
and the Versions app layer's HttpxTransport) and neither may import from the
other, so a neutral shared module is the only way to keep this one real
invariant in a single place instead of duplicated.
"""

from __future__ import annotations

from typing import Any


def normalize_links(value: Any) -> Any:
    """Recursively replace an explicit ``"_links": null`` with ``{}``
    throughout a parsed HAL+JSON response body, mutating in place. HAL+JSON
    convention says `_links` is always an object; this guards the
    (unconfirmed but plausible) case where OpenProject emits an explicit
    null instead, so every existing `payload.get("_links", {})` read
    downstream keeps working via its "absent key" default rather than
    raising AttributeError on the following `.get` (OPM-190).
    """
    if isinstance(value, dict):
        if "_links" in value and value["_links"] is None:
            value["_links"] = {}
        for v in value.values():
            normalize_links(v)
    elif isinstance(value, list):
        for item in value:
            normalize_links(item)
    return value
