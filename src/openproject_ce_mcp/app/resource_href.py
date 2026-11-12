"""The resource an API link of this instance names.

Package-root shared kernel: pure string parsing, importing only `origin`. A link names a resource
only in the exact shape OpenProject emits for this instance: a relative path or an absolute URL on
the instance's origin, below the instance's API prefix, with a plain numeric id and no query,
fragment, parameters, dot segments or percent-encoding. Anything else names nothing, so a look-alike
path cannot pass for a resource.
"""

from __future__ import annotations

import re
from typing import Any, NamedTuple
from urllib.parse import urlsplit

from .origin import api_prefix_from_url, has_dot_segment, strict_origin

_RESOURCE = re.compile(r"(?P<namespace>[a-z][a-z_]*)/(?P<id>[1-9][0-9]{0,18})")
BIGINT_MAX = 2**63 - 1
# urlsplit silently drops tabs, newlines and leading control characters, so anything outside
# printable ASCII is rejected before it can be normalized into a valid-looking link.
_PRINTABLE_ASCII = re.compile(r"[!-~]+")


def instance_path(href: Any, *, origin: tuple[str, str, int] | None) -> str | None:
    """The path of an href that is a relative path or an absolute URL on the instance's origin,
    without query, fragment, parameters, dot segments or percent-encoding; None for anything else.
    Whether the path names a resource is for the caller to decide."""
    if not isinstance(href, str) or not _PRINTABLE_ASCII.fullmatch(href) or any(c in href for c in "?#;%"):
        return None
    try:
        parts = urlsplit(href)
    except ValueError:
        return None
    if (parts.scheme or parts.netloc) and (origin is None or strict_origin(href) != origin):
        return None
    if has_dot_segment(parts.path):
        return None
    return parts.path


class ResourceLink(NamedTuple):
    namespace: str
    id: int


class ResourceLinks:
    def __init__(self, base_url: str) -> None:
        self._origin = strict_origin(base_url)
        self._api_prefix = api_prefix_from_url(base_url)

    def parse(self, link: Any) -> ResourceLink | None:
        """The namespace and id of a link's href (`versions/7`), or None when the href is not a
        resource link of this instance."""
        path = instance_path(link.get("href") if isinstance(link, dict) else None, origin=self._origin)
        if path is None or not path.startswith(self._api_prefix):
            return None
        match = _RESOURCE.fullmatch(path[len(self._api_prefix) :])
        if match is None or int(match.group("id")) > BIGINT_MAX:
            return None
        return ResourceLink(match.group("namespace"), int(match.group("id")))
