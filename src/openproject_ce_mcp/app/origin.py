"""Shared same-origin-check helper.

Package-root shared kernel: pure, dependency-free URL parsing used by both
Adapters (via `app/adapters/_text.py`, which re-exports it for backward
compatibility and its own `link_to_web_url` helper) and Services that need
to reject a caller-supplied absolute URL pointing at a foreign origin.

Shared here because `BoardService._resolve_query_reference_href` needs the
same same-origin check as `app/adapters/_text.py`'s `origin_from_url`, but
`services` cannot import from `adapters` (enforced by
`tests/test_architecture_boundaries.py`).
"""

from __future__ import annotations

from urllib.parse import urlparse, urlsplit

_DEFAULT_PORTS = {"http": 80, "https": 443}


def origin_from_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def strict_origin(url: str) -> tuple[str, str, int] | None:
    """(scheme, host, port) for a comparison that must not be talked into a
    match: None, which equals nothing, for userinfo, a missing host or a port
    urlsplit cannot read."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme not in _DEFAULT_PORTS or not parts.hostname or "@" in parts.netloc:
        return None
    return scheme, parts.hostname, _DEFAULT_PORTS[scheme] if port is None else port


def root_path_from_url(base_url: str) -> str:
    """The instance's root path, "/" or "/openproject/", as OpenProject prefixes its links."""
    return urlsplit(base_url).path.rstrip("/") + "/"


def api_prefix_from_url(base_url: str) -> str:
    return f"{root_path_from_url(base_url)}api/v3/"
